from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from codex_usage.sync.format_migration import migrate_remote_layout_v2_to_v3
from codex_usage.sync.errors import (
    ConcurrentRemoteChangeError,
    LegacySyncLayoutError,
    MalformedSyncIndexError,
    TransferFormatMigrationError,
)


def _session_payload(thread_id: str = "task-1") -> bytes:
    return (
        json.dumps(
            {
                "timestamp": "2026-07-15T00:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": thread_id,
                    "timestamp": "2026-07-15T00:00:00Z",
                    "cwd": "/source/project",
                },
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()


def _write_v2_index(root: Path, threads: dict[str, object]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "sync-index.json").write_text(
        json.dumps(
            {
                "format_version": 2,
                "updated_at": "2026-07-15T00:00:00Z",
                "threads": threads,
            }
        ),
        encoding="utf-8",
    )


def _v2_entry(thread_id: str, payload: bytes) -> dict[str, object]:
    return {
        "file": f"conversations/{thread_id}.jsonl",
        "source_relative_path": f"2026/07/15/{thread_id}.jsonl",
        "index_entry": {"id": thread_id, "thread_name": "Task one"},
        "project_key": "/source/project",
        "project_label": "project",
        "project_aliases": [],
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
        "session_updated_at": "2026-07-15T00:00:00Z",
        "exported_at": "2026-07-15T00:00:00Z",
        "source_machine_id": "source",
    }


def _write_v2_folder(root: Path, thread_id: str = "task-1") -> bytes:
    payload = _session_payload(thread_id)
    source = root / "conversations" / f"{thread_id}.jsonl"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    _write_v2_index(root, {thread_id: _v2_entry(thread_id, payload)})
    return payload


def _read_index(root: Path) -> dict[str, object]:
    return json.loads((root / "sync-index.json").read_text(encoding="utf-8"))


def test_migrates_valid_v2_folder_to_v3_tasks_layout(tmp_path: Path) -> None:
    payload = _write_v2_folder(tmp_path)

    result = migrate_remote_layout_v2_to_v3(tmp_path)
    index = _read_index(tmp_path)

    assert result.migrated is True
    assert result.cleaned_legacy is True
    assert index["format_version"] == 3
    assert index["threads"]["task-1"]["file"] == "tasks/task-1.jsonl"  # type: ignore[index]
    assert (tmp_path / "tasks" / "task-1.jsonl").read_bytes() == payload
    assert not (tmp_path / "conversations").exists()

    rerun = migrate_remote_layout_v2_to_v3(tmp_path)
    assert rerun.migrated is False
    assert rerun.cleaned_legacy is False


def test_failed_index_commit_leaves_v2_authoritative_and_rerun_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _write_v2_folder(tmp_path)
    from codex_usage.sync import format_migration

    real_write = format_migration.atomic_write_json
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated index failure")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(format_migration, "atomic_write_json", fail_once)
    with pytest.raises(OSError, match="simulated index failure"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert _read_index(tmp_path)["format_version"] == 2
    assert (tmp_path / "conversations" / "task-1.jsonl").read_bytes() == payload
    assert (tmp_path / "tasks" / "task-1.jsonl").read_bytes() == payload

    result = migrate_remote_layout_v2_to_v3(tmp_path)
    assert result.migrated is True
    assert _read_index(tmp_path)["format_version"] == 3


def test_legacy_directory_change_before_commit_keeps_v2_authoritative(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_v2_folder(tmp_path)
    from codex_usage.sync import format_migration

    real_stage = format_migration._stage_tasks

    def stage_then_add_legacy(*args, **kwargs):
        staged = real_stage(*args, **kwargs)
        (tmp_path / "conversations" / "late.jsonl").write_bytes(
            _session_payload("late-task")
        )
        return staged

    monkeypatch.setattr(format_migration, "_stage_tasks", stage_then_add_legacy)
    with pytest.raises(
        ConcurrentRemoteChangeError, match="changed before migration commit"
    ):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert _read_index(tmp_path)["format_version"] == 2
    assert (tmp_path / "conversations" / "late.jsonl").exists()
    assert (tmp_path / "tasks" / "task-1.jsonl").exists()


def test_conflicting_staged_task_blocks_without_overwrite(tmp_path: Path) -> None:
    source = _write_v2_folder(tmp_path)
    staged = tmp_path / "tasks" / "task-1.jsonl"
    staged.parent.mkdir()
    staged.write_bytes(b"different\n")

    with pytest.raises(TransferFormatMigrationError, match="tasks/task-1.jsonl"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert staged.read_bytes() == b"different\n"
    assert (tmp_path / "conversations" / "task-1.jsonl").read_bytes() == source
    assert _read_index(tmp_path)["format_version"] == 2


def test_post_commit_cleanup_failure_resumes_from_v3(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _write_v2_folder(tmp_path)
    legacy = tmp_path / "conversations" / "task-1.jsonl"
    real_unlink = Path.unlink
    failed = False

    def fail_legacy_unlink(path: Path, *args, **kwargs) -> None:
        nonlocal failed
        if path == legacy and not failed:
            failed = True
            raise OSError("simulated cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_legacy_unlink)
    with pytest.raises(OSError, match="simulated cleanup failure"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert _read_index(tmp_path)["format_version"] == 3
    assert legacy.read_bytes() == payload
    assert (tmp_path / "tasks" / "task-1.jsonl").read_bytes() == payload

    monkeypatch.setattr(Path, "unlink", real_unlink)
    result = migrate_remote_layout_v2_to_v3(tmp_path)
    assert result.migrated is False
    assert result.cleaned_legacy is True
    assert not legacy.parent.exists()


def test_matching_staged_task_is_reused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = _write_v2_folder(tmp_path)
    staged = tmp_path / "tasks" / "task-1.jsonl"
    staged.parent.mkdir()
    staged.write_bytes(payload)
    from codex_usage.sync import format_migration

    def unexpected_copy(*_args, **_kwargs):
        raise AssertionError("matching staged task must be reused")

    monkeypatch.setattr(format_migration, "atomic_copy", unexpected_copy)
    result = migrate_remote_layout_v2_to_v3(tmp_path)

    assert result.migrated is True
    assert staged.read_bytes() == payload


@pytest.mark.parametrize("conflict", ["different", "unrepresented"])
def test_v3_cleanup_conflict_preserves_both_directories(
    tmp_path: Path,
    conflict: str,
) -> None:
    payload = _write_v2_folder(tmp_path)
    migrate_remote_layout_v2_to_v3(tmp_path)
    legacy = tmp_path / "conversations"
    legacy.mkdir()
    if conflict == "different":
        (legacy / "task-1.jsonl").write_bytes(
            _session_payload("task-1") + b"different\n"
        )
    else:
        (legacy / "task-2.jsonl").write_bytes(_session_payload("task-2"))
    index_before = (tmp_path / "sync-index.json").read_bytes()

    with pytest.raises(TransferFormatMigrationError, match="conversations/"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert (tmp_path / "sync-index.json").read_bytes() == index_before
    assert (tmp_path / "tasks" / "task-1.jsonl").read_bytes() == payload
    assert legacy.exists()


@pytest.mark.parametrize("unsafe_path", ["conversations", "tasks"])
def test_symlinked_migration_directory_is_rejected_without_mutation(
    tmp_path: Path,
    unsafe_path: str,
) -> None:
    external = tmp_path / "external"
    external.mkdir()
    root = tmp_path / "sync"
    if unsafe_path == "conversations":
        _write_v2_index(root, {})
    else:
        _write_v2_folder(root)
    link = root / unsafe_path
    try:
        if link.exists():
            link.rmdir()
        link.symlink_to(external, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")
    index_before = (root / "sync-index.json").read_bytes()

    with pytest.raises(MalformedSyncIndexError, match=unsafe_path):
        migrate_remote_layout_v2_to_v3(root)

    assert (root / "sync-index.json").read_bytes() == index_before
    assert list(external.iterdir()) == []


def test_symlinked_legacy_file_is_rejected_without_mutation(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    payload = _write_v2_folder(root)
    source = root / "conversations" / "task-1.jsonl"
    external = tmp_path / "external.jsonl"
    external.write_bytes(payload)
    source.unlink()
    try:
        source.symlink_to(external)
    except OSError as error:
        pytest.skip(f"symlinks are unavailable: {error}")

    with pytest.raises(MalformedSyncIndexError, match="task-1.jsonl"):
        migrate_remote_layout_v2_to_v3(root)

    assert source.is_symlink()
    assert not (root / "tasks").exists()


def test_junction_like_directory_is_rejected_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "sync"
    _write_v2_folder(root)
    from codex_usage.sync import format_migration_layout

    real_path_kind = format_migration_layout.path_kind

    def junction_conversations(path: Path) -> str:
        if path == root / "conversations":
            return "junction"
        return real_path_kind(path)

    monkeypatch.setattr(format_migration_layout, "path_kind", junction_conversations)
    with pytest.raises(MalformedSyncIndexError, match="junction"):
        migrate_remote_layout_v2_to_v3(root)

    assert _read_index(root)["format_version"] == 2
    assert not (root / "tasks").exists()


def test_v2_index_path_traversal_is_rejected_without_mutation(tmp_path: Path) -> None:
    payload = _write_v2_folder(tmp_path)
    index = _read_index(tmp_path)
    index["threads"]["task-1"]["file"] = "../outside.jsonl"  # type: ignore[index]
    (tmp_path / "sync-index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(MalformedSyncIndexError, match="direct child"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert (tmp_path / "conversations" / "task-1.jsonl").read_bytes() == payload
    assert not (tmp_path / "tasks").exists()


def test_duplicate_v2_file_claims_are_rejected_without_mutation(tmp_path: Path) -> None:
    payload = _write_v2_folder(tmp_path)
    first = _v2_entry("task-1", payload)
    second = _v2_entry("task-2", payload)
    second["file"] = first["file"]
    _write_v2_index(tmp_path, {"task-1": first, "task-2": second})

    with pytest.raises(MalformedSyncIndexError, match="same remote file"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert not (tmp_path / "tasks").exists()


def test_missing_indexed_v2_file_blocks_without_mutation(tmp_path: Path) -> None:
    _write_v2_folder(tmp_path)
    (tmp_path / "conversations" / "task-1.jsonl").unlink()

    with pytest.raises(TransferFormatMigrationError, match="missing"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert _read_index(tmp_path)["format_version"] == 2
    assert not (tmp_path / "tasks").exists()


def test_wrong_indexed_task_identity_blocks_without_mutation(tmp_path: Path) -> None:
    _write_v2_folder(tmp_path)
    wrong = _session_payload("task-2")
    (tmp_path / "conversations" / "task-1.jsonl").write_bytes(wrong)
    index = _read_index(tmp_path)
    index["threads"]["task-1"].update(  # type: ignore[index, union-attr]
        sha256=hashlib.sha256(wrong).hexdigest(),
        size_bytes=len(wrong),
    )
    (tmp_path / "sync-index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(TransferFormatMigrationError, match="task-2"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert not (tmp_path / "tasks").exists()


@pytest.mark.parametrize("field", ["sha256", "size_bytes"])
def test_bad_indexed_fingerprint_blocks_without_mutation(
    tmp_path: Path, field: str
) -> None:
    _write_v2_folder(tmp_path)
    index = _read_index(tmp_path)
    entry = index["threads"]["task-1"]  # type: ignore[index]
    entry[field] = "bad-hash" if field == "sha256" else 1  # type: ignore[index]
    (tmp_path / "sync-index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(TransferFormatMigrationError, match=field):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert not (tmp_path / "tasks").exists()


def test_malformed_v2_jsonl_blocks_without_mutation(tmp_path: Path) -> None:
    malformed = b"{not-json\n"
    source = tmp_path / "conversations" / "task-1.jsonl"
    source.parent.mkdir()
    source.write_bytes(malformed)
    _write_v2_index(tmp_path, {"task-1": _v2_entry("task-1", malformed)})

    with pytest.raises(TransferFormatMigrationError, match="readable session_meta"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert source.read_bytes() == malformed
    assert not (tmp_path / "tasks").exists()


def test_malformed_index_json_is_rejected_without_mutation(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "sync-index.json").write_bytes(b"{not-json\n")

    with pytest.raises(MalformedSyncIndexError, match="Malformed sync-index.json"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert not (tmp_path / "tasks").exists()


def test_unindexed_readable_v2_jsonl_is_reconstructed_and_migrated(
    tmp_path: Path,
) -> None:
    _write_v2_index(tmp_path, {})
    source = tmp_path / "conversations" / "legacy-name.jsonl"
    source.parent.mkdir()
    payload = _session_payload("task-2")
    source.write_bytes(payload)

    result = migrate_remote_layout_v2_to_v3(tmp_path)
    index = _read_index(tmp_path)

    assert result.migrated is True
    assert index["threads"]["task-2"]["file"] == "tasks/task-2.jsonl"  # type: ignore[index]
    assert (tmp_path / "tasks" / "task-2.jsonl").read_bytes() == payload
    assert not source.parent.exists()


def test_unreadable_unindexed_v2_jsonl_blocks_without_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_v2_index(tmp_path, {})
    source = tmp_path / "conversations" / "task-1.jsonl"
    source.parent.mkdir()
    payload = _session_payload()
    source.write_bytes(payload)
    from codex_usage.sync import remote_reconciliation

    real_read = remote_reconciliation.read_bytes_with_snapshot

    def deny_source(path: Path):
        if path == source:
            raise PermissionError(f"Cannot read {path}")
        return real_read(path)

    monkeypatch.setattr(remote_reconciliation, "read_bytes_with_snapshot", deny_source)
    with pytest.raises(PermissionError, match="Cannot read"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert _read_index(tmp_path)["format_version"] == 2
    assert source.read_bytes() == payload
    assert not (tmp_path / "tasks").exists()


@pytest.mark.parametrize("with_threads_directory", [False, True])
def test_version_1_still_raises_legacy_layout_error_without_mutation(
    tmp_path: Path,
    with_threads_directory: bool,
) -> None:
    _write_v2_index(tmp_path, {})
    index = _read_index(tmp_path)
    index["format_version"] = 1
    (tmp_path / "sync-index.json").write_text(json.dumps(index), encoding="utf-8")
    if with_threads_directory:
        (tmp_path / "threads").mkdir()
    before = (tmp_path / "sync-index.json").read_bytes()

    with pytest.raises(LegacySyncLayoutError):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert (tmp_path / "sync-index.json").read_bytes() == before
    assert not (tmp_path / "tasks").exists()


def test_version_4_is_rejected_as_unsupported_without_mutation(tmp_path: Path) -> None:
    _write_v2_index(tmp_path, {})
    index = _read_index(tmp_path)
    index["format_version"] = 4
    (tmp_path / "sync-index.json").write_text(json.dumps(index), encoding="utf-8")
    before = (tmp_path / "sync-index.json").read_bytes()

    with pytest.raises(MalformedSyncIndexError, match="Unsupported.*format.*4"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert (tmp_path / "sync-index.json").read_bytes() == before
    assert not (tmp_path / "tasks").exists()
