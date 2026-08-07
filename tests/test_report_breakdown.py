from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_usage.aggregation import UsageSummary
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.report_breakdown import (
    OTHER_MODEL_KEY,
    _validate_equal,
    build_report_breakdown,
)
from codex_usage.report_breakdown_view import build_breakdown_view


def _record(
    project_key: str,
    project_label: str,
    role: str,
    model: str,
    *,
    total: int,
    cached: int = 0,
    timestamp: datetime | None = None,
) -> UsageRecord:
    return UsageRecord(
        timestamp=timestamp or datetime(2026, 8, 1, tzinfo=UTC),
        usage=TokenUsage(
            input_tokens=total,
            cached_input_tokens=cached,
            cache_write_input_tokens=total // 10,
            output_tokens=total // 4,
            reasoning_output_tokens=total // 20,
            total_tokens=total,
        ),
        session_id=f"{project_key}-{role}-{model}",
        file_path=Path("/tmp/session.jsonl"),
        usage_role=role,  # type: ignore[arg-type]
        model=model,
        project_key=project_key,
        project_label=project_label,
    )


def _assert_summary_equal(actual: UsageSummary, expected: UsageSummary) -> None:
    for field in fields(actual.usage):
        assert getattr(actual.usage, field.name) == getattr(expected.usage, field.name)
    for field in fields(actual.cost):
        actual_value = getattr(actual.cost, field.name)
        expected_value = getattr(expected.cost, field.name)
        if isinstance(actual_value, float):
            assert actual_value == pytest.approx(expected_value, rel=0, abs=1e-9)
        else:
            assert actual_value == expected_value
    for field in fields(actual.credits):
        actual_value = getattr(actual.credits, field.name)
        expected_value = getattr(expected.credits, field.name)
        if isinstance(actual_value, float):
            assert actual_value == pytest.approx(expected_value, rel=0, abs=1e-9)
        else:
            assert actual_value == expected_value
    assert actual.record_count == expected.record_count


def _summary(rows: tuple[object, ...]) -> UsageSummary:
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


def test_build_report_breakdown_builds_project_role_model_cube_and_conserves_fields() -> None:
    records = [
        _record("alpha", "Alpha", "root", "gpt-5.6-sol", total=100, cached=20),
        _record("alpha", "Alpha", "subagent", "gpt-5.6-terra", total=40),
        _record("alpha", "Alpha", "subagent", "gpt-5.6-luna", total=10),
        _record("beta", "Beta", "root", "gpt-5.6-sol", total=30),
    ]

    breakdown = build_report_breakdown(records)

    assert [project.row.key for project in breakdown.projects] == ["alpha", "beta"]
    alpha = breakdown.projects[0]
    assert alpha.row.usage.total_tokens == 150
    assert [(role.role, role.total.usage.total_tokens) for role in alpha.roles] == [
        ("root", 100),
        ("subagent", 50),
    ]
    assert [bucket.label for bucket in breakdown.visual_models] == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ]

    for project in breakdown.projects:
        _assert_summary_equal(_summary(tuple(role.total for role in project.roles)), _as_summary(project.row))
        for role in project.roles:
            _assert_summary_equal(_summary(role.model_rows), role.total)
    _assert_summary_equal(_summary(breakdown.model_rows), _summary(breakdown.visual_model_rows))


def test_build_report_breakdown_keeps_top_seven_visual_models_and_groups_the_rest() -> None:
    totals = {
        "model-01": 100,
        "model-02": 90,
        "model-03": 80,
        "model-04": 70,
        "model-05": 60,
        "model-06": 50,
        "model-07-a": 40,
        "model-07-b": 40,
        "model-09": 30,
    }
    records = [
        _record("alpha", "Alpha", "root", model, total=total)
        for model, total in totals.items()
    ]
    expected_top_seven = [
        "model-01",
        "model-02",
        "model-03",
        "model-04",
        "model-05",
        "model-06",
        "model-07-a",
    ]
    expected_other_models = ["model-07-b", "model-09"]

    breakdown = build_report_breakdown(records)
    reversed_breakdown = build_report_breakdown(list(reversed(records)))

    assert [bucket.label for bucket in breakdown.visual_models[:-1]] == expected_top_seven
    assert breakdown.visual_models[-1].key == OTHER_MODEL_KEY
    assert breakdown.visual_models[-1].label == "Other"
    assert breakdown.visual_models[-1].exact_models == tuple(sorted(expected_other_models))
    assert breakdown.visual_model_rows[-1].usage.total_tokens == 70
    assert [row.label for row in breakdown.model_rows] == [*expected_top_seven, *expected_other_models]
    assert breakdown.visual_models == reversed_breakdown.visual_models
    assert [item.color_slot for item in build_breakdown_view(breakdown).model_legend] == [
        *range(7),
        7,
    ]


def test_build_report_breakdown_rejects_more_than_seven_exact_visual_models() -> None:
    records = [
        _record("alpha", "Alpha", "root", f"model-{number}", total=10)
        for number in range(8)
    ]

    with pytest.raises(ValueError, match="visual_model_limit must be between 0 and 7"):
        build_report_breakdown(records, visual_model_limit=8)


def test_build_report_breakdown_handles_small_unknown_role_only_and_empty_inputs() -> None:
    records = [
        _record("root-project", "Root", "root", "unknown-model", total=20),
        _record("subagent-project", "Subagent", "subagent", "gpt-5.6-luna", total=10),
    ]

    breakdown = build_report_breakdown(records)

    assert [bucket.label for bucket in breakdown.visual_models] == ["unknown-model", "gpt-5.6-luna"]
    assert [role.role for role in breakdown.projects[0].roles] == ["root"]
    assert [role.role for role in breakdown.projects[1].roles] == ["subagent"]
    assert build_report_breakdown([]).projects == ()
    assert build_report_breakdown([]).visual_models == ()
    assert build_report_breakdown([]).model_rows == ()


def test_build_report_breakdown_omits_zero_token_records_from_visible_rows() -> None:
    records = [
        _record("empty", "Empty", "root", "zero-only-model", total=0),
        _record("active", "Active", "root", "positive-model", total=10),
        _record("active", "Active", "subagent", "zero-role-model", total=0),
    ]

    breakdown = build_report_breakdown(records)

    assert [project.row.key for project in breakdown.projects] == ["active"]
    assert breakdown.projects[0].row.usage.total_tokens == 10
    assert breakdown.projects[0].row.record_count == 1
    assert [role.role for role in breakdown.projects[0].roles] == ["root"]
    assert [row.key for row in breakdown.projects[0].roles[0].model_rows] == ["positive-model"]
    assert [row.key for row in breakdown.model_rows] == ["positive-model"]
    assert [bucket.key for bucket in breakdown.visual_models] == ["positive-model"]
    assert [row.key for row in breakdown.visual_model_rows] == ["positive-model"]


def test_build_report_breakdown_orders_tied_projects_by_project_key() -> None:
    records = [
        _record("zeta", "Zeta", "root", "gpt-5.6-sol", total=100),
        _record("alpha", "Alpha", "root", "gpt-5.6-sol", total=100),
        _record("middle", "Middle", "root", "gpt-5.6-sol", total=100),
    ]

    breakdown = build_report_breakdown(records)
    reversed_breakdown = build_report_breakdown(list(reversed(records)))

    assert [project.row.key for project in breakdown.projects] == [
        "alpha",
        "middle",
        "zeta",
    ]
    assert breakdown.projects == reversed_breakdown.projects


def test_build_report_breakdown_conserves_effective_dated_pricing_through_other() -> None:
    records = [
        _record("alpha", "Alpha", "root", "gpt-5.6-sol", total=100),
        _record(
            "alpha",
            "Alpha",
            "subagent",
            "gpt-5.6-terra",
            total=20,
            timestamp=datetime(2026, 7, 30, tzinfo=UTC),
        ),
        _record(
            "alpha",
            "Alpha",
            "subagent",
            "gpt-5.6-terra",
            total=20,
            timestamp=datetime(2026, 8, 1, tzinfo=UTC),
        ),
    ]

    breakdown = build_report_breakdown(records, visual_model_limit=1)

    other = breakdown.visual_model_rows[-1]
    assert other.key == OTHER_MODEL_KEY
    assert other.cost.total_usd == pytest.approx(0.00022725, rel=0, abs=1e-9)
    assert other.credits.total_credits == pytest.approx(0.00625, rel=0, abs=1e-9)
    _assert_summary_equal(_as_summary(other), _as_summary(breakdown.model_rows[-1]))


def test_conservation_tolerance_scales_for_observed_30_day_credit_total() -> None:
    expected = UsageSummary(
        usage=TokenUsage(total_tokens=1_000_000_000),
        cost=CostBreakdown(total_usd=832.1772),
        credits=CreditBreakdown(total_credits=20_804.0),
        record_count=10_000,
    )
    actual = UsageSummary(
        usage=expected.usage,
        cost=CostBreakdown(total_usd=832.1772 + 2e-10),
        credits=CreditBreakdown(total_credits=20_804.0 + 2e-9),
        record_count=expected.record_count,
    )

    _validate_equal(actual, expected, "30-day regression")


def _as_summary(row: object) -> UsageSummary:
    return UsageSummary(
        usage=row.usage,  # type: ignore[attr-defined]
        cost=row.cost,  # type: ignore[attr-defined]
        credits=row.credits,  # type: ignore[attr-defined]
        record_count=row.record_count,  # type: ignore[attr-defined]
    )
