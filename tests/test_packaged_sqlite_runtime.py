"""Frozen engine proof rejects mismatched engine, build options and DLL bytes."""
import json

import pytest

from release_tooling_support import load_tool


verifier = load_tool('verify_packaged_sqlite')


@pytest.mark.parametrize('mutation', [None, 'version', 'source_id', 'compile_options', 'library_sha256'])
def test_frozen_probe_must_match_the_private_build_runtime(tmp_path, monkeypatch, mutation):
    expected = {'version': '3.54.1', 'source_id': 'official source',
                'compile_options': ['THREADSAFE=1'], 'library_sha256': 'original'}
    actual = dict(expected)
    if mutation:
        actual[mutation] = ['changed'] if mutation == 'compile_options' else 'changed'
    monkeypatch.setattr(verifier, 'require_release_runtime', lambda: expected)
    monkeypatch.setattr(verifier.subprocess, 'check_output', lambda *args, **kwargs: json.dumps(actual))
    output = tmp_path / 'runtime.json'
    if mutation:
        with pytest.raises(ValueError, match='differs'):
            verifier.verify(tmp_path / 'collector', output)
        assert not output.exists()
    else:
        assert verifier.verify(tmp_path / 'collector', output) == expected
        assert json.loads(output.read_text()) == expected
