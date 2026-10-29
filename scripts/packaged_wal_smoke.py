"""Nonempty-WAL cleanup through the real disposable collector on either target."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
from time import monotonic, sleep

from codex_usage.agent_paths import ledger_database_path
from codex_usage.ledger_queries import query_ledger_records
from codex_usage.ledger_schema import open_ledger
from codex_usage.process_tree import _cleanup_failed_process, _launch_owned_process
from observed_speed_fixture import write_source
from packaged_agent_parallel_smoke import _client
from collector_smoke_environment import smoke_environment, verify_synthetic_probe


def _wait(client, descriptor, predicate):
    deadline = monotonic() + 30
    while monotonic() < deadline:
        status = client._request(descriptor, 'GET', '/v1/status')
        if predicate(status):
            return status
        sleep(.02)
    raise RuntimeError(f'Packaged maintenance did not make expected progress: {status}')


def _last(status):
    return status['storage_maintenance']['last_result'] or {}


@contextmanager
def _running(command, settings, home, root, environment):
    client = _client()
    process, job = _launch_owned_process(
        [*command, '--background', '--settings-file', str(settings)],
        environment=environment, cwd=root, platform_name=os.name)
    descriptor = None
    try:
        descriptor = client._wait_for_descriptor(home / '.codex-usage/agent.json')
        _wait(client, descriptor, lambda s: s['last_capture_outcome'] == 'success')
        yield client, descriptor
    finally:
        if descriptor is not None and process.poll() is None:
            try:
                client._request(descriptor, 'POST', '/v1/shutdown', {})
                process.wait(timeout=10)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                pass
        _cleanup_failed_process(process, platform_name=os.name, windows_job=job)
        if process.returncode != 0:
            raise RuntimeError(f'Collector exited unsuccessfully during WAL acceptance: {process.returncode}')


def run_acceptance(executable):
    command = [str(executable)] if isinstance(executable, (str, Path)) else list(executable)
    with tempfile.TemporaryDirectory(prefix='collector-wal-') as raw:
        root = Path(raw).resolve()
        home = root / 'home'
        source = write_source(home, count=30, cwd=str(root / 'project'))
        source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
        settings = root / 'settings.json'
        settings.write_text(json.dumps({'schema_version': 1, 'codex_home': str(home),
            'capture_interval_minutes': None, 'background_capture': False,
            'daily_update_checks': False, 'onboarding_complete': True,
            'timezone': 'UTC', 'theme': 'night', 'auto_project_transitions': False}))
        environment = smoke_environment(root, home)
        runtime = json.loads(subprocess.check_output([*command, '--sqlite-runtime'],
            env=environment, cwd=root, text=True, timeout=30))
        with _running(command, settings, home, root, environment):
            pass
        path = ledger_database_path(home)
        with open_ledger(path) as db:
            before = query_ledger_records(db)
            assert before, 'fixture must contain retained usage'
            db.execute('create table synthetic_wal_smoke(value blob)')
            db.commit()
        keeper, blocker = sqlite3.connect(path), sqlite3.connect(path)
        try:
            keeper.execute('pragma wal_autocheckpoint=0')
            keeper.execute('pragma wal_checkpoint(TRUNCATE)')
            blocker.execute('begin')
            blocker.execute('select count(*) from synthetic_wal_smoke').fetchone()
            keeper.execute('insert into synthetic_wal_smoke values (zeroblob(1048576))')
            keeper.commit()
            with _running(command, settings, home, root, environment) as (client, descriptor):
                first = _wait(client, descriptor, lambda s: _last(s).get('outcome') == 'partial')
                assert first['storage_maintenance']['reclaim_pending']
            # The previous process exits while reclaim remains reader-blocked.
            with _running(command, settings, home, root, environment) as (client, descriptor):
                restarted = _wait(client, descriptor, lambda s: _last(s).get('outcome') == 'partial')
                assert _last(restarted)['log_frames'] > _last(restarted)['checkpointed_frames']
                blocker.close()
                keeper.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
                keeper.close()
                completed = _wait(client, descriptor, lambda s: _last(s).get('outcome') == 'reclaimed')
                assert _last(completed)['wal_before'] > 0
                assert _last(completed)['wal_after'] == 0
                assert not completed['storage_maintenance']['reclaim_pending']
                report = client._request(descriptor, 'GET', '/v1/report?range=all&theme=night')
                assert 'Codex Usage Report' in report['html']
                export = client._request(descriptor, 'GET', '/v1/agent-activity?range=all')
                assert export['csv'] and export['row_count'] > 0
                with open_ledger(path, read_only=True) as db:
                    assert query_ledger_records(db) == before
                    assert db.execute('select length(value) from synthetic_wal_smoke').fetchone()[0] == 1048576
                    assert db.execute('pragma integrity_check').fetchone()[0] == 'ok'
            assert hashlib.sha256(source.read_bytes()).hexdigest() == source_hash
            return {'contract': 'collector-wal-http-v1', 'runtime': runtime, **verify_synthetic_probe(root),
                'blocked': _last(first), 'restarted': _last(restarted),
                'completed': _last(completed), 'records_equal': True,
                'source_unchanged': True, 'integrity': 'ok'}
        finally:
            blocker.close()
            keeper.close()
