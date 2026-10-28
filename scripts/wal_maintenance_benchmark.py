"""Synthetic WAL/capture adapter for the existing collector benchmark entrypoint."""
from contextlib import closing
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
from time import monotonic, perf_counter, process_time, sleep
from unittest.mock import patch

from filelock import FileLock


def measure(args):
    from codex_usage.agent_capture import capture_once
    from codex_usage.agent_jobs import HeavyIOLane, JobPriority
    from codex_usage.agent_paths import agent_lock_path, ledger_database_path
    from codex_usage.agent_storage_maintenance import StorageMaintenance
    from codex_usage.allowance_probe import QuotaRead
    from codex_usage.ledger_queries import query_ledger_records
    from codex_usage.ledger_schema import open_ledger
    from codex_usage import sqlite_wal
    from codex_usage.sqlite_runtime import require_release_runtime
    from wal_benchmark_budget import Budget
    from observed_speed_fixture import AT, append_rows, response, write_source

    require_release_runtime()
    home = args.home.resolve()
    session = write_source(home, count=100, cwd=str(home.parent / 'project'))
    path = ledger_database_path(home)
    lane, controller = HeavyIOLane(), None
    entered = threading.Event()
    traces = []
    original = sqlite_wal._progress

    def observed(connection, result, mode):
        started = perf_counter()
        if mode == 'PASSIVE':
            entered.set()
        try:
            return original(connection, result, mode)
        finally:
            traces.append({'mode': mode, 'started': started, 'finished': perf_counter()})
            # Checkpoint I/O need not execute enough VM instructions to sample.
            # Observe MAIN and WAL together before a following TRUNCATE.
            budget.check(unlinked=True)

    def quota(_):
        return QuotaRead(AT.isoformat(), diagnostics='synthetic offline WAL qualification')

    try:
        with patch('codex_usage.allowance_capture.probe_allowance', quota):
            initial = capture_once(home, request_kind='synthetic-initial', max_workers=1)
            assert initial.outcome == 'success', initial.error
            budget = Budget(home.parent, path)
            with (budget.observe_sqlite(writable_root=home.parent),
                  FileLock(agent_lock_path(home), thread_local=False) as owner,
                  closing(sqlite3.connect(path)) as keeper):
                keeper.execute('pragma wal_autocheckpoint=0')
                keeper.execute('create table synthetic_wal_backlog(value blob)')
                keeper.execute('pragma wal_checkpoint(TRUNCATE)')
                # 256 MiB matches the order of the measured bootstrap WAL, not
                # an application limit. Setup is excluded and identical in both arms.
                budget.check(reserve=768 * 1024**2, unlinked=True)
                for _ in range(16):
                    keeper.executemany('insert into synthetic_wal_backlog values (randomblob(1048576))',
                                       [() for _ in range(16)])
                    budget.check(reserve=32 * 1024**2, unlinked=True)
                keeper.commit()
                wal_path = path.with_name(path.name + '-wal')
                initial_wal = wal_path.stat().st_size
                assert initial_wal >= 256 * 1024**2
                append_rows(session, response(100, response_id='wal-capture-append'))
                with patch.object(sqlite_wal, '_progress', observed):
                    if args.wal_cleanup_enabled:
                        controller = StorageMaintenance(path, owner=owner, lane=lane,
                            capture_running=lambda: False, wakeup=lambda: None)
                        controller.tick()
                        assert entered.wait(10), 'real checkpoint did not start'
                    submitted, cpu = perf_counter(), process_time()
                    timing = {}

                    def capture():
                        timing['started'] = perf_counter()
                        return capture_once(home, request_kind='synthetic-wal-overlap', max_workers=1)

                    captured = lane.submit('capture', JobPriority.CAPTURE_NOW, capture).result(120)
                    finished = perf_counter()
                    capture_cpu = process_time() - cpu
                    assert captured.outcome == 'success', captured.error
                    if controller is not None:
                        keeper.setconfig(sqlite3.SQLITE_DBCONFIG_NO_CKPT_ON_CLOSE, True)
                        keeper.close()
                        controller.request(reclaim=True)
                        deadline = monotonic() + 120
                        while controller.status()['pending'] or controller.status()['running']:
                            assert monotonic() < deadline, controller.status()
                            controller.tick()
                            sleep(0.01)
                        maintenance = controller.status()
                        controller.close()
                        controller = None
                    else:
                        maintenance = None
                with open_ledger(path, read_only=True) as reader:
                    records = query_ledger_records(reader)
                    assert reader.execute('pragma integrity_check').fetchone()[0] == 'ok'
                    assert reader.execute('select count(*) from synthetic_wal_backlog').fetchone()[0] == 256
                values = [asdict(record) for record in records]
                result = {'capture_seconds': finished-submitted, 'capture_cpu_seconds': capture_cpu,
                    'capture_queue_seconds': timing['started']-submitted,
                    'checkpoint_overlap': any(row['started'] < finished and row['finished'] > timing['started']
                                              for row in traces),
                    'checkpoint_calls': [{**row, 'seconds': row['finished']-row['started']} for row in traces],
                    'initial_wal_bytes': initial_wal, 'final_wal_bytes': sqlite_wal.allocation(wal_path),
                    'maintenance': maintenance, 'capture_stats': asdict(captured.stats),
                    'new_file_observed_high_water_bytes': budget.high_water,
                    'inventory_observation': budget.observation(),
                    'records': len(values), 'records_sha256': hashlib.sha256(
                        json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()}
                print(json.dumps(result))
    finally:
        if controller is not None:
            controller.close()
        lane.close()


def run(args):
    from codex_usage.sqlite_runtime import require_release_runtime
    output = args.output.resolve()
    if output.exists():
        raise ValueError('WAL qualification requires a fresh output file')
    repo = Path(__file__).resolve().parents[1]
    runtime = require_release_runtime()
    evidence = {'scope': 'synthetic real capture entrypoint; one parser worker; no private/account access',
        'runtime': runtime, 'excluded_pairs': 1, 'measured_pairs': args.repeats,
        'fixture_backlog_bytes': 256 * 1024**2, 'total_new_files_bound_bytes': 6 * 1024**3,
        'source': {str(path.relative_to(repo)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for root in (repo/'src', repo/'scripts') for path in sorted(root.rglob('*.py'))},
        'pairs': []}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wal-qualification-', dir=output.parent) as raw:
        root = Path(raw).resolve()
        for index in range(args.repeats + 1):
            pair = {}
            order = ('off', 'on') if index % 2 == 0 else ('on', 'off')
            for name in order:
                if shutil.disk_usage(root).free < 2 * 1024**3:
                    raise ValueError('Insufficient fixture headroom')
                home = root / 'work' / 'home'
                home.mkdir(parents=True)
                command = [sys.executable, str(repo/'scripts/benchmark_collector.py'), '--mode', 'wal-cleanup',
                    '--measure', '--home', str(home)]
                if name == 'on':
                    command.append('--wal-cleanup-enabled')
                env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(repo/'src'), str(repo/'scripts'))),
                           HOME=str(home.parent), USERPROFILE=str(home.parent), CODEX_HOME=str(home),
                           CODEX_USAGE_DATA_DIR=str(home))
                pair[name] = json.loads(subprocess.check_output(command, env=env, cwd=repo, text=True))
                shutil.rmtree(home.parent)
                print(index, name, round(pair[name]['capture_seconds'], 4),
                      'overlap', pair[name]['checkpoint_overlap'], flush=True)
            assert pair['on']['records_sha256'] == pair['off']['records_sha256']
            evidence['pairs'].append({'excluded': index == 0, **pair})
    measured = evidence['pairs'][1:]
    medians = {name: statistics.median(row[name]['capture_seconds'] for row in measured) for name in ('off', 'on')}
    delta = medians['on'] - medians['off']
    evidence.update(capture_medians=medians, capture_delta_seconds=delta,
        capture_regression=delta > 0.1 and medians['on'] > medians['off'] * 1.1,
        all_measured_overlap=all(row['on']['checkpoint_overlap'] for row in measured),
        synthetic_files_removed=True)
    output.write_text(json.dumps(evidence, indent=2) + '\n')
    assert evidence['all_measured_overlap'], 'Capture must overlap actual checkpoint I/O'
    assert not evidence['capture_regression'], 'Cleanup materially regressed real capture'
