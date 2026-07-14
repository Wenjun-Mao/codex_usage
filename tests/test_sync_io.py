from __future__ import annotations

import errno
from pathlib import Path
from typing import Any

import pytest

import codex_usage.sync.io as sync_io
from codex_usage.sync.io import snapshot_file


def test_streaming_prefix_retries_transient_read_from_both_stream_starts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix_path = tmp_path / "prefix.jsonl"
    full_path = tmp_path / "full.jsonl"
    prefix_path.write_bytes(b"base")
    full_path.write_bytes(b"base+tail")
    prefix = snapshot_file(prefix_path)
    full = snapshot_file(full_path)
    original_open = Path.open
    open_counts = {prefix_path: 0, full_path: 0}
    injected_failure = False

    class TransientReadProxy:
        def __init__(self, wrapped: Any, fail_read: bool) -> None:
            self._wrapped = wrapped
            self._fail_read = fail_read

        def __enter__(self) -> TransientReadProxy:
            return self

        def __exit__(self, *_args: object) -> None:
            self._wrapped.close()

        def read(self, size: int = -1) -> bytes:
            nonlocal injected_failure
            if self._fail_read:
                self._fail_read = False
                injected_failure = True
                raise OSError(errno.EBUSY, "cloud file is temporarily busy")
            return self._wrapped.read(size)

    def transient_open(path: Path, mode: str = "r", *args: object, **kwargs: object) -> Any:
        opened = original_open(path, mode, *args, **kwargs)
        if path not in open_counts or mode != "rb":
            return opened
        open_counts[path] += 1
        return TransientReadProxy(opened, path == prefix_path and open_counts[path] == 1)

    monkeypatch.setattr(Path, "open", transient_open)

    assert sync_io.is_byte_prefix(prefix, full)
    assert injected_failure
    assert open_counts == {prefix_path: 2, full_path: 2}


def test_streaming_prefix_attempts_permanent_open_error_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prefix_path = tmp_path / "prefix.jsonl"
    full_path = tmp_path / "full.jsonl"
    prefix_path.write_bytes(b"base")
    full_path.write_bytes(b"base+tail")
    prefix = snapshot_file(prefix_path)
    full = snapshot_file(full_path)
    original_open = Path.open
    attempts = 0

    def denied_open(path: Path, mode: str = "r", *args: object, **kwargs: object) -> Any:
        nonlocal attempts
        if path == prefix_path and mode == "rb":
            attempts += 1
            raise PermissionError("denied")
        return original_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", denied_open)

    with pytest.raises(PermissionError, match="denied"):
        sync_io.is_byte_prefix(prefix, full)
    assert attempts == 1
