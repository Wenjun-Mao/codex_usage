from __future__ import annotations

import hmac
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from codex_usage.agent_protocol import AGENT_API_VERSION, MAX_API_REQUEST_BYTES


class AgentHttpServer:
    def __init__(self, agent: Any, *, token: str, port: int = 0) -> None:
        handler = _handler_type(agent, token)
        self._server = ThreadingHTTPServer(("127.0.0.1", port), handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="codex-usage-api",
            daemon=True,
        )

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _handler_type(agent: Any, token: str) -> type[BaseHTTPRequestHandler]:
    class AgentRequestHandler(BaseHTTPRequestHandler):
        server_version = "CodexUsageAgent/2"
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:  # noqa: N802
            if not self._authorize():
                return
            path, query = self._path_and_query()
            try:
                if path == "/v1/health":
                    self._json(
                        HTTPStatus.OK,
                        {
                            "ok": True,
                            "api_version": AGENT_API_VERSION,
                            "status": agent.status_payload(),
                        },
                    )
                elif path == "/v1/status":
                    self._json(HTTPStatus.OK, agent.status_payload())
                elif path == "/v1/settings":
                    self._json(HTTPStatus.OK, agent.settings.to_dict())
                elif path == "/v1/projects":
                    self._json(HTTPStatus.OK, {"projects": agent.projects()})
                elif path == "/v1/tasks":
                    project_key = _first(query, "project_key") or None
                    self._json(
                        HTTPStatus.OK,
                        {"tasks": agent.tasks(project_key=project_key)},
                    )
                elif path == "/v1/transitions":
                    self._json(
                        HTTPStatus.OK,
                        {"transitions": agent.transitions()},
                    )
                elif path == "/v1/report":
                    report = agent.report(
                        range_name=_first(query, "range") or "30d",
                        project_keys=query.get("project_key", []),
                        theme=_first(query, "theme") or agent.settings.theme,
                    )
                    self._json(HTTPStatus.OK, report.to_dict())
                elif path == "/v1/storage/snapshot":
                    self._json(
                        HTTPStatus.OK,
                        agent.storage_snapshot(query.get("project_key", [])),
                    )
                elif path == "/v1/migration/plan":
                    self._json(HTTPStatus.OK, agent.migration_plan())
                elif path == "/v1/service":
                    self._json(HTTPStatus.OK, agent.service_status())
                elif path.startswith("/v1/jobs/"):
                    operation_id = _path_identifier(path, "/v1/jobs/")
                    self._json(
                        HTTPStatus.OK,
                        agent.operation_status(operation_id),
                    )
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except Exception as exc:
                self._exception(exc)

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorize():
                return
            path, _ = self._path_and_query()
            try:
                payload = self._read_json_object()
                if path == "/v1/capture":
                    result = agent.capture_now().result()
                    status = (
                        HTTPStatus.OK
                        if result.outcome == "success"
                        else HTTPStatus.INTERNAL_SERVER_ERROR
                    )
                    self._json(status, result.to_dict())
                elif path == "/v1/settings":
                    settings = agent.update_settings(payload)
                    self._json(HTTPStatus.OK, settings.to_dict())
                elif path == "/v1/storage/jobs":
                    tree_id = str(payload.get("tree_id", "")).strip()
                    if not tree_id:
                        raise ValueError("tree_id is required")
                    self._json(
                        HTTPStatus.ACCEPTED,
                        agent.start_storage_analysis(tree_id),
                    )
                elif path.startswith("/v1/jobs/") and path.endswith("/cancel"):
                    operation_id = _path_identifier(
                        path[: -len("/cancel")], "/v1/jobs/"
                    )
                    self._json(
                        HTTPStatus.OK,
                        agent.cancel_operation(operation_id),
                    )
                elif path == "/v1/migration/run":
                    raw_precedence = payload.get("precedence", {})
                    if not isinstance(raw_precedence, dict) or not all(
                        isinstance(key, str) and isinstance(value, str)
                        for key, value in raw_precedence.items()
                    ):
                        raise ValueError("precedence must be a string map")
                    self._json(
                        HTTPStatus.OK,
                        agent.migrate_legacy(dict(raw_precedence)),
                    )
                elif path == "/v1/transfer/inventory":
                    self._json(HTTPStatus.OK, agent.transfer_inventory(payload))
                elif path == "/v1/transfer/execute":
                    self._json(HTTPStatus.OK, agent.execute_transfer(payload))
                elif path == "/v1/shutdown":
                    self._json(HTTPStatus.ACCEPTED, {"stopping": True})
                    threading.Timer(0.05, agent.request_shutdown).start()
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except Exception as exc:
                self._exception(exc)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _authorize(self) -> bool:
            if self.headers.get("Origin"):
                self._json(
                    HTTPStatus.FORBIDDEN,
                    {"error": "browser origins are not accepted"},
                )
                return False
            host = self.headers.get("Host", "")
            if not (
                host.startswith("127.0.0.1:")
                or host.startswith("localhost:")
                or host == "127.0.0.1"
                or host == "localhost"
            ):
                self._json(HTTPStatus.BAD_REQUEST, {"error": "invalid host"})
                return False
            expected = f"Bearer {token}"
            supplied = self.headers.get("Authorization", "")
            if not hmac.compare_digest(supplied, expected):
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"})
                return False
            return True

        def _path_and_query(self) -> tuple[str, dict[str, list[str]]]:
            parsed = urlsplit(self.path)
            return parsed.path, parse_qs(parsed.query, keep_blank_values=True)

        def _read_json_object(self) -> dict[str, object]:
            if self.headers.get("Transfer-Encoding"):
                raise ValueError("streaming request bodies are not accepted")
            raw_length = self.headers.get("Content-Length", "0")
            try:
                length = int(raw_length)
            except ValueError as exc:
                raise ValueError("invalid Content-Length") from exc
            if length < 0 or length > MAX_API_REQUEST_BYTES:
                raise ValueError("request body is too large")
            raw = self.rfile.read(length)
            if not raw:
                return {}
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("request body must be a JSON object")
            return payload

        def _exception(self, exc: Exception) -> None:
            status = (
                HTTPStatus.BAD_REQUEST
                if isinstance(exc, (ValueError, KeyError, json.JSONDecodeError))
                else HTTPStatus.INTERNAL_SERVER_ERROR
            )
            self._json(status, {"error": f"{type(exc).__name__}: {exc}"})

        def _json(self, status: HTTPStatus, payload: object) -> None:
            encoded = json.dumps(payload, separators=(",", ":")).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(encoded)

    return AgentRequestHandler


def _first(query: dict[str, list[str]], key: str) -> str:
    values = query.get(key, [])
    return values[0] if values else ""


def _path_identifier(path: str, prefix: str) -> str:
    value = path.removeprefix(prefix).strip("/")
    if not value or "/" in value or len(value) > 100:
        raise ValueError("invalid operation id")
    return value
