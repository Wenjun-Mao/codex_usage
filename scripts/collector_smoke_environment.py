"""Disposable synthetic RPC/environment for packaged collector acceptance only."""
import json
import os
from pathlib import Path
import sys

ENVIRONMENT_KEYS = ('PATH', 'TMPDIR', 'TMP', 'TEMP', 'LANG', 'LC_ALL', 'SYSTEMROOT',
                    'WINDIR', 'COMSPEC', 'PATHEXT')


def isolated_environment(root, *, source=None):
    source = os.environ if source is None else source
    root = Path(root).resolve()
    scripts = Path(__file__).resolve().parent
    return dict({key: source[key] for key in ENVIRONMENT_KEYS if key in source},
        HOME=str(root), USERPROFILE=str(root), LOCALAPPDATA=str(root/'local'), APPDATA=str(root/'config'),
        XDG_CONFIG_HOME=str(root/'config'), XDG_CACHE_HOME=str(root/'cache'),
        CODEX_CLI_PATH=str(root/'no-probe-allowed'),
        PYTHONPATH=os.pathsep.join((str(scripts.parent/'src'), str(scripts))))


def launcher_text(python, fixture, *, windows):
    if any(c in str(python)+str(fixture) for c in ('\r', '\n', '"', '%')):
        raise ValueError('Unsupported synthetic launcher path')
    if windows:
        return f'@echo off\r\n"{python}" "{fixture}"\r\n'
    return f'#!{python}\nimport runpy\nrunpy.run_path({str(fixture)!r}, run_name="__main__")\n'


def smoke_environment(root, home):
    root, home = Path(root).resolve(), Path(home).resolve()
    assert home.parent == root
    environment = isolated_environment(root)
    fixture = Path(__file__).with_name('breakdown_rpc_fixture.py').resolve()
    launcher = root/('synthetic-rpc.cmd' if os.name == 'nt' else 'synthetic-rpc')
    launcher.write_text(launcher_text(sys.executable, fixture, windows=os.name == 'nt'), newline='')
    launcher.chmod(0o700)
    data = root/'synthetic-rpc.json'
    data.write_text(json.dumps({'account/read': {'account': None},
        'account/rateLimits/read': {'rateLimitsByLimitId': {}}, 'account/usage/read': {'summary': {}}}))
    environment.update(CODEX_HOME=str(home), CODEX_USAGE_DATA_DIR=str(root),
        CODEX_CLI_PATH=str(launcher), CODEX_BREAKDOWN_RPC_FIXTURE=str(data),
        CODEX_BREAKDOWN_RPC_AUDIT=str(root/'synthetic-rpc-methods.jsonl'))
    return environment


def verify_synthetic_probe(root):
    path = Path(root)/'synthetic-rpc-methods.jsonl'
    methods = [json.loads(line) for line in path.read_text().splitlines()]
    allowed = {'initialize', 'account/read', 'account/rateLimits/read', 'account/usage/read'}
    assert methods and all(type(method) is str and method in allowed for method in methods)
    assert set(methods) == allowed, 'Packaged collector did not complete its synthetic-only probe'
    return {'synthetic_probe': True, 'method_names': sorted(set(methods))}
