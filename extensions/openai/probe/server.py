from __future__ import annotations

import os
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.apps import Apps, ResourceCsp

from probe.data import Period, ProbeUsage, Project, synthetic_usage

UI_URI = "ui://codex-usage/probe-v2.html"
ROOT = Path(__file__).resolve().parents[1]


def create_server() -> MCPServer:
    bundle = ROOT / "web" / "dist" / "probe.html"
    if not bundle.is_file():
        raise RuntimeError("Build the probe UI first: npm --prefix web run build")
    apps = Apps()
    apps.add_html_resource(
        UI_URI,
        bundle.read_text(encoding="utf-8"),
        title="Codex Usage connection test",
        csp=ResourceCsp(connect_domains=[], resource_domains=[], frame_domains=[]),
        prefers_border=False,
    )

    @apps.tool(
        resource_uri=UI_URI,
        title="Open synthetic Codex Usage dashboard",
        description="Open a synthetic-only dashboard to test the private connection and UI. No real usage is available.",
        meta={"openai/ui": {"entrypoints": [{"type": "global"}, {"type": "thread"}]}},
        structured_output=True,
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    )
    def open_probe_dashboard(period: Period = "7d", project: Project = "all") -> ProbeUsage:
        return synthetic_usage(period, project)

    server = MCPServer(
        "Codex Usage private test",
        version="0.0.1",
        instructions="This is a synthetic-only connection test. Never present its values as the user's real usage. It has no filesystem, collector, capture, or deletion tools.",
        extensions=[apps],
    )

    @server.tool(
        title="Query synthetic usage",
        description="Query the synthetic connection-test dataset without opening a dashboard. No real usage is available.",
        structured_output=True,
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
    )
    def probe_usage(period: Period = "7d", project: Project = "all") -> ProbeUsage:
        return synthetic_usage(period, project)

    return server


def main() -> None:
    os.environ.pop("CONTROL_PLANE_API_KEY", None)
    create_server().run()


if __name__ == "__main__":
    main()
