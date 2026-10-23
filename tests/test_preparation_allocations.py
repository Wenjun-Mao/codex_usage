"""Compact preparation must preserve identities, order and causal evidence."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_pace_inputs import PaceInputs
from codex_usage.allowance_pace_evidence import Series
from codex_usage.allowance_preparation import AllowancePreparation
from codex_usage.allowance_report_codec import _point_key
from codex_usage.allowance_reset_periods import reset_periods
from codex_usage.breakdown_display import identity
from codex_usage.ledger_schema import open_ledger
from test_allowance_window_cache import breakdown_home


def point(hours=0, **kwargs):
    at = datetime(2026, 10, 22, tzinfo=UTC)+timedelta(hours=hours)
    return QuotaObservation(at.isoformat(), "codex", "secondary", "pro", 20, 10080,
                            int((at+timedelta(days=5)).timestamp()), **kwargs)


def test_display_identity_ignores_only_private_fields_and_shares_schema():
    first = dict(point().to_dict(), provenance="Live probe")
    reordered = dict(reversed(list(first.items())))
    assert identity(first) == identity(dict(reordered, _boundary=True, _conflict=True))
    assert identity(first)[0] is identity(first.copy())[0]
    for key, value in first.items():
        assert identity(first) != identity({**first, key: str(value)+"changed"})
    assert identity(first) != identity({**first, "extra": "public"})
    assert identity({"value": 1}) == identity({"value": 1.0})


def test_codec_keys_preserve_json_scalar_types_and_share_schema():
    first = dict(point().to_dict(), provenance="Live probe")
    assert _point_key(first) == _point_key(dict(reversed(list(first.items()))))
    assert _point_key(first)[0] is _point_key(first.copy())[0]
    values = [1, 1.0, True, "1", None, 0.0, -0.0]
    assert len({_point_key({"value": value}) for value in values}) == len(values)
    assert _point_key({"nested": [1, 2]}) != _point_key({"nested": [2, 1]})


def test_pace_input_directory_reused_with_cross_duration_and_future_plan_events():
    points = [point(i) for i in range(4)]
    points += [replace(point(1), duration_minutes=300, plan="team"),
               replace(point(4), duration_minutes=300, plan="future")]
    raw = (tuple(points), {}, frozenset(points))
    with patch("codex_usage.allowance_preparation.cache.identity", return_value=None), \
         patch("codex_usage.allowance_preparation.PaceInputs", wraps=PaceInputs) as directory:
        preparation = AllowancePreparation(None, reuse_history=False)
        preparation.__dict__["raw"] = raw
        weekly = preparation.pace({("codex", 10080)})
        combined = preparation.pace({("codex", 300), ("codex", 10080)})
        assert directory.call_count == 1
        assert weekly.series[("codex", 10080)] is combined.series[("codex", 10080)]
        assert combined == PaceInputs(points).prepare(points)
        assert weekly.cycle(points[3]).plan == "pro"
        assert any(event[1] == "team" for event in preparation._pace_inputs.events["codex"])


def test_stable_pace_checkpoints_share_values_without_losing_origin_positions():
    points = [replace(point(0), timestamp=point(i).timestamp) for i in range(20)]
    series = Series.prepare(points, [])
    assert len(series.times) == len(series.checkpoints) == len(series.cycle_stats) == 20
    assert len({id(state) for state in series.checkpoints}) == 1
    assert len({id(state) for state in series.cycle_stats}) == 2


def test_reset_membership_reuses_primary_index_without_rescanning_other_series():
    class SinglePass(list):
        def __iter__(self):
            assert not getattr(self, "iterated", False)
            self.iterated = True
            return super().__iter__()
    weekly = [point(i) for i in range(3)]
    other = [replace(p, limit_id="other", duration_minutes=300) for p in weekly]
    points = SinglePass([p for pair in zip(weekly, other) for p in pair])
    periods, owners = reset_periods([], frozenset(weekly), [weekly[-1]], points=points)
    assert set(owners) == {0, 2, 4}
    assert periods[0]["capture_indices"] == [0, 2, 4]


def test_record_metadata_reuse_matches_each_uncached_row_and_expires_with_query(tmp_path):
    import codex_usage.ledger_queries as queries
    import codex_usage.ledger_record_materialization as materialization
    path = breakdown_home(tmp_path, days=10, extended=True)
    original = queries._row_to_usage_record
    seen = set()
    def checked(row, metadata):
        record = original(row, metadata)
        assert record == original(row)
        assert record.to_dict() == original(row).to_dict()
        seen.add(row["context_id"])
        return record
    with open_ledger(path) as connection:
        with patch.object(queries, "_row_to_usage_record", checked):
            records = queries.query_ledger_records(connection)
        assert records
        with patch.object(materialization, "context_values", wraps=materialization.context_values) as context:
            assert queries.query_ledger_records(connection) == records
            assert context.call_count == len(seen) < len(records)
        connection.execute("update ledger_contexts set project_aliases_json='[\"changed\"]'")
        changed = queries.query_ledger_records(connection)
        assert all(record.project_aliases == ("changed",) for record in changed)
        connection.rollback()
        assert queries.query_ledger_records(connection) == records


@pytest.mark.parametrize("kind", ["weekly", "balance"])
def test_direct_boundary_pass_matches_previous_reducer_with_duplicates_and_midnight(kind):
    import codex_usage.breakdown_display as display
    points = []
    for i in range(30):
        at = datetime(2026, 11, 1, 3, 30, tzinfo=UTC)+timedelta(minutes=30*(i//2))
        p = dict(timestamp=at.isoformat(), plan="pro" if i % 7 else "team")
        if kind == "weekly":
            p.update(limit_id="codex", slot="primary", duration_minutes=10080 if i % 5 else 300,
                     used_percent=i % 20, resets_at=1793000000+i//10, reset_credits=i//15)
        else:
            p.update(balance=str(100-i) if i % 4 else None, unlimited=i % 8 == 0,
                     diagnostic="invalid" if i % 9 == 0 else "", change="-1" if i % 3 else None)
        points.append(p)
    points.extend([dict(points[4], _boundary=True), dict(points[5], _conflict=True)])
    def old_pass(prepared, kind):
        reduced = display._reduce_points(prepared, kind, min(p.stamp for p in prepared),
            max(p.stamp for p in prepared)+.000001, buckets=1, detect_boundaries=True)
        return {p.signature for p in reduced if p.raw.get("_boundary")}
    expected = display.display_partitions(points, kind, ZoneInfo("America/Toronto"))
    with patch.object(display, "_boundaries", old_pass):
        assert display.display_partitions(points, kind, ZoneInfo("America/Toronto")) == expected
