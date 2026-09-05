from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_usage.aggregation import UsageSummary
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.pricing import CostBreakdown, CreditBreakdown
from codex_usage.report_breakdown import OTHER_MODEL_KEY, build_report_breakdown
from codex_usage.report_view import build_report_view_model


def test_report_view_model_prepares_role_and_model_presentation_points() -> None:
    records = [
        _record("demo", "demo", "root", "gpt-5.6-sol", total=1_000),
        _record("demo", "demo", "subagent", "gpt-5.6-terra", total=100),
        _record("other", "other", "root", "gpt-5.6-luna", total=10),
        _record("other", "other", "root", "gpt-6-astra", total=5),
    ]

    view_model = _view_model(records)

    assert [item.label for item in view_model.model_legend] == [
        "gpt-6-astra",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
    ]
    assert [item.color_slot for item in view_model.model_legend] == [0, 1, 2, 3]

    project = view_model.project_points[0]
    assert project.label == "demo"
    assert project.root_tokens == 1_000
    assert project.subagent_tokens == 100
    assert [(group.role, group.label) for group in project.roles] == [
        ("root", "Root tasks"),
        ("subagent", "Subagents"),
    ]
    assert project.roles[0].project_share == pytest.approx(1_000 / 1_100)
    assert project.roles[0].cost_usd > 0
    assert project.roles[0].project_cost_share > 0
    assert project.roles[1].segments[0].project_share == pytest.approx(100 / 1_100)
    assert view_model.project_detail_points == view_model.breakdown_view.project_points


def test_report_view_model_keeps_all_project_details_but_limits_chart_to_twelve() -> None:
    records = [
        _record(f"project-{number:02d}", f"Project {number:02d}", "root", "gpt-5.6-sol", total=100 - number)
        for number in range(13)
    ]

    view_model = _view_model(records)

    assert len(view_model.project_points) == 12
    assert len(view_model.project_detail_points) == 13
    assert view_model.project_points == list(view_model.project_detail_points[:12])


def test_report_view_model_uses_project_key_for_tied_top_twelve_membership() -> None:
    records = [
        _record(
            f"project-{number:02d}",
            f"Project {number:02d}",
            "root",
            "gpt-5.6-sol",
            total=100,
        )
        for number in range(13)
    ]

    view_model = _view_model(records)
    reversed_view_model = _view_model(list(reversed(records)))

    expected_keys = [f"project-{number:02d}" for number in range(12)]
    assert [point.key for point in view_model.project_points] == expected_keys
    assert [point.key for point in reversed_view_model.project_points] == expected_keys
    assert [point.key for point in view_model.project_detail_points] == [
        *expected_keys,
        "project-12",
    ]


def test_report_view_model_reserves_other_model_color_slot_seven() -> None:
    records = [
        _record("demo", "demo", "root", f"model-{number}", total=100 - number)
        for number in range(8)
    ]

    view_model = _view_model(records)

    assert [item.color_slot for item in view_model.model_legend[:-1]] == list(range(7))
    assert view_model.model_legend[-1].key == OTHER_MODEL_KEY
    assert view_model.model_legend[-1].color_slot == 7
    assert view_model.model_points[-1].key == OTHER_MODEL_KEY
    assert view_model.model_points[-1].color_slot == 7


def _view_model(records: list[UsageRecord]):
    total = UsageSummary(
        usage=TokenUsage(total_tokens=sum(record.usage.total_tokens for record in records)),
        cost=CostBreakdown(),
        credits=CreditBreakdown(),
        record_count=len(records),
    )
    return build_report_view_model(
        generated_at=datetime(2026, 8, 1, tzinfo=UTC),
        range_name="all",
        total=total,
        daily_rows=[],
        hourly_rows=[],
        breakdown=build_report_breakdown(records),
        sessions_dirs=[Path("sessions")],
        files_scanned=1,
    )


def _record(
    project_key: str,
    project_label: str,
    role: str,
    model: str,
    *,
    total: int,
) -> UsageRecord:
    return UsageRecord(
        timestamp=datetime(2026, 8, 1, tzinfo=UTC),
        usage=TokenUsage(input_tokens=total, total_tokens=total),
        session_id=f"{project_key}-{role}-{model}",
        file_path=Path("/tmp/session.jsonl"),
        usage_role=role,  # type: ignore[arg-type]
        model=model,
        project_key=project_key,
        project_label=project_label,
    )
