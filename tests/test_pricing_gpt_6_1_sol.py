from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codex_usage.aggregation import aggregate_records
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.pricing import (
    ModelRate,
    credit_rate_for_model,
    estimate_codex_credits,
    estimate_cost,
    rate_for_model,
)


LAUNCH = datetime(2026, 9, 29, tzinfo=UTC)


def test_exact_model_rates_begin_on_launch_without_changing_gpt_6_sol() -> None:
    model = "gpt-6.1-sol"
    assert rate_for_model(model, at=LAUNCH - timedelta(microseconds=1)) is None
    assert credit_rate_for_model(model, at=LAUNCH - timedelta(microseconds=1)) is None
    assert rate_for_model(model, at=LAUNCH) == ModelRate(2, 0.1, 10, 2.5)
    assert credit_rate_for_model(model, at=LAUNCH) == ModelRate(50, 2.5, 250)
    assert rate_for_model(model.upper()) == ModelRate(2, 0.1, 10, 2.5)
    assert rate_for_model(f"{model}-fast") is None
    assert rate_for_model("gpt-6-sol", at=LAUNCH) == ModelRate(2, 0.2, 10, 2.5)
    assert credit_rate_for_model("gpt-6-sol", at=LAUNCH) == ModelRate(50, 5, 250)


@pytest.mark.parametrize(
    ("input_tokens", "ordinary", "cached", "write", "output"),
    (
        (272_000, 0.3, 0.0072, 0.125, 1.0),
        (272_001, 0.600004, 0.0144, 0.25, 1.5),
    ),
)
def test_full_request_long_context_api_rates(
    input_tokens: int,
    ordinary: float,
    cached: float,
    write: float,
    output: float,
) -> None:
    usage = TokenUsage(
        input_tokens=input_tokens,
        cached_input_tokens=72_000,
        cache_write_input_tokens=50_000,
        output_tokens=100_000,
        total_tokens=input_tokens + 100_000,
    )
    cost = estimate_cost(usage, "gpt-6.1-sol", at=LAUNCH)
    assert cost is not None
    assert cost.ordinary_input_usd == pytest.approx(ordinary)
    assert cost.cached_input_usd == pytest.approx(cached)
    assert cost.cache_write_input_usd == pytest.approx(write)
    assert cost.output_usd == pytest.approx(output)
    assert cost.total_usd == pytest.approx(ordinary + cached + write + output)

    credits = estimate_codex_credits(usage, "gpt-6.1-sol", at=LAUNCH)
    assert credits is not None
    assert credits.cached_input_credits == pytest.approx(0.18)
    assert credits.cache_write_input_credits == pytest.approx(2.5)
    assert credits.output_credits == pytest.approx(25)


def test_mixed_date_aggregation_keeps_prelaunch_usage_unpriced() -> None:
    usage = TokenUsage(input_tokens=1_000, output_tokens=100, total_tokens=1_100)
    records = [
        UsageRecord(
            timestamp=timestamp,
            usage=usage,
            session_id=f"session-{index}",
            file_path=Path("/tmp/session.jsonl"),
            usage_role="root",
            model="gpt-6.1-sol",
        )
        for index, timestamp in enumerate((LAUNCH - timedelta(microseconds=1), LAUNCH))
    ]
    row = aggregate_records(records, "model", UTC)[0]
    assert row.cost.unpriced_tokens == usage.total_tokens
    assert row.credits.unpriced_tokens == usage.total_tokens
    assert row.cost.total_usd == pytest.approx(0.003)
    assert row.credits.total_credits == pytest.approx(0.075)
