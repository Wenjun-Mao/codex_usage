"""Finite union queries retain canonical records without unrelated decoding."""
from datetime import timedelta
from pathlib import Path
from runpy import run_path

import pytest

from codex_usage.aggregation import RangeBounds
from codex_usage.ledger_usage_ranges import merge_bounds, subtract_bounds, usage_union_clause
from codex_usage.ledger_queries import query_ledger_records
from codex_usage.ledger_schema import open_ledger

fixture = run_path(str(Path(__file__).resolve().parents[1] / "scripts/usage_breakdown_fixture.py"))
AT, breakdown_home = fixture["AT"], fixture["breakdown_home"]


def test_merge_and_calendar_subtraction_preserve_exact_microsecond_membership():
    assert merge_bounds([RangeBounds(10,20), RangeBounds(15,25), RangeBounds(25,30), RangeBounds(40,40)]) == [RangeBounds(10,30)]
    assert subtract_bounds([RangeBounds(10,30), RangeBounds(40,50)], RangeBounds(15,45)) == [RangeBounds(10,15), RangeBounds(45,50)]
    assert subtract_bounds([RangeBounds(10,30)], RangeBounds(None,None)) == []
    assert subtract_bounds([RangeBounds(10,30)], RangeBounds(40,50)) == [RangeBounds(10,30)]
    assert subtract_bounds([RangeBounds(10,30)], RangeBounds(None,20)) == [RangeBounds(20,30)]
    with pytest.raises(ValueError, match="finite"):
        usage_union_clause([RangeBounds(None,30)])


def test_union_seeks_timestamp_index_and_decodes_only_union_members(tmp_path, monkeypatch):
    path = breakdown_home(tmp_path, days=40, extended=True)
    lo, hi = round((AT-timedelta(days=10)).timestamp()*1e6), round((AT-timedelta(days=8)).timestamp()*1e6)
    ranges = [RangeBounds(lo+1,hi+1), RangeBounds(lo+100,hi+1)]
    import codex_usage.ledger_queries as queries
    decoded = []
    original = queries._row_to_usage_record
    def checked(row):
        assert lo < row["timestamp_us"] <= hi
        decoded.append(row["event_id"])
        return original(row)
    monkeypatch.setattr(queries, "_row_to_usage_record", checked)
    with open_ledger(path, read_only=True) as connection:
        records = query_ledger_records(connection, bounds_union=ranges)
        expected = connection.execute("select count(*) from ledger_usage_events where timestamp_us>? and timestamp_us<=?", (lo,hi)).fetchone()[0]
        assert len(records) == len(set(decoded)) == expected
        assert query_ledger_records(connection, bounds_union=[]) == []
        clause, parameters = usage_union_clause(ranges)
        plan = connection.execute("explain query plan select event_id from ledger_usage_events where "+clause, parameters).fetchall()
        assert any("ledger_usage_timestamp_idx" in row["detail"] and "SEARCH" in row["detail"] for row in plan)
