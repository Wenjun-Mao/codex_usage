from __future__ import annotations

import os
from pathlib import Path


def candidate_session_dirs(
    *,
    codex_home: str | None = None,
    userprofile: str | None = None,
    home: Path | None = None,
) -> list[Path]:
    candidates: list[Path] = []
    if codex_home:
        candidates.append(Path(codex_home) / "sessions")
    if userprofile:
        candidates.append(Path(userprofile) / ".codex" / "sessions")

    base_home = home or Path.home()
    candidates.append(base_home / ".codex" / "sessions")
    return _dedupe_paths(candidates)


def find_session_dirs() -> list[Path]:
    codex_home = os.getenv("CODEX_HOME")
    candidates = candidate_session_dirs(
        codex_home=codex_home,
        userprofile=os.getenv("USERPROFILE"),
    )
    if codex_home:
        codex_home_sessions = candidates[0]
        if codex_home_sessions.is_dir():
            return [codex_home_sessions]
        raise FileNotFoundError(f"CODEX_HOME sessions directory does not exist or is not a directory: {codex_home_sessions}")

    for path in candidates:
        if path.is_dir():
            return [path]

    checked = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"No Codex sessions directory found. Checked: {checked}")


def default_session_dir() -> Path:
    return candidate_session_dirs(
        codex_home=os.getenv("CODEX_HOME"),
        userprofile=os.getenv("USERPROFILE"),
    )[0]


def collect_jsonl_files(session_dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for session_dir in session_dirs:
        files.extend(path for path in session_dir.rglob("*.jsonl") if path.is_file())
    return sorted(_dedupe_paths(files), key=lambda path: str(path).casefold())

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
