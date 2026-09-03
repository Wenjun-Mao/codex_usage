from __future__ import annotations

from pathlib import Path

from codex_usage import agent_client
from codex_usage.agent_protocol import AGENT_API_VERSION, AgentDescriptor


class _JsonResponse:
    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return b'{"ok":true}'


def test_internal_client_times_out_health_but_allows_long_operations(
    monkeypatch,
    tmp_path: Path,
) -> None:
    observed_timeouts: list[float | None] = []

    def open_request(request: object, *, timeout: float | None) -> _JsonResponse:
        observed_timeouts.append(timeout)
        return _JsonResponse()

    monkeypatch.setattr(agent_client, "urlopen", open_request)
    client = agent_client.AgentClient(
        AgentDescriptor(
            pid=123,
            api_version=AGENT_API_VERSION,
            port=43123,
            token="a" * 40,
            started_at="2026-09-02T00:00:00+00:00",
            codex_home=str(tmp_path),
        )
    )

    client.get("/v1/health")
    client.post("/v1/capture", {})

    assert observed_timeouts == [2, None]
