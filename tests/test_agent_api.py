from __future__ import annotations

import http.client
import json

import pytest

from codex_usage.agent_api import AgentHttpServer
from codex_usage.agent_protocol import (
    ACCOUNTING_CAPABILITY,
    AGENT_API_VERSION,
    MAX_API_REQUEST_BYTES,
)
from codex_usage.companion_contract import CompanionError


class _StubAgent:
    def status_payload(self) -> dict[str, object]:
        return {"ready": True, "capabilities": [ACCOUNTING_CAPABILITY]}

    def report(self, **kwargs: object) -> object:
        self.report_kwargs = kwargs
        return _StubReport()


class _StubReport:
    def to_dict(self) -> dict[str, object]:
        return {"html": "report"}


def test_agent_api_requires_bearer_token_and_rejects_browser_origin() -> None:
    server = AgentHttpServer(_StubAgent(), token="x" * 40)
    server.start()
    try:
        assert _request(server.port, headers={})[0] == 401
        assert _request(
            server.port,
            headers={"Authorization": f"Bearer {'x' * 40}", "Origin": "null"},
        )[0] == 403
        status, payload = _request(
            server.port,
            headers={"Authorization": f"Bearer {'x' * 40}"},
        )
        assert status == 200
        assert f'"api_version":{AGENT_API_VERSION}' in payload
        assert json.loads(payload)["capabilities"] == [ACCOUNTING_CAPABILITY]
    finally:
        server.stop()


def test_agent_api_rejects_oversized_requests() -> None:
    server = AgentHttpServer(_StubAgent(), token="x" * 40)
    server.start()
    try:
        connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
        connection.request(
            "POST",
            "/v1/capture",
            body=b"",
            headers={
                "Authorization": f"Bearer {'x' * 40}",
                "Content-Length": str(MAX_API_REQUEST_BYTES + 1),
            },
        )
        response = connection.getresponse()
        assert response.status == 400
        assert "too large" in response.read().decode()
        connection.close()
    finally:
        server.stop()


def test_agent_api_omits_absent_calendar_bounds_for_preset_reports() -> None:
    agent = _StubAgent()
    server = AgentHttpServer(agent, token="x" * 40)
    server.start()
    try:
        status, _ = _request(
            server.port,
            headers={"Authorization": f"Bearer {'x' * 40}"},
            path="/v1/report?range=all&theme=night",
        )
        assert status == 200
        assert agent.report_kwargs == {
            "range_name": "all",
            "start_date": None,
            "end_date": None,
            "project_keys": [],
            "theme": "night",
            "speed_granularity": None,
            "speed_window_start": None,
            "speed_window_scope": None,
            "breakdown_action": None,
            "allowance_action": None,
        }
    finally:
        server.stop()


def test_private_allowance_action_uses_existing_authenticated_report_transport():
    from urllib.parse import urlencode
    from codex_usage.allowance_history_navigation import AllowanceScopeExpired
    class Agent(_StubAgent):
        def report(self, **kwargs):
            super().report(**kwargs)
            if kwargs["allowance_action"] == "expired":
                raise AllowanceScopeExpired("expired")
            if kwargs["allowance_action"] == "crafted":
                raise ValueError("unissued")
            return _StubReport()
    agent = Agent()
    server = AgentHttpServer(agent, token="x"*40)
    server.start()
    try:
        for action, expected in (("issued", 200), ("expired", 409), ("crafted", 400)):
            status, payload = _request(server.port, headers={"Authorization": "Bearer " + "x"*40},
                                       path="/v1/report?" + urlencode({"range": "all", "theme": "day", "allowance_action": action}))
            assert status == expected, payload
            assert agent.report_kwargs["allowance_action"] == action
            if expected == 409:
                assert json.loads(payload)["code"] == "allowance_scope_expired"
    finally:
        server.stop()


def test_allowance_diagnostics_is_explicit_and_requires_authentication():
    class Agent(_StubAgent):
        calls = 0
        def allowance_diagnostics(self):
            self.calls += 1
            return {"schema_version": 1, "text": "bounded diagnostics"}
    agent = Agent()
    server = AgentHttpServer(agent, token="x"*40)
    server.start()
    try:
        assert agent.calls == 0
        for headers, expected in (({}, 401),
            ({"Authorization": "Bearer " + "x"*40, "Origin": "null"}, 403),
            ({"Authorization": "Bearer " + "x"*40}, 200)):
            status, payload = _request(server.port, headers=headers, path="/v1/allowance/diagnostics")
            assert status == expected
            if status == 200:
                assert json.loads(payload) == {"schema_version": 1, "text": "bounded diagnostics"}
        assert agent.calls == 1
    finally:
        server.stop()


@pytest.mark.parametrize("path,method", [
    ("/v1/companion/health", "GET"), ("/v1/companion/query", "POST"),
])
def test_companion_routes_retain_auth_and_browser_exclusion(path, method):
    class Agent:
        def companion_query(self, payload):
            return {"schema_version": 1, "data": payload}
    server = AgentHttpServer(Agent(), token="x" * 40)
    server.start()
    try:
        for headers, expected in (({}, 401),
                ({"Authorization": "Bearer " + "x" * 40, "Origin": "null"}, 403),
                ({"Authorization": "Bearer " + "x" * 40}, 200)):
            connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
            connection.request(method, path, body="{}" if method == "POST" else None, headers=headers)
            response = connection.getresponse()
            assert response.status == expected
            response.read()
            connection.close()
    finally:
        server.stop()


@pytest.mark.parametrize("exception,code", [
    (CompanionError("selection_expired"), "selection_expired"),
    (RuntimeError("SECRET /private/task/path"), "query_failed"),
])
def test_companion_http_errors_do_not_serialize_raw_exceptions(exception, code):
    class Agent:
        def companion_query(self, payload):
            raise exception
    server = AgentHttpServer(Agent(), token="x" * 40)
    server.start()
    try:
        for path, method in (("/v1/companion/health", "GET"), ("/v1/companion/query", "POST")):
            connection = http.client.HTTPConnection("127.0.0.1", server.port, timeout=5)
            connection.request(method, path, body="{}" if method == "POST" else None,
                               headers={"Authorization": "Bearer " + "x" * 40})
            response = connection.getresponse()
            assert response.status in {400, 500}
            assert json.loads(response.read()) == {"schema_version": 1, "error_code": code}
            connection.close()
    finally:
        server.stop()


def _request(
    port: int,
    *,
    headers: dict[str, str],
    path: str = "/v1/health",
) -> tuple[int, str]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", path, headers=headers)
    response = connection.getresponse()
    result = response.status, response.read().decode()
    connection.close()
    return result
