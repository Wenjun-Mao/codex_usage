from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from codex_usage.session_files import (
    codex_home_from_session_dir,
    read_index_entries,
    timestamp_key,
)
from codex_usage.sync.io import (
    atomic_copy,
    atomic_write_json,
    atomic_write_text,
    path_kind,
    read_json_object,
)
from codex_usage.sync.models import LocalSyncState, SyncFileSnapshot, SyncPlanItem
from codex_usage.sync.paths import portable_thread_filename


_SQLITE_PARAMETER_BATCH_SIZE = 500


class LocalStateStore:
    """Persist per-thread sync bases under one sync-folder namespace."""

    def __init__(self, session_dir: Path, sync_dir: Path) -> None:
        self.session_dir = session_dir
        self.sync_dir = sync_dir

    def path_for(self, thread_id: str) -> Path:
        return (
            codex_home_from_session_dir(self.session_dir)
            / ".codex-sync-state"
            / sync_dir_fingerprint(self.sync_dir)
            / "threads"
            / f"{_thread_storage_name(thread_id)}.json"
        )

    def read(self, thread_id: str) -> LocalSyncState | None:
        try:
            value = read_json_object(self.path_for(thread_id))
            state = LocalSyncState.from_dict(value) if value is not None else None
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError):
            return None
        if (
            state is None
            or state.thread_id != thread_id
            or state.sync_dir_fingerprint != sync_dir_fingerprint(self.sync_dir)
        ):
            return None
        return state

    def write(self, state: LocalSyncState) -> None:
        if state.sync_dir_fingerprint != sync_dir_fingerprint(self.sync_dir):
            raise ValueError("Local sync state belongs to a different sync folder.")
        atomic_write_json(self.path_for(state.thread_id), state.to_dict())

    def record_success(
        self,
        item: SyncPlanItem,
        local: SyncFileSnapshot,
        remote: SyncFileSnapshot,
    ) -> None:
        self.write(local_state_from_success(item, local, remote, self.sync_dir))


def sync_dir_fingerprint(sync_dir: Path) -> str:
    normalized = str(sync_dir.resolve(strict=False)).replace("\\", "/").casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def local_state_from_success(
    item: SyncPlanItem,
    local: SyncFileSnapshot,
    remote: SyncFileSnapshot,
    sync_dir: Path,
) -> LocalSyncState:
    base = local if local.exists else remote
    if not base.exists:
        raise ValueError("Successful sync state requires a local or remote conversation snapshot.")
    return LocalSyncState(
        thread_id=item.thread_id,
        sync_dir_fingerprint=sync_dir_fingerprint(sync_dir),
        base_sha256=base.sha256,
        base_size_bytes=base.size_bytes,
        base_updated_at=item.updated_at,
        last_remote_sha256=remote.sha256,
        last_local_sha256=local.sha256,
        source_relative_path=item.source_relative_path,
        project_key=item.project_key,
        project_label=item.project_label,
        synced_at=now_iso(),
    )


def backup_local_session(source: Path, backup_dir: Path, thread_id: str) -> Path:
    target = backup_dir / _thread_storage_name(thread_id) / "session.jsonl"
    atomic_copy(source, target)
    return target


def save_conflict_candidate(source: Path, backup_dir: Path, thread_id: str) -> Path:
    target = backup_dir / _thread_storage_name(thread_id) / "remote-conflict-session.jsonl"
    atomic_copy(source, target)
    return target


def merge_session_index(
    session_dir: Path,
    new_entries: list[dict[str, Any]],
    backup_dir: Path,
) -> None:
    index_path = codex_home_from_session_dir(session_dir) / "session_index.jsonl"
    if index_path.is_file():
        atomic_copy(index_path, backup_dir / "session_index.jsonl")

    entries: dict[str, dict[str, Any]] = {}
    for entry in [*read_index_entries(index_path), *new_entries]:
        thread_id = str(entry.get("id") or "")
        if not thread_id:
            continue
        existing = entries.get(thread_id)
        if existing is None or timestamp_key(str(entry.get("updated_at") or "")) >= timestamp_key(
            str(existing.get("updated_at") or "")
        ):
            entries[thread_id] = entry

    ordered = sorted(entries.values(), key=lambda item: timestamp_key(str(item.get("updated_at") or "")))
    contents = "".join(json.dumps(entry, separators=(",", ":")) + "\n" for entry in ordered)
    atomic_write_text(index_path, contents)


def memory_database_row_counts(
    session_dir: Path,
    thread_ids: tuple[str, ...],
) -> dict[str, int]:
    selected_ids = tuple(dict.fromkeys(thread_ids))
    counts = dict.fromkeys(selected_ids, 0)
    if not selected_ids:
        return counts
    database_path = codex_home_from_session_dir(session_dir) / "state_5.sqlite"
    if path_kind(database_path) != "file":
        return counts
    try:
        with tempfile.TemporaryDirectory(prefix="codex-usage-memory-") as temporary_dir:
            copied_database = _snapshot_memory_database(database_path, Path(temporary_dir))
            counts.update(_query_memory_database(copied_database, selected_ids))
    except (OSError, sqlite3.Error):
        pass
    return counts


def _snapshot_memory_database(database_path: Path, snapshot_dir: Path) -> Path:
    copied_database = snapshot_dir / database_path.name
    for suffix in ("", "-wal", "-shm"):
        source = Path(f"{database_path}{suffix}")
        if path_kind(source) == "file":
            atomic_copy(source, Path(f"{copied_database}{suffix}"))
    return copied_database


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _thread_storage_name(thread_id: str) -> str:
    return portable_thread_filename(thread_id).removesuffix(".jsonl")


def _is_retryable_sqlite_error(error: BaseException) -> bool:
    return isinstance(error, sqlite3.OperationalError) and any(
        marker in str(error).casefold() for marker in ("busy", "locked")
    )


@retry(
    retry=retry_if_exception(_is_retryable_sqlite_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _query_memory_database(
    database_path: Path,
    thread_ids: tuple[str, ...],
) -> dict[str, int]:
    connection = sqlite3.connect(f"{database_path.resolve().as_uri()}?mode=ro", uri=True)
    try:
        counts: dict[str, int] = {}
        for start in range(0, len(thread_ids), _SQLITE_PARAMETER_BATCH_SIZE):
            batch = thread_ids[start : start + _SQLITE_PARAMETER_BATCH_SIZE]
            placeholders = ",".join("?" for _ in batch)
            rows = connection.execute(
                f"select thread_id, count(*) from stage1_outputs "
                f"where thread_id in ({placeholders}) group by thread_id",
                batch,
            ).fetchall()
            counts.update((str(thread_id), int(count)) for thread_id, count in rows)
    finally:
        connection.close()
    return counts
