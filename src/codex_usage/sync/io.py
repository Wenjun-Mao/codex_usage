from __future__ import annotations

import errno
import hashlib
import json
import shutil
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from codex_usage.sync.errors import ConcurrentRemoteChangeError
from codex_usage.sync.models import SyncFileSnapshot


_TRANSIENT_ERRNOS = frozenset(
    {
        errno.EAGAIN,
        errno.EBUSY,
        errno.EINTR,
        errno.ETIMEDOUT,
        *(
            value
            for name in ("ESTALE", "ETXTBSY")
            if (value := getattr(errno, name, None)) is not None
        ),
    }
)
_TRANSIENT_WINERRORS = frozenset(
    {
        32,  # ERROR_SHARING_VIOLATION
        33,  # ERROR_LOCK_VIOLATION
        54,  # ERROR_NETWORK_BUSY
        121,  # ERROR_SEM_TIMEOUT
        170,  # ERROR_BUSY
        1237,  # ERROR_RETRY
    }
)
_PERMANENT_FILESYSTEM_ERRORS = (FileNotFoundError, PermissionError, NotADirectoryError, IsADirectoryError)


def _is_transient_filesystem_error(error: BaseException) -> bool:
    if not isinstance(error, OSError) or isinstance(error, FileNotFoundError):
        return False
    winerror = getattr(error, "winerror", None)
    if winerror is not None:
        return winerror in _TRANSIENT_WINERRORS
    if isinstance(error, _PERMANENT_FILESYSTEM_ERRORS):
        return False
    return error.errno in _TRANSIENT_ERRNOS


def snapshot_file(path: Path | None) -> SyncFileSnapshot:
    _, snapshot = read_bytes_with_snapshot(path)
    return snapshot


def read_bytes_with_snapshot(path: Path | None) -> tuple[bytes | None, SyncFileSnapshot]:
    if path is None:
        return None, SyncFileSnapshot(path=None, exists=False)
    try:
        contents = _read_bytes(path)
    except (FileNotFoundError, IsADirectoryError):
        return None, SyncFileSnapshot(path=path, exists=False)
    return contents, _snapshot_from_bytes(path, contents)


def read_json_object(path: Path) -> dict[str, Any] | None:
    value, _ = read_json_object_with_snapshot(path)
    return value


def read_json_object_with_snapshot(path: Path) -> tuple[dict[str, Any] | None, SyncFileSnapshot]:
    contents, snapshot = read_bytes_with_snapshot(path)
    if contents is None:
        return None, snapshot
    value = json.loads(contents)
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value, snapshot


def path_kind(path: Path) -> str:
    try:
        mode = _lstat(path).st_mode
    except FileNotFoundError:
        return "missing"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "file"
    return "other"


def list_directory(path: Path) -> tuple[Path, ...]:
    return _list_directory(path)


def atomic_copy(
    source: Path,
    target: Path,
    *,
    expected_target: SyncFileSnapshot | None = None,
    target_label: str = "file",
    path_guard: Callable[[], None] | None = None,
) -> SyncFileSnapshot:
    _make_directory(target.parent, path_guard=path_guard)
    tmp_path = _new_sibling_temp_path(target, path_guard=path_guard)
    try:
        _copy_file(source, tmp_path)
        copied = snapshot_file(tmp_path)
        if expected_target is None:
            _replace(tmp_path, target, path_guard=path_guard)
        else:
            _replace_if_expected(
                tmp_path,
                target,
                expected_target,
                target_label,
                path_guard=path_guard,
            )
        return _verify_replacement(target, copied, target_label, path_guard=path_guard)
    finally:
        if _temporary_path_is_safe(path_guard) and tmp_path.exists():
            tmp_path.unlink()


def atomic_write_json(
    path: Path,
    value: dict[str, Any],
    *,
    expected_target: SyncFileSnapshot | None = None,
    target_label: str = "file",
    path_guard: Callable[[], None] | None = None,
) -> SyncFileSnapshot:
    contents = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    _make_directory(path.parent, path_guard=path_guard)
    tmp_path = _new_sibling_temp_path(path, path_guard=path_guard)
    try:
        _write_bytes(tmp_path, contents)
        written = _snapshot_from_bytes(tmp_path, contents)
        if expected_target is None:
            _replace(tmp_path, path, path_guard=path_guard)
        else:
            _replace_if_expected(
                tmp_path,
                path,
                expected_target,
                target_label,
                path_guard=path_guard,
            )
        return _verify_replacement(path, written, target_label, path_guard=path_guard)
    finally:
        if _temporary_path_is_safe(path_guard) and tmp_path.exists():
            tmp_path.unlink()


def _snapshot_from_bytes(path: Path, contents: bytes) -> SyncFileSnapshot:
    return SyncFileSnapshot(
        path=path,
        exists=True,
        sha256=hashlib.sha256(contents).hexdigest(),
        size_bytes=len(contents),
    )


def _validate_expected_target(
    path: Path,
    expected: SyncFileSnapshot | None,
    target_label: str,
) -> None:
    if expected is not None and snapshot_file(path) != expected:
        raise ConcurrentRemoteChangeError(
            f"Remote {target_label} changed before {target_label} replacement"
        )


def _verify_replacement(
    path: Path,
    temporary_snapshot: SyncFileSnapshot,
    target_label: str,
    *,
    path_guard: Callable[[], None] | None = None,
) -> SyncFileSnapshot:
    expected = SyncFileSnapshot(
        path=path,
        exists=True,
        sha256=temporary_snapshot.sha256,
        size_bytes=temporary_snapshot.size_bytes,
    )
    _run_path_guard(path_guard)
    actual = snapshot_file(path)
    if actual != expected:
        raise ConcurrentRemoteChangeError(
            f"Remote {target_label} changed after {target_label} replacement"
        )
    return actual


def _temporary_path_is_safe(path_guard: Callable[[], None] | None) -> bool:
    # A swapped guarded parent is no longer safe to traverse for temp cleanup.
    try:
        _run_path_guard(path_guard)
    except Exception:
        return False
    return True


def _run_path_guard(path_guard: Callable[[], None] | None) -> None:
    if path_guard is not None:
        path_guard()


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _make_directory(
    path: Path,
    *,
    path_guard: Callable[[], None] | None = None,
) -> None:
    _run_path_guard(path_guard)
    path.mkdir(parents=True, exist_ok=True)


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _new_sibling_temp_path(
    target: Path,
    *,
    path_guard: Callable[[], None] | None = None,
) -> Path:
    _run_path_guard(path_guard)
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    ) as temporary:
        return Path(temporary.name)


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _lstat(path: Path) -> Any:
    return path.lstat()


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _list_directory(path: Path) -> tuple[Path, ...]:
    return tuple(path.iterdir())


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _write_bytes(path: Path, contents: bytes) -> None:
    path.write_bytes(contents)


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _copy_file(source: Path, target: Path) -> None:
    shutil.copyfile(source, target)


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _replace(
    source: Path,
    target: Path,
    *,
    path_guard: Callable[[], None] | None = None,
) -> None:
    _run_path_guard(path_guard)
    source.replace(target)


@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _replace_if_expected(
    source: Path,
    target: Path,
    expected_target: SyncFileSnapshot,
    target_label: str,
    *,
    path_guard: Callable[[], None] | None = None,
) -> None:
    _run_path_guard(path_guard)
    _validate_expected_target(target, expected_target, target_label)
    source.replace(target)
