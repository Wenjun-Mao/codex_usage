"""Real WAL lifecycle, no-wait ownership and non-mutating telemetry."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import hashlib
import sqlite3
import subprocess
import sys
import threading
from time import monotonic
from types import SimpleNamespace

from filelock import FileLock
import pytest

from codex_usage import sqlite_wal as wal
from codex_usage.agent_paths import agent_lock_path, ledger_database_path
from codex_usage.cache_refresh_lock import acquire_cache_refresh_lock
from codex_usage.ledger_schema import open_ledger
from codex_usage.sqlite_maintenance_lock import exclude_physical_maintenance
from codex_usage.sqlite_runtime import RELEASE_VERSION, require_release_runtime
from codex_usage.sqlite_writer_admission import admit_sqlite_writer, try_admit_sqlite_writer


@pytest.fixture
def database(tmp_path):
    path = ledger_database_path(tmp_path)
    with open_ledger(path) as writer:
        writer.execute('create table synthetic_wal(value blob)')
        writer.commit()
    owner = FileLock(agent_lock_path(tmp_path), thread_local=False)
    with owner, closing(sqlite3.connect(path)) as keeper:
        keeper.execute('pragma wal_autocheckpoint=0')
        keeper.execute('pragma wal_checkpoint(TRUNCATE)')
        yield path, owner, keeper


def append(keeper):
    keeper.execute('insert into synthetic_wal values (zeroblob(1048576))')
    keeper.commit()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def close_retaining_wal(connection):
    connection.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
    connection.close()


def test_python_loads_the_pinned_official_release():
    result = require_release_runtime()
    assert result['version'] == RELEASE_VERSION == '3.54.1'


def test_noop_is_really_nonmutating_and_passive_reuses_before_truncate(database):
    path, owner, keeper = database
    with closing(sqlite3.connect(path)) as reader:
        reader.execute('begin')
        reader.execute('select count(*) from synthetic_wal').fetchone()
        append(keeper)
        before = digest(path)
        busy, frames, copied = keeper.execute('pragma main.wal_checkpoint(NOOP)').fetchone()
        assert busy == 0 and frames > copied
        assert digest(path) == before
        partial = wal.checkpoint(path, owner=owner)
        assert partial.outcome == 'partial'
        assert partial.busy == 0 and partial.log_frames > partial.checkpointed_frames
        assert reader.execute('select count(*) from synthetic_wal').fetchone()[0] == 0
    complete = wal.checkpoint(path, owner=owner)
    assert complete.outcome == 'complete'
    assert complete.log_frames == complete.checkpointed_frames > 0
    assert complete.wal_after > 0
    close_retaining_wal(keeper)
    reclaimed = wal.checkpoint(path, owner=owner, reclaim=True)
    assert reclaimed.outcome == 'reclaimed' and reclaimed.mode == 'TRUNCATE'
    assert reclaimed.log_frames == reclaimed.checkpointed_frames == reclaimed.wal_after == 0
    with closing(sqlite3.connect(path)) as reader:
        assert reader.execute('select length(value) from synthetic_wal').fetchone()[0] == 1048576
        assert reader.execute('pragma integrity_check').fetchone()[0] == 'ok'


def test_no_wait_python_writer_admission_does_not_queue(database):
    path, owner, keeper = database
    append(keeper)
    entered, release = threading.Event(), threading.Event()

    def writer():
        with admit_sqlite_writer(path):
            entered.set()
            assert release.wait(5)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(writer)
        assert entered.wait(5)
        try:
            started = monotonic()
            with try_admit_sqlite_writer(path) as admitted:
                assert not admitted
            assert wal.checkpoint(path, owner=owner).outcome == 'deferred'
            assert monotonic() - started < 0.5
        finally:
            release.set()
        future.result(5)


@pytest.mark.parametrize('kind', ['physical', 'parser'])
def test_busy_maintenance_or_parser_is_not_stopped(database, kind):
    path, owner, keeper = database
    append(keeper)
    entered, release = threading.Event(), threading.Event()

    def blocker():
        context = exclude_physical_maintenance(path) if kind == 'physical' else acquire_cache_refresh_lock(path)
        with context:
            entered.set()
            assert release.wait(5)

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(blocker)
        assert entered.wait(5)
        try:
            assert wal.checkpoint(path, owner=owner, reclaim=True).outcome == 'busy'
        finally:
            release.set()
        future.result(5)
    close_retaining_wal(keeper)
    assert wal.checkpoint(path, owner=owner, reclaim=True).outcome == 'reclaimed'


def test_insufficient_headroom_refuses_before_checkpoint_writes(database, monkeypatch):
    path, owner, keeper = database
    append(keeper)
    before = digest(path)
    monkeypatch.setattr(wal.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    monkeypatch.setattr(wal, '_progress', lambda *_: pytest.fail('checkpoint began without headroom'))
    result = wal.checkpoint(path, owner=owner, reclaim=True)
    assert result.outcome == 'storage_pressure' and result.free_bytes == 0
    assert digest(path) == before


def test_pressure_reclamation_stays_pending_while_owned_readers_are_parked(database, monkeypatch):
    from codex_usage.sqlite_activity import operation
    path, owner, keeper = database
    append(keeper)
    monkeypatch.setattr(wal.shutil, 'disk_usage', lambda _: SimpleNamespace(free=4*1024**2))
    with operation(path, read_only=True) as token:
        result = wal.checkpoint(path, owner=owner, readers=(token,))
        assert result.mode == 'PASSIVE' and result.log_frames == result.checkpointed_frames > 0
        assert result.outcome == 'reclaim_deferred'
    close_retaining_wal(keeper)
    assert wal.checkpoint(path, owner=owner).outcome == 'reclaimed'


def test_last_maintenance_connection_does_not_checkpoint_implicitly_when_deferred(database, monkeypatch):
    path, owner, keeper = database
    keeper.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
    append(keeper)
    keeper.close()
    before = digest(path)
    wal_path = path.with_name(path.name+'-wal')
    wal_before = digest(wal_path)
    monkeypatch.setattr(wal.shutil, 'disk_usage', lambda _: SimpleNamespace(free=0))
    result = wal.checkpoint(path, owner=owner)
    assert result.outcome == 'storage_pressure'
    assert digest(path) == before and digest(wal_path) == wal_before


def test_owned_reader_lifetime_defers_and_releases_checkpoint(database):
    path, owner, keeper = database
    append(keeper)
    with open_ledger(path, read_only=True) as reader:
        reader.execute('begin')
        reader.execute('select count(*) from synthetic_wal').fetchone()
        assert wal.checkpoint(path, owner=owner).outcome == 'deferred'
    assert wal.checkpoint(path, owner=owner).outcome == 'complete'


def test_owner_must_be_held_for_the_exact_home(database, tmp_path):
    path, _, keeper = database
    append(keeper)
    wrong = FileLock(tmp_path / 'wrong.lock', thread_local=False)
    with wrong, pytest.raises(ValueError, match='home-agent lock'):
        wal.checkpoint(path, owner=wrong)


def test_successful_checkpoint_does_not_change_logical_source_identity(database):
    path, owner, keeper = database
    append(keeper)
    before = list(keeper.execute('select * from ledger_meta order by key'))
    close_retaining_wal(keeper)
    assert wal.checkpoint(path, owner=owner, reclaim=True).outcome == 'reclaimed'
    with closing(sqlite3.connect(path)) as reader:
        assert list(reader.execute('select * from ledger_meta order by key')) == before


def test_truncate_sqlite_fence_excludes_an_uncoordinated_other_process(database, monkeypatch):
    path, owner, keeper = database
    append(keeper)
    close_retaining_wal(keeper)
    original = wal._progress
    checked = []

    def observed(connection, result, mode):
        if mode == 'TRUNCATE':
            script = '''import sqlite3,sys
c=sqlite3.connect(sys.argv[1],timeout=0)
try:
 c.execute('insert into synthetic_wal values(1)');c.commit()
except sqlite3.OperationalError as e:
 sys.exit(0 if e.sqlite_errorcode==sqlite3.SQLITE_BUSY else 2)
sys.exit(1)
'''
            child = subprocess.run([sys.executable, '-c', script, str(path)], timeout=5)
            assert child.returncode == 0
            checked.append(True)
        return original(connection, result, mode)

    monkeypatch.setattr(wal, '_progress', observed)
    assert wal.checkpoint(path, owner=owner, reclaim=True).outcome == 'reclaimed'
    assert checked == [True]


def test_append_between_passive_and_exclusive_claim_defers_copying_under_writer_fence(database, monkeypatch):
    path, owner, keeper = database
    append(keeper)
    close_retaining_wal(keeper)
    original = wal._progress

    def raced(connection, result, mode):
        caught_up = original(connection, result, mode)
        assert mode == 'PASSIVE', 'raced backlog must not reach TRUNCATE'
        script = '''import sqlite3,sys
c=sqlite3.connect(sys.argv[1],timeout=0)
c.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE,True)
c.execute('pragma wal_autocheckpoint=0')
c.execute('insert into synthetic_wal values(1)');c.commit();c.close()
'''
        subprocess.run([sys.executable, '-c', script, str(path)], check=True, timeout=5)
        return caught_up

    monkeypatch.setattr(wal, '_progress', raced)
    result = wal.checkpoint(path, owner=owner, reclaim=True)
    assert result.outcome == 'reclaim_deferred' and result.mode == 'NOOP'
    assert result.log_frames > result.checkpointed_frames
