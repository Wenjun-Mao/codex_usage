"""Privacy enforcement must not close away another descriptor's SQLite locks."""
import os
import subprocess
import sys

import pytest

from codex_usage import agent_private_files as private

PROBE = '''
import fcntl, os, sys
fd = os.open(sys.argv[1], os.O_RDWR)
try:
    try:
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0)
    except BlockingIOError:
        print('blocked')
    else:
        print('unlocked')
finally:
    os.close(fd)
'''


@pytest.mark.parametrize('suffix', ['', '-wal', '-shm'])
@pytest.mark.parametrize('whole_set', [False, True])
def test_privacy_changes_preserve_existing_process_record_locks(tmp_path, monkeypatch, suffix, whole_set):
    path = tmp_path/'usage-ledger.sqlite3'
    for tail in ('', '-wal', '-shm'):
        path.with_name(path.name+tail).write_bytes(b'fixture')
    target = path.with_name(path.name+suffix)
    secure = (lambda: private.ensure_private_sqlite_files(path)) if whole_set else (
        lambda: private.ensure_private_file(target))
    if os.name == 'nt':
        # Windows uses its existing ACL owner, not POSIX file descriptors.
        calls = []
        monkeypatch.setattr(private, '_apply_windows_acl', lambda p, **kwargs: calls.append(p))
        secure()
        assert target in calls
        return
    import fcntl
    descriptor = os.open(target, os.O_RDWR)

    def probe():
        value = subprocess.run([sys.executable, '-I', '-S', '-c', PROBE, str(target)],
                               capture_output=True, text=True, check=True, timeout=10)
        return value.stdout.strip()

    try:
        fcntl.lockf(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB, 1, 0)
        assert probe() == 'blocked'
        secure()
        assert probe() == 'blocked', 'privacy enforcement discarded live process locks'
    finally:
        os.close(descriptor)


def test_permission_race_never_follows_a_replacement_symlink(tmp_path, monkeypatch):
    path, outside = tmp_path/'owned', tmp_path/'outside'
    path.write_text('owned')
    outside.write_text('outside')
    if os.name == 'nt':
        calls = []
        monkeypatch.setattr(private, '_apply_windows_acl', lambda p, **kwargs: calls.append(p))
        private.ensure_private_file(path)
        assert calls == [path]
        return
    outside.chmod(0o644)
    original = os.chmod

    def raced(target, mode, **kwargs):
        assert kwargs == {'follow_symlinks': False}
        path.unlink()
        path.symlink_to(outside)
        return original(target, mode, **kwargs)

    monkeypatch.setattr(private.os, 'chmod', raced)
    private.ensure_private_file(path)
    assert outside.stat().st_mode & 0o777 == 0o644
