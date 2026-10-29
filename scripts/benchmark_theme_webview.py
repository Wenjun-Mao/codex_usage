"""Paired first-unseen theme benchmark through production config and native rendering.

Private input is copied only into disposable homes. All output remains local.
The backend is the unchanged source at both revisions, via the real HTTP API.
"""
import argparse
import base64
import asyncio
from datetime import UTC, datetime
from hashlib import sha256
import json
from pathlib import Path
import shutil
import socket
import statistics
import platform
import sqlite3
from importlib.metadata import version
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
from zipfile import ZipFile

from playwright.async_api import async_playwright

from check_speed_webview import disposable_command, stop_owned_host, wait_cdp_endpoint
from check_usage_breakdown_webview import decode, synthetic_host_environment
from theme_native_target import ThemeTarget
from release.native import host_identity
from speed_native_target import attach_speed_target, attributes, node_text
from codex_usage.ledger_schema import open_ledger

BASE = 'df74863a7b50d17a1cf94976629c3f7c6c1df4da'


async def wait_file(path, process, deadline):
    while not path.exists():
        failure = path.parent / 'failure.txt'
        if failure.exists():
            raise RuntimeError(failure.read_text())
        if process.poll() is not None:
            raise RuntimeError(f'Owned process exited {process.returncode}; {path}')
        if time.monotonic() >= deadline:
            raise TimeoutError(str(path))
        await asyncio.sleep(.01)
    return json.loads(path.read_text()) if path.suffix == '.json' else None


async def rendered_theme(target, theme, screenshot):
    await target.send('DOM.enable')
    await target.send('CSS.enable')
    while time.monotonic() < target.deadline:
        target.begin_snapshot()
        try:
            html = await target.describe('html')
        except (RuntimeError, AssertionError):
            await asyncio.sleep(.01)
            continue
        if attributes(html).get('data-codex-theme') == theme:
            complete = True
            try:
                for selector in ('.companion-actions', '.usage-breakdown', '.observed-speed', '.plan-allowance'):
                    if not await target.select(selector):
                        complete = False
                        break
            except RuntimeError:
                complete = False
            if not complete:
                await asyncio.sleep(.01)
                continue
            style = await target.visible('body')
            expected = {'day': ('rgb(245, 247, 249)', 'rgb(23, 32, 39)'),
                'night': ('rgb(16, 19, 22)', 'rgb(237, 242, 245)')}[theme]
            assert (style['background-color'], style['color']) == expected, style
            for selector in ('.companion-actions', '.usage-breakdown', '.observed-speed', '.plan-allowance'):
                await target.visible(selector)
            controls = await target.describe('.companion-actions', 5)
            text = node_text(controls)
            assert f'Theme: {theme.title()}' in text and 'Last 30 days' in text
            assert 'Capture Usage' in text and 'Export' in text
            state = await target.state(decode)
            verified = time.time()
            capture = await target.page_session.send('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False, 'optimizeForSpeed': True})
            completed = time.time()
            screenshot.write_bytes(base64.b64decode(capture['data']))
            return {'theme': theme, 'background': style['background-color'], 'color': style['color'],
                'complete_controls': True, 'visible_sections': 4, 'verified_at': verified,
                'compositor_completed_at': completed, 'screenshot_seconds': completed-verified,
                'breakdown': state, 'native_screenshot': screenshot.name}
        await asyncio.sleep(.01)
    raise TimeoutError(f'Complete native {theme} report absent')


async def trial(args, arm, pair, now, playwright):
    repo = Path(__file__).resolve().parents[1]
    output = args.output / f'{pair:02}-{arm}'
    output.mkdir()
    with TemporaryDirectory(prefix='speed-native-', dir='/tmp') as raw:
        root = Path(raw).resolve()
        (root / 'home').mkdir()
        database = root / 'codex/.codex-usage/usage-ledger.sqlite3'
        database.parent.mkdir(parents=True)
        # APFS copy-on-write clone: the sealed source is never opened writable.
        subprocess.run(['cp', '-c', str(args.ledger), str(database)], check=True)
        database.chmod(0o600)
        with open_ledger(database) as connection:
            connection.execute('delete from rendered_reports')
            connection.execute('delete from speed_html_cache')
            connection.commit()
        extension = root / 'extension'
        with ZipFile(args.baseline_vsix) as archive:
            archive.extractall(root / 'package')
        shutil.move(root / 'package/extension', extension)
        manifest = json.loads(((repo / 'extensions/vscode/package.json') if arm == 'candidate' else (extension / 'package.json')).read_text())
        manifest['activationEvents'] = []
        (extension / 'package.json').write_text(json.dumps(manifest))
        if arm == 'candidate':
            shutil.rmtree(extension / 'out')
            shutil.copytree(args.output / 'frozen-candidate', extension / 'out')
        shutil.copy2(repo / 'scripts/vscode_theme_acceptance.js', extension / 'acceptance.js')
        user = root / 'user-data/User'
        user.mkdir(parents=True)
        (user / 'settings.json').write_text(json.dumps({'codexUsage.range': '30d', 'codexUsage.theme': 'night',
            'telemetry.telemetryLevel': 'off', 'update.mode': 'none', 'extensions.autoUpdate': False,
            'workbench.startupEditor': 'none', 'window.restoreWindows': 'none'}))
        environment = synthetic_host_environment(root, root / 'codex', root / 'no-rpc', root / 'no-fixture')
        environment['PYTHONPATH'] = str(repo / 'src')
        with (output / 'collector.log').open('w') as collector_log, (output / 'host.log').open('w') as host_log:
            server = subprocess.Popen([sys.executable, str(repo / 'scripts/theme_offline_collector.py'),
                '--root', str(root), '--now', now], env=environment, cwd=repo,
                stdout=collector_log, stderr=subprocess.STDOUT)
            host = None
            try:
                deadline = time.monotonic()+180
                await wait_file(root / 'server-ready', server, deadline)
                with socket.socket() as sock:
                    sock.bind(('127.0.0.1', 0))
                    port = sock.getsockname()[1]
                host_started = time.time()
                host = subprocess.Popen(disposable_command(args.code, root, extension, port), env=environment,
                    cwd=repo, stdout=host_log, stderr=subprocess.STDOUT, start_new_session=True)
                await wait_file(root / 'ready.json', host, deadline)
                diagnostics = {'endpoint_attempts': 0}
                endpoint = wait_cdp_endpoint(port, deadline, diagnostics)
                browser = await playwright.chromium.connect_over_cdp(endpoint['webSocketDebuggerUrl'])
                try:
                    target, _ = await attach_speed_target(browser, deadline, decode, diagnostics,
                        output / 'targets.json', ThemeTarget)
                    target.page_session = await browser.contexts[0].new_cdp_session(target.page)
                    initial = await rendered_theme(target, 'night', output / 'initial.png')
                    (root / 'request.json').write_text(json.dumps({'serial': 1, 'theme': 'day'}))
                    started = await wait_file(root / 'started.json', host, deadline)
                    assigned = await wait_file(root / 'assigned.json', host, deadline)
                    visible = await rendered_theme(target, 'day', output / 'day.png')
                    seconds = visible['compositor_completed_at']-started['started']/1000
                    (root / 'flush-reports').touch()
                    await wait_file(root / 'reports-flushed', server, deadline)
                    assert visible['background'] != initial['background'], (initial, visible)
                    calls = json.loads((root / 'collector.json').read_text())
                    assert len(calls) == 2, calls
                    assert calls[0]['query']['theme'] == ('night' if arm == 'baseline' else 'auto')
                    assert calls[1]['query']['theme'] == ('day' if arm == 'baseline' else 'auto')
                    if arm == 'candidate':
                        assert not calls[1]['work'], calls
                        assert calls[1]['cache_hit'], calls
                    parity = []
                    for index in (0, 1):
                        html = (root / f'report-{index}.html').read_text()
                        metadata = json.loads((root / f'report-{index}.json').read_text())
                        transport = calls[index]['query']['theme']
                        html = html.replace(f'data-codex-theme="{transport}"', 'data-codex-theme="auto"', 1)
                        for name in ('speed_navigation', 'breakdown_navigation', 'allowance_navigation'):
                            navigation = metadata[name]
                            if navigation:
                                html = html.replace(navigation['scope'], name)
                                navigation.pop('scope')
                                for action in navigation.get('actions', []):
                                    action.pop('scope', None)
                        for name in ('cache_hit', 'elapsed_seconds'):
                            metadata.pop(name)
                        parity.append({'html_sha256': sha256(html.encode()).hexdigest(),
                            'fields_sha256': sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()})
                    assert parity[0] == parity[1], 'Theme changed accounting or issued state inventory'
                    result = {'arm': arm, 'pair': pair, 'excluded_setup': pair == 0, 'seconds': seconds,
                        'configuration_event': started, 'assignment_receipt': assigned,
                        'assignment_seconds': (assigned['assigned']-started['started'])/1000,
                        'initial_visible_seconds': initial['compositor_completed_at']-host_started,
                        'initial': initial, 'visible': visible, 'collector': calls, 'parity': parity,
                        'observation_calls': target.observations}
                    (output / 'sample.json').write_text(json.dumps(result, indent=2))
                    print(json.dumps({'pair': pair, 'arm': arm, 'seconds': seconds, 'work': calls[-1]['work']}), flush=True)
                    (root / 'done.json').write_text('{}')
                    await target.close()
                finally:
                    await browser.close()
                return result
            except BaseException as error:
                (output / 'failure.json').write_text(json.dumps({'status': 'failed', 'arm': arm, 'pair': pair,
                    'error': f'{type(error).__name__}: {error}'}, indent=2))
                if 'target' in locals() and hasattr(target, 'shallow_document'):
                    (output / 'shallow-document.json').write_text(json.dumps(target.shallow_document))
                for name in ('failure.txt', 'started.json', 'assigned.json'):
                    if (root / name).exists():
                        shutil.copy2(root / name, output / name)
                raise
            finally:
                if host:
                    stop_owned_host(host)
                (root / 'stop-server').touch()
                try:
                    server.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    server.terminate()
                    server.wait(timeout=5)
                if (root / 'collector.json').exists():
                    shutil.copy2(root / 'collector.json', output / 'collector.json')


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ledger', type=Path, required=True)
    parser.add_argument('--baseline-vsix', type=Path, required=True)
    parser.add_argument('--expected-ledger-sha256', required=True, help='Owner-selected sealed representative control identity')
    parser.add_argument('--expected-ledger-bytes', type=int, required=True)
    parser.add_argument('--code', type=Path, default=Path('/Applications/Visual Studio Code.app/Contents/MacOS/Code'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--pairs', type=int, default=10)
    args = parser.parse_args()
    assert not args.output.exists(), 'Keep every previous measurement'
    args.output.mkdir(parents=True)
    assert args.ledger.stat().st_mode & 0o222 == 0, 'Input must be sealed read-only'
    assert not Path(str(args.ledger)+'-wal').exists()
    repo = Path(__file__).resolve().parents[1]
    assert not subprocess.check_output(['git', 'diff', BASE, '--', 'src', ':(exclude)src/codex_usage/__init__.py'], cwd=repo), 'Backend must equal baseline except package metadata'
    original_init = subprocess.check_output(['git', 'show', BASE+':src/codex_usage/__init__.py'], cwd=repo, text=True)
    current_init = (repo / 'src/codex_usage/__init__.py').read_text()
    assert current_init.replace('2.13.4', '2.13.3') == original_init
    frozen = args.output / 'frozen-candidate'
    shutil.copytree(repo / 'extensions/vscode/out', frozen)
    def tree_identity(directory):
        return {p.relative_to(directory).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in sorted(directory.rglob('*')) if p.is_file()}
    artifacts = {'baseline_vsix_sha256': sha256(args.baseline_vsix.read_bytes()).hexdigest(),
        'candidate_out': tree_identity(frozen),
        'candidate_manifest_sha256': sha256((repo / 'extensions/vscode/package.json').read_bytes()).hexdigest(),
        'candidate_sources': tree_identity(repo / 'extensions/vscode/src'),
        'backend_metadata_only': '2.13.3 to 2.13.4 __version__; all other Python source equals fixed baseline', 'backend_source': subprocess.check_output(
            ['git', 'rev-parse', BASE+':src'], cwd=repo, text=True).strip(),
        'harness': {name: sha256((repo / 'scripts' / name).read_bytes()).hexdigest() for name in (
            'benchmark_theme_webview.py', 'theme_native_target.py', 'theme_offline_collector.py', 'vscode_theme_acceptance.js')},
        'runtime': {'native_host': host_identity(args.code), 'python': sys.version,
            'sqlite': sqlite3.sqlite_version, 'platform': platform.platform(), 'playwright': version('playwright')}}
    assert artifacts['baseline_vsix_sha256'] == 'e277eee9a7da7dccab7f3ad71e3d88942e88adaa049b1ce5caa2fd8dc0eb81e8'
    now = datetime.now(UTC).isoformat()
    evidence = {'artifacts': artifacts, 'baseline': BASE, 'input_bytes': args.ledger.stat().st_size,
        'input_sha256': sha256(args.ledger.read_bytes()).hexdigest(), 'fixed_clock': now,
        'private_local_only': True, 'protocol': 'Fresh process/copy; empty presentation caches; initial Night 30d then first Day; alternating arm order; native compositor completion',
        'timing_origin': 'production configuration listener receives committed theme event',
        'samples': []}
    (args.output / 'evidence.json').write_text(json.dumps(evidence, indent=2))
    async with async_playwright() as playwright:
        for pair in range(args.pairs+1):
            for arm in (('baseline', 'candidate') if pair % 2 == 0 else ('candidate', 'baseline')):
                assert all(sha256((repo / 'scripts' / name).read_bytes()).hexdigest() == digest
                    for name, digest in artifacts['harness'].items()), 'Frozen harness changed'
                evidence['samples'].append(await trial(args, arm, pair, now, playwright))
                assert tree_identity(frozen) == artifacts['candidate_out'], 'Frozen output changed'
                assert tree_identity(repo / 'extensions/vscode/src') == artifacts['candidate_sources'], 'Frozen product source changed'
                assert sha256((repo / 'extensions/vscode/package.json').read_bytes()).hexdigest() == artifacts['candidate_manifest_sha256'], 'Frozen metadata changed'
                (args.output / 'evidence.json').write_text(json.dumps(evidence, indent=2))
    assert len({json.dumps(s['parity'][1], sort_keys=True) for s in evidence['samples']}) == 1, 'Cross-arm accounting parity differs'
    medians = {arm: statistics.median(s['seconds'] for s in evidence['samples']
        if s['arm'] == arm and not s['excluded_setup']) for arm in ('baseline', 'candidate')}
    evidence['medians'] = medians
    evidence['saving_seconds'] = medians['baseline']-medians['candidate']
    evidence['screening_only'] = args.pairs != 10
    evidence['representative_input'] = evidence['input_bytes'] == args.expected_ledger_bytes and evidence['input_sha256'] == args.expected_ledger_sha256
    evidence['passed'] = evidence['representative_input'] and args.pairs == 10 and medians['candidate'] <= 1 and evidence['saving_seconds'] > 1
    (args.output / 'evidence.json').write_text(json.dumps(evidence, indent=2))
    print(json.dumps({key: evidence[key] for key in ('medians', 'saving_seconds', 'passed')}))
    assert medians['candidate'] <= 1, 'Visible candidate median exceeds one second'


if __name__ == '__main__':
    asyncio.run(main())
