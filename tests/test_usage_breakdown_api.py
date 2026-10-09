"""Real authenticated HTTP routing of synthetic clock and allowance boundaries."""
from dataclasses import replace
from datetime import timedelta
import http.client
import json
from pathlib import Path
from runpy import run_path
from urllib.parse import urlencode

from codex_usage.agent_api import AgentHttpServer
from codex_usage.agent_reports import render_ledger_report
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_queries import allowance_status
from codex_usage.allowance_store import store_read
from codex_usage.ledger_schema import increment_ledger_revision, open_ledger

_fixture = run_path(str(Path(__file__).resolve().parents[1] / "scripts" / "usage_breakdown_fixture.py"))
AT, breakdown_home = _fixture["AT"], _fixture["breakdown_home"]


class SyntheticReports:
    def __init__(self, home):
        self.home = home
        self.now = AT
        self.timezone = "UTC"
        self.transitions = True

    def report(self, **kwargs):
        return render_ledger_report(self.home, timezone_name=self.timezone, now=self.now,
            auto_transitions=self.transitions, **kwargs)


def request(server, action=None, range_name="all"):
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    query = {"range": range_name, "theme": "day"}
    if action is not None:
        query["breakdown_action"] = json.dumps(action)
    connection.request("GET", "/v1/report?" + urlencode(query), headers={"Authorization": "Bearer " + "x" * 40})
    response = connection.getresponse()
    result = response.status, json.loads(response.read())
    connection.close()
    return result


def test_api_stale_expiry_rebase_slots_and_multi_series(tmp_path):
    ledger = breakdown_home(tmp_path)
    agent = SyntheticReports(tmp_path)
    server = AgentHttpServer(agent, token="x" * 40)
    server.start()
    try:
        code, report = request(server)
        assert code == 200
        nav = report["breakdown_navigation"]
        assert nav["state"]["basis"] == "cycle"
        action = next(a for a in nav["actions"] if a["state"]["metric"] == "tokens")
        assert request(server, action)[0] == 200
        assert request(server, {**action, "extra": True})[0] == 400
        agent.now = AT + timedelta(hours=2)
        assert request(server)[1]["breakdown_navigation"]["state"]["basis"] == "selected"
        assert request(server, action)[0] == 409
        with open_ledger(ledger) as connection:
            point = QuotaObservation(**allowance_status(connection, now=AT)["active_buckets"][0])
            point = replace(point, timestamp=(AT + timedelta(minutes=1)).isoformat(),
                            resets_at=int((AT + timedelta(minutes=5)).timestamp()), slot="secondary")
            store_read(connection, QuotaRead(point.timestamp, "pro", (point,)), None)
            increment_ledger_revision(connection)
            connection.commit()
        agent.now = AT + timedelta(minutes=1)
        rebased = request(server)[1]
        assert rebased["breakdown_navigation"]["state"]["basis"] == "cycle"
        assert "deadline rebase" in rebased["html"]
        agent.now = AT + timedelta(minutes=6)
        expired = request(server)[1]
        assert expired["breakdown_navigation"]["state"]["basis"] == "selected"
        assert "deadline elapsed" in expired["html"]
        with open_ledger(ledger) as connection:
            point = replace(point, timestamp=agent.now.isoformat(), resets_at=int((AT + timedelta(days=4)).timestamp()))
            store_read(connection, QuotaRead(point.timestamp, "pro", (point, replace(point, slot="primary"))), None)
            increment_ledger_revision(connection)
            connection.commit()
        assert request(server)[1]["breakdown_navigation"]["state"]["basis"] == "cycle"
        with open_ledger(ledger) as connection:
            store_read(connection, QuotaRead(point.timestamp, "pro", (point, replace(point, limit_id="other-series"))), None)
            increment_ledger_revision(connection)
            connection.commit()
        ambiguous = request(server)[1]
        assert ambiguous["breakdown_navigation"]["state"]["basis"] == "selected"
        assert "ambiguous" in ambiguous["html"]
    finally:
        server.stop()


def test_api_only_previously_issued_scope_recovers_expiry_calendar_and_settings(tmp_path):
    breakdown_home(tmp_path)
    agent = SyntheticReports(tmp_path)
    server = AgentHttpServer(agent, token="x" * 40)
    server.start()
    try:
        for scenario in ("selected expiry", "midnight", "transitions", "timezone"):
            agent.now, agent.timezone, agent.transitions = AT, "UTC", True
            report_range = "today" if scenario == "midnight" else "all"
            if scenario == "midnight":
                agent.now = AT.replace(hour=23, minute=59)
            first = request(server, range_name=report_range)[1]
            selected = next(a for a in first["breakdown_navigation"]["actions"] if a["state"]["basis"] == "selected")
            report = request(server, selected, report_range)[1]
            issued = next(a for a in report["breakdown_navigation"]["actions"] if a["state"]["metric"] == "tokens")
            if scenario == "selected expiry":
                agent.now += timedelta(hours=2)
            elif scenario == "midnight":
                agent.now += timedelta(minutes=2)
            elif scenario == "transitions":
                agent.transitions = False
            else:
                agent.timezone = "America/Toronto"
            code, payload = request(server, issued, report_range)
            assert (code, payload.get("code")) == (409, "breakdown_scope_expired"), scenario
            assert request(server, range_name=report_range)[0] == 200, scenario
            assert request(server, {**issued, "scope": "f"*64}, report_range)[0] == 400
            assert request(server, {**issued, "state": {**issued["state"], "detail": "project:forged"}}, report_range)[0] == 400
            assert request(server, {**issued, "extra": True}, report_range)[0] == 400
    finally:
        server.stop()


def test_api_recent_issued_action_survives_new_client_report_pruning(tmp_path):
    ledger = breakdown_home(tmp_path)
    server = AgentHttpServer(SyntheticReports(tmp_path), token="x"*40)
    server.start()
    try:
        old = request(server)[1]
        issued = next(a for a in old["breakdown_navigation"]["actions"] if a["state"]["metric"] == "tokens")
        with open_ledger(ledger) as connection:
            increment_ledger_revision(connection)
            connection.commit()
        assert request(server)[0] == 200  # another client renders and prunes R1
        with open_ledger(ledger, read_only=True) as connection:
            assert connection.execute("select 1 from rendered_reports where cache_key=?",
                ("breakdown-issued:"+issued["scope"],)).fetchone()
            assert not connection.execute("select 1 from rendered_reports where cache_key like 'breakdown:%' and ledger_revision=?",
                (old["ledger_revision"],)).fetchone()
        code, payload = request(server, issued)
        assert (code, payload.get("code")) == (409, "breakdown_scope_expired")
        assert request(server, {**issued, "scope": "f"*64})[0] == 400
        assert request(server, {**issued, "state": {**issued["state"], "detail": "forged"}})[0] == 400
        assert request(server)[0] == 200
    finally:
        server.stop()


def test_historical_credit_scope_commands_and_recovery_without_current_anchor(tmp_path):
    breakdown_home(tmp_path, extended=True, days=12)
    agent = SyntheticReports(tmp_path)
    server = AgentHttpServer(agent, token="x"*40)
    server.start()
    try:
        first = request(server)[1]
        historical = next(a for a in first["breakdown_navigation"]["actions"] if a["state"]["basis"].startswith("window:"))
        code, report = request(server, historical)
        assert code == 200
        credits = next(a for a in report["breakdown_navigation"]["actions"] if a["state"]["metric"] == "credits")
        assert request(server, credits)[0] == 200
        assert request(server, {**credits, "state": {**credits["state"], "basis": "window:"+"f"*64}})[0] == 400
        agent.now += timedelta(hours=2)
        code, expired = request(server, credits)
        assert (code, expired["code"]) == (409, "breakdown_scope_expired")
        stale = request(server)[1]
        reissued = next(a for a in stale["breakdown_navigation"]["actions"] if a["state"]["basis"] == historical["state"]["basis"])
        assert request(server, reissued)[0] == 200
        assert stale["breakdown_navigation"]["state"]["basis"] == "selected"
    finally:
        server.stop()
