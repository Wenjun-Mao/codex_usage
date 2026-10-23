import importlib.util
from contextlib import nullcontext
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest
from codex_usage.ledger_writer_contract import LEDGER_SCHEMA_VERSION


def load_smoke(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("packaged_agent_smoke", scripts / "smoke-test-packaged-agent.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    return smoke


@pytest.mark.parametrize("status,payload,accepted", [
    (404, {"error": "not found"}, True),
    (404, {"error": "different failure"}, False),
    (200, {"error": "not found"}, False),
    (403, {"error": "not found"}, False),
    (500, {"error": "not found"}, False),
])
def test_packaged_retirement_requires_unknown_routes(monkeypatch, status, payload, accepted):
    smoke = load_smoke(monkeypatch)
    calls = []

    def request(value, *, timeout):
        assert timeout == 30
        assert value.get_header("Authorization") == "Bearer synthetic"
        calls.append((value.get_method(), value.full_url))
        if status == 200:
            return nullcontext(BytesIO(json.dumps(payload).encode()))
        raise HTTPError(value.full_url, status, "synthetic", None, BytesIO(json.dumps(payload).encode()))

    monkeypatch.setattr(smoke, "urlopen", request)
    if accepted:
        smoke._verify_retired_transfer_routes({"port": 1234, "token": "synthetic"})
        assert calls == [(method, f"http://127.0.0.1:1234/v1/transfer/{operation}")
                         for operation in ("inventory", "execute") for method in ("GET", "POST")]
    else:
        with pytest.raises(RuntimeError, match="did not reject"):
            smoke._verify_retired_transfer_routes({"port": 1234, "token": "synthetic"})


@pytest.mark.parametrize("matching", [True, False])
def test_packaged_speed_checks_close_sqlite_even_on_assertion(tmp_path, monkeypatch, matching):
    smoke = load_smoke(monkeypatch)
    baseline = (20, 14000, 12000)

    class Connection:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass  # sqlite3's transaction context does not close its handle.

        def execute(self, query):
            row = baseline if "sum(" in query else ((20,) if "ledger_speed_facts" in query else (str(LEDGER_SCHEMA_VERSION),))
            if not matching:
                row = (0,)
            return SimpleNamespace(fetchone=lambda: row)

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(smoke.sqlite3, "connect", lambda path: connection)
    monkeypatch.setattr(smoke, "_request", lambda *args: {
        "capabilities": ["observed-output-speed-v1"], "speed": {"pending": 0},
        "cache_hit": True, "speed_navigation": {"granularity": "hourly"},
    })
    (tmp_path / "ledger.schema-5-backup-synthetic").touch()
    report = {"html": "Observed Output Speed 300.0"}
    if matching:
        smoke._verify_packaged_speed({}, tmp_path / "ledger", baseline, report)
    else:
        with pytest.raises(AssertionError):
            smoke._verify_packaged_speed({}, tmp_path / "ledger", baseline, report)
    assert connection.closed


@pytest.mark.parametrize("schema_offset", [-1, 0, 1])
def test_packaged_speed_accepts_only_the_actual_supported_ledger_upgrade(tmp_path, monkeypatch, schema_offset):
    from codex_usage.ledger_schema import open_ledger
    from codex_usage.speed_recovery import run_speed_recovery_slice
    from observed_speed_fixture import legacy_speed_home

    smoke = load_smoke(monkeypatch)
    db, baseline = legacy_speed_home(tmp_path / "codex")
    run_speed_recovery_slice(db)
    with open_ledger(db, read_only=True) as connection:
        assert connection.execute("select count(*) from ledger_speed_facts where reason=''").fetchone()[0] == 20
    if schema_offset:
        with open_ledger(db) as connection:
            connection.execute("update ledger_meta set value=? where key='schema_version'",
                (str(LEDGER_SCHEMA_VERSION+schema_offset),))
            connection.commit()
    monkeypatch.setattr(smoke, "_request", lambda *args: {
        "capabilities": ["observed-output-speed-v1"], "speed": {"pending": 0},
        "cache_hit": True, "speed_navigation": {"granularity": "hourly"},
    })
    if schema_offset:
        with pytest.raises(AssertionError):
            smoke._verify_packaged_speed({}, db, baseline, {"html": "Observed Output Speed 300.0"})
    else:
        smoke._verify_packaged_speed({}, db, baseline, {"html": "Observed Output Speed 300.0"})
