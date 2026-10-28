"""Project-speed decoding stays snapshot-local during real agent capture."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from time import monotonic, sleep
from urllib.parse import quote

import pytest

from codex_usage import speed_queries
from codex_usage.agent_paths import agent_descriptor_path, ledger_database_path
from codex_usage.agent_runtime import CodexUsageAgent
from codex_usage.allowance_probe import QuotaRead
from codex_usage.ledger_queries import query_ledger_records
from codex_usage.ledger_schema import ledger_revision, open_ledger
from release_tooling_support import load_tool
from test_agent_runtime import _settings_file
from test_agent_wal_integration import wait_status

fixture = load_tool("observed_speed_fixture")
client = load_tool("smoke-test-packaged-agent")


@pytest.mark.parametrize("change", ["usage", "quota", "replacement"])
def test_project_report_snapshot_does_not_block_capture(tmp_path, monkeypatch, change):
    home = tmp_path / "home"
    cwd = str(tmp_path / "project")
    source = fixture.write_source(home, count=30, cwd=cwd)
    if change == "quota":
        monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance",
            lambda _: QuotaRead(fixture.AT.isoformat(), diagnostics="synthetic offline"))
    else:
        monkeypatch.setattr("codex_usage.agent_capture.capture_quota_read", lambda *a: None)
    agent = CodexUsageAgent(settings_file=_settings_file(tmp_path, home, interval=None))
    entered, release = Event(), Event()
    observed = []
    original = speed_queries._row_to_usage_record

    def decode(row, metadata=None):
        if not entered.is_set():
            entered.set()
            assert release.wait(15), "capture did not finish while report snapshot was open"
        record = original(row, metadata)
        observed.append(record)
        return record

    try:
        agent.start()
        wait_status(agent, lambda status: status["last_capture_outcome"] == "success")
        descriptor = agent.descriptor.to_dict()
        path = ledger_database_path(home)
        with open_ledger(path, read_only=True) as db:
            before = query_ledger_records(db)
            revision = ledger_revision(db)
            generations = tuple(db.execute("select generation_id from ledger_generations where status='trusted'"))
            quota_count = db.execute("select count(*) from quota_reads").fetchone()[0]
        key = before[0].project_key
        url = f"/v1/report?range=all&theme=night&project_key={quote(key, safe='')}"
        monkeypatch.setattr(speed_queries, "_row_to_usage_record", decode)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(client._request, descriptor, "GET", url)
            try:
                assert entered.wait(10), "HTTP project report did not reach speed decoding"
                if change == "usage":
                    fixture.append_rows(source, fixture.response(30))
                elif change == "replacement":
                    fixture.write_source(home, count=4, seconds=3, cwd=cwd)
                else:
                    stamp = (fixture.AT + timedelta(minutes=1)).isoformat()
                    monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance",
                        lambda _: QuotaRead(stamp, diagnostics="synthetic offline"))
                started = monotonic()
                capture = client._request(descriptor, "POST", "/v1/capture", {})
                assert capture["outcome"] == "success"
                assert monotonic() - started < 10
                expected_count = {"usage": 31, "quota": 30, "replacement": 4}[change]
                deadline = monotonic() + 10
                while True:
                    with open_ledger(path, read_only=True) as db:
                        after = query_ledger_records(db)
                    if len(after) == expected_count:
                        break
                    assert monotonic() < deadline, "ordinary replacement did not finish"
                    sleep(0.01)
            finally:
                release.set()
            first = pending.result(timeout=10)
        assert first["ledger_revision"] == revision
        assert observed == before
        observed.clear()
        second = client._request(descriptor, "GET", url)
        assert second["ledger_revision"] > revision
        assert observed == after
        with open_ledger(path, read_only=True) as db:
            assert db.execute("pragma integrity_check").fetchone()[0] == "ok"
            assert db.execute("select count(*) from quota_reads").fetchone()[0] == quota_count + (change == "quota")
            if change == "replacement":
                assert tuple(db.execute("select generation_id from ledger_generations where status='trusted'")) != generations
    finally:
        release.set()
        agent.stop()
    assert source.is_file()
    assert not agent_descriptor_path(home).exists()
