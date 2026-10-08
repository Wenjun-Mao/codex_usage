from dataclasses import replace
from datetime import UTC, datetime
import json
import sqlite3

import pytest

from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.ledger_schema import open_ledger
from codex_usage.ledger_sync import synchronize_parser_workset
from codex_usage.parser import parse_session_append, parse_session_generation
from codex_usage.session_parser_models import parser_state_from_json, parser_state_to_json
from codex_usage.speed_recovery import run_speed_recovery_slice
from codex_usage.speed_store import revision
from codex_usage.agent_rebuild import rebuild_stale_source_slice, stale_source_keys
from speed_test_support import AT, append_rows, response, write_source


@pytest.fixture(autouse=True)
def no_quota(monkeypatch):
    monkeypatch.setattr("codex_usage.agent_capture.capture_quota_read", lambda *a: None)


@pytest.mark.parametrize("boundary", range(1, 7))
def test_full_append_and_checkpoint_restart_match(tmp_path, boundary):
    path = write_source(tmp_path, count=1)
    full = parse_session_generation(path)
    lines = path.read_bytes().splitlines(keepends=True)
    stop = sum(map(len, lines[:boundary]))
    first = parse_session_generation(path, stop_offset=stop)
    state = parser_state_from_json(parser_state_to_json(first.checkpoint.state), path)
    second = parse_session_append(path, replace(first.checkpoint, state=state), stop_offset=path.stat().st_size)
    assert first.speed_facts + second.speed_facts == full.speed_facts
    assert first.records + second.records == full.records
    assert len(full.speed_facts) == 1 and not full.speed_facts[0].reason
    assert "SYNTHETIC SECRET" not in parser_state_to_json(second.checkpoint.state)


@pytest.mark.parametrize("late_kind", ["completion", "output"])
def test_late_tools_revoke_prior_sample_across_captures(tmp_path, late_kind):
    path = write_source(tmp_path)
    result = capture_once(tmp_path, request_kind="manual", max_workers=1)
    assert result.outcome == "success"
    db = ledger_database_path(tmp_path)
    with open_ledger(db) as connection:
        assert connection.execute("select count(*) from ledger_speed_facts where reason='' ").fetchone()[0] == 5
        before = revision(connection)
    at = AT.timestamp() * 1000
    payload = {"type": "item_completed", "turn_id": "turn-0", "started_at_ms": at + 500, "completed_at_ms": at + 1000, "item": {"type": "ToolCall", "id": "late"}}
    row = {"type": "event_msg", "timestamp": datetime.fromtimestamp((at + 150000) / 1000, UTC).isoformat(), "payload": payload}
    if late_kind == "output":
        row = {"type": "response_item", "timestamp": datetime.fromtimestamp((at + 1000) / 1000, UTC).isoformat(), "payload": {"type": "function_call_output", "output": "PRIVATE TOOL CONTENT"}}
    append_rows(path, [row])
    assert capture_once(tmp_path, request_kind="manual", max_workers=1).outcome == "success"
    with open_ledger(db) as connection:
        assert connection.execute("select reason from ledger_speed_facts where record_index=0").fetchone()[0] == "tool_execution_overlap"
        assert revision(connection) > before
        encoded = "".join(r[0] for r in connection.execute("select evidence_json from ledger_speed_facts"))
        assert "PRIVATE" not in encoded and "SYNTHETIC SECRET" not in encoded


@pytest.mark.parametrize("reverse", [False, True])
def test_duplicate_equivalence_and_conflicts_are_order_independent(tmp_path, reverse):
    for task, seconds in ([('a', 2), ('b', 4)] if reverse else [('a', 4), ('b', 2)]):
        write_source(tmp_path, task=task, seconds=seconds)
    assert capture_once(tmp_path, request_kind="manual", max_workers=1).outcome == "success"
    with open_ledger(ledger_database_path(tmp_path)) as connection:
        assert connection.execute("select count(*) from ledger_speed_identities where conflict=1").fetchone()[0] == 5
    write_source(tmp_path, task="a", seconds=2)
    write_source(tmp_path, task="b", seconds=2)
    assert capture_once(tmp_path, request_kind="manual", max_workers=1).outcome == "success"
    db = ledger_database_path(tmp_path)
    for key in stale_source_keys(db):
        assert rebuild_stale_source_slice(tmp_path, key, max_bytes=16 * 1024 * 1024).complete
    with open_ledger(ledger_database_path(tmp_path)) as connection:
        assert connection.execute("select count(*) from ledger_speed_identities where conflict=0").fetchone()[0] == 5


def test_additive_schema_five_ten_upgrade_keeps_usage_and_private_backup(tmp_path):
    write_source(tmp_path)
    capture_once(tmp_path, request_kind="manual", max_workers=1)
    db = ledger_database_path(tmp_path)
    with sqlite3.connect(db) as connection:
        usage = connection.execute("select * from ledger_usage_events order by event_id").fetchall()
        checkpoints = connection.execute("select * from parser_checkpoints").fetchall()
        for table in ("ledger_speed_identities", "ledger_speed_facts", "speed_recovery", "speed_report_cache", "speed_html_cache", "speed_cache_facts", "speed_cache_tools", "speed_cache_dirty"):
            connection.execute(f"drop table {table}")
        connection.execute("update ledger_meta set value='5' where key='schema_version'")
        connection.execute("update schema_meta set value='10' where key='schema_version'")
        connection.commit()
    with open_ledger(db) as connection:
        assert [tuple(r) for r in connection.execute("select * from ledger_usage_events order by event_id")] == usage
        assert [tuple(r) for r in connection.execute("select * from parser_checkpoints")] == checkpoints
        monetary_revision = connection.execute("select value from ledger_meta where key='ledger_revision'").fetchone()[0]
    backups = list(db.parent.glob("*.schema-5-backup-*"))
    assert backups and backups[0].stat().st_mode & 0o777 == 0o600
    assert run_speed_recovery_slice(db).changed
    with open_ledger(db) as connection:
        assert connection.execute("select value from ledger_meta where key='ledger_revision'").fetchone()[0] == monetary_revision
        assert [tuple(r) for r in connection.execute("select * from ledger_usage_events order by event_id")] == usage
        assert connection.execute("select count(*) from ledger_speed_facts where reason='' ").fetchone()[0] == 5
    assert synchronize_parser_workset(db)[1] is False


def test_missing_source_keeps_durable_samples(tmp_path):
    path = write_source(tmp_path)
    capture_once(tmp_path, request_kind="manual", max_workers=1)
    db = ledger_database_path(tmp_path)
    path.unlink()
    capture_once(tmp_path, request_kind="manual", max_workers=1)
    with open_ledger(db) as connection:
        assert connection.execute("select count(*) from ledger_speed_facts where reason='' ").fetchone()[0] == 5


def test_superseding_only_conflicting_nonwinner_restores_surviving_identity(tmp_path):
    write_source(tmp_path, task="a", seconds=2)
    write_source(tmp_path, task="b", seconds=4)
    capture_once(tmp_path, request_kind="manual", max_workers=1)
    db = ledger_database_path(tmp_path)
    with open_ledger(db) as connection:
        winner = connection.execute("select generation_id from ledger_speed_identities limit 1").fetchone()[0]
        loser = connection.execute("select generation_id from ledger_generations where status='trusted' and generation_id!=?", (winner,)).fetchone()[0]
        connection.execute("update ledger_generations set status='superseded' where generation_id=?", (loser,))
        from codex_usage.speed_store import synchronize_speed
        synchronize_speed(connection, usage_changed=True)
        assert connection.execute("select count(*) from ledger_speed_identities where conflict=0").fetchone()[0] == 5


@pytest.mark.parametrize("gap", ["invalid", "new_turn", "reversed", "reversed_context"])
def test_unsafe_pending_boundaries_cannot_be_accepted(tmp_path, gap):
    path = write_source(tmp_path, count=0)
    rows = response()
    if gap == "new_turn":
        rows.insert(-1, {"type": "turn_context", "timestamp": rows[-1]["timestamp"], "payload": {"turn_id": "new", "model": "gpt-6.1-sol"}})
    elif gap == "reversed":
        rows[-1]["timestamp"] = AT.isoformat()
    elif gap == "reversed_context":
        rows.insert(1, {"type": "turn_context", "timestamp": "2026-10-08T11:00:00+00:00", "payload": rows[0]["payload"]})
    append_rows(path, rows)
    if gap == "invalid":
        contents = path.read_text().splitlines()
        contents.insert(-1, "{invalid gap")
        path.write_text("\n".join(contents) + "\n")
    fact = parse_session_generation(path).speed_facts[0]
    assert fact.reason


def test_legacy_timing_checkpoint_starts_unsafe(tmp_path):
    path = write_source(tmp_path, count=1)
    lines = path.read_bytes().splitlines(keepends=True)
    first = parse_session_generation(path, stop_offset=sum(map(len, lines[:3])))
    value = json.loads(parser_state_to_json(first.checkpoint.state))
    value.pop("speed_state")
    checkpoint = replace(first.checkpoint, state=parser_state_from_json(json.dumps(value), path))
    appended = parse_session_append(path, checkpoint, stop_offset=path.stat().st_size)
    assert appended.speed_facts[0].reason == "incomplete_response_boundary"


def test_newer_source_header_does_not_invalidate_ordered_inherited_history(tmp_path):
    from datetime import timedelta
    path = write_source(tmp_path, count=0)
    append_rows(path, response(at=AT - timedelta(days=1)))
    assert not parse_session_generation(path).speed_facts[0].reason
