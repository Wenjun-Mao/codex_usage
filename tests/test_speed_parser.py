from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.speed_parser import SpeedParser

BASE = 1_790_000_000_000
USAGE = TokenUsage(100, 20, 3, 600, 200, 700)


def response_rows(usage=USAGE):
    return [
        {"type": "turn_context", "payload": {"turn_id": "turn", "model": "model"}},
        {"type": "event_msg", "payload": {"type": "item_completed", "turn_id": "turn", "started_at_ms": BASE, "completed_at_ms": BASE + 1000, "item": {"type": "Reasoning", "id": "r"}}},
        {"type": "event_msg", "payload": {"type": "item_completed", "turn_id": "turn", "started_at_ms": BASE + 1000, "completed_at_ms": BASE + 2000, "item": {"type": "AgentMessage", "id": "a"}}},
        {"type": "token_usage_record", "timestamp": datetime.fromtimestamp((BASE + 2000) / 1000, UTC).isoformat(), "payload": {"response_id": "response", "turn_id": "turn", "usage": usage.to_dict()}},
        {"type": "event_msg", "timestamp": datetime.fromtimestamp((BASE + 2001) / 1000, UTC).isoformat(), "payload": {"type": "token_count", "info": {"last_token_usage": usage.to_dict(), "total_token_usage": usage.to_dict()}}},
    ]


def run(rows, record_usage=USAGE, split=None):
    parser = SpeedParser()
    for index, row in enumerate(rows):
        if split == index:
            parser = SpeedParser(parser.state)
        parser.observe(row, "model", "turn")
    record = UsageRecord(datetime.fromtimestamp((BASE + 2001) / 1000, UTC), record_usage, "task", Path("synthetic.jsonl"), "root", "model", "turn")
    parser.finish(record, 0, "synthetic")
    return parser.facts[0]


def test_reasoning_is_counted_once_and_checkpoints_are_equivalent():
    fact = run(response_rows())
    assert fact.eligible
    assert fact.usage[3] / ((fact.end_ms - fact.start_ms) / 1000) == 300
    for split in range(5):
        assert run(response_rows(), split=split) == fact


@pytest.mark.parametrize("field", ["input_tokens", "cached_input_tokens", "cache_write_input_tokens", "output_tokens", "reasoning_output_tokens", "total_tokens"])
def test_reconciles_every_token_field(field):
    assert run(response_rows(), replace(USAGE, **{field: getattr(USAGE, field) + 1})).reason == "token_fields_mismatch"


@pytest.mark.parametrize("duration,reason", [(0, "collapsed_item_duration"), (-1, "negative_item_duration"), (9, "sub_resolution_item_duration")])
def test_rejects_unusable_item_duration(duration, reason):
    rows = response_rows()
    rows[1]["payload"]["completed_at_ms"] = BASE + duration
    assert run(rows).reason == reason


def test_rejects_missing_reasoning_and_overlap_and_ambiguous_pairing():
    rows = response_rows()
    rows[1]["payload"]["item"]["type"] = "AgentMessage"
    assert run(rows).reason == "missing_reasoning_interval"
    rows = response_rows()
    rows[2]["payload"]["started_at_ms"] -= 1
    assert run(rows).reason == "overlapping_model_intervals"
    rows = response_rows()
    rows.insert(4, rows[3])
    assert run(rows).reason == "ambiguous_response_records"


def test_aborted_and_old_checkpoint_boundaries_are_not_measurable():
    assert run(response_rows()[1:]).reason == "incomplete_response_boundary"
    rows = response_rows()
    rows.insert(3, {"type": "event_msg", "payload": {"type": "turn_aborted"}})
    assert run(rows).reason == "incomplete_response_boundary"


def test_state_is_content_free_and_bounded():
    parser = SpeedParser()
    rows = response_rows()
    rows[1]["payload"]["item"]["text"] = "PRIVATE CONTENT"
    for row in rows[:2] + [rows[1]] * 150:
        parser.observe(row, "model", "turn")
    assert "PRIVATE" not in repr(parser.state)
    assert len(parser.state["items"]) == 128
    assert parser.state["reason"] == "timing_state_limit"
