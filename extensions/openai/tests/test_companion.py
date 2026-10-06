import http.client
import json
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from companion.client import CollectorClient
from companion.server import ROOT, UI_URI, create_server


@pytest.fixture
def anyio_backend():
    return "asyncio"


class FakeClient:
    def __init__(self):
        self.requests = []
    def query(self, payload):
        self.requests.append(payload)
        return {"schema_version": 1, "state": "ok", "result": {"schema_version": 1, "data": {"kind": payload["kind"]}}, "error_code": None}


@pytest.mark.anyio
async def test_private_tool_contract_and_app_resource():
    fake = FakeClient()
    async with Client(create_server(fake)) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert set(tools) == {"collector_status", "usage_summary", "usage_breakdown", "compare_usage", "list_projects", "allowance_status", "storage_inventory", "analyze_storage_tree", "storage_job", "cancel_storage_analysis", "capture_usage", "open_usage_dashboard"}
        for name, t in tools.items():
            assert t.output_schema["properties"]["schema_version"]["const"] == 1
            assert t.annotations.read_only_hint is (name not in {"analyze_storage_tree", "cancel_storage_analysis", "capture_usage"})
            assert t.annotations.destructive_hint is False
        assert tools["open_usage_dashboard"].meta["ui"]["resourceUri"] == UI_URI
        assert not (tools["usage_summary"].meta or {}).get("ui")
        resource = (await client.read_resource(UI_URI)).contents[0]
        assert resource.meta["ui"]["csp"]["connectDomains"] == []
        assert resource.mime_type == "text/html;profile=mcp-app"
        assert "Task Storage" in resource.text
        a = await client.call_tool("usage_summary", {"period": "yesterday"})
        b = await client.call_tool("open_usage_dashboard", {"period": "yesterday"})
        assert a.structured_content["result"]["data"] == b.structured_content["result"]["data"]
        assert fake.requests[-1] == {"kind": "summary", "scope": {"period": "yesterday", "project_ids": [], "start_date": None, "end_date": None}}


@pytest.mark.anyio
async def test_companion_stdio_disabled_without_data_or_secrets():
    async with Client(StdioServerParameters(command=sys.executable, args=["-m", "companion.server"],
            cwd=str(ROOT), env={"CODEX_USAGE_COMPANION_ENABLED": "0", "CONTROL_PLANE_API_KEY": "SECRET_KEY"})) as client:
        result = await client.call_tool("usage_summary", {})
        assert result.structured_content["state"] == "disabled"
        assert "SECRET" not in json.dumps(result.model_dump(mode="json"))


def descriptor(tmp_path):
    path = tmp_path / ".codex-usage" / "agent.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"api_version": 1, "process_owner": "transient", "port": 12345,
        "token": "SECRET" * 8, "started_at": "now", "codex_home": str(tmp_path)}))
    path.chmod(0o600)
    return path


def test_transport_capability_auth_loopback_and_no_retry(tmp_path):
    descriptor(tmp_path)
    calls = []
    class Connection:
        def __init__(self, host, port, timeout):
            assert host == "127.0.0.1" and port == 12345
        def request(self, method, route, body, headers):
            assert headers["Authorization"] == "Bearer " + "SECRET" * 8
            calls.append((method, route))
            self.route = route
        def getresponse(self):
            body = {"schema_version": 1, "capability": "private-companion-v1", "data": {}} if self.route.endswith("health") else {"schema_version": 1, "data": {}}
            return SimpleNamespace(status=200, read=lambda limit: json.dumps(body).encode())
        def close(self):
            pass
    with patch.object(http.client, "HTTPConnection", Connection):
        client = CollectorClient(home=tmp_path, enabled=True)
        assert client.query({"kind": "summary"})["state"] == "ok"
        assert len(calls) == 2
        assert "SECRET" not in json.dumps(client.query({"kind": "summary"}))
        assert len(calls) == 3
    with patch.object(client, "_request", side_effect=OSError("SECRET path")):
        assert client.query({"kind": "capture"}) == {"schema_version": 1, "state": "uncertain", "result": {}, "error_code": "action_completion_unknown"}


def test_offline_incompatible_and_malformed_descriptor_are_safe(tmp_path):
    client = CollectorClient(home=tmp_path, enabled=True)
    assert client.query({"kind": "summary"})["state"] == "offline"
    path = descriptor(tmp_path)
    path.write_text("[]")
    assert client.query({"kind": "summary"})["state"] == "offline"
    path.write_text(json.dumps({"api_version": 999}))
    assert client.query({"kind": "summary"})["state"] == "incompatible"
    assert "SECRET" not in json.dumps(client.query({"kind": "summary"}))


def test_adapter_does_not_import_writer_or_open_database():
    for path in (ROOT / "companion").glob("*.py"):
        source = path.read_text()
        for forbidden in ("sqlite3", "codex_usage", "subprocess", "AgentSettings", "capture_once"):
            assert forbidden not in source
    assert not CollectorClient(enabled=False).enabled
