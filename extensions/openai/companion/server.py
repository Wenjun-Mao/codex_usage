"""Private conversational workflows. The synthetic probe remains separate."""
import os
from pathlib import Path
from typing import Literal

from mcp.server import MCPServer
from mcp.server.apps import Apps, ResourceCsp

from companion.client import CollectorClient, Reply

ROOT = Path(__file__).resolve().parents[1]
Period = Literal["today", "yesterday", "7d", "30d", "month", "all", "custom"]
Dimension = Literal["project", "model", "agent", "day", "hour"]
Metric = Literal["api_cost", "tokens"]
READ_ONLY = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
ACTION = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False, "idempotentHint": False}
UI_URI = "ui://codex-usage/companion-v1.html"


def scope(period, project_ids, start_date, end_date):
    return {"period": period, "project_ids": project_ids or [], "start_date": start_date, "end_date": end_date}


def create_server(client=None) -> MCPServer:
    client = client or CollectorClient()
    apps = Apps()
    bundle = ROOT / "web" / "dist" / "companion.html"
    if not bundle.is_file():
        raise RuntimeError("Build the private companion UI first")
    apps.add_html_resource(UI_URI, bundle.read_text(encoding="utf-8"), title="Codex Usage",
        csp=ResourceCsp(connect_domains=[], resource_domains=[], frame_domains=[]), prefers_border=False)
    @apps.tool(resource_uri=UI_URI, title="Open Codex Usage dashboard", structured_output=True,
               annotations=READ_ONLY, meta={"openai/ui": {"entrypoints": [{"type": "global"}, {"type": "thread"}]}})
    def open_usage_dashboard(period: Period = "30d", project_ids: list[str] | None = None,
                             start_date: str | None = None, end_date: str | None = None,
                             view: Literal["usage", "storage"] = "usage") -> Reply:
        """Open the private Usage or Storage view at this selection. Opening does not capture or scan tree contents."""
        reply = client.query({"kind": "summary", "scope": scope(period, project_ids, start_date, end_date)}
                             if view == "usage" else {"kind": "storage", "project_ids": project_ids or []})
        if reply["state"] == "ok":
            reply = dict(reply, result=dict(reply["result"], view=view))
        return reply

    server = MCPServer("Codex Usage private companion", version="0.0.1", instructions=(
        "Read captured aggregates through the existing VS Code collector. Returned data is shared with OpenAI. "
        "Never treat estimates as contractual allowance or billing. Images are separate from language costs. "
        "Use opaque issued selections and cursor pages; do not infer task contents or causes. "
        "Only invoke capture or selected-tree analysis/cancellation on an explicit user request. "
        "If action completion is uncertain, query status; do not replay. No deletion, settings, transfer, "
        "migration, schedule, or collector launch tools exist."
    ), extensions=[apps])

    @server.tool(title="Collector status", structured_output=True, annotations=READ_ONLY)
    def collector_status() -> Reply:
        """Check compatibility, captured-data freshness and coverage without starting a collector."""
        return client.query({"kind": "health"})

    @server.tool(title="Usage summary", structured_output=True, annotations=READ_ONLY)
    def usage_summary(period: Period = "30d", project_ids: list[str] | None = None,
                      start_date: str | None = None, end_date: str | None = None) -> Reply:
        """Language/category economics, separate image values, turn metrics and coverage. Custom dates are inclusive local days."""
        return client.query({"kind": "summary", "scope": scope(period, project_ids, start_date, end_date)})

    @server.tool(title="Usage breakdown", structured_output=True, annotations=READ_ONLY)
    def usage_breakdown(period: Period = "30d", project_ids: list[str] | None = None,
                        dimension: Dimension = "project", metric: Metric = "api_cost", limit: int = 25,
                        start_date: str | None = None, end_date: str | None = None,
                        cursor: str | None = None) -> Reply:
        """Exact project/model/agent/day/hour rows, not visual Other buckets. Cursor continuation preserves its original scope and revision."""
        if cursor:
            return client.query({"kind": "breakdown", "cursor": cursor})
        return client.query({"kind": "breakdown", "scope": scope(period, project_ids, start_date, end_date),
                             "dimension": dimension, "metric": metric, "limit": limit})

    @server.tool(title="Compare usage", structured_output=True, annotations=READ_ONLY)
    def compare_usage(left: dict, right: dict) -> Reply:
        """Compare two scopes on one captured revision. Scopes have period, project_ids and optional custom dates. Changes are right minus left."""
        return client.query({"kind": "compare", "left": left, "right": right})

    @server.tool(title="Project selections", structured_output=True, annotations=READ_ONLY)
    def list_projects(limit: int = 25, cursor: str | None = None) -> Reply:
        """Issue opaque project selections. Labels are intentionally generic; no paths or task titles are shared."""
        return client.query({"kind": "projects", **({"cursor": cursor} if cursor else {"limit": limit})})

    @server.tool(title="Plan Allowance", structured_output=True, annotations=READ_ONLY)
    def allowance_status() -> Reply:
        """Account-wide quota, reset, observed credit balance, calibrated reference and recent/daily/cycle pace; unaffected by report filters."""
        return client.query({"kind": "allowance"})

    @server.tool(title="Task Storage", structured_output=True, annotations=READ_ONLY)
    def storage_inventory(project_ids: list[str] | None = None, limit: int = 25, cursor: str | None = None) -> Reply:
        """Bounded metadata inventory, not a content scan. Tree handles are tied to the returned storage snapshot."""
        return client.query({"kind": "storage", **({"cursor": cursor} if cursor else {
            "project_ids": project_ids or [], "limit": limit,
        })})

    @server.tool(title="Analyze selected task tree", structured_output=True, annotations=ACTION)
    def analyze_storage_tree(snapshot_id: str, tree_id: str) -> Reply:
        """Explicit selected-tree content analysis only. Membership changes require refreshing and reselecting; never fall back to the corpus."""
        return client.query({"kind": "storage_start", "snapshot_id": snapshot_id, "tree_id": tree_id})

    @server.tool(title="Storage analysis progress", structured_output=True, annotations=READ_ONLY)
    def storage_job(job_id: str) -> Reply:
        """Read a companion-started job's progress or frozen findings. Scan completion does not guarantee complete evidence."""
        return client.query({"kind": "storage_job", "job_id": job_id})

    @server.tool(title="Cancel storage analysis", structured_output=True, annotations=ACTION)
    def cancel_storage_analysis(job_id: str) -> Reply:
        """Request cancellation of a companion-started job. Cancellation is cooperative and does not promise diagnostic-cache rollback."""
        return client.query({"kind": "storage_cancel", "job_id": job_id})

    @server.tool(title="Capture Usage", structured_output=True, annotations=ACTION)
    def capture_usage() -> Reply:
        """Explicit capture through the existing coalesced writer; no new collector/schedule. Do not replay on uncertain completion."""
        return client.query({"kind": "capture"})

    return server


def main():
    os.environ.pop("CONTROL_PLANE_API_KEY", None)
    create_server().run()


if __name__ == "__main__":
    main()
