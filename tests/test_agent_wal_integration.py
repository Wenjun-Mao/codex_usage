"""Real normal-agent scheduling, HTTP reports and restart-safe reclamation."""
from contextlib import closing
import sqlite3
from time import monotonic, sleep

from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_runtime import CodexUsageAgent
from codex_usage.allowance_probe import QuotaRead
from codex_usage.ledger_queries import query_ledger_records
from codex_usage.ledger_schema import open_ledger
from release_tooling_support import load_tool
from test_agent_runtime import _settings_file


fixture = load_tool('observed_speed_fixture')
client = load_tool('smoke-test-packaged-agent')


def wait_status(agent, predicate):
    deadline = monotonic() + 10
    while monotonic() < deadline:
        status = client._request(agent.descriptor.to_dict(), 'GET', '/v1/status')
        if predicate(status):
            return status
        sleep(0.01)
    raise AssertionError(f'normal-agent progress did not complete: {status}')


def last(status):
    return status['storage_maintenance']['last_result'] or {}


def test_deferred_startup_reclaim_survives_restart_and_external_reader_release(tmp_path, monkeypatch):
    home = tmp_path / 'home'
    fixture.write_source(home, count=30, cwd=str(tmp_path / 'project'))
    monkeypatch.setattr('codex_usage.allowance_capture.probe_allowance',
        lambda _: QuotaRead(fixture.AT.isoformat(), diagnostics='synthetic offline qualification'))
    settings = _settings_file(tmp_path, home, interval=None)
    agent = CodexUsageAgent(settings_file=settings)
    try:
        agent.start()
        wait_status(agent, lambda s: s['last_capture_outcome'] == 'success')
    finally:
        agent.stop()
    path = ledger_database_path(home)
    with open_ledger(path) as db:
        before = query_ledger_records(db)
        db.execute('create table synthetic_wal_restart(value blob)')
        db.commit()
    keeper = sqlite3.connect(path)
    blocker = sqlite3.connect(path)
    try:
        keeper.execute('pragma wal_autocheckpoint=0')
        keeper.execute('pragma wal_checkpoint(TRUNCATE)')
        blocker.execute('begin')
        blocker.execute('select count(*) from synthetic_wal_restart').fetchone()
        keeper.execute('insert into synthetic_wal_restart values (zeroblob(1048576))')
        keeper.commit()
        agent = CodexUsageAgent(settings_file=settings)
        try:
            agent.start()
            blocked = wait_status(agent, lambda s: last(s).get('outcome') == 'partial')
            assert blocked['storage_maintenance']['reclaim_pending']
            assert last(blocked)['log_frames'] > last(blocked)['checkpointed_frames']
        finally:
            agent.stop()
        agent = CodexUsageAgent(settings_file=settings)
        try:
            agent.start()
            wait_status(agent, lambda s: last(s).get('outcome') == 'partial'
                and s['last_capture_outcome'] == 'success')
            blocker.close()
            keeper.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
            keeper.close()
            complete = wait_status(agent, lambda s: last(s).get('outcome') == 'reclaimed')
            assert last(complete)['wal_before'] > 0
            assert last(complete)['wal_after'] == 0
            assert not complete['storage_maintenance']['reclaim_pending']
            descriptor = agent.descriptor.to_dict()
            report = client._request(descriptor, 'GET', '/v1/report?range=all&theme=night')
            assert 'Codex Usage Report' in report['html']
            export = client._request(descriptor, 'GET', '/v1/agent-activity?range=all')
            assert export['csv'] and export['row_count'] > 0
            with open_ledger(path, read_only=True) as db:
                assert query_ledger_records(db) == before
                assert db.execute('select length(value) from synthetic_wal_restart').fetchone()[0] == 1048576
                assert db.execute('pragma integrity_check').fetchone()[0] == 'ok'
        finally:
            agent.stop()
    finally:
        with closing(blocker), closing(keeper):
            pass
