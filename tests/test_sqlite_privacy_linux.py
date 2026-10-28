"""Legacy libc fallback must use path-only descriptors, never regular opens."""
import os
import subprocess
import sys

import pytest

from codex_usage import agent_private_files as private
from test_sqlite_privacy_locks import PROBE


def old_libc(monkeypatch):
    original = os.chmod

    def chmod(path, mode, **kwargs):
        if kwargs.get('follow_symlinks') is False:
            raise NotImplementedError('older libc lacks no-follow chmod')
        return original(path, mode, **kwargs)

    monkeypatch.setattr(private.os, 'chmod', chmod)


def test_legacy_libc_fallback_preserves_live_record_lock_or_fails_closed(tmp_path, monkeypatch):
    path = tmp_path/'database'
    path.write_bytes(b'fixture')
    old_libc(monkeypatch)
    if not hasattr(os, 'O_PATH'):
        with pytest.raises(NotImplementedError):
            private._chmod_nonsymlink(path, 0o600)
        return
    import fcntl
    descriptor = os.open(path, os.O_RDWR)
    try:
        fcntl.lockf(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0)
        private._chmod_nonsymlink(path, 0o600)
        result = subprocess.run([sys.executable, '-I', '-S', '-c', PROBE, str(path)],
                                capture_output=True, text=True, check=True, timeout=10)
        assert result.stdout.strip() == 'blocked'
        assert path.stat().st_mode & 0o777 == 0o600
    finally:
        os.close(descriptor)


def test_legacy_libc_path_open_rejects_replacement_symlink(tmp_path, monkeypatch):
    path, outside = tmp_path/'owned', tmp_path/'outside'
    path.write_text('owned')
    outside.write_text('outside')
    outside.chmod(0o644)
    old_libc(monkeypatch)
    if not hasattr(os, 'O_PATH'):
        with pytest.raises(NotImplementedError):
            private._chmod_nonsymlink(path, 0o600)
        return
    original = os.open

    def raced(target, flags, *args, **kwargs):
        assert flags & os.O_PATH and flags & os.O_NOFOLLOW
        path.unlink()
        path.symlink_to(outside)
        return original(target, flags, *args, **kwargs)

    monkeypatch.setattr(private.os, 'open', raced)
    private._chmod_nonsymlink(path, 0o600)
    assert outside.stat().st_mode & 0o777 == 0o644
