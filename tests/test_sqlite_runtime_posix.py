"""Runtime reuse binds both installed bytes and the native upstream inputs."""
from dataclasses import asdict
import hashlib

import pytest

from release_tooling_support import load_tool


builder = load_tool('build_sqlite_runtime')
sources = load_tool('runtime_sources')


@pytest.mark.parametrize('platform', ['linux', 'darwin'])
def test_native_probe_does_not_load_setup_python_host_library(tmp_path, monkeypatch, platform):
    monkeypatch.setattr(builder.sys, 'platform', platform)
    monkeypatch.setenv('LD_LIBRARY_PATH', '/host/python/lib')
    environment = builder.runtime_environment(tmp_path / 'install')
    expected = str(tmp_path / 'install/lib') if platform == 'linux' else '/host/python/lib'
    assert environment['LD_LIBRARY_PATH'] == expected
    assert environment['PYTHONPATH'] == str(builder.ROOT / 'src')


@pytest.mark.parametrize('mutation', [None, 'archive', 'native', 'artifact', 'legacy'])
def test_reuse_requires_original_archives_inputs_and_installed_bytes(tmp_path, monkeypatch, mutation):
    pins = []
    for name in ('SQLITE', 'PYTHON', 'OPENSSL'):
        data = name.encode()
        source = sources.Source(f'https://example.invalid/{name}.zip', 'sha256',
                                hashlib.sha256(data).hexdigest(), name)
        monkeypatch.setattr(builder, name, source)
        path = tmp_path / 'downloads' / f'{name}.zip'
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        pins.append(asdict(source))
    inputs = {}
    for name in ('sqlite3.c', 'sqlite3.h', 'sqlite3ext.h'):
        path = tmp_path / 'sources' / name
        path.parent.mkdir(exist_ok=True)
        path.write_text(name)
        inputs[path.relative_to(tmp_path).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    install = tmp_path / 'install'
    install.mkdir()
    (install / 'runtime').write_bytes(b'compiled fixture')
    saved = {'sources': pins, 'native_inputs': inputs, 'artifacts': builder.artifacts(install)}
    if mutation == 'archive':
        (tmp_path / 'downloads/SQLITE.zip').write_bytes(b'changed')
    elif mutation == 'native':
        (tmp_path / 'sources/sqlite3.c').write_bytes(b'changed')
    elif mutation == 'artifact':
        (install / 'runtime').write_bytes(b'changed')
    elif mutation == 'legacy':
        saved.pop('native_inputs')
    if mutation is None:
        builder.validate_saved(saved, tmp_path)
    else:
        with pytest.raises(ValueError):
            builder.validate_saved(saved, tmp_path)
