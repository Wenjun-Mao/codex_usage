from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codex_usage.aggregation import aggregate_records
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.report_tables import render_aggregate_table, render_model_details_table


LAUNCH = datetime(2026, 9, 22, tzinfo=UTC)


def _record(
    index: int, timestamp: datetime, usage: TokenUsage, model: str = "gpt-6-sol"
) -> UsageRecord:
    return UsageRecord(
        timestamp=timestamp,
        usage=usage,
        session_id=f"session-{index}",
        file_path=Path("/tmp/session.jsonl"),
        usage_role="root",
        model=model,
    )


def test_categories_conserve_event_valuations_across_context_and_date() -> None:
    usage = TokenUsage(
        input_tokens=272_000,
        cached_input_tokens=70_000,
        cache_write_input_tokens=20_000,
        output_tokens=30_000,
        total_tokens=302_000,
    )
    long_usage = TokenUsage(
        input_tokens=272_001,
        cached_input_tokens=71_000,
        cache_write_input_tokens=21_000,
        output_tokens=31_000,
        total_tokens=303_001,
    )
    rows = aggregate_records(
        [
            _record(1, LAUNCH - timedelta(microseconds=1), usage),
            _record(2, LAUNCH, usage),
            _record(3, LAUNCH + timedelta(days=1), long_usage),
        ],
        "model",
        UTC,
    )
    row = rows[0]
    cost, credits = row.cost, row.credits
    assert cost.total_usd == pytest.approx(cost.input_usd + cost.output_usd)
    assert cost.input_usd == pytest.approx(
        cost.cached_input_usd + cost.ordinary_input_usd + cost.cache_write_input_usd
    )
    assert credits.total_credits == pytest.approx(
        credits.input_credits + credits.output_credits
    )
    assert credits.input_credits == pytest.approx(
        credits.cached_input_credits
        + credits.ordinary_input_credits
        + credits.cache_write_input_credits
    )
    assert cost.unpriced_tokens == credits.unpriced_tokens == usage.total_tokens
    assert (
        cost.unpriced_input_tokens
        == credits.unpriced_input_tokens
        == usage.input_tokens
    )
    assert cost.unpriced_cache_write_input_tokens == usage.cache_write_input_tokens
    assert cost.cache_write_input_usd == pytest.approx(
        20_000 / 1e6 * 2.5 + 21_000 / 1e6 * 5
    )
    assert credits.cache_write_input_credits == pytest.approx(41_000 / 1e6 * 50)

    model_html = render_model_details_table(rows)
    assert "Share" not in model_html and 'class="bar"' not in model_html
    assert model_html.count('<details class="model-breakdown">') == 1
    assert 'scope="row">Input subtotal' in model_html
    assert 'scope="row">Regular input' in model_html
    assert 'scope="row">Cache write (reported)' in model_html
    assert 'class="model-partial">partial' in model_html
    assert 'aria-labelledby="model-details-heading"' in model_html
    assert 'aria-label="Token and price categories for gpt-6-sol"' in model_html
    assert "ordinary input contribution, not a separate surcharge" in model_html
    assert "Fast usage cannot be identified" in model_html

    hourly_html = render_aggregate_table(
        "Hourly Details", rows, section_id="hourly-details"
    )
    assert "Share" in hourly_html and 'class="bar"' in hourly_html


def test_unknown_model_categories_do_not_display_price_zero() -> None:
    usage = TokenUsage(
        input_tokens=100,
        cached_input_tokens=20,
        cache_write_input_tokens=10,
        output_tokens=5,
        total_tokens=105,
    )
    row = aggregate_records([_record(1, LAUNCH, usage, "future-model")], "model", UTC)[
        0
    ]
    model_html = render_model_details_table([row])
    assert model_html.count('aria-label="No published rate"') == 14
    assert "No Credit Rate</th>" in model_html
    assert "105</td>" in model_html
