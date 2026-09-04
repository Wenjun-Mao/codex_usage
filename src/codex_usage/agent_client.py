from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from codex_usage.agent_protocol import AgentDescriptor, read_agent_descriptor


class AgentUnavailableError(RuntimeError):
    pass


class AgentClient:
    def __init__(
        self,
        descriptor: AgentDescriptor,
        *,
        descriptor_path: Path | None = None,
    ) -> None:
        self.descriptor = descriptor
        self._descriptor_path = descriptor_path

    @classmethod
    def from_descriptor(cls, path: Path) -> "AgentClient":
        try:
            return cls(read_agent_descriptor(path), descriptor_path=path)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise AgentUnavailableError(f"Codex Usage agent is unavailable: {exc}") from exc

    def get(
        self,
        path: str,
        query: list[tuple[str, str]] | None = None,
    ) -> dict[str, Any]:
        suffix = f"?{urlencode(query or [])}" if query else ""
        request_path = f"{path}{suffix}"
        try:
            return self._request("GET", request_path, None)
        except AgentUnavailableError:
            self._refresh_descriptor()
            return self._request("GET", request_path, None)

    def post(self, path: str, payload: dict[str, object]) -> dict[str, Any]:
        return self._request("POST", path, payload)

    def _refresh_descriptor(self) -> None:
        if self._descriptor_path is None:
            raise AgentUnavailableError("agent descriptor cannot be refreshed")
        try:
            self.descriptor = read_agent_descriptor(self._descriptor_path)
        except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
            raise AgentUnavailableError(
                f"Codex Usage agent is unavailable: {exc}"
            ) from exc

    def _request(
        self,
        method: str,
        path: str,
        payload: dict[str, object] | None,
    ) -> dict[str, Any]:
        body = None if payload is None else json.dumps(payload).encode()
        request = Request(
            f"http://127.0.0.1:{self.descriptor.port}{path}",
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.descriptor.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            timeout = 2 if path.split("?", 1)[0] == "/v1/health" else None
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed loopback URL.
                decoded = json.loads(response.read())
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise AgentUnavailableError(f"agent request failed: {exc}") from exc
        if not isinstance(decoded, dict):
            raise AgentUnavailableError("agent response was not a JSON object")
        return decoded
