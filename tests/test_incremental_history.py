"""Incremental preparation must equal fresh history, including backward effects."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from codex_usage.allowance_captures import CaptureDirectory
from codex_usage.allowance_display_history import display_history
from codex_usage.allowance_pace_evidence import Group
from codex_usage.allowance_models import QuotaObservation
from codex_usage.breakdown_readings import display_day, partition_readings
from codex_usage.breakdown_day_cache import reused_display_day
from codex_usage.history_preparation_cache import HistoryPreparationCache, encode
from codex_usage.ledger_schema import open_ledger

AT = datetime(2026, 11, 1, 3, tzinfo=UTC)


def point(minutes, used=10, **kwargs):
    base = QuotaObservation((AT + timedelta(minutes=minutes)).isoformat(), "codex", "secondary",
                            "pro", used, 10080, int((AT + timedelta(days=7)).timestamp()), 4)
    return replace(base, **kwargs)


class MemoryCache:
    def __init__(self):
        self.values = {}
        self.dependency = []

    def read(self, slot):
        return json.loads(self.values[slot]) if slot in self.values else None

    def stage(self, slot, value):
        self.values[slot] = encode(value)

    def prefix_unchanged(self, previous, end):
        return ([p for p in previous if datetime.fromisoformat(p["timestamp"]).timestamp() <= end]
                == [p for p in self.dependency if datetime.fromisoformat(p["timestamp"]).timestamp() <= end])


def history(points, live, cache=None):
    provenance = {p: {"Live probe" if p in live else "Task snapshot"} for p in points}
    directory = CaptureDirectory(points, provenance)
    if cache is not None:
        cache.dependency = directory.captures
    return display_history(points, provenance, [], [points[-1]], live_points=live,
                           directory=directory, cache=cache)


def assert_fresh(points, live, cache):
    assert encode(history(points, live, cache)) == encode(history(points, live))


def test_append_only_resumes_all_durations_without_replaying_old_groups():
    points = [point(i, 10 + i / 100, duration_minutes=300 if i % 2 else 10080) for i in range(100)]
    cache = MemoryCache()
    assert_fresh(points, set(points), cache)
    points.append(point(101, 12))
    with patch.object(Group, "from_points", wraps=Group.from_points) as groups:
        result = history(points, set(points), cache)
    assert groups.call_count == 1
    assert encode(result) == encode(history(points, set(points)))
    with patch.object(Group, "from_points", side_effect=AssertionError("replayed unchanged history")):
        assert history(points, set(points), cache) == result


@pytest.mark.parametrize("change", ["append_plan", "same_time", "insert", "delete", "correct", "provenance", "offset"])
def test_backward_effects_fall_back_to_fresh_lane(change):
    points = [point(0), point(1, 20, plan=""), point(2, 0, plan="", reset_credits=3),
              point(3, 2, plan="", reset_credits=3)]
    live = set(points)
    cache = MemoryCache()
    assert_fresh(points, live, cache)
    if change == "append_plan":
        points.append(point(4, 3, plan="team", reset_credits=3))
        live = set(points)
    elif change == "same_time":
        points.append(replace(points[-1], used_percent=90))
        live = set(points)
    elif change == "insert":
        points.insert(0, point(-1, 0))
        live = set(points)
    elif change == "delete":
        points.pop(0)
        live = set(points)
    elif change == "correct":
        points[1] = replace(points[1], plan="team")
        live = set(points)
    elif change == "provenance":
        live.remove(points[1])
    elif change == "offset":
        points[1] = replace(points[1], timestamp="2026-10-31T23:01:00-04:00")
        live = set(points)
    assert_fresh(points, live, cache)
    points.append(point(5, 5, reset_credits=3))
    live.add(points[-1])
    assert_fresh(points, live, cache)


def test_new_official_bracket_reassigns_previous_task_lane_and_restores_after_removal():
    points = [point(0, 10), point(1, 11), point(2, 12)]
    live = {points[0]}
    cache = MemoryCache()
    assert_fresh(points, live, cache)
    points.append(point(3, 13))
    live.add(points[-1])
    assert_fresh(points, live, cache)
    live.remove(points[-1])
    assert_fresh(points, live, cache)


def test_prefix_fingerprint_is_independent_of_hash_batch_boundary():
    points = [point(i, i / 1000) for i in range(4100)]
    cache = MemoryCache()
    history(points[:4095], set(points), cache)
    assert_fresh(points, set(points), cache)
    with patch.object(Group, "from_points", side_effect=AssertionError("prefix hash changed")):
        history(points, set(points), cache)


def test_daily_reuse_includes_sparse_neighbors_raw_order_and_dst():
    cache = MemoryCache()
    tz = ZoneInfo("America/Toronto")
    points = [point(i, i / 200).to_dict() for i in (-1440, 0, 90, 150, 210, 5 * 1440)]
    _, _, partitions = partition_readings(points, "weekly", tz)
    name = "meter-display:2026-11-01"
    expected = display_day(name, tz, partitions.get)
    def encoded(key):
        return json.dumps(partitions.get(key, []))
    assert reused_display_day(name, tz, encoded, cache) == expected
    with patch("codex_usage.breakdown_readings.display_partitions", side_effect=AssertionError("rebuilt day")):
        assert reused_display_day(name, tz, encoded, cache) == expected
    points[-1]["plan"] = "team"
    _, _, changed = partition_readings(points, "weekly", tz)
    with patch("codex_usage.breakdown_readings.display_partitions", wraps=__import__(
            "codex_usage.breakdown_display", fromlist=["display_partitions"]).display_partitions) as reduce:
        assert reused_display_day(name, tz, lambda key: json.dumps(changed.get(key, [])), cache) == display_day(name, tz, changed.get)
        assert reduce.call_count == 2


def test_persistent_cache_corruption_bounds_and_stale_publication(tmp_path, monkeypatch):
    import codex_usage.history_preparation_cache as module
    path = tmp_path / "ledger.sqlite3"
    with open_ledger(path):
        pass
    with open_ledger(path, read_only=True) as reader:
        reader.execute("begin")
        cache = HistoryPreparationCache(reader)
        cache.stage("one", {"value": 1})
        with open_ledger(path) as writer:
            cache.finish(writer)
            writer.commit()
    with open_ledger(path, read_only=True) as reader:
        reader.execute("begin")
        assert HistoryPreparationCache(reader).read("one") == {"value": 1}
    with open_ledger(path) as writer:
        writer.execute("update history_preparation_cache set payload='broken'")
        writer.commit()
    with open_ledger(path, read_only=True) as reader:
        reader.execute("begin")
        cache = HistoryPreparationCache(reader)
        assert cache.read("one") is None
        cache.stage("two", {"value": 2})
        with open_ledger(path) as writer:
            writer.execute("update dashboard_preparation_state set generation=generation+1")
            writer.commit()
        with open_ledger(path) as writer:
            cache.finish(writer)
            assert writer.execute("select count(*) from history_preparation_cache where slot='two'").fetchone()[0] == 0
    monkeypatch.setattr(module, "MAX_BYTES", 12)
    with open_ledger(path, read_only=True) as reader:
        reader.execute("begin")
        cache = HistoryPreparationCache(reader)
        cache.stage("three", {"value": 3})
        cache.stage("four", {"value": 4})
        assert cache.pending_bytes <= 12
        with open_ledger(path) as writer:
            cache.finish(writer)
            assert writer.execute("select sum(length(cast(payload as blob))) from history_preparation_cache").fetchone()[0] <= 12


def test_writable_rollback_generation_collision_cannot_publish(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    with open_ledger(path) as writer:
        writer.execute("begin")
        writer.execute("update dashboard_preparation_state set generation=generation+1")
        cache = HistoryPreparationCache(writer)
        cache.stage("uncommitted", {"wrong": True})
        writer.rollback()
        writer.execute("update dashboard_preparation_state set generation=generation+1")
        cache.finish(writer)
        assert cache.dependency is None and not cache.pending
        assert not writer.execute("select 1 from sqlite_master where name='history_preparation_cache'").fetchone()
    with open_ledger(path, read_only=True) as reader:
        cache = HistoryPreparationCache(reader)
        cache.stage("unpinned", {})
        assert cache.dependency is None and not cache.pending
