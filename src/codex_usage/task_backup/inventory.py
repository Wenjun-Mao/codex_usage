from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from codex_usage.session_files import session_index_path_for_session_dir
from codex_usage.storage_context import StorageContext
from codex_usage.storage_insights import TaskStorageTree
from codex_usage.storage_metadata import StorageFile
from codex_usage.task_backup.filesystem import (
    is_transient_filesystem_error,
    stat_path,
)
from codex_usage.task_backup.models import (
    MAX_SESSION_INDEX_BYTES,
    MAX_SESSION_INDEX_LINE_BYTES,
    BackupSelection,
    BackupSource,
    SourceIdentity,
)


class BackupSelectionError(RuntimeError):
    pass


def select_backup_tree(context: StorageContext, tree_id: str) -> BackupSelection:
    selected_id = tree_id.strip()
    tree = next(
        (
            candidate
            for candidate in context.insights.task_trees
            if candidate.root_task_id == selected_id
        ),
        None,
    )
    if tree is None:
        raise BackupSelectionError(f"Task storage tree was not found: {selected_id}")
    if not tree.storage_files:
        raise BackupSelectionError(f"Task storage tree has no present files: {selected_id}")

    sources = tuple(
        _backup_source(file, index)
        for index, file in enumerate(tree.storage_files, start=1)
    )
    task_ids = {source.task_id for source in sources}
    session_index_bytes, entry_count = _selected_session_index(
        {source.session_dir for source in sources},
        task_ids,
    )
    corpus_metadata_diagnostics = {
        file.metadata_diagnostic
        for file in context.files
        if file.metadata_diagnostic
    }
    diagnostics = set(_tree_diagnostics(tree))
    if corpus_metadata_diagnostics:
        diagnostics.add("corpus_task_metadata_unresolved")
    return BackupSelection(
        tree_id=tree.root_task_id,
        root_task_id=tree.root_task_id,
        title=tree.title,
        project_key=tree.project_key,
        project_label=tree.project_label,
        project_aliases=tree.project_aliases,
        recovery_ready=tree.recovery_ready and not corpus_metadata_diagnostics,
        diagnostics=tuple(sorted(diagnostics)),
        sources=sources,
        session_index_bytes=session_index_bytes,
        session_index_entry_count=entry_count,
    )


def _backup_source(file: StorageFile, index: int) -> BackupSource:
    path = Path(file.path)
    session_dir = Path(file.session_dir)
    _validate_source_path(path, session_dir)
    identity = _identity_from_stat(stat_path(path))
    expected_size = file.size_bytes
    expected_mtime = file.mtime_ns
    if (identity.size_bytes, identity.mtime_ns) != (expected_size, expected_mtime):
        raise BackupSelectionError(
            f"Task file changed while preparing the backup: {path}"
        )
    relative_path = _source_relative_path(path, session_dir)
    return BackupSource(
        path=path,
        session_dir=session_dir,
        storage_state=file.storage_state,
        original_relative_path=relative_path,
        archive_member=f"payload/{index:06d}.jsonl",
        task_id=file.task_id,
        parent_task_id=file.parent_task_id,
        usage_role=file.usage_role,
        identity=identity,
    )


def _validate_source_path(path: Path, session_dir: Path) -> None:
    try:
        root = session_dir.resolve(strict=True)
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise BackupSelectionError(f"Task file is unavailable: {path}") from error
    if resolved == root or root not in resolved.parents:
        raise BackupSelectionError(f"Task file is outside its Codex storage root: {path}")
    current = path
    while current != session_dir:
        try:
            path_stat = current.lstat()
        except OSError as error:
            raise BackupSelectionError(f"Task file is unavailable: {path}") from error
        if stat.S_ISLNK(path_stat.st_mode) or _is_mount_point_reparse(path_stat):
            raise BackupSelectionError(f"Task file path contains a link or junction: {path}")
        if current.parent == current:
            raise BackupSelectionError(f"Task file path is not rooted in Codex storage: {path}")
        current = current.parent
    if not stat.S_ISREG(path.lstat().st_mode):
        raise BackupSelectionError(f"Task backup accepts regular JSONL files only: {path}")


def _is_mount_point_reparse(path_stat: os.stat_result) -> bool:
    mount_tag = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", None)
    return bool(
        mount_tag is not None
        and getattr(path_stat, "st_reparse_tag", None) == mount_tag
    )


def _source_relative_path(path: Path, session_dir: Path) -> str:
    codex_home = session_dir.parent
    try:
        relative = path.relative_to(codex_home)
    except ValueError as error:
        raise BackupSelectionError(
            f"Task file has no safe Codex-relative path: {path}"
        ) from error
    if relative.is_absolute() or ".." in relative.parts:
        raise BackupSelectionError(f"Task file has an unsafe relative path: {path}")
    return relative.as_posix()


def _identity_from_stat(value: os.stat_result) -> SourceIdentity:
    return SourceIdentity(
        size_bytes=int(value.st_size),
        mtime_ns=int(value.st_mtime_ns),
        source_device=int(value.st_dev),
        source_inode=int(value.st_ino),
    )


def _tree_diagnostics(tree: TaskStorageTree) -> tuple[str, ...]:
    diagnostics = set(tree.diagnostics)
    if tree.has_missing_root:
        diagnostics.add("task_root_missing")
    return tuple(sorted(diagnostics))


def _selected_session_index(
    session_dirs: set[Path],
    task_ids: set[str],
) -> tuple[bytes, int]:
    selected = bytearray()
    entry_count = 0
    index_paths = sorted(
        {session_index_path_for_session_dir(path) for path in session_dirs},
        key=lambda path: str(path).casefold(),
    )
    for index_path in index_paths:
        contents, count = _read_selected_index_lines(
            index_path,
            task_ids,
            max_bytes=MAX_SESSION_INDEX_BYTES - len(selected),
        )
        selected.extend(contents)
        entry_count += count
    return bytes(selected), entry_count


@retry(
    retry=retry_if_exception(is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _read_selected_index_lines(
    path: Path,
    task_ids: set[str],
    *,
    max_bytes: int,
) -> tuple[bytes, int]:
    selected = bytearray()
    entry_count = 0
    try:
        with path.open("rb") as handle:
            while raw_line := handle.readline(MAX_SESSION_INDEX_LINE_BYTES + 1):
                if len(raw_line) > MAX_SESSION_INDEX_LINE_BYTES:
                    raise BackupSelectionError(
                        "Session index contains a line larger than the backup metadata limit"
                    )
                try:
                    value = json.loads(raw_line)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if (
                    isinstance(value, dict)
                    and str(value.get("id") or "") in task_ids
                ):
                    normalized = raw_line.rstrip(b"\r\n") + b"\n"
                    if len(selected) + len(normalized) > max_bytes:
                        raise BackupSelectionError(
                            "Selected session-index metadata exceeds the 64 MiB backup limit"
                        )
                    selected.extend(normalized)
                    entry_count += 1
    except FileNotFoundError:
        return b"", 0
    return bytes(selected), entry_count


def source_identity(path: Path) -> SourceIdentity:
    return _identity_from_stat(stat_path(path))
