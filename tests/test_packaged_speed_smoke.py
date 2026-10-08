import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("matching", [True, False])
def test_packaged_speed_checks_close_sqlite_even_on_assertion(tmp_path, monkeypatch, matching):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("packaged_agent_smoke", scripts / "smoke-test-packaged-agent.py")
    smoke = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(smoke)
    baseline = (20, 14000, 12000)

    class Connection:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass  # sqlite3's transaction context does not close its handle.

        def execute(self, query):
            row = baseline if "sum(" in query else ((20,) if "ledger_speed_facts" in query else ("6",))
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
