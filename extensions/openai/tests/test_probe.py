from __future__ import annotations

import json
import sys

import pytest
from mcp import Client
from mcp.client.stdio import StdioServerParameters

from probe.data import synthetic_usage
from probe.server import ROOT, UI_URI, create_server


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.parametrize("period", ["today", "yesterday", "7d", "30d"])
@pytest.mark.parametrize("project", ["all", "demo-a", "demo-b"])
def test_synthetic_scope_and_totals(period, project):
    result = synthetic_usage(period, project)
    assert result["source"] == "synthetic"
    assert result["live_data_supported"] is False
    assert result["scope"]["period"] == period
    assert result["scope"]["project"] == project
    assert result["tokens"] == sum(row["tokens"] for row in result["projects"])
    assert result["api_cost_usd"] == pytest.approx(
        sum(row["api_cost_usd"] for row in result["projects"])
    )
    assert result["allowance"]["remaining_percent"] == 83
    assert len(result["projects"]) == (2 if project == "all" else 1)


@pytest.mark.anyio
async def test_tool_discovery_and_dashboard_resource():
    async with Client(create_server()) as client:
        tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        assert set(tools) == {"probe_usage", "open_probe_dashboard"}
        for tool in tools.values():
            assert tool.output_schema["properties"]["source"]["const"] == "synthetic"
            assert tool.output_schema["properties"]["live_data_supported"]["const"] is False
            assert tool.annotations.read_only_hint is True
            assert tool.annotations.destructive_hint is False
            assert tool.annotations.open_world_hint is False
        dashboard_meta = tools["open_probe_dashboard"].meta
        assert dashboard_meta["ui"]["resourceUri"] == UI_URI
        assert dashboard_meta["openai/ui"]["entrypoints"] == [
            {"type": "global"}, {"type": "thread"}
        ]
        assert not (tools["probe_usage"].meta or {}).get("ui")
        resource = (await client.read_resource(UI_URI)).contents[0]
        assert resource.mime_type == "text/html;profile=mcp-app"
        assert resource.meta["ui"]["csp"] == {
            "connectDomains": [], "resourceDomains": [], "frameDomains": []
        }
        assert "Synthetic data" in resource.text
        assert "<!-- SCRIPT -->" not in resource.text
        assert "<!-- STYLE -->" not in resource.text
        assert resource.text.count("<!doctype html>") == 1


@pytest.mark.anyio
async def test_headless_and_ui_queries_agree():
    async with Client(create_server()) as client:
        args = {"period": "yesterday", "project": "demo-b"}
        headless = await client.call_tool("probe_usage", args)
        dashboard = await client.call_tool("open_probe_dashboard", args)
        assert not headless.is_error
        assert not dashboard.is_error
        assert headless.structured_content == dashboard.structured_content
        assert headless.structured_content == synthetic_usage(**args)
        assert "synthetic" in headless.content[0].text


@pytest.mark.anyio
@pytest.mark.parametrize("args", [
    {"period": "all"}, {"project": "/Users/private"},
])
async def test_invalid_scopes_are_rejected(args):
    async with Client(create_server()) as client:
        result = await client.call_tool("probe_usage", args)
        assert result.is_error
        assert result.structured_content is None


@pytest.mark.anyio
async def test_real_stdio_process():
    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "probe.server"],
        cwd=str(ROOT),
        env={"CONTROL_PLANE_API_KEY": "sentinel-must-not-be-returned"},
    )
    async with Client(parameters) as client:
        result = await client.call_tool("probe_usage", {"period": "today"})
        assert not result.is_error
        assert result.structured_content["api_cost_usd"] == 17.2
        assert "sentinel-must-not-be-returned" not in json.dumps(
            result.model_dump(mode="json")
        )


def test_probe_has_no_live_core_dependency():
    for module in (ROOT / "probe").glob("*.py"):
        source = module.read_text(encoding="utf-8")
        assert "codex_usage" not in source
        assert "sqlite3" not in source
