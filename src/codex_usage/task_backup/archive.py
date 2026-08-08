from __future__ import annotations

import hashlib
import io
import json
import os
import platform
import stat
import tarfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

import zstandard
from filelock import FileLock, Timeout

from codex_usage import __version__
from codex_usage.task_backup.filesystem import open_binary_read
from codex_usage.task_backup.inventory import source_identity
from codex_usage.task_backup.models import (
    BACKUP_SUFFIX,
    MANIFEST_MEMBER,
    SESSION_INDEX_MEMBER,
    BackupFileManifest,
    BackupManifest,
    BackupResult,
    BackupSelection,
    BackupSource,
    CompressionManifest,
    CompressionPreset,
    SessionIndexManifest,
    SourceIdentity,
    TaskTreeManifest,
)
from codex_usage.task_backup.progress import (
    BackupProgress,
    ProgressCallback,
    ThrottledProgress,
    ignore_progress,
)
from codex_usage.task_backup.verification import verify_task_backup


_COMPRESSION_LEVELS: dict[CompressionPreset, int] = {
    "maximum": 19,
    "balanced": 9,
}


class BackupCreationError(RuntimeError):
    pass


def create_task_backup(
    selection: BackupSelection,
    output_path: Path,
    *,
    refresh_selection: Callable[[], BackupSelection],
    compression: CompressionPreset = "maximum",
    replace_existing: bool = False,
    progress: ProgressCallback = ignore_progress,
    lock_path: Path | None = None,
) -> BackupResult:
    target = _validate_output_path(output_path, replace_existing=replace_existing)
    selected_level = _compression_level(compression)
    operation_lock = FileLock(
        str(lock_path or target.parent / ".codex-task-backup.lock"),
        timeout=0,
    )
    try:
        operation_lock.acquire()
    except Timeout as error:
        raise BackupCreationError("Another task backup is already running") from error

    partial = target.with_name(f".{target.name}.{uuid.uuid4().hex}.partial")
    try:
        _assert_sources_unchanged(selection.sources)
        progress(BackupProgress("preparing", 0, selection.source_bytes, 0, len(selection.sources)))
        _write_archive(
            selection,
            partial,
            compression=compression,
            level=selected_level,
            progress=progress,
        )
        verification = verify_task_backup(partial, progress=progress)
        _assert_sources_unchanged(selection.sources)
        if refresh_selection() != selection:
            raise BackupCreationError(
                "Task tree membership or selected metadata changed during backup"
            )
        if verification.manifest.task_tree.tree_id != selection.tree_id:
            raise BackupCreationError("Verified archive did not retain the selected task tree")
        _commit_archive(partial, target, replace_existing=replace_existing)
        return BackupResult(
            archive_path=target,
            source_bytes=verification.manifest.source_bytes,
            archive_bytes=target.stat().st_size,
            file_count=verification.manifest.physical_file_count,
            recovery_ready=verification.manifest.task_tree.recovery_ready,
            warnings=verification.warnings,
            archive_sha256=verification.archive_sha256,
            compression=verification.manifest.compression.preset,
        )
    except BackupCreationError:
        raise
    except Exception as error:
        raise BackupCreationError(f"Task backup failed: {error}") from error
    finally:
        operation_lock.release()
        _remove_partial(partial)


def _write_archive(
    selection: BackupSelection,
    partial: Path,
    *,
    compression: CompressionPreset,
    level: int,
    progress: ProgressCallback,
) -> None:
    compressed_progress = ThrottledProgress(
        progress,
        phase="compressing",
        total_bytes=selection.source_bytes,
        file_count=len(selection.sources),
    )
    file_manifests: list[BackupFileManifest] = []
    index_digest = hashlib.sha256(selection.session_index_bytes).hexdigest()
    with partial.open("xb") as raw_output:
        compressor = zstandard.ZstdCompressor(
            level=level,
            threads=0,
            write_checksum=True,
            write_content_size=False,
        )
        with compressor.stream_writer(raw_output, closefd=False) as compressed_output:
            with tarfile.open(
                fileobj=compressed_output,
                mode="w|",
                format=tarfile.PAX_FORMAT,
            ) as archive:
                for index, source in enumerate(selection.sources, start=1):
                    compressed_progress.begin_file(index)
                    file_manifests.append(
                        _add_source_member(archive, source, compressed_progress)
                    )
                _add_bytes_member(
                    archive,
                    SESSION_INDEX_MEMBER,
                    selection.session_index_bytes,
                )
                manifest = _build_manifest(
                    selection,
                    compression=compression,
                    level=level,
                    files=file_manifests,
                    index_digest=index_digest,
                )
                manifest_bytes = (
                    json.dumps(
                        manifest.model_dump(mode="json"),
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
                _add_bytes_member(archive, MANIFEST_MEMBER, manifest_bytes)
        raw_output.flush()
        os.fsync(raw_output.fileno())
    compressed_progress.finish()


def _add_source_member(
    archive: tarfile.TarFile,
    source: BackupSource,
    progress: ThrottledProgress,
) -> BackupFileManifest:
    try:
        with open_binary_read(source.path) as handle:
            before = _identity_from_handle(handle)
            if before != source.identity:
                raise BackupCreationError(
                    f"Task file changed before it could be read: {source.path}"
                )
            reader = _HashingReader(handle, source.identity.size_bytes, progress)
            archive.addfile(_tar_info(source.archive_member, source.identity.size_bytes), reader)
            if reader.remaining:
                raise BackupCreationError(
                    f"Task file ended before its captured size: {source.path}"
                )
            after = _identity_from_handle(handle)
            if after != source.identity:
                raise BackupCreationError(
                    f"Task file changed while it was being read: {source.path}"
                )
    except OSError as error:
        raise BackupCreationError(f"Task file could not be read: {source.path}") from error
    _assert_source_unchanged(source)
    return BackupFileManifest(
        member=source.archive_member,
        task_id=source.task_id,
        parent_task_id=source.parent_task_id,
        usage_role=source.usage_role,
        storage_state=source.storage_state,
        original_relative_path=source.original_relative_path,
        size_bytes=source.identity.size_bytes,
        mtime_ns=source.identity.mtime_ns,
        sha256=reader.hexdigest,
    )


def _build_manifest(
    selection: BackupSelection,
    *,
    compression: CompressionPreset,
    level: int,
    files: list[BackupFileManifest],
    index_digest: str,
) -> BackupManifest:
    return BackupManifest(
        created_at=datetime.now(UTC).isoformat(),
        producer="codex-usage",
        producer_version=__version__,
        source_platform=f"{platform.system()}-{platform.machine()}",
        compression=CompressionManifest(preset=compression, level=level),
        task_tree=TaskTreeManifest(
            tree_id=selection.tree_id,
            root_task_id=selection.root_task_id,
            title=selection.title,
            project_key=selection.project_key,
            project_label=selection.project_label,
            project_aliases=list(selection.project_aliases),
            recovery_ready=selection.recovery_ready,
            diagnostics=list(selection.diagnostics),
        ),
        source_bytes=selection.source_bytes,
        physical_file_count=len(files),
        files=files,
        session_index=SessionIndexManifest(
            entry_count=selection.session_index_entry_count,
            size_bytes=len(selection.session_index_bytes),
            sha256=index_digest,
        ),
    )


def _add_bytes_member(archive: tarfile.TarFile, name: str, contents: bytes) -> None:
    archive.addfile(_tar_info(name, len(contents)), io.BytesIO(contents))


def _tar_info(name: str, size: int) -> tarfile.TarInfo:
    info = tarfile.TarInfo(name)
    info.size = size
    info.mode = 0o600
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    info.type = tarfile.REGTYPE
    return info


def _compression_level(preset: CompressionPreset) -> int:
    try:
        return _COMPRESSION_LEVELS[preset]
    except KeyError as error:
        raise BackupCreationError(f"Unknown compression preset: {preset}") from error


def _validate_output_path(path: Path, *, replace_existing: bool) -> Path:
    target = path.expanduser().absolute()
    if not target.name.endswith(BACKUP_SUFFIX):
        raise BackupCreationError(f"Backup output must end with {BACKUP_SUFFIX}")
    if not target.parent.is_dir():
        raise BackupCreationError(f"Backup destination directory does not exist: {target.parent}")
    if target.exists() and not replace_existing:
        raise BackupCreationError(f"Backup output already exists: {target}")
    if target.exists() and not target.is_file():
        raise BackupCreationError(f"Backup output is not a regular file: {target}")
    if target.is_symlink():
        raise BackupCreationError(f"Backup output cannot be a symbolic link: {target}")
    return target


def _commit_archive(partial: Path, target: Path, *, replace_existing: bool) -> None:
    if target.exists() and not replace_existing:
        raise BackupCreationError(f"Backup output appeared before publication: {target}")
    if target.is_symlink() or (target.exists() and not target.is_file()):
        raise BackupCreationError(f"Backup output became unsafe before publication: {target}")
    os.replace(partial, target)
    _fsync_directory(target.parent)


def _fsync_directory(directory: Path) -> None:
    flags = getattr(os, "O_DIRECTORY", 0) | os.O_RDONLY
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _assert_sources_unchanged(sources: tuple[BackupSource, ...]) -> None:
    for source in sources:
        _assert_source_unchanged(source)


def _assert_source_unchanged(source: BackupSource) -> None:
    try:
        path_stat = source.path.lstat()
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise BackupCreationError(f"Task file path changed type: {source.path}")
        observed = source_identity(source.path)
    except OSError as error:
        raise BackupCreationError(f"Task file became unavailable: {source.path}") from error
    if observed != source.identity:
        raise BackupCreationError(f"Task file changed during backup: {source.path}")


def _identity_from_handle(handle: io.BufferedReader) -> SourceIdentity:
    value = os.fstat(handle.fileno())
    return SourceIdentity(
        size_bytes=int(value.st_size),
        mtime_ns=int(value.st_mtime_ns),
        source_device=int(value.st_dev),
        source_inode=int(value.st_ino),
    )


def _remove_partial(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass


class _HashingReader:
    def __init__(
        self,
        handle: io.BufferedReader,
        size_bytes: int,
        progress: ThrottledProgress,
    ) -> None:
        self._handle = handle
        self._remaining = size_bytes
        self._digest = hashlib.sha256()
        self._progress = progress

    @property
    def remaining(self) -> int:
        return self._remaining

    @property
    def hexdigest(self) -> str:
        return self._digest.hexdigest()

    def read(self, size: int = -1) -> bytes:
        requested = self._remaining if size < 0 else min(size, self._remaining)
        if requested <= 0:
            return b""
        chunk = self._handle.read(requested)
        self._remaining -= len(chunk)
        self._digest.update(chunk)
        self._progress.advance(len(chunk))
        return chunk
