"""Disposable captured-ledger parity and the outbound sharing boundary."""
from datetime import UTC, datetime
import json
from types import SimpleNamespace

import pytest

import codex_usage.ledger_materialization as materialization
from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.aggregation import summarize_records, resolve_timezone
from codex_usage.companion_contract import CompanionError
from codex_usage.companion_service import CompanionService
from codex_usage.companion_snapshots import SnapshotStore
from codex_usage.ledger_queries import load_ledger_records
from codex_usage.ledger_schema import increment_ledger_revision, open_ledger


def write_session(home, task, project, stamp, *, total=1000):
    path = home / "sessions" / f"{task}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {"timestamp": stamp, "type": "session_meta", "payload": {
            "id": task, "cwd": f"/private/SECRET_HOME/{project}", "title": "SECRET_TASK_TITLE",
        }},
        {"timestamp": stamp, "type": "turn_context", "payload": {"model": "gpt-6-sol"}},
        {"timestamp": stamp, "type": "event_msg", "payload": {"type": "token_count", "info": {
            "total_token_usage": {"input_tokens": total - 10, "cached_input_tokens": 500,
                                  "output_tokens": 10, "total_tokens": total},
        }}},
    ]
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    return path


@pytest.fixture
def companion(tmp_path, monkeypatch):
    home = tmp_path / ".codex"
    write_session(home, "SECRET_TASK_1", "alpha", "2026-10-05T16:00:00Z")
    write_session(home, "SECRET_TASK_2", "beta", "2026-10-06T16:00:00Z", total=2000)
    monkeypatch.setattr("codex_usage.agent_capture.capture_quota_read", lambda *a: None)
    assert capture_once(home, request_kind="manual", max_workers=1).outcome == "success"
    settings = SimpleNamespace(timezone="America/Toronto", auto_project_transitions=True)
    service = CompanionService(home, lambda: settings, now=lambda: datetime(2026, 10, 6, 20, tzinfo=UTC))
    return service


def test_shared_materialization_parity_privacy_and_zero_source_reads(companion, monkeypatch):
    expected = summarize_records(load_ledger_records(ledger_database_path(companion.home)))
    from pathlib import Path
    original = Path.open
    def reject_sources(path, *args, **kwargs):
        if path.suffix == ".jsonl":
            pytest.fail("structured query reopened a rollout")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "open", reject_sources)
    result = companion.query({"kind": "summary", "scope": {"period": "all"}})
    assert result["data"]["language"]["usage"] == expected.usage.to_dict()
    assert result["data"]["language"]["api_cost"] == expected.cost.to_dict()
    assert result["data"]["language"]["estimated_standard_credits"] == expected.credits.to_dict()
    assert result["timezone"] == "America/Toronto"
    for kind, extra in (("summary", {}), ("breakdown", {"dimension": "agent"}),
                        ("projects", {}), ("health", {}), ("allowance", {})):
        output = json.dumps(companion.query({"kind": kind, **extra}))
        for secret in ("SECRET", "/private", str(companion.home), "file_path", "last_capture_error"):
            assert secret not in output


def test_warm_queries_do_not_reprice_or_load_historical_evidence(companion, monkeypatch):
    scope = {"period": "all"}
    first = companion.query({"kind": "summary", "scope": scope})
    def fail(*a, **kw):
        pytest.fail("warm projection recalculated captured usage")
    monkeypatch.setattr(materialization, "value_records", fail)
    monkeypatch.setattr(materialization, "query_ledger_records", fail)
    assert companion.query({"kind": "summary", "scope": scope}) == first
    page = companion.query({"kind": "breakdown", "scope": scope, "dimension": "model"})
    assert page["data"]["rows"][0]["usage"]["total_tokens"] == 3000


def test_scope_clock_project_selection_and_invalid_handle(companion):
    today = companion.query({"kind": "summary", "scope": {"period": "today"}})
    assert today["resolved_range"]["start_date"] == "2026-10-06"
    assert today["scope"]["start_date"] is None
    assert companion.query({"kind": "summary", "scope": today["scope"]}) == today
    assert today["data"]["language"]["usage"]["total_tokens"] == 2000
    projects = companion.query({"kind": "breakdown", "scope": {"period": "all"}, "dimension": "project"})
    selected = projects["data"]["rows"][0]
    filtered = companion.query({"kind": "summary", "scope": {"period": "all", "project_ids": [selected["id"]]}})
    assert filtered["data"]["language"]["usage"] == selected["usage"]
    with pytest.raises(CompanionError, match="selection_expired"):
        companion.query({"kind": "summary", "scope": {"project_ids": ["/private/arbitrary"]}})


def test_pages_remain_on_original_snapshot_and_expire(companion):
    now = [0]
    companion.store = SnapshotStore(clock=lambda: now[0], ttl=10)
    first = companion.query({"kind": "breakdown", "scope": {"period": "all"}, "dimension": "project", "limit": 1})
    with open_ledger(ledger_database_path(companion.home)) as conn:
        increment_ledger_revision(conn)
        conn.commit()
    current = companion.query({"kind": "summary", "scope": {"period": "all"}})
    assert current["status"]["ledger_revision"] > first["status"]["ledger_revision"]
    second = companion.query({"kind": "breakdown", "cursor": first["data"]["next_cursor"]})
    assert first["snapshot_id"] == second["snapshot_id"]
    assert first["status"]["ledger_revision"] == second["status"]["ledger_revision"]
    assert second["data"]["rows"][0]["id"] != first["data"]["rows"][0]["id"]
    with pytest.raises(CompanionError):
        companion.query({"kind": "projects", "cursor": first["data"]["next_cursor"]})
    now[0] = 11
    with pytest.raises(CompanionError, match="snapshot_expired"):
        companion.query({"kind": "breakdown", "cursor": first["data"]["next_cursor"]})


def test_comparison_one_snapshot_and_zero_baseline(companion):
    compared = companion.query({"kind": "compare", "left": {"period": "yesterday"}, "right": {"period": "today"}})
    assert compared["data"]["changes"]["tokens"] == {"left": 1000, "right": 2000, "delta": 1000, "percent_change": 100}
    empty = companion.query({"kind": "compare", "left": {
        "period": "custom", "start_date": "2026-10-04", "end_date": "2026-10-04",
    }, "right": {"period": "today"}})
    assert empty["data"]["changes"]["api_cost_usd"]["percent_change"] is None


@pytest.mark.parametrize("payload", [
    {"kind": "summary", "scope": {"path": "/private"}},
    {"kind": "summary", "scope": {"period": "invalid"}},
    {"kind": "breakdown", "limit": 101},
    {"kind": "breakdown", "limit": True},
    {"kind": "breakdown", "dimension": "sql"},
    {"kind": "delete"}, {"kind": "capture", "scope": {}},
    {"kind": ["summary"]}, {"kind": "summary", "dimension": "model"},
])
def test_strict_request_contract(companion, payload):
    with pytest.raises(CompanionError):
        companion.query(payload)


def test_allowance_independent_of_filters(companion):
    allowance = companion.query({"kind": "allowance"})
    assert allowance["data"]["scope"] == "account-wide"
    assert allowance["data"]["headline"] is None
    assert resolve_timezone(allowance["timezone"])


def test_explicit_capture_only_and_sanitized_failure(companion):
    from concurrent.futures import Future
    from codex_usage.ledger_queries import load_ledger_status
    calls = []
    def capture():
        calls.append(True)
        future = Future()
        future.set_result(SimpleNamespace(run_id=5, request_kind="scheduled", outcome="failed", elapsed_seconds=1,
            status=load_ledger_status(ledger_database_path(companion.home)), error="SECRET_ERROR"))
        return future
    companion.query({"kind": "summary"}, capture=capture)
    assert calls == []
    result = companion.query({"kind": "capture"}, capture=capture)
    assert calls == [True]
    assert result["data"]["error_code"] == "capture_failed"
    assert result["data"]["request_kind"] == "scheduled"
    assert "SECRET" not in json.dumps(result)


def test_adapter_to_real_loopback_api_preserves_core_results(companion):
    import importlib.util
    from pathlib import Path
    from codex_usage.agent_api import AgentHttpServer

    adapter_path = Path(__file__).resolve().parents[1] / "extensions/openai/companion/client.py"
    spec = importlib.util.spec_from_file_location("private_client", adapter_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server = AgentHttpServer(SimpleNamespace(companion_query=companion.query), token="SECRET" * 8)
    descriptor = companion.home / ".codex-usage/agent.json"
    descriptor.write_text(json.dumps({"api_version": 1, "process_owner": "transient",
        "port": server.port, "token": "SECRET" * 8, "started_at": "2026-10-06T20:00:00Z",
        "codex_home": str(companion.home)}))
    descriptor.chmod(0o600)
    server.start()
    try:
        client = module.CollectorClient(home=companion.home, enabled=True)
        payload = {"kind": "summary", "scope": {"period": "all"}}
        result = client.query(payload)
        assert result["state"] == "ok"
        assert result["result"] == companion.query(payload)
        assert "SECRET" not in json.dumps(result)
        assert client.query({"kind": "delete"})["error_code"] == "invalid_request"
        assert client.query({"kind": "capture"})["error_code"] == "action_unavailable"
    finally:
        server.stop()
    assert client.query(payload)["state"] == "offline"
