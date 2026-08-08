from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Protocol

from codex_usage.session_inventory import (
    StorageRootSnapshot,
    storage_state_for_session_dir,
)
from codex_usage.storage_metadata import StorageFile


@dataclass(frozen=True, slots=True)
class StorageRootContribution:
    path: str
    storage_state: str
    file_count: int
    total_bytes: int


class _TreeWithStorageRoots(Protocol):
    storage_root_contributions: tuple[StorageRootContribution, ...]


def build_storage_roots(
    files: tuple[StorageFile, ...], session_dirs: list[Path]
) -> tuple[StorageRootSnapshot, ...]:
    files_by_session_dir: dict[str, list[StorageFile]] = defaultdict(list)
    for file in files:
        files_by_session_dir[file.session_dir].append(file)
    paths = {str(session_dir): session_dir for session_dir in session_dirs}
    paths.update({path: Path(path) for path in files_by_session_dir})
    roots = [
        StorageRootSnapshot(
            path=path,
            storage_state=storage_state_for_session_dir(path),
            exists=path.is_dir(),
            jsonl_count=len(files_by_session_dir.get(path_text, [])),
            total_bytes=sum(
                file.size_bytes for file in files_by_session_dir.get(path_text, [])
            ),
        )
        for path_text, path in paths.items()
    ]
    return tuple(sorted(roots, key=lambda root: str(root.path).casefold()))


def storage_root_contributions(
    files: list[StorageFile],
) -> tuple[StorageRootContribution, ...]:
    grouped: dict[tuple[str, str], list[StorageFile]] = defaultdict(list)
    for file in files:
        grouped[(file.session_dir, file.storage_state)].append(file)
    return tuple(
        StorageRootContribution(
            path=path,
            storage_state=storage_state,
            file_count=len(root_files),
            total_bytes=sum(file.size_bytes for file in root_files),
        )
        for (path, storage_state), root_files in sorted(grouped.items())
    )


def filter_storage_roots(
    roots: tuple[StorageRootSnapshot, ...],
    trees: Iterable[_TreeWithStorageRoots],
) -> tuple[StorageRootSnapshot, ...]:
    totals: dict[str, tuple[int, int]] = {}
    for tree in trees:
        for contribution in tree.storage_root_contributions:
            count, total_bytes = totals.get(contribution.path, (0, 0))
            totals[contribution.path] = (
                count + contribution.file_count,
                total_bytes + contribution.total_bytes,
            )
    return tuple(
        replace(
            root,
            jsonl_count=totals.get(str(root.path), (0, 0))[0],
            total_bytes=totals.get(str(root.path), (0, 0))[1],
        )
        for root in roots
    )
