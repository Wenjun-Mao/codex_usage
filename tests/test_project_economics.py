from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_usage.aggregation import UsageSummary, value_records
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.project_economics import ALL_PROJECTS_KEY, build_project_economics
from codex_usage.report_breakdown import build_report_breakdown_from_valued
from codex_usage.report_view import build_report_view_model


def test_project_economics_uses_distinct_project_and_model_turn_grains() -> None:
    records = [
        _record("alpha", "task-a", "one", "gpt-5.6-sol", 100),
        _record("alpha", "task-a", "one", "gpt-5.6-sol", 50, role="subagent"),
        _record("alpha", "task-a", "mixed", "gpt-5.6-sol", 40),
        _record("alpha", "task-a", "mixed", "gpt-5.6-terra", 60),
        _record("alpha", "task-b", "one", "gpt-5.6-terra", 20),
        _record("alpha", "task-a", "", "unknown-model", 30),
        # A transition during one task turn is intentionally two project turns.
        _record("beta", "task-a", "moved", "gpt-5.6-sol", 25),
        _record("gamma", "task-a", "moved", "gpt-5.6-sol", 35),
    ]

    economics = build_project_economics(value_records(records))
    alpha = next(project for project in economics.projects if project.key == "alpha")

    assert alpha.metrics.turn_count == 3
    assert alpha.metrics.response_count == 5
    assert alpha.metrics.responses_per_turn == pytest.approx(5 / 3)
    assert alpha.metrics.tokens_per_turn == pytest.approx(270 / 3)
    assert alpha.coverage.total_responses == 6
    assert alpha.coverage.measured_responses == 5
    assert alpha.coverage.response_share == pytest.approx(5 / 6)
    assert alpha.coverage.total_tokens == 300
    assert alpha.coverage.measured_tokens == 270
    assert alpha.coverage.token_share == pytest.approx(0.9)

    models = {model.key: model for model in alpha.models}
    assert models["gpt-5.6-sol"].metrics.turn_count == 2
    assert models["gpt-5.6-terra"].metrics.turn_count == 2
    assert models["unknown-model"].metrics.turn_count == 0
    assert [model.key for model in alpha.models] == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "unknown-model",
    ]
    assert economics.benchmark.key == ALL_PROJECTS_KEY
    assert economics.benchmark.metrics.turn_count == 5


def test_project_economics_keeps_complete_totals_and_exposes_missing_turn_coverage() -> None:
    records = [
        _record("alpha", "task-a", "known", "gpt-5.6-sol", 100),
        _record("alpha", "task-a", "", "unknown-model", 40),
        _record("beta", "task-b", "known", "unknown-model", 20),
        _record("beta", "task-b", "ignored", "gpt-5.6-sol", 0),
    ]
    valued = value_records(records)
    economics = build_project_economics(valued)
    breakdown = build_report_breakdown_from_valued(valued)

    assert economics.benchmark.total == _summary_from_rows(
        tuple(project.row for project in breakdown.projects)
    )
    alpha = next(project for project in economics.projects if project.key == "alpha")
    beta = next(project for project in economics.projects if project.key == "beta")
    assert alpha.total.usage.total_tokens == 140
    assert alpha.coverage.missing_responses == 1
    assert alpha.coverage.missing_tokens == 40
    assert beta.metrics.turn_count == 1
    assert beta.metrics.priced_turn_count == 0
    assert beta.metrics.average_cost_per_turn is None
    assert beta.metrics.median_cost_per_turn is None


def test_weighted_benchmark_uses_only_fully_priced_turns_not_project_averages() -> None:
    records = [
        _record("alpha", "task-a", "one", "gpt-5.6-sol", 1_000),
        _record("alpha", "task-a", "two", "gpt-5.6-sol", 1_000),
        _record("beta", "task-b", "one", "gpt-5.6-terra", 1_000),
        _record("beta", "task-b", "unknown", "unknown-model", 1_000),
    ]

    economics = build_project_economics(value_records(records))
    alpha, beta = economics.projects
    benchmark = economics.benchmark

    assert alpha.metrics.priced_turn_count == 2
    assert beta.metrics.priced_turn_count == 1
    assert benchmark.metrics.priced_turn_count == 3
    assert benchmark.metrics.average_cost_per_turn == pytest.approx(
        benchmark.metrics.priced_turn_cost_usd / 3
    )
    assert benchmark.metrics.average_cost_per_turn != pytest.approx(
        (alpha.metrics.average_cost_per_turn + beta.metrics.average_cost_per_turn) / 2  # type: ignore[operator]
    )


def test_project_economics_conserves_model_totals_and_shares() -> None:
    records = [
        _record("alpha", "task-a", "one", "gpt-5.6-sol", 100),
        _record("alpha", "task-a", "two", "gpt-5.6-terra", 50),
        _record("alpha", "task-a", "", "unknown-model", 25),
    ]

    project = build_project_economics(value_records(records)).projects[0]
    assert _summary_from_models(project) == project.total
    assert sum(model.token_share for model in project.models) == pytest.approx(1.0)
    assert sum(model.cost_share for model in project.models) == pytest.approx(1.0)
    assert project.is_small_sample


def test_report_view_carries_precomputed_economics_without_a_second_valuation() -> None:
    records = [_record("alpha", "task-a", "one", "gpt-5.6-sol", 100)]
    valued = value_records(records)
    economics = build_project_economics(valued)
    total = economics.benchmark.total

    view = build_report_view_model(
        generated_at=datetime(2026, 9, 8, tzinfo=UTC),
        range_name="30d",
        total=total,
        daily_rows=[],
        hourly_rows=[],
        breakdown=build_report_breakdown_from_valued(valued),
        sessions_dirs=[],
        files_scanned=1,
        project_economics=economics,
    )

    assert view.project_economics is economics


def _record(
    project: str,
    task: str,
    turn: str,
    model: str,
    total: int,
    *,
    role: str = "root",
) -> UsageRecord:
    return UsageRecord(
        timestamp=datetime(2026, 9, 8, tzinfo=UTC),
        usage=TokenUsage(input_tokens=total, total_tokens=total),
        session_id=task,
        file_path=Path(f"/{task}.jsonl"),
        usage_role=role,  # type: ignore[arg-type]
        model=model,
        turn_id=turn,
        project_key=project,
        project_label=project.title(),
    )


def _summary_from_models(project: object) -> UsageSummary:
    total = UsageSummary(
        usage=TokenUsage(),
        cost=CostBreakdown(),
        credits=CreditBreakdown(),
        record_count=0,
    )
    for model in project.models:  # type: ignore[attr-defined]
        total = total.add(model.total)
    return total


def _summary_from_rows(rows: tuple[object, ...]) -> UsageSummary:
    total = UsageSummary(
        usage=TokenUsage(),
        cost=CostBreakdown(),
        credits=CreditBreakdown(),
        record_count=0,
    )
    for row in rows:
        total = total.add(
            UsageSummary(
                usage=row.usage,  # type: ignore[attr-defined]
                cost=row.cost,  # type: ignore[attr-defined]
                credits=row.credits,  # type: ignore[attr-defined]
                record_count=row.record_count,  # type: ignore[attr-defined]
            )
        )
    return total
