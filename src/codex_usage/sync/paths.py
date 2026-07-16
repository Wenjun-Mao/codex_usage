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
        "CONIN$",
        "CONOUT$",
        *(f"COM{number}" for number in range(1, 10)),
        *(f"LPT{number}" for number in range(1, 10)),
        *(f"COM{number}" for number in "¹²³"),
        *(f"LPT{number}" for number in "¹²³"),
    }
)
_WINDOWS_INVALID_CHARACTERS = frozenset('<>:"\\|?*')


def portable_thread_filename(thread_id: str) -> str:
    value = thread_id.strip()
    stem = value.split(".", 1)[0].upper()
    if value == value.casefold() and _SAFE_THREAD_ID.fullmatch(value) and stem not in WINDOWS_RESERVED_NAMES:
        return f"{value}.jsonl"
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]
    return f"id-{digest}.jsonl"


def safe_session_target_path(session_dir: Path, relative_path: str) -> Path | None:
    if not is_portable_session_relative_path(relative_path):
        return None

    value = relative_path
    windows_path = PureWindowsPath(value)
    posix_path = PurePosixPath(value)
    if windows_path.is_absolute() or windows_path.drive or windows_path.root or posix_path.is_absolute():
        return None

    root = session_dir.resolve(strict=False)
    target = (session_dir / Path(*posix_path.parts)).resolve(strict=False)
    if target == root or root not in target.parents:
        return None
    return target


def is_portable_session_relative_path(value: str) -> bool:
    if not value or value != value.strip() or "\\" in value:
        return False
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    if (
        posix_path.is_absolute()
        or windows_path.is_absolute()
        or windows_path.drive
        or windows_path.root
        or posix_path.as_posix() != value
        or not posix_path.parts
    ):
        return False
    if any(not _is_portable_windows_component(part) for part in posix_path.parts):
        return False
    leaf = posix_path.name
    return leaf.endswith(".jsonl") and len(leaf) > len(".jsonl")


def is_direct_task_path(value: str, directory: str) -> bool:
    posix_path = PurePosixPath(value)
    return (
        value == value.strip()
        and "\\" not in value
        and not posix_path.is_absolute()
        and posix_path.as_posix() == value
        and posix_path.parts == (directory, posix_path.name)
        and is_direct_jsonl_filename(posix_path.name)
    )


def is_direct_jsonl_filename(value: str) -> bool:
    posix_path = PurePosixPath(value)
    windows_path = PureWindowsPath(value)
    return (
        value == value.strip()
        and bool(value)
        and "\\" not in value
        and not posix_path.is_absolute()
        and not windows_path.is_absolute()
        and not windows_path.drive
        and len(posix_path.parts) == 1
        and len(windows_path.parts) == 1
        and posix_path.name == value
        and posix_path.suffix == ".jsonl"
        and portable_thread_filename(posix_path.stem) == value
    )


def _is_portable_windows_component(value: str) -> bool:
    if value in {"", ".", ".."} or value.endswith((".", " ")):
        return False
    if any(ord(character) < 32 or character in _WINDOWS_INVALID_CHARACTERS for character in value):
        return False
    basename = value.split(".", 1)[0].upper()
    return basename not in WINDOWS_RESERVED_NAMES
