from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from codex_usage.sync.models import SyncFileSnapshot


def snapshot_file(path: Path | None) -> SyncFileSnapshot:
    if path is None or not path.is_file():
        return SyncFileSnapshot(path=path, exists=False)
    contents = _read_bytes(path)
    return SyncFileSnapshot(
        path=path,
        exists=True,
        sha256=hashlib.sha256(contents).hexdigest(),
        size_bytes=len(contents),
    )


def read_json_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(_read_bytes(path))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def atomic_copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _new_sibling_temp_path(target)
    try:
        _copy_file(source, tmp_path)
        _replace(tmp_path, target)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    contents = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = _new_sibling_temp_path(path)
    try:
        _write_bytes(tmp_path, contents)
        _replace(tmp_path, path)
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _new_sibling_temp_path(target: Path) -> Path:
    with tempfile.NamedTemporaryFile(
        delete=False,
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    ) as temporary:
        return Path(temporary.name)


@retry(
    retry=retry_if_exception_type(OSError),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


@retry(
    retry=retry_if_exception_type(OSError),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _write_bytes(path: Path, contents: bytes) -> None:
    path.write_bytes(contents)


@retry(
    retry=retry_if_exception_type(OSError),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _copy_file(source: Path, target: Path) -> None:
    shutil.copyfile(source, target)


@retry(
    retry=retry_if_exception_type(OSError),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def _replace(source: Path, target: Path) -> None:
    source.replace(target)
