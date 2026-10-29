"""Synthetic smoke probes fail closed before any installed runtime is queried."""
from pathlib import Path
from unittest.mock import patch

import pytest

from codex_usage.allowance_probe import probe_allowance
from codex_usage import codex_runtime
from release_tooling_support import load_tool

fixture = load_tool('collector_smoke_environment')


@pytest.mark.parametrize('failure', ['none', 'missing', 'crashed', 'malformed'])
def test_real_probe_uses_only_authoritative_synthetic_override_even_when_broken(tmp_path, monkeypatch, failure):
    root = tmp_path/'collector-parallel-test'
    home = root/'home'
    home.mkdir(parents=True)
    environment = fixture.smoke_environment(root, home)
    launcher = Path(environment['CODEX_CLI_PATH'])
    if failure == 'missing':
        launcher.unlink()
    elif failure == 'crashed':
        Path(environment['CODEX_BREAKDOWN_RPC_FIXTURE']).unlink()
    elif failure == 'malformed':
        Path(environment['CODEX_BREAKDOWN_RPC_FIXTURE']).write_text('[]')
    # The production discovery function must return before enumerating installed
    # apps or PATH. Real subprocess/protocol/cleanup still run for this fixture.
    monkeypatch.setattr(codex_runtime.os, 'environ', environment)
    with (patch.object(codex_runtime, '_macos_codex_executables', side_effect=AssertionError('Real app discovery')),
          patch.object(codex_runtime.shutil, 'which', side_effect=AssertionError('Real PATH discovery'))):
        read = probe_allowance(home, timeout=4)
    if failure == 'none':
        assert read.diagnostics == 'quota_unavailable'
        assert fixture.verify_synthetic_probe(root)['synthetic_probe'] is True
    else:
        assert read.diagnostics == 'probe_unavailable'
    assert not read.observations


def test_smoke_child_environment_excludes_credentials_and_binds_disposable_paths(tmp_path):
    source = dict(PATH='synthetic-path', SYSTEMROOT='system', OPENAI_API_KEY='do-not-copy',
        CODEX_AUTH_TOKEN='do-not-copy', GITHUB_TOKEN='do-not-copy', AWS_SECRET_ACCESS_KEY='do-not-copy',
        HOME='original', CODEX_HOME='original', PYTHONPATH='untrusted')
    environment = fixture.isolated_environment(tmp_path, source=source)
    assert not set(environment) & {'OPENAI_API_KEY','CODEX_AUTH_TOKEN','GITHUB_TOKEN','AWS_SECRET_ACCESS_KEY'}
    assert environment['HOME'] == environment['USERPROFILE'] == str(tmp_path.resolve())
    assert environment['PATH'] == 'synthetic-path'
    assert environment['PYTHONPATH'] != 'untrusted'


def test_windows_synthetic_launcher_uses_windows_paths_and_does_not_forward_shell_arguments():
    launcher = fixture.launcher_text(r'C:\Program Files\Python313\python.exe',
        r'D:\a\codex_usage\scripts\breakdown_rpc_fixture.py', windows=True)
    assert '"C:\\Program Files\\Python313\\python.exe"' in launcher
    assert '"D:\\a\\codex_usage\\scripts\\breakdown_rpc_fixture.py"' in launcher
    assert '%*' not in launcher and '/usr/' not in launcher
