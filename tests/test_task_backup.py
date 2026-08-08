from __future__ import annotations

import hashlib
import io
import json
import tarfile
from collections.abc import Callable
from pathlib import Path

import pytest
import zstandard

import codex_usage.storage_metadata as storage_metadata
import codex_usage.task_backup.inventory as backup_inventory
from codex_usage.session_files import SessionMetadataRead
from codex_usage.storage_context import load_storage_context
from codex_usage.task_backup import (
    create_task_backup,
    select_backup_tree,
    verify_task_backup,
)
from codex_usage.task_backup.archive import BackupCreationError
from codex_usage.task_backup.inventory import BackupSelectionError
from codex_usage.task_backup.verification import BackupVerificationError


def test_backup_preserves_complete_physical_tree_and_verifies(tmp_path: Path) -> None:
    home = _codex_home(tmp_path)
    root = _write_task(home, "root", body="side-chat-content")
    child = _write_task(home, "child", parent_id="root", body="descendant")
    archived = _write_task(home, "root", archived=True, suffix="copy", body="archived")
    _write_index(home, [{"id": "root", "thread_name": "Backup me"}, {"id": "child"}])
    context = load_storage_context(
        session_dirs=[home / "sessions", home / "archived_sessions"],
        cache_dir=tmp_path / "cache",
    )

    selection = select_backup_tree(context, "root")
    assert [source.path for source in selection.sources] == sorted(
        [root, child, archived], key=lambda path: str(path).casefold()
    )
    assert selection.session_index_entry_count == 2
    output = tmp_path / "root.codex-task-backup"
    result = create_task_backup(
        selection,
        output,
        refresh_selection=lambda: selection,
        compression="balanced",
        lock_path=tmp_path / "backup.lock",
    )

    verified = verify_task_backup(output)
    assert result.recovery_ready is True
    assert verified.manifest.task_tree.title == "Backup me"
    assert verified.manifest.physical_file_count == 3
    assert verified.manifest.source_bytes == sum(path.stat().st_size for path in (root, child, archived))
    assert {entry.storage_state for entry in verified.manifest.files} == {"active", "archived"}
    assert {entry.task_id for entry in verified.manifest.files} == {"root", "child"}
    assert all(not entry.original_relative_path.startswith(str(home)) for entry in verified.manifest.files)
    assert result.archive_sha256 == hashlib.sha256(output.read_bytes()).hexdigest()


@pytest.mark.parametrize("compression,level", [("maximum", 19), ("balanced", 9)])
def test_backup_supports_both_compression_presets(
    tmp_path: Path, compression: str, level: int
) -> None:
    home = _codex_home(tmp_path)
    _write_task(home, "root", body="repeated" * 10_000)
    context = load_storage_context(
        session_dirs=[home / "sessions"], cache_dir=tmp_path / "cache"
    )
    selection = select_backup_tree(context, "root")
    output = tmp_path / f"{compression}.codex-task-backup"

    create_task_backup(
        selection,
        output,
        refresh_selection=lambda: selection,
        compression=compression,  # type: ignore[arg-type]
        lock_path=tmp_path / "backup.lock",
    )

    assert verify_task_backup(output).manifest.compression.level == level


def test_backup_aborts_when_source_changes_and_preserves_existing_target(
    tmp_path: Path,
) -> None:
    home = _codex_home(tmp_path)
    source = _write_task(home, "root", body="stable")
    context = load_storage_context(
        session_dirs=[home / "sessions"], cache_dir=tmp_path / "cache"
    )
    selection = select_backup_tree(context, "root")
    output = tmp_path / "existing.codex-task-backup"
    output.write_bytes(b"previous verified backup")
    changed = False

    def mutate(progress: object) -> None:
        nonlocal changed
        completed = int(getattr(progress, "completed_bytes"))
        phase = str(getattr(progress, "phase"))
        if phase == "compressing" and completed > 0 and not changed:
            with source.open("ab") as handle:
                handle.write(b"changed")
            changed = True

    with pytest.raises(BackupCreationError, match="changed"):
        create_task_backup(
            selection,
            output,
            refresh_selection=lambda: selection,
            compression="balanced",
            replace_existing=True,
            progress=mutate,
            lock_path=tmp_path / "backup.lock",
        )

    assert output.read_bytes() == b"previous verified backup"
    assert not list(tmp_path.glob(".*.partial"))


def test_missing_root_creates_verified_salvage_backup(tmp_path: Path) -> None:
    home = _codex_home(tmp_path)
    _write_task(home, "child", parent_id="missing-root", body="salvage")
    context = load_storage_context(
        session_dirs=[home / "sessions"], cache_dir=tmp_path / "cache"
    )
    selection = select_backup_tree(context, "missing:missing-root")
    output = tmp_path / "salvage.codex-task-backup"

    result = create_task_backup(
        selection,
        output,
        refresh_selection=lambda: selection,
        compression="balanced",
        lock_path=tmp_path / "backup.lock",
    )

    assert result.recovery_ready is False
    assert "task_root_missing" in result.warnings
    assert verify_task_backup(output).manifest.task_tree.recovery_ready is False


def test_verify_rejects_corrupted_archive(tmp_path: Path) -> None:
    home = _codex_home(tmp_path)
    _write_task(home, "root", body="payload" * 1_000)
    context = load_storage_context(
        session_dirs=[home / "sessions"], cache_dir=tmp_path / "cache"
    )
    output = tmp_path / "root.codex-task-backup"
    selection = select_backup_tree(context, "root")
    create_task_backup(
        selection,
        output,
        refresh_selection=lambda: selection,
        compression="balanced",
        lock_path=tmp_path / "backup.lock",
    )
    contents = bytearray(output.read_bytes())
    contents[len(contents) // 2] ^= 0xFF
    output.write_bytes(contents)

    with pytest.raises(BackupVerificationError, match="damaged"):
        verify_task_backup(output)


@pytest.mark.parametrize(
    "corruption",
    ["nonzero_tar_suffix", "missing_tar_terminator", "second_zstd_frame"],
)
def test_verify_rejects_noncanonical_archive_termination(
    tmp_path: Path,
    corruption: str,
) -> None:
    source = _create_small_backup(tmp_path)
    altered = tmp_path / f"{corruption}.codex-task-backup"
    if corruption == "second_zstd_frame":
        altered.write_bytes(
            source.read_bytes()
            + zstandard.ZstdCompressor(level=1).compress(b"another frame")
        )
    else:
        tar_bytes = _decompress_archive(source)
        if corruption == "nonzero_tar_suffix":
            corrupted_tar = tar_bytes + b"unexpected trailing bytes"
        else:
            corrupted_tar = tar_bytes[:_final_member_end(tar_bytes)]
        _compress_tar(corrupted_tar, altered)

    with pytest.raises(
        BackupVerificationError,
        match="termination|non-zero|trailing compressed|zstd frame",
    ):
        verify_task_backup(altered)


def test_verify_rejects_global_pax_metadata(tmp_path: Path) -> None:
    source = _create_small_backup(tmp_path)
    altered = tmp_path / "global-pax.codex-task-backup"
    _rewrite_manifest(
        source,
        altered,
        lambda _manifest: None,
        global_pax_headers={"comment": "not canonical"},
    )

    with pytest.raises(BackupVerificationError, match="PAX metadata"):
        verify_task_backup(altered)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda manifest: manifest.__setitem__("format_version", 2), "manifest is invalid"),
        (
            lambda manifest: manifest["files"][0].update(
                {"usage_role": "root", "parent_task_id": ""}
            ),
            "unrelated root",
        ),
        (
            lambda manifest: manifest["files"][0].update(
                {"original_relative_path": "../outside.jsonl"}
            ),
            "unsafe source path",
        ),
    ],
)
def test_verify_rejects_unsupported_or_unsafe_manifests(
    tmp_path: Path,
    mutate: Callable[[dict[str, object]], None],
    message: str,
) -> None:
    home = _codex_home(tmp_path)
    _write_task(home, "root", body="root")
    _write_task(home, "child", parent_id="root", body="child")
    context = load_storage_context(
        session_dirs=[home / "sessions"], cache_dir=tmp_path / "cache"
    )
    selection = select_backup_tree(context, "root")
    source = tmp_path / "source.codex-task-backup"
    create_task_backup(
        selection,
        source,
        refresh_selection=lambda: selection,
        compression="balanced",
        lock_path=tmp_path / "backup.lock",
    )
    altered = tmp_path / "altered.codex-task-backup"
    _rewrite_manifest(source, altered, mutate)

    with pytest.raises(BackupVerificationError, match=message):
        verify_task_backup(altered)


def test_selection_rejects_unknown_tree(tmp_path: Path) -> None:
    home = _codex_home(tmp_path)
    _write_task(home, "root")
    context = load_storage_context(
        session_dirs=[home / "sessions"], cache_dir=tmp_path / "cache"
    )
    with pytest.raises(BackupSelectionError, match="not found"):
        select_backup_tree(context, "unknown")


def test_unresolved_corpus_metadata_prevents_recovery_ready_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _codex_home(tmp_path)
    root = _write_task(home, "root")
    child = _write_task(home, "child", parent_id="root")
    original_read = storage_metadata.read_session_metadata_bounded

    def unreadable_child(path: Path):
        if path == child:
            return SessionMetadataRead(None, "session_meta_unreadable")
        return original_read(path)

    monkeypatch.setattr(
        storage_metadata,
        "read_session_metadata_bounded",
        unreadable_child,
    )
    context = load_storage_context(
        session_dirs=[home / "sessions"], cache_dir=tmp_path / "cache"
    )

    selection = select_backup_tree(context, "root")
    assert [source.path for source in selection.sources] == [root]
    assert selection.recovery_ready is False
    assert "corpus_task_metadata_unresolved" in selection.diagnostics


def test_selection_bounds_session_index_before_archive_creation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    home = _codex_home(tmp_path)
    _write_task(home, "root")
    _write_index(
        home,
        [
            {"id": "root", "thread_name": "x" * 48},
            {"id": "root", "thread_name": "y" * 48},
        ],
    )
    context = load_storage_context(
        session_dirs=[home / "sessions"], cache_dir=tmp_path / "cache"
    )
    monkeypatch.setattr(backup_inventory, "MAX_SESSION_INDEX_BYTES", 64)

    with pytest.raises(BackupSelectionError, match="64 MiB"):
        select_backup_tree(context, "root")


def test_backup_aborts_when_task_tree_gains_a_new_descendant(tmp_path: Path) -> None:
    home = _codex_home(tmp_path)
    _write_task(home, "root", body="stable root")
    cache_dir = tmp_path / "cache"
    context = load_storage_context(
        session_dirs=[home / "sessions"], cache_dir=cache_dir
    )
    selection = select_backup_tree(context, "root")
    output = tmp_path / "drift.codex-task-backup"

    def refresh():
        _write_task(home, "late-child", parent_id="root", body="arrived during backup")
        return select_backup_tree(
            load_storage_context(
                session_dirs=[home / "sessions"], cache_dir=cache_dir
            ),
            "root",
        )

    with pytest.raises(BackupCreationError, match="membership"):
        create_task_backup(
            selection,
            output,
            refresh_selection=refresh,
            compression="balanced",
            lock_path=tmp_path / "backup.lock",
        )

    assert not output.exists()
    assert not list(tmp_path.glob(".*.partial"))


def _codex_home(tmp_path: Path) -> Path:
    home = tmp_path / ".codex"
    (home / "sessions").mkdir(parents=True)
    (home / "archived_sessions").mkdir(parents=True)
    return home


def _write_task(
    home: Path,
    task_id: str,
    *,
    parent_id: str = "",
    archived: bool = False,
    suffix: str = "",
    body: str = "payload",
) -> Path:
    root = home / ("archived_sessions" if archived else "sessions")
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{task_id}{('-' + suffix) if suffix else ''}.jsonl"
    payload: dict[str, object] = {
        "id": task_id,
        "cwd": "/projects/example",
        "timestamp": "2026-08-07T00:00:00Z",
    }
    if parent_id:
        payload["source"] = {
            "subagent": {"thread_spawn": {"parent_thread_id": parent_id}}
        }
    rows = [
        {
            "timestamp": "2026-08-07T00:00:00Z",
            "type": "session_meta",
            "payload": payload,
        },
        {"type": "response_item", "payload": {"text": body}},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _write_index(home: Path, entries: list[dict[str, object]]) -> None:
    (home / "session_index.jsonl").write_text(
        "".join(json.dumps(entry) + "\n" for entry in entries),
        encoding="utf-8",
    )


def _rewrite_manifest(
    source: Path,
    output: Path,
    mutate: Callable[[dict[str, object]], None],
    *,
    global_pax_headers: dict[str, str] | None = None,
) -> None:
    members: list[tuple[str, bytes]] = []
    with source.open("rb") as raw_input:
        with zstandard.ZstdDecompressor().stream_reader(raw_input) as uncompressed:
            with tarfile.open(fileobj=uncompressed, mode="r|") as archive:
                for member in archive:
                    handle = archive.extractfile(member)
                    assert handle is not None
                    members.append((member.name, handle.read()))
    manifest = json.loads(members[-1][1])
    assert isinstance(manifest, dict)
    mutate(manifest)
    members[-1] = (
        members[-1][0],
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )
    with output.open("wb") as raw_output:
        with zstandard.ZstdCompressor(
            level=9, write_checksum=True, write_content_size=False
        ).stream_writer(raw_output, closefd=False) as compressed:
            with tarfile.open(
                fileobj=compressed,
                mode="w|",
                format=tarfile.PAX_FORMAT,
                pax_headers=global_pax_headers,
            ) as archive:
                for name, contents in members:
                    info = tarfile.TarInfo(name)
                    info.size = len(contents)
                    info.mode = 0o600
                    info.uid = 0
                    info.gid = 0
                    info.mtime = 0
                    archive.addfile(info, io.BytesIO(contents))


def _create_small_backup(tmp_path: Path) -> Path:
    home = _codex_home(tmp_path)
    _write_task(home, "root", body="verified")
    context = load_storage_context(
        session_dirs=[home / "sessions"], cache_dir=tmp_path / "cache"
    )
    selection = select_backup_tree(context, "root")
    output = tmp_path / "source.codex-task-backup"
    create_task_backup(
        selection,
        output,
        refresh_selection=lambda: selection,
        compression="balanced",
        lock_path=tmp_path / "backup.lock",
    )
    return output


def _decompress_archive(source: Path) -> bytes:
    return zstandard.ZstdDecompressor().decompress(
        source.read_bytes(),
        max_output_size=16 * 1024 * 1024,
    )


def _compress_tar(contents: bytes, output: Path) -> None:
    output.write_bytes(zstandard.ZstdCompressor(level=9).compress(contents))


def _final_member_end(contents: bytes) -> int:
    with tarfile.open(fileobj=io.BytesIO(contents), mode="r:") as archive:
        members = archive.getmembers()
    final = members[-1]
    logical_end = final.offset_data + final.size
    return (
        (logical_end + tarfile.BLOCKSIZE - 1) // tarfile.BLOCKSIZE
    ) * tarfile.BLOCKSIZE
