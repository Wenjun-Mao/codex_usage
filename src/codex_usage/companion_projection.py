"""Explicit outbound fields; no raw record, status, or task serialization."""
from dataclasses import asdict

from codex_usage.aggregation import aggregate_valued_records, summarize_valued_records
from codex_usage.companion_contract import SelectionHandles, model_label
from codex_usage.ledger_materialization import LedgerMaterialization
from codex_usage.ledger_queries import LedgerStatus
from codex_usage.project_economics import build_project_economics


def status_projection(status: LedgerStatus) -> dict:
    return {
        "ledger_revision": status.revision,
        "last_capture_at": status.last_capture_at,
        "last_capture_outcome": status.last_capture_outcome,
        "coverage": status.coverage.to_dict(),
        "image_backfill": status.image_backfill.to_dict(),
    }


def summary_projection(summary) -> dict:
    return {"usage": summary.usage.to_dict(), "api_cost": summary.cost.to_dict(),
            "estimated_standard_credits": summary.credits.to_dict(),
            "responses": summary.record_count}


def categories(summary) -> list[dict]:
    u, c, cr = summary.usage, summary.cost, summary.credits
    values = [
        ("Total", u.total_tokens, c.total_usd, cr.total_credits, c.unpriced_tokens, cr.unpriced_tokens),
        ("Input subtotal", u.input_tokens, c.input_usd, cr.input_credits, c.unpriced_input_tokens, cr.unpriced_input_tokens),
        ("Cached input", u.cached_input_tokens, c.cached_input_usd, cr.cached_input_credits, c.unpriced_cached_input_tokens, cr.unpriced_cached_input_tokens),
        ("Regular input", u.ordinary_input_tokens, c.ordinary_input_usd, cr.ordinary_input_credits, c.unpriced_ordinary_input_tokens, cr.unpriced_ordinary_input_tokens),
        ("Cache write (reported)", u.cache_write_input_tokens, c.cache_write_input_usd, cr.cache_write_input_credits, c.unpriced_cache_write_input_tokens, cr.unpriced_cache_write_input_tokens),
        ("Output", u.output_tokens, c.output_usd, cr.output_credits, c.unpriced_output_tokens, cr.unpriced_output_tokens),
    ]
    return [dict(category=name, tokens=tokens, api_cost_usd=cost,
                 estimated_standard_credits=credits, api_unpriced_tokens=api_missing,
                 credit_unpriced_tokens=credit_missing)
            for name, tokens, cost, credits, api_missing, credit_missing in values]


def usage_projection(data: LedgerMaterialization, timezone, handles: SelectionHandles) -> dict:
    valued = data.valued
    summary = summarize_valued_records(valued)
    dimensions = {}
    for dimension, group in (("project", "project"), ("model", "model"),
                             ("agent", "session"), ("day", "day"), ("hour", "hour")):
        rows = []
        for row in aggregate_valued_records(valued, group, timezone):
            handle = handles.issue(dimension, row.key) if dimension in {"project", "model", "agent"} else row.key
            label = (model_label(row.label) if dimension == "model" else
                     row.label if dimension in {"day", "hour"} else
                     f"{dimension.title()} {handle[-6:]}")
            rows.append({"id": handle, "label": label, "usage": row.usage.to_dict(),
                         "api_cost": row.cost.to_dict(),
                         "estimated_standard_credits": row.credits.to_dict(),
                         "responses": row.record_count,
                         "categories": categories(row)})
        dimensions[dimension] = rows
    economics = build_project_economics(valued)
    economics_by_project = {p.key: p for p in economics.projects}
    for row in dimensions["project"]:
        p = economics_by_project.get(handles.resolve("project", row["id"]))
        if p:
            row["economics"] = {"coverage": asdict(p.coverage), "metrics": asdict(p.metrics)}
    agents = {handles.issue("agent", a.agent_id): a for a in data.activity.agent_rows}
    for row in dimensions["agent"]:
        agent = agents[row["id"]]
        row.update(role=agent.role, root_id=handles.issue("agent", agent.root_task_id), active_days=agent.active_days)
    return {
        "language": summary_projection(summary), "categories": categories(summary),
        "images": asdict(data.images.summary),
        "image_coverage": asdict(data.images.coverage),
        "image_groups": {
            "models": [{"label": m.label, "summary": asdict(m.summary)} for m in data.images.models[:25]],
            "projects": [{"project_id": handles.issue("project", p.project_key),
                          "summary": asdict(p.summary)} for p in data.images.projects[:25]],
            "models_truncated": len(data.images.models) > 25,
            "projects_truncated": len(data.images.projects) > 25,
        },
        "dimensions": dimensions,
        "economics": {
            "benchmark": {"coverage": asdict(economics.benchmark.coverage),
                          "metrics": asdict(economics.benchmark.metrics)},
            "projects": [
                {"project_id": handles.issue("project", p.key),
                 "coverage": asdict(p.coverage), "metrics": asdict(p.metrics),
                 "models": [{"model_id": handles.issue("model", m.key),
                             "label": model_label(m.label), "metrics": asdict(m.metrics),
                             "coverage": asdict(m.coverage)} for m in p.models]}
                for p in economics.projects
            ],
        },
        "roles": [{"role": role, "usage": totals.usage.to_dict(), "responses": totals.responses}
                  for role, totals in data.activity.role_totals.items()],
    }


def allowance_projection(report: dict, now: float) -> dict:
    from codex_usage.allowance_pace import pace_state
    status = report["status"]
    buckets = [{key: row.get(key) for key in (
        "timestamp", "limit_id", "slot", "plan", "used_percent", "duration_minutes", "resets_at",
    )} for row in status.get("active_buckets", [])]
    window_keys = ("limit_id", "plan", "duration_minutes", "start", "end", "completed",
                   "fully_priced", "coverage_complete")
    def window(w):
        return ({**{key: w.get(key) for key in window_keys},
                 "estimate": {key: w["estimate"].get(key) for key in ("value", "confidence")}}
                if w else None)
    paces = []
    for group in report.get("paces", []):
        for p in group:
            keys = ("limit_id", "duration_minutes", "name", "span_seconds", "observations",
                    "rate", "reason", "anchor", "reset", "used", "exhaustion", "reset_balance",
                    "method", "cost", "coverage_complete", "unpriced_tokens")
            row = {key: p.get(key) for key in keys}
            row["state"] = pace_state(p, status["probe_status"], now)
            reference = p.get("reference")
            row["reference"] = ({key: reference.get(key) for key in (
                "value", "start", "end", "previous", "confidence",
            )} if reference else None)
            paces.append(row)
    credits = status.get("credits") or {}
    return {"scope": "account-wide", "plan": status.get("plan"),
            "buckets": buckets, "probe_status": status.get("probe_status"),
            "last_observed_at": status.get("last_observed_at"),
            "credits": {key: credits.get(key) for key in (
                "balance", "freshness", "observed_at", "has_credits", "unlimited",
            )},
            "headline": window(report.get("headline")),
            "headline_previous": report.get("headline_previous", False),
            "paces": paces,
            "history": [window(w) for w in report.get("history", [])[:50]],
            "history_truncated": len(report.get("history", [])) > 50}
