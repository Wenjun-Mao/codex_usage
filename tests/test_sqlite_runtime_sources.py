"""Upstream archive verification applies to the files actually used for builds."""
import hashlib
import zipfile

import pytest

from release_tooling_support import load_tool


sources = load_tool('runtime_sources')


def fixture_source(tmp_path, members=None):
    archive = tmp_path / 'upstream.zip'
    with zipfile.ZipFile(archive, 'w') as bundle:
        for name, body in (members or {'official/sqlite3.c': 'upstream source'}).items():
            bundle.writestr(name, body)
    return sources.Source(archive.as_uri(), 'sha256', hashlib.sha256(archive.read_bytes()).hexdigest(), 'official')


def test_modified_extracted_cache_is_never_reused(tmp_path):
    source = fixture_source(tmp_path)
    root = tmp_path / 'build'
    first = sources.prepare(source, root)
    (first / 'sqlite3.c').write_text('modified source retaining the official version constants')
    second = sources.prepare(source, root)
    assert first != second
    assert (second / 'sqlite3.c').read_text() == 'upstream source'
    assert not list((root / 'sources').glob('extract-*'))


def test_corrupt_download_is_rejected_even_with_an_extracted_directory(tmp_path):
    source = fixture_source(tmp_path)
    root = tmp_path / 'build'
    sources.prepare(source, root)
    (root / 'downloads/upstream.zip').write_bytes(b'corrupt')
    with pytest.raises(ValueError, match='checksum mismatch'):
        sources.prepare(source, root)


@pytest.mark.parametrize('name', ['../outside', '/absolute', 'other-root/file'])
def test_unsafe_archive_does_not_publish_partial_sources(tmp_path, name):
    source = fixture_source(tmp_path, {name: 'unsafe'})
    root = tmp_path / 'build'
    with pytest.raises(ValueError, match='Unsafe'):
        sources.prepare(source, root)
    assert list((root / 'sources').iterdir()) == []
    assert not (tmp_path / 'outside').exists()
