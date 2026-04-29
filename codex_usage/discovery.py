from __future__ import annotations

import os
from pathlib import Path

from codex_usage.settings import AppSettings


def candidate_session_dirs(
    *,
    explicit: Path | None = None,
    configured: Path | None = None,
    codex_home: str | None = None,
    userprofile: str | None = None,
    home: Path | None = None,
) -> list[Path]:
    candidates: list[Path] = []
    if explicit is not None:
        candidates.append(explicit)
    if configured is not None:
        candidates.append(configured)
    if codex_home:
        candidates.append(Path(codex_home) / "sessions")
    if userprofile:
        candidates.append(Path(userprofile) / ".codex" / "sessions")

    base_home = home or Path.home()
    candidates.append(base_home / ".codex" / "sessions")
    return _dedupe_paths(candidates)


def find_session_dirs(explicit: str | Path | None, settings: AppSettings) -> list[Path]:
    explicit_path = Path(explicit).expanduser() if explicit else None
    configured_path = settings.sessions_dir.expanduser() if settings.sessions_dir else None

    if explicit_path is not None:
        return [_require_dir(explicit_path, "explicit sessions directory")]
    if configured_path is not None:
        return [_require_dir(configured_path, "configured sessions directory")]

    candidates = candidate_session_dirs(
        codex_home=os.getenv("CODEX_HOME"),
        userprofile=os.getenv("USERPROFILE"),
    )
    existing = [path for path in candidates if path.is_dir()]
    if existing:
        return existing

    checked = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"No Codex sessions directory found. Checked: {checked}")


def collect_jsonl_files(session_dirs: list[Path]) -> list[Path]:
    files: list[Path] = []
    for session_dir in session_dirs:
        files.extend(path for path in session_dir.rglob("*.jsonl") if path.is_file())
    return sorted(_dedupe_paths(files), key=lambda path: str(path).casefold())


def _require_dir(path: Path, label: str) -> Path:
    if not path.is_dir():
        raise FileNotFoundError(f"{label} does not exist or is not a directory: {path}")
    return path


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
