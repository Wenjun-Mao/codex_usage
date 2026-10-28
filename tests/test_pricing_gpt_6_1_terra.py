from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from codex_usage.aggregation import aggregate_records
from codex_usage.model_presentation import model_display_sort_key
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.pricing import (
    ModelRate,
    credit_rate_for_model,
    estimate_codex_credits,
    estimate_cost,
    rate_for_model,
)
from codex_usage.report_breakdown import OTHER_MODEL_KEY, build_report_breakdown
from codex_usage.report_breakdown_view import build_breakdown_view
from codex_usage.report_tables import render_model_details_table

LAUNCH = datetime(2026, 10, 26, tzinfo=UTC)
MODEL = "gpt-6.1-terra"


def test_exact_terra_rates_start_at_launch_without_repricing_other_models():
    before = LAUNCH - timedelta(microseconds=1)
    assert rate_for_model(MODEL, at=before) is None
    assert credit_rate_for_model(MODEL, at=before) is None
    assert rate_for_model(MODEL, at=LAUNCH) == ModelRate(1, .05, 5, 1.25)
    assert credit_rate_for_model(MODEL, at=LAUNCH) == ModelRate(25, 1.25, 125)
    assert rate_for_model("  GPT-6.1-TERRA  ") == ModelRate(1, .05, 5, 1.25)
    for unknown in (MODEL + "-fast", MODEL + "-2026-10-26", "gpt-6-terra"):
        assert rate_for_model(unknown) is None
        assert credit_rate_for_model(unknown) is None
    assert rate_for_model("gpt-6.1-sol", at=LAUNCH) == ModelRate(2, .1, 10, 2.5)
    assert rate_for_model("gpt-5.6-terra", at=LAUNCH) == ModelRate(2, .2, 12, 2.5)
    assert credit_rate_for_model("gpt-5.6-terra", at=LAUNCH) == ModelRate(50, 5, 300)


@pytest.mark.parametrize(
    ("inputs", "ordinary", "cached", "write", "output"),
    ((272_000, .15, .0036, .0625, .5),
     (272_001, .300002, .0072, .125, .75)),
)
def test_full_request_context_boundary_and_flat_standard_credits(inputs, ordinary, cached, write, output):
    usage = TokenUsage(input_tokens=inputs, cached_input_tokens=72_000,
        cache_write_input_tokens=50_000, output_tokens=100_000, total_tokens=inputs+100_000)
    cost = estimate_cost(usage, MODEL, at=LAUNCH)
    assert cost.ordinary_input_usd == pytest.approx(ordinary)
    assert cost.cached_input_usd == pytest.approx(cached)
    assert cost.cache_write_input_usd == pytest.approx(write)
    assert cost.output_usd == pytest.approx(output)
    assert cost.total_usd == pytest.approx(ordinary+cached+write+output)
    credits = estimate_codex_credits(usage, MODEL, at=LAUNCH)
    assert credits.ordinary_input_credits == pytest.approx((inputs-122_000)*25/1e6)
    assert credits.cached_input_credits == pytest.approx(.09)
    assert credits.cache_write_input_credits == pytest.approx(1.25)
    assert credits.output_credits == pytest.approx(12.5)
    assert credits.total_credits == pytest.approx((inputs-72_000)*25/1e6 + .09 + 12.5)


def record(index, *, model=MODEL, timestamp=LAUNCH):
    return UsageRecord(timestamp=timestamp,
        usage=TokenUsage(input_tokens=1000, output_tokens=100, total_tokens=1100),
        session_id=f"session-{index}", file_path=Path("/tmp/synthetic.jsonl"),
        usage_role="root", model=model)


def test_mixed_launch_dates_keep_prelaunch_usage_visibly_unpriced():
    records = [record(0, timestamp=LAUNCH-timedelta(microseconds=1)), record(1)]
    row = aggregate_records(records, "model", UTC)[0]
    assert row.usage.total_tokens == 2200
    assert row.cost.unpriced_tokens == row.credits.unpriced_tokens == 1100
    assert row.cost.total_usd == pytest.approx(.0015)
    assert row.credits.total_credits == pytest.approx(.0375)
    html = render_model_details_table([row])
    assert MODEL in html and 'class="model-partial">partial' in html


def test_terra_sort_and_eight_model_breakdown_preserve_colors_and_all_totals():
    models = (MODEL, "gpt-6.1-sol", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna",
              "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna")
    assert sorted(models[:3], key=model_display_sort_key) == ["gpt-6.1-sol", MODEL, "gpt-6-astra"]
    records = [record(index, model=model) for index, model in enumerate(models)]
    breakdown = build_report_breakdown(records)
    view = build_breakdown_view(breakdown)
    assert len(breakdown.model_rows) == 8
    assert len(view.model_legend) == 8
    assert view.model_legend[-1].key == OTHER_MODEL_KEY
    assert view.model_legend[-1].color_slot == 7
    assert len({item.color_slot for item in view.model_legend}) == 8
    assert sum(point.total_tokens for point in view.model_points) == 8800
    assert sum(point.cost_usd for point in view.model_points) == pytest.approx(
        sum(row.cost.total_usd for row in breakdown.model_rows))
    slots = {item.key: item.color_slot for item in view.model_legend}
    for model, expected in (("gpt-6.1-sol", 6), ("gpt-6-astra", 0), ("gpt-6-sol", 4),
                            ("gpt-6-luna", 5), ("gpt-5.6-sol", 1), ("gpt-5.6-terra", 2)):
        if model in slots:
            assert slots[model] == expected
