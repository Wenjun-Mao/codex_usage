from __future__ import annotations

import http.client

from codex_usage.agent_api import AgentHttpServer
from codex_usage.agent_protocol import AGENT_API_VERSION, MAX_API_REQUEST_BYTES


class _StubAgent:
    def status_payload(self) -> dict[str, object]:
        return {"ready": True}


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


def _request(port: int, *, headers: dict[str, str]) -> tuple[int, str]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request("GET", "/v1/health", headers=headers)
    response = connection.getresponse()
    result = response.status, response.read().decode()
    connection.close()
    return result
