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

LAUNCH = datetime(2026, 11, 17, tzinfo=UTC)
MODELS = (
    pytest.param("gpt-6.2-astra", ModelRate(8, .4, 40, 10), ModelRate(200, 10, 1000), id="astra"),
    pytest.param("gpt-6.2-sol", ModelRate(2, .1, 10, 2.5), ModelRate(50, 2.5, 250), id="sol"),
)


@pytest.mark.parametrize("model, api, credits", MODELS)
def test_launch_rates_are_effective_dated_and_match_exact_models(model, api, credits):
    before = LAUNCH - timedelta(microseconds=1)
    assert rate_for_model(model, at=before) is None
    assert credit_rate_for_model(model, at=before) is None
    assert rate_for_model(model, at=LAUNCH) == api
    assert credit_rate_for_model(model, at=LAUNCH) == credits
    assert rate_for_model(f"  {model.upper()}  ") == api
    for unknown in (f"{model}-fast", f"{model}-2026-11-17", "gpt-6.2"):
        assert rate_for_model(unknown) is None
        assert credit_rate_for_model(unknown) is None


@pytest.mark.parametrize("model, api, credit_rate", MODELS)
@pytest.mark.parametrize("inputs, input_multiplier, output_multiplier", (
    (272_000, 1, 1), (272_001, 2, 1.5), (500_000, 2, 1.5),
))
def test_api_context_premium_applies_to_full_request_but_not_standard_credits(
    model, api, credit_rate, inputs, input_multiplier, output_multiplier,
):
    usage = TokenUsage(input_tokens=inputs, cached_input_tokens=72_000,
                       cache_write_input_tokens=50_000, output_tokens=10_000,
                       reasoning_output_tokens=5_000, total_tokens=inputs + 10_000)
    cost = estimate_cost(usage, model, at=LAUNCH)
    expected = ((inputs - 122_000) / 1e6 * api.input_per_1m * input_multiplier,
                .072 * api.cached_input_per_1m * input_multiplier,
                .05 * api.cache_write_input_per_1m * input_multiplier,
                .01 * api.output_per_1m * output_multiplier)
    assert (cost.ordinary_input_usd, cost.cached_input_usd, cost.cache_write_input_usd,
            cost.output_usd) == pytest.approx(expected)
    assert cost.total_usd == pytest.approx(sum(expected))
    credits = estimate_codex_credits(usage, model, at=LAUNCH)
    assert credits.cache_write_input_credits == pytest.approx(.05 * credit_rate.input_per_1m)
    assert credits.total_credits == pytest.approx(
        (inputs - 72_000) / 1e6 * credit_rate.input_per_1m
        + .072 * credit_rate.cached_input_per_1m + .01 * credit_rate.output_per_1m
    )


def test_mixed_model_rollup_keeps_prelaunch_usage_unpriced_and_predecessors_unchanged():
    usage = TokenUsage(input_tokens=1_000, output_tokens=100, total_tokens=1_100)
    evidence = (
        ("gpt-6.2-astra", LAUNCH - timedelta(seconds=1)),
        ("gpt-6.2-astra", LAUNCH),
        ("gpt-6.2-sol", LAUNCH),
        ("gpt-6-astra", LAUNCH),
        ("gpt-6.1-sol", LAUNCH),
    )
    rows = aggregate_records([
        UsageRecord(timestamp=at, usage=usage, session_id=f"session-{index}",
                    file_path=Path("/tmp/synthetic.jsonl"), usage_role="root", model=model)
        for index, (model, at) in enumerate(evidence)
    ], "model", UTC)
    priced = {row.key: (row.cost.total_usd, row.credits.total_credits) for row in rows}
    assert priced == {
        "gpt-6.2-astra": pytest.approx((.012, .3)),
        "gpt-6.2-sol": pytest.approx((.003, .075)),
        "gpt-6-astra": pytest.approx((.015, .375)),
        "gpt-6.1-sol": pytest.approx((.003, .075)),
    }
    assert sum(row.cost.unpriced_tokens for row in rows) == 1_100
    assert sum(row.credits.unpriced_tokens for row in rows) == 1_100
    assert sum(row.usage.total_tokens for row in rows) == 5_500
