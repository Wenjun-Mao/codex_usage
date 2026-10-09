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

    def report(self, **kwargs):
        return render_ledger_report(self.home, timezone_name="UTC", now=self.now, **kwargs)


def request(server, action=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=10)
    query = {"range": "all", "theme": "day"}
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
        assert request(server, action)[0] == 400
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
