"""Included approval reviews retain telemetry without blocking quota valuation."""
import json
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_reports import PRICING_REVISION, render_ledger_report
from codex_usage.aggregation import summarize_record, summarize_records
from codex_usage.allowance_costs import allowance_cost_components
from codex_usage.allowance_index import indexed_allowance_report
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_probe import QuotaRead
from codex_usage.allowance_queries import build_allowance_report
from codex_usage.allowance_store import store_observations
from codex_usage.ledger_queries import query_ledger_records
from codex_usage.ledger_schema import increment_ledger_revision, ledger_revision, open_ledger
from codex_usage.models import SUBAGENT_USAGE_ROLE, TokenUsage, UsageRecord
from codex_usage.pricing import (
    credit_rate_for_model,
    estimate_codex_credits,
    estimate_cost,
    rate_for_model,
)
from codex_usage.subscription_usage import AUTO_REVIEW_FREE_FROM, is_included_subscription_usage


USAGE = TokenUsage(input_tokens=1_000_000, cached_input_tokens=700_000,
                   cache_write_input_tokens=100_000, output_tokens=10_000,
                   total_tokens=1_010_000)


def _record(model, at):
    return UsageRecord(at, USAGE, "review", Path("review.jsonl"),
                       SUBAGENT_USAGE_ROLE, model=model)


def test_free_review_is_known_zero_credits_but_has_no_public_api_rate():
    for at in (AUTO_REVIEW_FREE_FROM, AUTO_REVIEW_FREE_FROM + timedelta(days=1), None):
        rate = credit_rate_for_model("codex-auto-review", at)
        assert (rate.input_per_1m, rate.cached_input_per_1m, rate.output_per_1m) == (0, 0, 0)
        credits = estimate_codex_credits(USAGE, "codex-auto-review", at)
        assert credits.total_credits == credits.input_credits == credits.output_credits == 0
        assert credits.unpriced_tokens == 0
        assert rate_for_model("codex-auto-review", at) is None
        assert estimate_cost(USAGE, "codex-auto-review", at) is None

    summary = summarize_record(_record("codex-auto-review", AUTO_REVIEW_FREE_FROM))
    assert summary.usage == USAGE and summary.record_count == 1
    assert summary.cost.unpriced_tokens == USAGE.total_tokens
    assert summary.credits.total_credits == summary.credits.unpriced_tokens == 0


def test_unknown_earlier_review_prices_are_not_retroactively_changed():
    at = AUTO_REVIEW_FREE_FROM - timedelta(microseconds=1)
    assert credit_rate_for_model("codex-auto-review", at) is None
    assert not is_included_subscription_usage("codex-auto-review", at)
    summary = summarize_record(_record("codex-auto-review", at))
    assert summary.cost.unpriced_tokens == summary.credits.unpriced_tokens == USAGE.total_tokens
    assert allowance_cost_components(summary.cost, model="codex-auto-review", at=at,
                                     total_tokens=USAGE.total_tokens) == (0, USAGE.total_tokens)


@pytest.mark.parametrize("model", ["unknown", "gpt-6.1-sol-review", "codex-auto-review-v2",
                                  "codex-auto-review-pro", "openai.codex-auto-review"])
def test_free_rule_does_not_match_other_reviews_or_unknown_variants(model):
    at = AUTO_REVIEW_FREE_FROM
    assert not is_included_subscription_usage(model, at)
    summary = summarize_record(_record(model, at))
    assert summary.cost.unpriced_tokens == summary.credits.unpriced_tokens == USAGE.total_tokens
    assert allowance_cost_components(None, model=model, at=at,
                                     total_tokens=USAGE.total_tokens) == (0, USAGE.total_tokens)


def test_normal_code_review_keeps_its_model_cost_and_credits():
    record = _record("gpt-6.1-sol", AUTO_REVIEW_FREE_FROM)
    summary = summarize_record(record)
    assert summary.cost.total_usd > 0 and summary.credits.total_credits > 0
    assert allowance_cost_components(summary.cost, model=record.model, at=record.timestamp,
                                     total_tokens=USAGE.total_tokens) == (summary.cost.total_usd, 0)


def test_free_boundary_normalizes_model_ids_and_timezones():
    local = AUTO_REVIEW_FREE_FROM.astimezone(ZoneInfo("America/Toronto"))
    assert is_included_subscription_usage(" CODEX-AUTO-REVIEW ", local)
    assert credit_rate_for_model(" CODEX-AUTO-REVIEW ", local).input_per_1m == 0
    assert is_included_subscription_usage("codex-auto-review", AUTO_REVIEW_FREE_FROM.replace(tzinfo=None))
    assert not is_included_subscription_usage("codex-auto-review", local - timedelta(seconds=1))


def _home(tmp_path, monkeypatch, base):
    home = tmp_path / "codex"
    directory = home / "sessions"
    directory.mkdir(parents=True)
    reset = int((base + timedelta(days=7)).timestamp())
    points = [QuotaObservation((base + timedelta(hours=i)).isoformat(), "codex", "primary",
                              "pro", i * 5, 10080, reset) for i in range(5)]
    root = [
        {"timestamp": base.isoformat(), "type": "session_meta", "payload": {"id": "root"}},
        {"timestamp": base.isoformat(), "type": "turn_context", "payload": {"model": "gpt-6.1-sol"}},
    ]
    root += [{"timestamp": p.timestamp, "type": "event_msg", "payload": {"type": "token_count",
              "info": {"total_token_usage": {"input_tokens": (i + 1) * 1000,
                                               "total_tokens": (i + 1) * 1000}}}}
             for i, p in enumerate(points)]
    review = [
        {"timestamp": base.isoformat(), "type": "session_meta", "payload": {
            "id": "review", "session_id": "root", "source": {"subagent": {"other": "guardian"}}}},
        {"timestamp": base.isoformat(), "type": "turn_context", "payload": {"model": "codex-auto-review"}},
        {"timestamp": (base + timedelta(minutes=30)).isoformat(), "type": "event_msg",
         "payload": {"type": "token_count", "info": {"total_token_usage": {
             "input_tokens": 100_000, "total_tokens": 100_000}}}},
    ]
    for name, rows in (("root", root), ("review", review)):
        (directory / f"{name}.jsonl").write_text("\n".join(map(json.dumps, rows)) + "\n")
    read = QuotaRead(points[-1].timestamp, "pro", (points[-1],))
    monkeypatch.setattr("codex_usage.allowance_capture.probe_allowance", lambda *_: read)
    assert capture_once(home, request_kind="manual", max_workers=1).outcome == "success"
    ledger = ledger_database_path(home)
    with open_ledger(ledger) as connection:
        store_observations(connection, points, source_key="fixture", provenance="live")
        increment_ledger_revision(connection)
        connection.commit()
    return home, ledger


@pytest.mark.parametrize("after", [False, True])
def test_captured_free_reviews_preserve_api_totals_and_full_indexed_parity(tmp_path, monkeypatch, after):
    base = AUTO_REVIEW_FREE_FROM + timedelta(days=1 if after else -1)
    home, ledger = _home(tmp_path, monkeypatch, base)
    with open_ledger(ledger, read_only=True) as connection:
        connection.execute("begin")
        records = query_ledger_records(connection)
        total = summarize_records(records)
        assert total.usage.total_tokens == 105_000 and total.record_count == 6
        assert total.cost.total_usd == pytest.approx(0.01)
        assert total.cost.unpriced_tokens == 100_000
        assert total.credits.total_credits == pytest.approx(0.25)
        assert total.credits.unpriced_tokens == (0 if after else 100_000)
        oracle = build_allowance_report(connection)
        indexed = indexed_allowance_report(connection, ledger, revision=ledger_revision(connection),
                                            pricing_revision=PRICING_REVISION, coverage_complete=True)
    oracle["status"].pop("probe_age_seconds")
    indexed["status"].pop("probe_age_seconds")
    assert indexed == oracle
    assert indexed["windows"][0]["fully_priced"] is after
    if after:
        assert indexed["headline"]["estimate"]["value"] == pytest.approx(0.04)
        for pace in indexed["paces"][0]:
            assert pace["method"] == "calibrated cost"
            assert pace["rate"] == pytest.approx(5)
            assert pace["unpriced_tokens"] == 0
    else:
        assert indexed["headline"] is None
    with open_ledger(ledger, read_only=True) as connection:
        row = connection.execute("""select c.total_usd, c.unpriced_tokens from allowance_event_costs c
            join ledger_usage_events e using(event_id) join ledger_models m using(model_id)
            where m.model_key = 'codex-auto-review'""").fetchone()
        assert tuple(row) == (0, 0 if after else 100_000)
        assert connection.execute("select count(*) from ledger_usage_events").fetchone()[0] == 6

    view = render_ledger_report(home, range_name="all", project_keys=[], theme="day",
                                timezone_name="America/Toronto", now=base + timedelta(hours=4))
    assert "codex-auto-review" in view.html
    assert render_ledger_report(home, range_name="all", project_keys=[], theme="day",
                               timezone_name="America/Toronto", now=base + timedelta(hours=4)).cache_hit


def test_pricing_revision_replaces_old_unknown_review_cost_evidence(tmp_path, monkeypatch):
    home, ledger = _home(tmp_path, monkeypatch, AUTO_REVIEW_FREE_FROM + timedelta(days=1))
    with open_ledger(ledger) as connection:
        connection.execute("""insert into allowance_event_costs
            select e.event_id, 'old-pricing:allowance-index-2', 0, e.total_tokens
            from ledger_usage_events e join ledger_models m using(model_id)
            where m.model_key = 'codex-auto-review'""")
        connection.commit()
    with open_ledger(ledger, read_only=True) as connection:
        connection.execute("begin")
        report = indexed_allowance_report(connection, ledger, revision=ledger_revision(connection),
                                          pricing_revision=PRICING_REVISION, coverage_complete=True)
    assert report["windows"][0]["fully_priced"]
    with open_ledger(ledger, read_only=True) as connection:
        assert not connection.execute("select 1 from allowance_event_costs where pricing_revision like 'old-%'").fetchone()
