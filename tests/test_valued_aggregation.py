from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import codex_usage.aggregation as aggregation
from codex_usage.aggregation import (
    aggregate_records,
    aggregate_valued_records,
    summarize_records,
    summarize_valued_records,
    value_records,
)
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.report_breakdown import (
    build_report_breakdown,
    build_report_breakdown_from_valued,
)


def test_report_consumers_reuse_one_valuation_per_record(monkeypatch) -> None:
    records = [
        _record("alpha", "gpt-5.6-sol", 100, hour=10),
        _record("alpha", "gpt-5.6-terra", 75, hour=11),
        _record("beta", "unknown-model", 25, hour=11),
    ]
    expected_summary = summarize_records(records)
    expected_daily = aggregate_records(records, "day", UTC)
    expected_hourly = aggregate_records(records, "hour", UTC)
    expected_breakdown = build_report_breakdown(records)
    cost_calls = 0
    credit_calls = 0
    unknown_calls = []
    real_cost = aggregation.cost_for_entry
    real_credits = aggregation.credits_for_rate
    real_unpriced = aggregation._unpriced

    def count_cost(*args, **kwargs):
        nonlocal cost_calls
        cost_calls += 1
        return real_cost(*args, **kwargs)

    def count_credits(*args, **kwargs):
        nonlocal credit_calls
        credit_calls += 1
        return real_credits(*args, **kwargs)

    def count_unknown(usage, breakdown):
        unknown_calls.append(breakdown)
        return real_unpriced(usage, breakdown)

    monkeypatch.setattr(aggregation, "cost_for_entry", count_cost)
    monkeypatch.setattr(aggregation, "credits_for_rate", count_credits)
    monkeypatch.setattr(aggregation, "_unpriced", count_unknown)

    valued = value_records(records)

    assert summarize_valued_records(valued) == expected_summary
    assert aggregate_valued_records(valued, "day", UTC) == expected_daily
    assert aggregate_valued_records(valued, "hour", UTC) == expected_hourly
    assert build_report_breakdown_from_valued(valued) == expected_breakdown
    assert cost_calls + unknown_calls.count(aggregation.CostBreakdown) == len(records)
    assert credit_calls + unknown_calls.count(aggregation.CreditBreakdown) == len(records)


def _record(project: str, model: str, total: int, *, hour: int) -> UsageRecord:
    return UsageRecord(
        timestamp=datetime(2026, 8, 7, hour, tzinfo=UTC),
        usage=TokenUsage(input_tokens=total, total_tokens=total),
        session_id=f"{project}-{model}",
        file_path=Path(f"/{project}-{model}.jsonl"),
        usage_role="root",
        model=model,
        project_key=project,
        project_label=project.title(),
    )
