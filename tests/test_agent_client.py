from __future__ import annotations

from pathlib import Path
from urllib.error import URLError
from urllib.request import Request

import pytest

from codex_usage import agent_client
from codex_usage.agent_protocol import (
    AGENT_API_VERSION,
    AgentDescriptor,
    write_agent_descriptor,
)


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


def test_read_only_client_request_retries_once_after_descriptor_replacement(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    descriptor_path = tmp_path / "agent.json"
    write_agent_descriptor(descriptor_path, _descriptor(tmp_path))
    attempts = 0
    requested_ports: list[int] = []

    def open_request(request: Request, *, timeout: float | None) -> _JsonResponse:
        nonlocal attempts
        attempts += 1
        url = request.full_url
        requested_ports.append(int(url.rsplit(":", 1)[1].split("/", 1)[0]))
        if attempts == 1:
            write_agent_descriptor(
                descriptor_path,
                _descriptor(tmp_path, port=43124, token="b" * 40),
            )
            raise URLError("collector restarted")
        return _JsonResponse()

    monkeypatch.setattr(agent_client, "urlopen", open_request)

    assert agent_client.AgentClient.from_descriptor(descriptor_path).get("/v1/status") == {"ok": True}
    assert attempts == 2
    assert requested_ports == [43123, 43124]


def test_mutating_client_request_is_not_replayed_after_an_unavailable_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    descriptor_path = tmp_path / "agent.json"
    write_agent_descriptor(descriptor_path, _descriptor(tmp_path))
    attempts = 0

    def open_request(_request: object, *, timeout: float | None) -> _JsonResponse:
        nonlocal attempts
        attempts += 1
        raise URLError("collector restarted")

    monkeypatch.setattr(agent_client, "urlopen", open_request)

    with pytest.raises(agent_client.AgentUnavailableError):
        agent_client.AgentClient.from_descriptor(descriptor_path).post("/v1/capture", {})
    assert attempts == 1


def _descriptor(
    codex_home: Path,
    *,
    port: int = 43123,
    token: str = "a" * 40,
) -> AgentDescriptor:
    return AgentDescriptor(
        pid=123,
        api_version=AGENT_API_VERSION,
        port=port,
        token=token,
        started_at="2026-09-02T00:00:00+00:00",
        codex_home=str(codex_home),
        process_owner="background",
    )
