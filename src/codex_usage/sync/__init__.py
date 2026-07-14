from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

from codex_usage.session_files import (
    codex_home_from_session_dir,
    file_size,
    load_all_index_entries,
    owning_session_dir,
    read_index_entries,
    timestamp_key,
)
from codex_usage.sync_constants import SYNC_METADATA_OVERHEAD_BYTES as SYNC_METADATA_OVERHEAD_BYTES
from codex_usage.sync_io import (
    atomic_copy,
    atomic_write_json,
    atomic_write_text,
    backup_file,
    dedupe,
    now_iso,
    read_json_object,
    save_conflict_candidate,
    sha256_file,
)
from codex_usage.sync.runner import run_sync as run_sync
from codex_usage.threads import ThreadInfo, list_threads


SYNC_VERSION = 1
_SAFE_THREAD_STORAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "COM1",
    "COM2",
    "COM3",
    "COM4",
    "COM5",
    "COM6",
    "COM7",
    "COM8",
    "COM9",
    "LPT1",
    "LPT2",
    "LPT3",
    "LPT4",
    "LPT5",
    "LPT6",
    "LPT7",
    "LPT8",
    "LPT9",
}


@dataclass(frozen=True)
class ExportResult:
    exported: list[str]
    skipped: list[str]

    def to_dict(self) -> dict[str, object]:
        return {"exported": self.exported, "skipped": self.skipped}


@dataclass(frozen=True)
class ImportResult:
    imported: list[str]
    skipped: list[str]
    conflicts: list[str]
    backup_dir: Path | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "imported": self.imported,
            "skipped": self.skipped,
            "conflicts": self.conflicts,
            "backup_dir": str(self.backup_dir) if self.backup_dir else None,
        }


@dataclass(frozen=True)
class SyncStatus:
    threads: list[dict[str, object]]

    def to_dict(self) -> dict[str, object]:
        return {"threads": self.threads}


@dataclass(frozen=True)
class SyncFileSnapshot:
    path: Path | None
    exists: bool
    sha256: str = ""
    size_bytes: int = 0
    updated_at: str = ""


@dataclass(frozen=True)
class LocalSyncState:
    thread_id: str
    sync_dir_fingerprint: str
    base_sha256: str
    base_size_bytes: int
    base_updated_at: str
    last_remote_sha256: str
    last_local_sha256: str
    source_relative_path: str
    project_key: str
    project_label: str
    synced_at: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LocalSyncState | None":
        thread_id = str(value.get("thread_id") or "").strip()
        fingerprint = str(value.get("sync_dir_fingerprint") or "").strip()
        base_sha256 = str(value.get("base_sha256") or "").strip()
        if not thread_id or not fingerprint or not base_sha256:
            return None
        return cls(
            thread_id=thread_id,
            sync_dir_fingerprint=fingerprint,
            base_sha256=base_sha256,
            base_size_bytes=int(value.get("base_size_bytes") or 0),
            base_updated_at=str(value.get("base_updated_at") or ""),
            last_remote_sha256=str(value.get("last_remote_sha256") or ""),
            last_local_sha256=str(value.get("last_local_sha256") or ""),
            source_relative_path=str(value.get("source_relative_path") or ""),
            project_key=str(value.get("project_key") or ""),
            project_label=str(value.get("project_label") or ""),
            synced_at=str(value.get("synced_at") or ""),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "sync_version": SYNC_VERSION,
            "thread_id": self.thread_id,
            "sync_dir_fingerprint": self.sync_dir_fingerprint,
            "base_sha256": self.base_sha256,
            "base_size_bytes": self.base_size_bytes,
            "base_updated_at": self.base_updated_at,
            "last_remote_sha256": self.last_remote_sha256,
            "last_local_sha256": self.last_local_sha256,
            "source_relative_path": self.source_relative_path,
            "project_key": self.project_key,
            "project_label": self.project_label,
            "synced_at": self.synced_at,
        }


@dataclass(frozen=True)
class SyncPlanItem:
    thread_id: str
    state: str
    action: str
    reason: str
    local_path: str
    remote_path: str
    local_sha256: str
    remote_sha256: str
    base_sha256: str
    updated_at: str
    source_relative_path: str
    project_key: str
    project_label: str
    memory_database_rows: int

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "thread_id": self.thread_id,
            "state": self.state,
            "action": self.action,
            "reason": self.reason,
            "local_path": self.local_path,
            "remote_path": self.remote_path,
            "local_sha256": self.local_sha256,
            "remote_sha256": self.remote_sha256,
            "base_sha256": self.base_sha256,
            "updated_at": self.updated_at,
            "source_relative_path": self.source_relative_path,
            "project_key": self.project_key,
            "project_label": self.project_label,
            "memory_database_rows": self.memory_database_rows,
        }
        if self.memory_database_rows:
            value["memory_note"] = "memory database rows detected, not synced by this beta"
        return value


def plan_sync(*, session_dirs: list[Path], sync_dir: Path, thread_ids: list[str]) -> SyncStatus:
    target_session_dir = session_dirs[0]
    local_threads = {thread.thread_id: thread for thread in list_threads(session_dirs)}
    statuses = [
        _plan_thread_sync(target_session_dir, sync_dir, thread_id, local_threads.get(thread_id)).to_dict()
        for thread_id in dedupe(thread_ids)
    ]
    return SyncStatus(threads=statuses)


def _plan_thread_sync(
    target_session_dir: Path,
    sync_dir: Path,
    thread_id: str,
    local_thread: ThreadInfo | None,
) -> SyncPlanItem:
    thread_dir = _thread_dir(sync_dir, thread_id)
    manifest = read_json_object(thread_dir / "manifest.json") or {}
    remote_path = thread_dir / "session.jsonl"
    relative_path = str(manifest.get("source_relative_path") or _fallback_session_relative_path(thread_id))
    manifest_target_path = _safe_session_target_path(target_session_dir, relative_path)
    local_path = local_thread.session_path if local_thread is not None else manifest_target_path
    local = _snapshot_file(local_path)
    remote = _snapshot_file(remote_path)
    state_record = _read_local_sync_state(target_session_dir, sync_dir, thread_id)
    base_hash = state_record.base_sha256 if state_record else ""
    local_changed = local.exists and (not base_hash or local.sha256 != base_hash)
    remote_changed = remote.exists and (not base_hash or remote.sha256 != base_hash)
    relation = _prefix_relationship(local, remote)

    if local.exists and remote.exists and local.sha256 == remote.sha256:
        state, action, reason = "synced", "none", "local and remote match"
    elif local.exists and not remote.exists:
        state, action, reason = "local_only", "push", "local conversation is not in the sync folder"
    elif remote.exists and not local.exists:
        state, action, reason = "remote_only", "pull", "sync folder conversation is not local"
    elif not local.exists and not remote.exists:
        state, action, reason = "missing", "skip", "conversation is missing locally and remotely"
    elif base_hash and local_changed and not remote_changed:
        state, action, reason = "local_ahead", "push", "local changed since last sync"
    elif base_hash and remote_changed and not local_changed:
        state, action, reason = "remote_ahead", "pull", "remote changed since last sync"
    elif relation == "remote_prefix_of_local":
        state, action, reason = "fast_forward_push", "push", "local extends remote"
    elif relation == "local_prefix_of_remote":
        state, action, reason = "fast_forward_pull", "pull", "remote extends local"
    else:
        state, action, reason = "conflict", "conflict", "local and remote diverged"

    project_key = local_thread.project_key if local_thread else str(manifest.get("project_key") or "")
    project_label = local_thread.project_label if local_thread else str(manifest.get("project_label") or "")
    return SyncPlanItem(
        thread_id=thread_id,
        state=state,
        action=action,
        reason=reason,
        local_path=str(local.path) if local.path else "",
        remote_path=str(remote.path) if remote.path else "",
        local_sha256=local.sha256,
        remote_sha256=remote.sha256,
        base_sha256=base_hash,
        updated_at=str(manifest.get("updated_at") or (local_thread.updated_at if local_thread else "")),
        source_relative_path=relative_path,
        project_key=project_key,
        project_label=project_label,
        memory_database_rows=_memory_row_count(target_session_dir, thread_id),
    )


def export_threads(
    *,
    session_dirs: list[Path],
    sync_dir: Path,
    thread_ids: list[str],
    machine_id: str,
) -> ExportResult:
    sync_dir.mkdir(parents=True, exist_ok=True)
    threads = {thread.thread_id: thread for thread in list_threads(session_dirs)}
    planned = {
        item["thread_id"]: item
        for item in plan_sync(session_dirs=session_dirs, sync_dir=sync_dir, thread_ids=thread_ids).threads
    }
    index_entries = load_all_index_entries(session_dirs)
    exported: list[str] = []
    skipped: list[str] = []

    for thread_id in dedupe(thread_ids):
        thread = threads.get(thread_id)
        if thread is None:
            skipped.append(thread_id)
            continue
        plan_item = planned.get(thread_id, {})
        if plan_item.get("action") not in {"push", "none"}:
            skipped.append(thread_id)
            continue
        thread_dir = _thread_dir(sync_dir, thread_id)
        thread_dir.mkdir(parents=True, exist_ok=True)
        session_dir = owning_session_dir(thread.session_path, session_dirs)
        relative_path = thread.session_path.relative_to(session_dir).as_posix()
        session_hash = sha256_file(thread.session_path)
        manifest = {
            "sync_version": SYNC_VERSION,
            "thread_id": thread_id,
            "session_sha256": session_hash,
            "session_size_bytes": thread.session_bytes,
            "exported_at": now_iso(),
            "updated_at": thread.updated_at,
            "machine_id": machine_id,
            "source_relative_path": relative_path,
            "project_key": thread.project_key,
            "project_label": thread.project_label,
        }
        metadata = thread.to_dict()
        metadata["source_relative_path"] = relative_path
        atomic_copy(thread.session_path, thread_dir / "session.jsonl")
        atomic_write_json(thread_dir / "manifest.json", manifest)
        atomic_write_json(thread_dir / "metadata.json", metadata)
        atomic_write_json(thread_dir / "index-entry.json", index_entries.get(thread_id, _default_index_entry(thread)))
        local_snapshot = _snapshot_file(thread.session_path)
        remote_snapshot = _snapshot_file(thread_dir / "session.jsonl")
        _write_local_sync_state(
            session_dir,
            sync_dir,
            thread_id=thread_id,
            local_snapshot=local_snapshot,
            remote_snapshot=remote_snapshot,
            source_relative_path=relative_path,
            project_key=thread.project_key,
            project_label=thread.project_label,
        )
        exported.append(thread_id)

    return ExportResult(exported=exported, skipped=skipped)


def import_threads(
    *,
    session_dirs: list[Path],
    sync_dir: Path,
    thread_ids: list[str],
    conflict_policy: str = "skip",
    backup_label: str | None = None,
) -> ImportResult:
    target_session_dir = session_dirs[0]
    target_home = codex_home_from_session_dir(target_session_dir)
    backup_dir = target_home / ".codex-sync-backups" / (backup_label or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ"))
    imported: list[str] = []
    skipped: list[str] = []
    conflicts: list[str] = []
    imported_entries: list[dict[str, Any]] = []
    backup_created = False
    local_threads = {thread.thread_id: thread for thread in list_threads([target_session_dir], auto_transitions=False)}
    planned = {
        item["thread_id"]: item
        for item in plan_sync(session_dirs=[target_session_dir], sync_dir=sync_dir, thread_ids=thread_ids).threads
    }

    for thread_id in dedupe(thread_ids):
        plan_item = planned.get(thread_id, {})
        action = str(plan_item.get("action") or "")
        if action == "conflict" and conflict_policy != "remote":
            save_conflict_candidate(
                backup_dir,
                _thread_storage_name(thread_id),
                _thread_dir(sync_dir, thread_id) / "session.jsonl",
            )
            conflicts.append(thread_id)
            continue
        if action not in {"pull", "none"} and conflict_policy != "remote":
            skipped.append(thread_id)
            continue
        thread_dir = _thread_dir(sync_dir, thread_id)
        manifest = read_json_object(thread_dir / "manifest.json")
        if manifest is None or not (thread_dir / "session.jsonl").is_file():
            skipped.append(thread_id)
            continue
        relative_path = str(manifest.get("source_relative_path") or _fallback_session_relative_path(thread_id))
        target_path = _safe_session_target_path(target_session_dir, relative_path)
        if target_path is None:
            skipped.append(thread_id)
            continue
        remote_hash = sha256_file(thread_dir / "session.jsonl")
        local_thread = local_threads.get(thread_id)
        local_thread_path = local_thread.session_path if local_thread is not None else None
        if local_thread_path is not None and not _same_path(local_thread_path, target_path):
            if conflict_policy != "remote" and action != "pull":
                save_conflict_candidate(backup_dir, _thread_storage_name(thread_id), thread_dir / "session.jsonl")
                conflicts.append(thread_id)
                continue
            target_path = local_thread_path

        local_exists = target_path.is_file()
        local_hash = sha256_file(target_path) if local_exists else ""
        if local_exists and local_hash != remote_hash and action not in {"pull", "none"} and conflict_policy != "remote":
            save_conflict_candidate(backup_dir, _thread_storage_name(thread_id), thread_dir / "session.jsonl")
            conflicts.append(thread_id)
            continue

        needs_session_copy = not (local_exists and local_hash == remote_hash)
        if needs_session_copy and local_exists:
            backup_file(target_path, _backup_thread_dir(backup_dir, thread_id) / "session.jsonl")
            backup_created = True
        if needs_session_copy:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_copy(thread_dir / "session.jsonl", target_path)
        local_snapshot = _snapshot_file(target_path)
        remote_snapshot = _snapshot_file(thread_dir / "session.jsonl")
        _write_local_sync_state(
            target_session_dir,
            sync_dir,
            thread_id=thread_id,
            local_snapshot=local_snapshot,
            remote_snapshot=remote_snapshot,
            source_relative_path=relative_path,
            project_key=str(plan_item.get("project_key") or manifest.get("project_key") or ""),
            project_label=str(plan_item.get("project_label") or manifest.get("project_label") or ""),
        )
        local_threads.pop(thread_id, None)
        index_entry = read_json_object(thread_dir / "index-entry.json")
        if index_entry is not None:
            imported_entries.append(index_entry)
        imported.append(thread_id)

    if imported_entries:
        _merge_index_entries(target_home / "session_index.jsonl", imported_entries, backup_dir)
        backup_created = True

    return ImportResult(
        imported=imported,
        skipped=skipped,
        conflicts=conflicts,
        backup_dir=backup_dir if backup_created or conflicts else None,
    )


def sync_status(*, session_dirs: list[Path], sync_dir: Path, thread_ids: list[str]) -> SyncStatus:
    return plan_sync(session_dirs=session_dirs, sync_dir=sync_dir, thread_ids=thread_ids)


def _sync_dir_fingerprint(sync_dir: Path) -> str:
    normalized = str(sync_dir.resolve(strict=False)).replace("\\", "/").casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _thread_storage_name(thread_id: str) -> str:
    value = thread_id.strip()
    stem = value.split(".", 1)[0].upper()
    if _SAFE_THREAD_STORAGE_RE.fullmatch(value) and stem not in _WINDOWS_RESERVED_NAMES:
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return f"id-{digest[:32]}"


def _thread_dir(sync_dir: Path, thread_id: str) -> Path:
    return sync_dir / "threads" / _thread_storage_name(thread_id)


def _backup_thread_dir(backup_dir: Path, thread_id: str) -> Path:
    return backup_dir / _thread_storage_name(thread_id)


def _sync_state_path(session_dir: Path, sync_dir: Path, thread_id: str) -> Path:
    return (
        codex_home_from_session_dir(session_dir)
        / ".codex-sync-state"
        / _sync_dir_fingerprint(sync_dir)
        / "threads"
        / f"{_thread_storage_name(thread_id)}.json"
    )


def _read_local_sync_state(session_dir: Path, sync_dir: Path, thread_id: str) -> LocalSyncState | None:
    value = read_json_object(_sync_state_path(session_dir, sync_dir, thread_id))
    if value is None:
        return None
    state = LocalSyncState.from_dict(value)
    if state is None or state.sync_dir_fingerprint != _sync_dir_fingerprint(sync_dir):
        return None
    return state


def _write_local_sync_state(
    session_dir: Path,
    sync_dir: Path,
    *,
    thread_id: str,
    local_snapshot: SyncFileSnapshot,
    remote_snapshot: SyncFileSnapshot,
    source_relative_path: str,
    project_key: str,
    project_label: str,
) -> None:
    base_hash = local_snapshot.sha256 or remote_snapshot.sha256
    if not base_hash:
        return
    state = LocalSyncState(
        thread_id=thread_id,
        sync_dir_fingerprint=_sync_dir_fingerprint(sync_dir),
        base_sha256=base_hash,
        base_size_bytes=local_snapshot.size_bytes or remote_snapshot.size_bytes,
        base_updated_at=local_snapshot.updated_at or remote_snapshot.updated_at,
        last_remote_sha256=remote_snapshot.sha256,
        last_local_sha256=local_snapshot.sha256,
        source_relative_path=source_relative_path,
        project_key=project_key,
        project_label=project_label,
        synced_at=now_iso(),
    )
    atomic_write_json(_sync_state_path(session_dir, sync_dir, thread_id), state.to_dict())


def _safe_session_target_path(session_dir: Path, relative_path: str) -> Path | None:
    value = relative_path.strip()
    if not value:
        return None

    windows_path = PureWindowsPath(value)
    posix_path = PurePosixPath(value)
    if windows_path.is_absolute() or windows_path.drive or posix_path.is_absolute():
        return None

    path = Path(value)
    if not path.parts or any(part == ".." for part in path.parts):
        return None

    root = session_dir.resolve(strict=False)
    target = (session_dir / path).resolve(strict=False)
    if target == root or root not in target.parents:
        return None
    return target


def _same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def _merge_index_entries(path: Path, new_entries: list[dict[str, Any]], backup_dir: Path) -> None:
    if path.is_file():
        backup_file(path, backup_dir / "session_index.jsonl")
    entries: dict[str, dict[str, Any]] = {}
    for entry in [*read_index_entries(path), *new_entries]:
        thread_id = str(entry.get("id") or "")
        if not thread_id:
            continue
        existing = entries.get(thread_id)
        if existing is None or timestamp_key(str(entry.get("updated_at") or "")) >= timestamp_key(
            str(existing.get("updated_at") or "")
        ):
            entries[thread_id] = entry
    ordered = sorted(entries.values(), key=lambda item: timestamp_key(str(item.get("updated_at") or "")))
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, "".join(json.dumps(entry, separators=(",", ":")) + "\n" for entry in ordered))


def _memory_row_count(session_dir: Path, thread_id: str) -> int:
    db_path = codex_home_from_session_dir(session_dir) / "state_5.sqlite"
    if not db_path.is_file():
        return 0
    try:
        con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            row = con.execute("select count(*) from stage1_outputs where thread_id = ?", (thread_id,)).fetchone()
        finally:
            con.close()
    except sqlite3.Error:
        return 0
    return int(row[0] if row else 0)


def _default_index_entry(thread: ThreadInfo) -> dict[str, str]:
    return {"id": thread.thread_id, "thread_name": thread.title, "updated_at": thread.updated_at}


def _fallback_session_relative_path(thread_id: str) -> str:
    return f"synced/{_thread_storage_name(thread_id)}.jsonl"


def _snapshot_file(path: Path | None) -> SyncFileSnapshot:
    if path is None or not path.is_file():
        return SyncFileSnapshot(path=path, exists=False)
    return SyncFileSnapshot(
        path=path,
        exists=True,
        sha256=sha256_file(path),
        size_bytes=file_size(path),
        updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"),
    )


def _is_byte_prefix(prefix_path: Path, full_path: Path) -> bool:
    prefix_size = prefix_path.stat().st_size
    full_size = full_path.stat().st_size
    if prefix_size > full_size:
        return False
    with prefix_path.open("rb") as prefix, full_path.open("rb") as full:
        while True:
            prefix_chunk = prefix.read(1024 * 1024)
            if not prefix_chunk:
                return True
            if full.read(len(prefix_chunk)) != prefix_chunk:
                return False


def _prefix_relationship(local: SyncFileSnapshot, remote: SyncFileSnapshot) -> str:
    if not local.path or not remote.path or not local.exists or not remote.exists:
        return ""
    if local.sha256 == remote.sha256:
        return "equal"
    if _is_byte_prefix(remote.path, local.path):
        return "remote_prefix_of_local"
    if _is_byte_prefix(local.path, remote.path):
        return "local_prefix_of_remote"
    return "diverged"



