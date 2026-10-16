import importlib.util
from pathlib import Path
import sqlite3

import pytest


ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name+".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_is_coherent_private_and_refuses_overwrite(tmp_path):
    source = tmp_path / "source.sqlite3"
    with sqlite3.connect(source) as connection:
        connection.execute("pragma journal_mode=wal")
        connection.execute("create table value(n)")
        connection.execute("insert into value values (42)")
        connection.commit()
        result = load("collector_snapshot").snapshot(source, tmp_path / "private")
        with sqlite3.connect(tmp_path / "private/input.sqlite3") as copy:
            assert copy.execute("select n from value").fetchone()[0] == 42
        assert result["snapshot_bytes"] > 0 and len(result["snapshot_sha256"]) == 64
        with pytest.raises(ValueError, match="already exists"):
            load("collector_snapshot").snapshot(source, tmp_path / "private")
    import os
    if os.name == "posix":
        assert (tmp_path / "private").stat().st_mode & 0o077 == 0
        assert (tmp_path / "private/input.sqlite3").stat().st_mode & 0o077 == 0


def test_benchmark_guard_rejects_escaped_and_external_inputs(tmp_path):
    module = load("collector_benchmark_guard")
    owned = tmp_path / "private"
    owned.mkdir()
    check = module.audit_guard(owned, report=True)
    check("open", (str(owned / "fixture.jsonl"),))
    check("sqlite3.connect", ((owned / "copy.sqlite3").as_uri()+"?mode=ro",))
    assert module.database_path((owned / "literal%2e.sqlite3").as_uri()) == owned / "literal%2e.sqlite3"
    check("sqlite3.connect", (":memory:",))
    for event, values in [
        ("open", (str(tmp_path / "live.jsonl"),)),
        ("sqlite3.connect", (str(tmp_path / "live.sqlite3"),)),
        ("sqlite3.connect", ("file://remote/share/db.sqlite3",)),
        ("socket.connect", (object(), ("example.com", 443))),
        ("socket.getaddrinfo", ("example.com", 443)),
        ("subprocess.Popen", ("codex",)),
    ]:
        with pytest.raises(PermissionError):
            check(event, values)
