"""Exact numeric and compatibility guards for compact report preparation."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
import json
import math
from pathlib import Path
from unittest.mock import patch

import pytest

from codex_usage import pricing
from codex_usage.aggregation import UsageSummary, ValuedUsageRecord, summarize_record, value_records
from codex_usage.allowance_report_codec import decode_report, encode_report
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.pricing import CostBreakdown
from codex_usage.pricing_schedule import ScheduleResolver, schedule_entry_for_model
from codex_usage.project_economics import _turn_metrics


def record(model="gpt-6.1-sol", at=datetime(2026, 10, 22, tzinfo=UTC), **values):
    return UsageRecord(timestamp=at, model=model, usage=TokenUsage(**values),
                       file_path=Path('/synthetic'), session_id='task', turn_id='turn', usage_role='root')


def test_batch_valuation_matches_scalar_oracle_at_every_pricing_boundary():
    records = []
    for schedule in (pricing.API_PRICING_USD_SCHEDULE, pricing.CODEX_CREDIT_RATE_SCHEDULE):
        resolver = ScheduleResolver(schedule)
        for entry in schedule:
            for name in (entry.model_key, *entry.aliases, 'UNKNOWN', '  '+entry.model_key.upper()+'  '):
                for delta in (-1, 0, 1):
                    at = entry.effective_from + timedelta(microseconds=delta)
                    for stamp in (at, at.replace(tzinfo=None), at.astimezone(timezone(timedelta(hours=7)))):
                        assert resolver.entry(name, stamp) is schedule_entry_for_model(schedule, name, stamp)
                    for tokens in (272000, 272001):
                        records.append(record(name, at, input_tokens=tokens, cached_input_tokens=1000,
                                              cache_write_input_tokens=100, output_tokens=53,
                                              total_tokens=tokens+53))
            assert resolver.entry(entry.model_key) is schedule_entry_for_model(schedule, entry.model_key)
    assert [v.summary for v in value_records(records)] == [summarize_record(r) for r in records]


def test_resolver_keeps_stable_ties_and_refreshes_replaced_schedules(monkeypatch):
    a = pricing.API_PRICING_USD_SCHEDULE[0]
    later = replace(a, effective_from=a.effective_from+timedelta(days=1))
    tie = replace(a, rate=replace(a.rate, input_per_1m=999))
    schedule = (later, a, tie)
    resolver = ScheduleResolver(schedule)
    assert resolver.entry(a.model_key, a.effective_from) is tie
    assert resolver.entry(a.model_key, later.effective_from) is later
    records = [record(a.model_key, a.effective_from, input_tokens=10, total_tokens=10)]
    old = value_records(records)
    monkeypatch.setattr(pricing, 'API_PRICING_USD_SCHEDULE', schedule)
    assert value_records(records)[0].summary == summarize_record(records[0])
    assert value_records(records)[0].summary.cost != old[0].summary.cost
    monkeypatch.setattr(pricing, 'CODEX_CREDIT_RATE_SCHEDULE', (tie,))
    assert value_records(records)[0].summary == summarize_record(records[0])


def test_schedule_binding_is_per_batch_not_per_response():
    from codex_usage import pricing_schedule
    with patch.object(pricing_schedule, '_compiled_schedule', wraps=pricing_schedule._compiled_schedule) as compiled:
        value_records([record(input_tokens=10, total_tokens=10)] * 100)
        assert compiled.call_count == 2


@pytest.mark.parametrize('include_model', [False, True])
def test_turn_costs_preserve_sequential_addition_and_priced_response_population(include_model):
    items = []
    # Compensated sum would retain the two ones within the first turn; the old
    # sequential turn reducer loses them. The final population still uses sum.
    for turn, model, cost, unpriced in [
        ('a', 'sol', 1e16, 0), ('b', 'sol', 0.0, 0),
        ('a', 'sol', 1.0, 0), ('mixed', 'sol', 3.0, 0),
        ('a', 'sol', 1.0, 0), ('mixed', 'astra', 0.0, 1),
        ('', 'sol', 9.0, 0),
    ]:
        r = replace(record(input_tokens=1, total_tokens=1), turn_id=turn, model=model)
        items.append(ValuedUsageRecord(r, UsageSummary(r.usage, CostBreakdown(
            total_usd=cost, unpriced_tokens=unpriced), 1)))
    actual = _turn_metrics(items, include_model=include_model)
    costs = [1e16, 0.0, 3.0] if include_model else [1e16, 0.0]
    assert actual.priced_turn_cost_usd == sum(costs)
    assert actual.priced_response_cost_usd == sum([1e16, 0.0, 1.0, 3.0, 1.0])
    assert actual.priced_response_count == 5
    assert actual.priced_turn_count == len(costs)
    assert actual.response_count == actual.token_count == 6


def test_capture_table_roundtrip_preserves_layout_numeric_types_and_shared_ownership():
    points = [dict(value=v, timestamp=str(i)) for i, v in enumerate([1, 1.0, True, 0.0, -0.0, None])]
    points += [dict(timestamp='nested', value={'a': [1, 2]})]
    window = dict(points=points)
    original = dict(windows=[window], headline=window, qualified=[], history=[window])
    restored = decode_report(encode_report(original))
    assert list(restored['windows'][0]['points'][-1]) == ['timestamp', 'value']
    assert [type(p['value']) for p in restored['windows'][0]['points']] == [type(p['value']) for p in points]
    assert math.copysign(1, restored['windows'][0]['points'][4]['value']) == -1
    assert restored['headline'] is restored['windows'][0]


@pytest.mark.parametrize('schemas,rows', [
    (None, []), ([['x', 'x']], [[0, 1, 2]]), ([[1]], [[0, 1]]),
    ([['x']], [[True, 1]]), ([['x']], [[-1, 1]]), ([['x']], [[1, 1]]),
    ([['x']], [[0]]), ([['x']], [[0, 1, 2]]), ([['x']], [None]),
    ([['x'], ['x']], [[0, 1], [1, 1]]),
])
def test_malformed_capture_table_rejected(schemas, rows):
    with pytest.raises(ValueError):
        decode_report(json.dumps(dict(format='allowance-window-references-3', capture_schemas=schemas,
            captures=rows, report=dict(windows=[], qualified=[], history=[], headline=None))))


def test_fixed_legacy_formats_one_and_two():
    one = '{"format":"allowance-window-references-1","report":{"windows":[{"points":[{"x":1.0}]}],"headline":0,"qualified":[0],"history":[0]}}'
    two = '{"format":"allowance-window-references-2","captures":[{"x":1.0}],"report":{"windows":[{"point_indices":[0]}],"headline":0,"qualified":[0],"history":[0]}}'
    for payload in (one, two):
        report = decode_report(payload)
        assert report['headline'] is report['windows'][0]
        assert report['headline']['points'] == [{'x': 1.0}]
        assert type(report['headline']['points'][0]['x']) is float


def test_format_upgrade_reuses_cached_html_and_passes_prepared_history(tmp_path):
    from codex_usage import agent_reports, allowance_index
    from codex_usage.allowance_capture_codec import decode_captures
    from test_dashboard_work_contract import breakdown_home, render

    def encode_two(report):
        encoded = json.loads(encode_report(report))
        encoded['captures'] = decode_captures(encoded.pop('capture_schemas'), encoded['captures'])
        encoded['format'] = 'allowance-window-references-2'
        return json.dumps(encoded)

    breakdown_home(tmp_path, extended=True)
    with patch.object(allowance_index, 'REPORT_CACHE_FORMAT_REVISION', 2), \
         patch.object(allowance_index, 'encode_report', encode_two):
        old = render(tmp_path)
    with patch.object(agent_reports, 'materialize_ledger', side_effect=AssertionError('Cached range revalued')):
        upgraded = render(tmp_path)
        warm = render(tmp_path)
    assert [a['state'] for a in upgraded.allowance_navigation['actions']] == [a['state'] for a in old.allowance_navigation['actions']]
    assert upgraded.html == warm.html
    assert upgraded.allowance_navigation['scope'] != old.allowance_navigation['scope']
