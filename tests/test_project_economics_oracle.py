from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path

import pytest

from project_economics_oracle import (
    OracleCoverage,
    OracleMetrics,
    OracleProject,
    OracleSummary,
    RawValuedRecord,
    build_oracle,
)

from codex_usage.aggregation import UsageSummary, ValuedUsageRecord
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.project_economics import ALL_PROJECTS_KEY, build_project_economics


def test_project_economics_matches_independent_raw_record_oracle() -> None:
    raw_records = _raw_records()
    expected = build_oracle(raw_records)
    actual = build_project_economics(_to_valued_records(raw_records))

    assert actual.benchmark.key == ALL_PROJECTS_KEY
    _assert_project_matches(actual.benchmark, expected.benchmark)
    assert [project.key for project in actual.projects] == [
        project.key for project in expected.projects
    ]
    for actual_project, expected_project in zip(actual.projects, expected.projects, strict=True):
        _assert_project_matches(actual_project, expected_project)


def _assert_project_matches(actual: object, expected: OracleProject) -> None:
    _assert_summary_matches(actual.total, expected.total)  # type: ignore[attr-defined]
    _assert_coverage_matches(actual.coverage, expected.coverage)  # type: ignore[attr-defined]
    _assert_metrics_matches(actual.metrics, expected.metrics)  # type: ignore[attr-defined]
    assert [model.key for model in actual.models] == [model.key for model in expected.models]  # type: ignore[attr-defined]
    for actual_model, expected_model in zip(actual.models, expected.models, strict=True):  # type: ignore[attr-defined]
        _assert_summary_matches(actual_model.total, expected_model.total)
        _assert_coverage_matches(actual_model.coverage, expected_model.coverage)
        _assert_metrics_matches(actual_model.metrics, expected_model.metrics)
        assert actual_model.token_share == pytest.approx(expected_model.token_share)
        assert actual_model.cost_share == pytest.approx(expected_model.cost_share)


def _assert_summary_matches(actual: UsageSummary, expected: OracleSummary) -> None:
    for group in ("usage", "cost", "credits"):
        actual_group = getattr(actual, group)
        expected_group = getattr(expected, group)
        for field in fields(expected_group):
            value = getattr(expected_group, field.name)
            if isinstance(value, float):
                assert getattr(actual_group, field.name) == pytest.approx(value)
            else:
                assert getattr(actual_group, field.name) == value
    assert actual.record_count == expected.response_count


def _assert_coverage_matches(actual: object, expected: OracleCoverage) -> None:
    for field in fields(expected):
        assert getattr(actual, field.name) == getattr(expected, field.name)


def _assert_metrics_matches(actual: object, expected: OracleMetrics) -> None:
    for field in fields(expected):
        actual_value = getattr(actual, field.name)
        expected_value = getattr(expected, field.name)
        if isinstance(expected_value, float):
            assert actual_value == pytest.approx(expected_value)
        else:
            assert actual_value == expected_value


def _to_valued_records(raw_records: tuple[RawValuedRecord, ...]) -> tuple[ValuedUsageRecord, ...]:
    return tuple(
        ValuedUsageRecord(
            record=UsageRecord(
                timestamp=datetime(2026, 9, 8, tzinfo=UTC),
                usage=raw.usage,
                session_id=raw.task,
                file_path=Path(f"/{raw.task}.jsonl"),
                usage_role=raw.role,  # type: ignore[arg-type]
                model=raw.model,
                turn_id=raw.turn,
                project_key=raw.project,
                project_label=raw.project.title(),
            ),
            summary=UsageSummary(raw.usage, raw.cost, 1, raw.credits),
        )
        for raw in raw_records
    )


def _raw_records() -> tuple[RawValuedRecord, ...]:
    return (
        _raw("alpha", "task-a", "one", "gpt-5.6-sol", "root", 100, 1.0),
        _raw("alpha", "task-a", "one", "gpt-5.6-sol", "subagent", 50, 0.5),
        _raw("alpha", "task-a", "mixed", "gpt-5.6-sol", "root", 40, 0.4),
        _raw("alpha", "task-a", "mixed", "gpt-5.6-terra", "subagent", 60, 0.6),
        # Same turn label in a different task must remain a distinct turn.
        _raw("alpha", "task-b", "one", "gpt-5.6-terra", "root", 20, 0.2),
        # Blank IDs contribute to totals and coverage but never turn samples.
        _raw("alpha", "task-a", "", "unknown-model", "root", 30, 0.3),
        # A mixed priced/unpriced turn is not a priced turn; its priced response remains visible.
        _raw("beta", "task-a", "mixed", "gpt-5.6-sol", "root", 25, 0.25),
        _raw("beta", "task-a", "mixed", "unknown-model", "subagent", 35, 0.0, unpriced=35),
        # A project transition makes two project turns despite task and turn equality.
        _raw("gamma", "task-a", "moved", "gpt-5.6-sol", "root", 45, 0.45),
        _raw("alpha", "task-a", "ignored", "gpt-5.6-sol", "root", 0, 9.0),
    )


def _raw(
    project: str,
    task: str,
    turn: str,
    model: str,
    role: str,
    tokens: int,
    cost: float,
    *,
    unpriced: int = 0,
) -> RawValuedRecord:
    return RawValuedRecord(
        project=project,
        task=task,
        turn=turn,
        model=model,
        role=role,
        usage=TokenUsage(
            input_tokens=tokens,
            cached_input_tokens=tokens // 10,
            cache_write_input_tokens=tokens // 20,
            output_tokens=tokens // 4,
            reasoning_output_tokens=tokens // 8,
            total_tokens=tokens,
        ),
        cost=CostBreakdown(
            ordinary_input_usd=cost * 0.5,
            cached_input_usd=cost * 0.1,
            cache_write_input_usd=cost * 0.1,
            output_usd=cost * 0.3,
            total_usd=cost,
            unpriced_tokens=unpriced,
        ),
        credits=CreditBreakdown(
            uncached_input_credits=cost * 2,
            cached_input_credits=cost,
            output_credits=cost * 3,
            total_credits=cost * 6,
            unpriced_tokens=unpriced,
        ),
    )
