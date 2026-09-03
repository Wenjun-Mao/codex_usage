from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path


_secured_directories: set[str] = set()
_secured_files: set[str] = set()
_security_lock = threading.Lock()


def ensure_private_directory(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        path.chmod(0o700)
        return
    key = _path_key(path)
    with _security_lock:
        if key in _secured_directories:
            return
        _apply_windows_acl(path, directory=True)
        _secured_directories.add(key)


def ensure_private_file(path: Path) -> None:
    if not path.is_file():
        return
    if os.name != "nt":
        path.chmod(0o600)
        return
    key = _path_key(path)
    with _security_lock:
        if key in _secured_files:
            return
        _apply_windows_acl(path, directory=False)
        _secured_files.add(key)


def ensure_private_sqlite_files(path: Path) -> None:
    ensure_private_directory(path.parent)
    for suffix in ("", "-wal", "-shm"):
        ensure_private_file(path.with_name(path.name + suffix))


def windows_acl_command(
    path: Path,
    *,
    account: str,
    directory: bool,
) -> tuple[str, ...]:
    if not account:
        raise ValueError("Windows account is required for private local state")
    rights = "(OI)(CI)F" if directory else "F"
    return (
        "icacls.exe",
        str(path),
        "/inheritance:r",
        "/grant:r",
        f"{account}:{rights}",
        "/Q",
    )


def _apply_windows_acl(path: Path, *, directory: bool) -> None:
    account = _current_windows_account()
    result = subprocess.run(
        windows_acl_command(path, account=account, directory=directory),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            result.stderr.strip()
            or result.stdout.strip()
            or f"could not secure local state at {path}"
        )


def _current_windows_account() -> str:
    result = subprocess.run(
        ["whoami.exe"],
        capture_output=True,
        text=True,
        check=False,
    )
    account = result.stdout.strip()
    if result.returncode != 0 or not account:
        raise RuntimeError(
            result.stderr.strip() or "could not identify the current Windows account"
        )
    return account


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.expanduser().resolve()))
