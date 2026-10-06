from __future__ import annotations

from typing import Literal, TypedDict

Period = Literal["today", "yesterday", "7d", "30d"]
Project = Literal["all", "demo-a", "demo-b"]


class Scope(TypedDict):
    period: Period
    project: Project
    timezone: str


class ProjectLabel(TypedDict):
    id: str
    label: str


class ProjectUsage(ProjectLabel):
    api_cost_usd: float
    tokens: int


class Allowance(TypedDict):
    scope: Literal["account"]
    used_percent: int
    remaining_percent: int


class ProbeUsage(TypedDict):
    schema_version: Literal[1]
    source: Literal["synthetic"]
    live_data_supported: Literal[False]
    scope: Scope
    observed_at: str
    api_cost_usd: float
    tokens: int
    projects: list[ProjectUsage]
    available_projects: list[ProjectLabel]
    allowance: Allowance


def synthetic_usage(period: Period = "7d", project: Project = "all") -> ProbeUsage:
    factors = {"today": 1, "yesterday": 0.8, "7d": 7, "30d": 30}
    projects = [
        {"id": "demo-a", "label": "Demo Alpha", "api_cost_usd": 12.4, "tokens": 11000000},
        {"id": "demo-b", "label": "Demo Beta", "api_cost_usd": 4.8, "tokens": 8000000},
    ]
    selected = [row for row in projects if project == "all" or row["id"] == project]
    factor = factors[period]
    rows = [
        dict(
            row,
            api_cost_usd=round(row["api_cost_usd"] * factor, 2),
            tokens=int(row["tokens"] * factor),
        )
        for row in selected
    ]
    return {
        "schema_version": 1,
        "source": "synthetic",
        "live_data_supported": False,
        "scope": {"period": period, "project": project, "timezone": "America/Toronto"},
        "observed_at": "2026-10-06T20:00:00Z",
        "api_cost_usd": round(sum(row["api_cost_usd"] for row in rows), 2),
        "tokens": sum(row["tokens"] for row in rows),
        "projects": rows,
        "available_projects": [
            {"id": row["id"], "label": row["label"]} for row in projects
        ],
        "allowance": {"scope": "account", "used_percent": 17, "remaining_percent": 83},
    }
