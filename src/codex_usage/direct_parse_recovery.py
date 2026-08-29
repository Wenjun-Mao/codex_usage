from __future__ import annotations

import hashlib
import os
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from codex_usage.models import UsageRecord
from codex_usage.parser import finalize_session_records
from codex_usage.session_inventory import (
    ARCHIVED_SESSION_DIR_NAME,
    ACTIVE_SESSION_DIR_NAME,
    SessionFileInventoryEntry,
    collect_session_file_inventory,
    session_file_key,
)


@dataclass(frozen=True, slots=True)
class DirectParseTarget:
    path: Path
    file_key: str


@dataclass(frozen=True, slots=True)
class DirectParseResult:
    records: list[UsageRecord]
    files: list[Path]


def build_direct_parse_targets(
    paths: Sequence[Path],
    inventory: Iterable[SessionFileInventoryEntry],
    session_dirs: Sequence[Path],
) -> list[DirectParseTarget]:
    """Bind the path snapshot to stable session identities before parsing."""
    entries = tuple(inventory)
    targets: list[DirectParseTarget] = []
    for path in paths:
        entry = _entry_for_path(path, entries, session_dirs)
        file_key = entry.file_key if entry is not None else _identity_for_path(path)
        targets.append(DirectParseTarget(path=path, file_key=file_key))
    return targets


def parse_direct_files(
    targets: Sequence[DirectParseTarget],
    *,
    session_dirs: Sequence[Path],
    parse_file: Callable[[Path], Iterable[UsageRecord]],
) -> DirectParseResult:
    """Parse a fallback snapshot, relocating only a target that disappeared."""
    records_by_file: list[list[UsageRecord]] = []
    resolved_files: list[Path] = []
    for target in targets:
        path = target.path
        try:
            parsed = list(parse_file(path))
        except FileNotFoundError as error:
            relocated_path = _find_relocated_path(target, session_dirs)
            if relocated_path is None:
                raise FileNotFoundError(
                    f"direct parse target disappeared and identity-aware relocation "
                    f"discovery found no replacement: {target.path} "
                    f"(file key {target.file_key})"
                ) from error
            try:
                parsed = list(parse_file(relocated_path))
            except FileNotFoundError as relocated_error:
                raise FileNotFoundError(
                    f"direct parse target disappeared during relocation recovery: "
                    f"{relocated_path} (file key {target.file_key})"
                ) from relocated_error
            path = relocated_path

        records_by_file.append(_records_for_path(parsed, path))
        resolved_files.append(path)

    return DirectParseResult(
        records=finalize_session_records(records_by_file),
        files=resolved_files,
    )


def _entry_for_path(
    path: Path,
    entries: Sequence[SessionFileInventoryEntry],
    session_dirs: Sequence[Path],
) -> SessionFileInventoryEntry | None:
    exact = [entry for entry in entries if entry.path == path]
    if len(exact) == 1:
        return exact[0]

    matches = [
        entry
        for entry in entries
        if _same_session_location(path, entry.path, session_dirs, entry.session_dir)
    ]
    return matches[0] if len(matches) == 1 else None


def _same_session_location(
    path: Path,
    entry_path: Path,
    session_dirs: Sequence[Path],
    entry_session_dir: Path,
) -> bool:
    entry_location = _relative_session_location(entry_path, (entry_session_dir,))
    if entry_location is None:
        return False
    for session_dir in session_dirs:
        path_location = _relative_session_location(path, (session_dir,))
        if path_location == entry_location:
            return True
    return False


def _relative_session_location(
    path: Path,
    session_dirs: Sequence[Path],
) -> tuple[Path, Path] | None:
    for session_dir in session_dirs:
        try:
            relative = path.relative_to(session_dir)
        except ValueError:
            continue
        root = (
            session_dir.parent
            if session_dir.name.casefold()
            in {ACTIVE_SESSION_DIR_NAME, ARCHIVED_SESSION_DIR_NAME}
            else session_dir
        )
        return root, relative
    return None


def _identity_for_path(path: Path) -> str:
    try:
        return session_file_key(path)
    except OSError:
        normalized = os.path.normcase(
            os.path.normpath(os.path.abspath(os.path.expanduser(path)))
        ).replace("\\", "/")
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        return f"codex-usage:direct-parse:path:{digest}"


def _find_relocated_path(
    target: DirectParseTarget,
    session_dirs: Sequence[Path],
) -> Path | None:
    fresh_inventory = collect_session_file_inventory(
        list(session_dirs), read_metadata=True
    )
    for entry in fresh_inventory:
        if entry.file_key == target.file_key:
            return entry.path
    return None


def _records_for_path(
    records: Sequence[UsageRecord],
    path: Path,
) -> list[UsageRecord]:
    """Keep compatibility with single-file parser adapters that over-return rows."""
    scoped = [record for record in records if record.file_path == path]
    return scoped if scoped else list(records)
