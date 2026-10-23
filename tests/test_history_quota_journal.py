"""Prefix certificates survive compatible writers and fail closed on missing evidence."""
import sqlite3
from unittest.mock import patch
import zlib

import pytest

from codex_usage.allowance_preparation import AllowancePreparation
from codex_usage.allowance_pace_evidence import Cursor
from codex_usage.allowance_pace_inputs import PaceInputs
from codex_usage.allowance_store import store_observations
from codex_usage.dashboard_preparation_tracking import token
from codex_usage.history_quota_journal import prefix_unchanged
from codex_usage.ledger_schema import open_ledger
from codex_usage.ledger_writer_contract import authorize_writer_connection
from codex_usage import allowance_prepared_cache
from test_incremental_history import point


def add(path, points):
    with open_ledger(path) as writer:
        store_observations(writer, points, source_key="fixture", provenance="live")
        writer.commit()


def prepare(path):
    allowance_prepared_cache.clear()
    with open_ledger(path, read_only=True) as reader:
        reader.execute("begin")
        preparation = AllowancePreparation(reader)
        points, _, live = preparation.raw
        expected = PaceInputs(points).prepare(live)
        pushes = []
        original = Cursor.push
        def pushed(self, *args):
            pushes.append(args[0])
            return original(self, *args)
        with patch.object(Cursor, "push", pushed):
            actual = preparation.pace(set(expected.series))
        assert actual == expected
        with open_ledger(path) as writer:
            preparation.history_cache.finish(writer)
            writer.commit()
        return pushes


def test_persisted_pace_append_reuses_prefix_and_replays_after_old_edit(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    add(path, [point(i, 10 + i) for i in range(10)])
    assert len(prepare(path)) == 10
    add(path, [point(11, 21)])
    assert prepare(path) == [10]
    assert prepare(path) == []
    with sqlite3.connect(path) as old:
        authorize_writer_connection(old)
        old.execute("update quota_observations set used_percent=30 where used_percent=12")
    assert len(prepare(path)) == 11


def test_first_known_plan_and_other_duration_plan_event_match_causal_replay(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    add(path, [point(i, 10 + i, plan="") for i in range(4)])
    prepare(path)
    add(path, [point(5, 20)])
    assert len(prepare(path)) == 9  # Initial unknown origins plus first-known replay.
    add(path, [point(6, 21, plan="team", duration_minutes=300), point(7, 22)])
    assert sorted(prepare(path)) == [0, 5]
    add(path, [point(6, 80, plan="team", duration_minutes=300)])
    prepare(path)


@pytest.mark.parametrize("mutation", ["early", "provenance", "blob", "gap", "epoch", "rollback"])
def test_journal_does_not_certify_backwards_or_unverifiable_mutations(tmp_path, mutation):
    path = tmp_path / "ledger.sqlite3"
    add(path, [point(0, 10), point(1, 11)])
    with open_ledger(path, read_only=True) as reader:
        previous = token(reader)
    end = point(1).timestamp_seconds
    add(path, [point(5, 15)])
    with open_ledger(path, read_only=True) as reader:
        assert prefix_unchanged(reader, previous, token(reader), end)
    with open_ledger(path) as writer:
        if mutation == "early":
            writer.execute("update quota_observations set used_percent=19 where used_percent=10")
        elif mutation == "provenance":
            writer.execute("update quota_provenance set provenance='parsed'")
        elif mutation == "blob":
            writer.execute("update quota_observations set timestamps_blob=? where used_percent=15",
                           (zlib.compress(b'["2026-01-01T00:00:00+00:00"]'),))
        elif mutation == "gap":
            writer.execute("delete from dashboard_preparation_quota_changes")
        elif mutation == "epoch":
            writer.execute("drop trigger dashboard_preparation_quota_observations_update")
        else:
            writer.execute("update quota_observations set used_percent=20")
            uncommitted = token(writer)
            writer.rollback()
            assert not prefix_unchanged(writer, uncommitted, token(writer), end)
            return
        writer.commit()
    with open_ledger(path):
        pass  # Repair lost tracking gets a new epoch.
    with open_ledger(path, read_only=True) as reader:
        assert not prefix_unchanged(reader, previous, token(reader), end)


def test_journal_is_bounded_and_does_not_consume_fit_dirtiness(tmp_path):
    from codex_usage.allowance_window_tracking import ensure_tracking
    path = tmp_path / "ledger.sqlite3"
    add(path, [point(0)])
    with open_ledger(path) as writer:
        ensure_tracking(writer)
        previous = token(writer)
        writer.executemany("update quota_observations set used_percent=?", [(i % 100,) for i in range(4100)])
        assert writer.execute("select count(*) from dashboard_preparation_quota_changes").fetchone()[0] == 4096
        assert not prefix_unchanged(writer, previous, token(writer), -1e300)
        assert writer.execute("select count(*) from allowance_window_dirty where kind='quota'").fetchone()[0] == 1
        writer.rollback()
