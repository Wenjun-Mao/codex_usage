"""Compare capture bookkeeping and cold reports on disposable ledger copies.

Does not run a live capture, read task bodies, or probe account/network state.
Bookkeeping verifies local repository paths and reads the optional local state DB.
"""
import argparse
from datetime import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
from tempfile import TemporaryDirectory
from time import perf_counter, process_time
from types import SimpleNamespace


def copy_ledger(source, target):
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with sqlite3.connect(source.resolve().as_uri() + '?mode=ro', uri=True) as reader:
        with sqlite3.connect(target) as writer:
            reader.backup(writer)
    target.chmod(0o600)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def measure(args):
    import codex_usage.breakdown_reports as breakdown
    from codex_usage.agent_paths import ledger_database_path
    from codex_usage.agent_reports import render_ledger_report
    from codex_usage.ledger_schema import increment_ledger_revision, open_ledger
    from codex_usage.session_cache_project_identity import refresh_cached_project_identities
    from codex_usage.session_cache_transitions import replace_dirty_task_transitions, load_transitions
    # Compare full HTML with identical command scopes even when the disposable
    # presentation cache format changes. Never override monetary revisions.
    breakdown.BREAKDOWN_REVISION = args.comparison_revision
    path = ledger_database_path(args.home)
    results = []
    def timed(name, operation):
        wall, cpu = perf_counter(), process_time()
        value = operation()
        results.append({'operation': name, 'seconds': perf_counter() - wall,
                        'cpu_seconds': process_time() - cpu})
        return value
    # Additive index installation is measured separately from steady capture work.
    def initialize():
        with open_ledger(path):
            pass
    timed('initial schema preparation', initialize)
    with open_ledger(path) as connection:
        inventory = [SimpleNamespace(file_key=r['file_key'], path=Path(r['path'])) for r in
            connection.execute('select file_key, path from files where is_missing=0 and file_key=session_id')]
        tasks = tuple(r[0] for r in connection.execute('''select session_id from usage_records
            group by session_id order by max(timestamp_us) desc, session_id limit 12'''))
        paths = sorted({Path(r[0]) for r in connection.execute('select distinct session_dir from files')})
        affected = timed('repository identity reconciliation', lambda:
            refresh_cached_project_identities(connection, inventory))
        results[-1]['affected_tasks_sha256'] = digest(sorted(affected))
        timed('transition reconciliation: 12 recent tasks', lambda:
            replace_dirty_task_transitions(connection, paths, tasks))
        results[-1]['transitions_sha256'] = digest([t.to_dict() for t in load_transitions(connection)])
        increment_ledger_revision(connection)
        connection.execute('delete from rendered_reports')
        connection.execute('delete from speed_html_cache')
        connection.commit()
    for label, range_name in (('first Today after revision', 'today'), ('switch Yesterday', 'yesterday'),
                              ('cached Today', 'today')):
        report = timed(label, lambda: render_ledger_report(args.home, range_name=range_name,
            project_keys=[], theme='night', timezone_name='America/Toronto', now=datetime.fromisoformat(args.now)))
        results[-1].update(html_sha256=hashlib.sha256(report.html.encode()).hexdigest(),
                           html_bytes=len(report.html.encode()), cache_hit=report.cache_hit)
    print(json.dumps(results))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path)
    parser.add_argument('--now', required=True)
    parser.add_argument('--release', default='v2.12.1')
    parser.add_argument('--baseline-source', type=Path,
        help='Frozen src directory for comparing against an uncommitted checkpoint')
    parser.add_argument('--comparison-revision', type=int, default=10000)
    parser.add_argument('--repeats', type=int, default=3)
    parser.add_argument('--output', type=Path, default=Path('output/performance/capture-load/comparison.json'))
    parser.add_argument('--measure', action='store_true')
    parser.add_argument('--home', type=Path)
    args = parser.parse_args()
    if args.measure:
        measure(args)
        return
    if args.ledger is None or args.repeats < 1:
        parser.error('--ledger and a positive --repeats are required')
    repo = Path(__file__).resolve().parents[1]
    release = str(args.baseline_source.resolve()) if args.baseline_source else subprocess.check_output(
        ['git', 'rev-parse', args.release], cwd=repo, text=True).strip()
    evidence = {'release': release, 'fixed_clock': args.now, 'private_input': True,
        'comparison_presentation_revision': args.comparison_revision,
        'input_access': 'mode=ro ledger backup; all writes on temporary copies',
        'scope': 'bookkeeping only, excludes parsing and live quota RPC; cold report includes index catch-up',
        'results': []}
    with TemporaryDirectory(prefix='capture-load-benchmark-') as raw:
        root = Path(raw)
        frozen = root / 'input.sqlite3'
        copy_ledger(args.ledger, frozen)
        baseline_source = args.baseline_source.resolve() if args.baseline_source else None
        if baseline_source is None:
            baseline = root / 'released-source'
            baseline.mkdir()
            archive = subprocess.check_output(['git', 'archive', release, 'src'], cwd=repo)
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                tar.extractall(baseline, filter='data')
            baseline_source = baseline / 'src'
        for repeat in range(args.repeats):
            pair = {}
            authorities = [('release', baseline_source), ('candidate', repo / 'src')]
            if repeat % 2:
                authorities.reverse()
            for label, authority in authorities:
                home = root / f'{label}-{repeat}'
                copy_ledger(frozen, home / '.codex-usage/usage-ledger.sqlite3')
                environment = dict(os.environ, PYTHONPATH=str(authority), CODEX_HOME=str(home))
                command = [sys.executable, str(Path(__file__).resolve()), '--measure', '--home', str(home),
                    '--now', args.now, '--comparison-revision', str(args.comparison_revision)]
                pair[label] = json.loads(subprocess.check_output(command, env=environment, cwd=root, text=True))
                print(repeat, label, [(r['operation'], round(r['seconds'], 3)) for r in pair[label]], flush=True)
            for old, new in zip(pair['release'], pair['candidate'], strict=True):
                for key in ('html_sha256', 'affected_tasks_sha256', 'transitions_sha256'):
                    if key in old:
                        assert old[key] == new[key], (old['operation'], key)
            evidence['results'].append(pair)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    main()
