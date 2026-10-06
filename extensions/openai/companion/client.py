"""Loopback-only authenticated transport; no ledger/core imports or lifecycle."""
import http.client
import json
import os
from pathlib import Path
from typing import Literal, TypedDict

CAPABILITY = "private-companion-v1"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024
ERRORS = {"invalid_request", "selection_expired", "snapshot_expired", "scope_too_large",
          "action_unavailable", "query_failed", "job_unknown", "too_many_jobs"}
ACTION_KINDS = {"capture", "storage_start", "storage_cancel"}


class Reply(TypedDict):
    schema_version: Literal[1]
    state: Literal["ok", "disabled", "offline", "incompatible", "error", "uncertain"]
    result: dict
    error_code: str | None


def failure(state, code) -> Reply:
    return {"schema_version": 1, "state": state, "result": {}, "error_code": code}


class CollectorClient:
    def __init__(self, *, home: Path | None = None, enabled: bool | None = None):
        self.home = home or Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex"))).expanduser()
        self.enabled = enabled if enabled is not None else os.environ.get("CODEX_USAGE_COMPANION_ENABLED") == "1"
        self._verified = None

    def query(self, payload: dict) -> Reply:
        if not self.enabled:
            return failure("disabled", "sharing_not_enabled")
        action = payload.get("kind") in ACTION_KINDS
        action_sent = False
        try:
            descriptor = self._descriptor()
            identity = (descriptor["port"], descriptor["token"], descriptor["started_at"])
            if identity != self._verified or payload.get("kind") == "health":
                health = self._request(descriptor, "GET", "/v1/companion/health")
                if health.get("schema_version") != 1 or health.get("capability") != CAPABILITY:
                    return failure("incompatible", "collector_update_required")
                self._verified = identity
                if payload.get("kind") == "health":
                    return {"schema_version": 1, "state": "ok", "result": health, "error_code": None}
            action_sent = action
            result = self._request(descriptor, "POST", "/v1/companion/query", payload)
            if "error_code" in result:
                code = result["error_code"]
                return failure("error", code if code in ERRORS else "query_failed")
            if result.get("schema_version") != 1:
                return failure("incompatible", "collector_update_required")
            return {"schema_version": 1, "state": "ok", "result": result, "error_code": None}
        except IncompatibleCollector:
            return failure("incompatible", "collector_update_required")
        except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException):
            self._verified = None
            # A disconnected action may already have completed. Never replay it.
            return failure("uncertain" if action_sent else "offline",
                           "action_completion_unknown" if action_sent else "collector_unavailable")

    def _descriptor(self):
        path = self.home / ".codex-usage" / "agent.json"
        if path.stat().st_size > 64 * 1024:
            raise ValueError()
        if os.name == "posix" and path.stat().st_mode & 0o077:
            raise ValueError()
        descriptor = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(descriptor, dict):
            raise ValueError()
        if type(descriptor.get("api_version")) is not int or descriptor.get("api_version") != 1:
            raise IncompatibleCollector()
        if descriptor.get("process_owner") != "transient":
            raise IncompatibleCollector()
        if Path(descriptor["codex_home"]).resolve() != self.home.resolve():
            raise ValueError()
        port, token = descriptor["port"], descriptor["token"]
        if type(port) is not int or not 1 <= port <= 65535 or not isinstance(token, str) or len(token) < 32:
            raise ValueError()
        if not isinstance(descriptor["started_at"], str):
            raise ValueError()
        return descriptor

    @staticmethod
    def _request(descriptor, method, route, payload=None):
        connection = http.client.HTTPConnection("127.0.0.1", descriptor["port"], timeout=90)
        try:
            connection.request(method, route, body=json.dumps(payload) if payload is not None else None,
                headers={"Authorization": "Bearer " + descriptor["token"], "Content-Type": "application/json"})
            response = connection.getresponse()
            body = response.read(MAX_RESPONSE_BYTES + 1)
            if len(body) > MAX_RESPONSE_BYTES:
                raise ValueError()
            if response.status in {404, 405}:
                raise IncompatibleCollector()
            if response.status not in {200, 400, 500}:
                raise ValueError()
            result = json.loads(body)
            if not isinstance(result, dict):
                raise ValueError()
            return result
        finally:
            connection.close()


class IncompatibleCollector(Exception):
    pass
