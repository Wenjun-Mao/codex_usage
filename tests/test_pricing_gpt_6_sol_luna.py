from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codex_usage.aggregation import aggregate_records, summarize_records
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.pricing import (
    ModelRate,
    credit_rate_for_model,
    estimate_codex_credits,
    estimate_cost,
    rate_for_model,
)
from codex_usage.report_breakdown import build_report_breakdown
from codex_usage.reporting import render_html_report


LAUNCH = datetime(2026, 9, 22, tzinfo=UTC)
BEFORE_LAUNCH = LAUNCH - timedelta(microseconds=1)


@pytest.mark.parametrize(
    ("model", "expected", "credits"),
    (
        ("gpt-6-sol", ModelRate(2.0, 0.20, 10.0, 2.50), ModelRate(50, 5, 250)),
        ("gpt-6-luna", ModelRate(0.10, 0.01, 0.50, 0.125), ModelRate(2.5, 0.25, 12.5)),
    ),
)
def test_api_and_standard_credit_rates_begin_on_launch(
    model: str, expected: ModelRate, credits: ModelRate
) -> None:
    assert rate_for_model(model, at=BEFORE_LAUNCH) is None
    assert rate_for_model(model, at=LAUNCH) == expected
    assert rate_for_model(model.upper()) == expected
    assert credit_rate_for_model(model, at=BEFORE_LAUNCH) is None
    assert credit_rate_for_model(model, at=LAUNCH) == credits
    assert rate_for_model(f"{model}-fast") is None


@pytest.mark.parametrize(
    ("model", "ordinary", "cached", "write", "output"),
    (
        ("gpt-6-sol", 0.3, 0.0144, 0.125, 1.0),
        ("gpt-6-luna", 0.015, 0.00072, 0.00625, 0.05),
    ),
)
@pytest.mark.parametrize("input_tokens,multiplier", ((272_000, 1.0), (272_001, 2.0)))
def test_request_level_long_context_rates(
    model: str,
    ordinary: float,
    cached: float,
    write: float,
    output: float,
    input_tokens: int,
    multiplier: float,
) -> None:
    usage = TokenUsage(
        input_tokens=input_tokens,
        cached_input_tokens=72_000,
        cache_write_input_tokens=50_000,
        output_tokens=100_000,
        total_tokens=input_tokens + 100_000,
    )
    cost = estimate_cost(usage, model, at=LAUNCH)
    assert cost is not None
    assert cost.ordinary_input_usd == pytest.approx(
        (
            ordinary
            + (input_tokens - 272_000) / 1_000_000 * rate_for_model(model).input_per_1m
        )
        * multiplier
    )
    assert cost.cached_input_usd == pytest.approx(cached * multiplier)
    assert cost.cache_write_input_usd == pytest.approx(write * multiplier)
    assert cost.output_usd == pytest.approx(
        output * (1.5 if multiplier == 2.0 else 1.0)
    )


def test_report_shows_only_prelaunch_api_tokens_as_unpriced(tmp_path: Path) -> None:
    usage = TokenUsage(input_tokens=1_000, output_tokens=100, total_tokens=1_100)
    records = [
        UsageRecord(
            timestamp=timestamp,
            usage=usage,
            session_id=f"session-{index}",
            file_path=Path("/tmp/session.jsonl"),
            usage_role="root",
            model="gpt-6-sol",
            project_key="project",
            project_label="Project",
        )
        for index, timestamp in enumerate((BEFORE_LAUNCH, LAUNCH))
    ]
    row = aggregate_records(records, "model", UTC)[0]
    assert row.cost.unpriced_tokens == 1_100
    assert row.cost.total_usd > 0
    assert row.credits.unpriced_tokens == 1_100
    assert row.credits.total_credits > 0

    report = tmp_path / "report.html"
    render_html_report(
        output_path=report,
        generated_at=LAUNCH,
        range_name="all",
        total=summarize_records(records),
        daily_rows=aggregate_records(records, "day", UTC),
        hourly_rows=[],
        breakdown=build_report_breakdown(records),
        sessions_dirs=[Path("sessions")],
        files_scanned=1,
    )
    html = report.read_text()
    assert "API USD excludes 1,100 tokens" in html
    assert "No price data is available for 1,100 tokens" in html
    assert "1,100 without credit rates" in html


def test_cache_write_credit_contribution_has_no_separate_surcharge() -> None:
    usage = TokenUsage(
        input_tokens=1_000_000,
        cached_input_tokens=200_000,
        cache_write_input_tokens=300_000,
        output_tokens=100_000,
        total_tokens=1_100_000,
    )
    credits = estimate_codex_credits(usage, "gpt-6-sol", at=LAUNCH)
    assert credits is not None
    assert credits.ordinary_input_credits == pytest.approx(25)
    assert credits.cache_write_input_credits == pytest.approx(15)
    assert credits.uncached_input_credits == pytest.approx(40)
    assert credits.cached_input_credits == pytest.approx(1)
    assert credits.output_credits == pytest.approx(25)
    assert credits.total_credits == pytest.approx(66)
