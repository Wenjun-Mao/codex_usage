from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from codex_usage.session_files import read_session_metadata


ACTIVE_SESSION_DIR_NAME = "sessions"
ARCHIVED_SESSION_DIR_NAME = "archived_sessions"


@dataclass(frozen=True)
class SessionFileInventoryEntry:
    file_key: str
    path: Path
    session_dir: Path
    storage_state: str
    size_bytes: int
    mtime_ns: int


@dataclass(frozen=True)
class StorageRootSnapshot:
    path: Path
    storage_state: str
    exists: bool
    jsonl_count: int
    total_bytes: int


def candidate_session_dirs(
    *,
    codex_home: str | None = None,
    userprofile: str | None = None,
    home: Path | None = None,
) -> list[Path]:
    candidates: list[Path] = []
    for base in _candidate_codex_homes(codex_home=codex_home, userprofile=userprofile, home=home):
        candidates.append(base / ACTIVE_SESSION_DIR_NAME)
        candidates.append(base / ARCHIVED_SESSION_DIR_NAME)
    return _dedupe_paths(candidates)


def find_session_dirs() -> list[Path]:
    codex_home = os.getenv("CODEX_HOME")
    candidates = (
        candidate_session_dirs(codex_home=codex_home)
        if codex_home
        else candidate_session_dirs(userprofile=os.getenv("USERPROFILE"))
    )
    existing = [path for path in candidates if path.is_dir()]
    if existing:
        return existing
    checked = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"No Codex sessions directory found. Checked: {checked}")


def default_session_dir() -> Path:
    codex_home = os.getenv("CODEX_HOME", "").strip()
    if codex_home:
        return Path(codex_home).expanduser() / ACTIVE_SESSION_DIR_NAME
    userprofile = os.getenv("USERPROFILE", "").strip()
    if userprofile:
        return Path(userprofile).expanduser() / ".codex" / ACTIVE_SESSION_DIR_NAME
    return Path.home() / ".codex" / ACTIVE_SESSION_DIR_NAME


def collect_session_file_inventory(session_dirs: list[Path]) -> list[SessionFileInventoryEntry]:
    selected: dict[str, SessionFileInventoryEntry] = {}
    for session_dir in session_dirs:
        for path in sorted(session_dir.rglob("*.jsonl"), key=lambda item: str(item).casefold()):
            if not path.is_file():
                continue
            stat = path.stat()
            entry = SessionFileInventoryEntry(
                file_key=session_file_key(path),
                path=path,
                session_dir=session_dir,
                storage_state=storage_state_for_session_dir(session_dir),
                size_bytes=stat.st_size,
                mtime_ns=stat.st_mtime_ns,
            )
            existing = selected.get(entry.file_key)
            if existing is None or _inventory_priority(entry) < _inventory_priority(existing):
                selected[entry.file_key] = entry
    return sorted(selected.values(), key=lambda entry: str(entry.path).casefold())


def collect_jsonl_files(session_dirs: list[Path]) -> list[Path]:
    return [entry.path for entry in collect_session_file_inventory(session_dirs)]


def session_file_key(path: Path) -> str:
    metadata = read_session_metadata(path)
    if metadata and metadata.session_id:
        return metadata.session_id
    return path.stem


def storage_state_for_session_dir(session_dir: Path) -> str:
    name = session_dir.name.casefold()
    if name == ARCHIVED_SESSION_DIR_NAME:
        return "archived"
    if name == ACTIVE_SESSION_DIR_NAME:
        return "active"
    return "other"


def storage_snapshots() -> list[StorageRootSnapshot]:
    roots: list[StorageRootSnapshot] = []
    codex_home = os.getenv("CODEX_HOME")
    codex_homes = (
        _candidate_codex_homes(codex_home=codex_home)
        if codex_home
        else _candidate_codex_homes(userprofile=os.getenv("USERPROFILE"))
    )
    for codex_home in codex_homes:
        names = [ACTIVE_SESSION_DIR_NAME, ARCHIVED_SESSION_DIR_NAME]
        if codex_home.is_dir():
            names.extend(
                child.name
                for child in codex_home.iterdir()
                if child.is_dir() and child.name.endswith("_sessions") and child.name not in names
            )
        for name in dict.fromkeys(names):
            path = codex_home / name
            files = list(path.rglob("*.jsonl")) if path.is_dir() else []
            roots.append(
                StorageRootSnapshot(
                    path=path,
                    storage_state="active"
                    if name == ACTIVE_SESSION_DIR_NAME
                    else ("archived" if name == ARCHIVED_SESSION_DIR_NAME else name),
                    exists=path.is_dir(),
                    jsonl_count=len(files),
                    total_bytes=sum(file.stat().st_size for file in files if file.is_file()),
                )
            )
    return roots


def _candidate_codex_homes(
    *,
    codex_home: str | None = None,
    userprofile: str | None = None,
    home: Path | None = None,
) -> list[Path]:
    candidates: list[Path] = []
    if codex_home:
        candidates.append(Path(codex_home).expanduser())
    if userprofile:
        candidates.append(Path(userprofile).expanduser() / ".codex")
    if home is not None:
        candidates.append(home / ".codex")
    elif not codex_home:
        candidates.append(Path.home() / ".codex")
    return _dedupe_paths(candidates)


def _inventory_priority(entry: SessionFileInventoryEntry) -> tuple[int, int, str]:
    state_priority = 0 if entry.storage_state == "active" else 1 if entry.storage_state == "archived" else 2
    return (state_priority, -entry.mtime_ns, str(entry.path).casefold())


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        expanded = path.expanduser()
        key = str(expanded).rstrip("\\/").casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(expanded)
    return out
