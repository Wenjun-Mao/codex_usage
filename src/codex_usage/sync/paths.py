from __future__ import annotations

import hashlib
import re
from pathlib import Path, PurePosixPath, PureWindowsPath


_SAFE_THREAD_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}")
WINDOWS_RESERVED_NAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
    }
)


def portable_thread_filename(thread_id: str) -> str:
    value = thread_id.strip()
    stem = value.split(".", 1)[0].upper()
    if value == value.casefold() and _SAFE_THREAD_ID.fullmatch(value) and stem not in WINDOWS_RESERVED_NAMES:
        return f"{value}.jsonl"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"id-{digest}.jsonl"


def safe_session_target_path(session_dir: Path, relative_path: str) -> Path | None:
    value = relative_path.strip()
    if not value:
        return None

    windows_path = PureWindowsPath(value)
    posix_path = PurePosixPath(value.replace("\\", "/"))
    if windows_path.is_absolute() or windows_path.drive or windows_path.root or posix_path.is_absolute():
        return None
    if not posix_path.parts or any(part == ".." for part in (*windows_path.parts, *posix_path.parts)):
        return None

    root = session_dir.resolve(strict=False)
    target = (session_dir / Path(*posix_path.parts)).resolve(strict=False)
    if target == root or root not in target.parents:
        return None
    return target
