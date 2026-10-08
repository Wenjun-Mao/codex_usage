import json

from codex_usage.agent_paths import ledger_database_path
from codex_usage.ledger_schema import open_ledger
from codex_usage.parser import parse_session_generation, parse_session_append
from codex_usage.speed_recovery import run_speed_recovery_slice
from speed_test_support import write_source


def downgrade_timing(db):
    with open_ledger(db) as connection:
        connection.execute("delete from speed_recovery")
        connection.execute("delete from speed_cache_facts")
        connection.execute("delete from ledger_speed_facts")
        connection.execute("delete from ledger_speed_identities")
        connection.commit()


def test_bounded_fair_recovery_and_restart_without_language_insert(tmp_path, monkeypatch):
    from codex_usage.session_cache import refresh_cached_session_data
    from codex_usage.ledger_sync import synchronize_parser_workset
    for task in ("older", "recent", "archived"):
        write_source(tmp_path, task=task, count=10, directory="archived_sessions" if task == "archived" else "sessions")
    db = ledger_database_path(tmp_path)
    with open_ledger(db):
        pass
    refresh_cached_session_data([tmp_path / "sessions", tmp_path / "archived_sessions"], cache_database_path=db, max_workers=1)
    synchronize_parser_workset(db)
    downgrade_timing(db)
    monkeypatch.setattr("codex_usage.speed_recovery.SLICE_BYTES", 1200)
    with open_ledger(db) as connection:
        before = [tuple(r) for r in connection.execute("select * from ledger_usage_events order by event_id")]
        monetary_revision = connection.execute("select value from ledger_meta where key='ledger_revision'").fetchone()[0]
    for _ in range(3):
        result = run_speed_recovery_slice(db)
        assert result.sources == 1 and result.source_opens <= 4
        assert result.source_bytes <= 1200 + 640 * 1024 + 1
    with open_ledger(db) as connection:
        assert connection.execute("select count(*) from speed_recovery where served>0").fetchone()[0] == 3
        assert all(len(r[0]) < 12000 for r in connection.execute("select checkpoint_json from speed_recovery"))
    for _ in range(100):
        run_speed_recovery_slice(db)
        with open_ledger(db) as connection:
            if not connection.execute("select 1 from speed_recovery where status='pending'").fetchone():
                break
    with open_ledger(db) as connection:
        assert not connection.execute("select 1 from speed_recovery where status='pending'").fetchone()
        assert [tuple(r) for r in connection.execute("select * from ledger_usage_events order by event_id")] == before
        assert connection.execute("select value from ledger_meta where key='ledger_revision'").fetchone()[0] == monetary_revision
        assert connection.execute("select count(*) from ledger_speed_facts where reason='' ").fetchone()[0] == 30
    assert run_speed_recovery_slice(db).source_opens == 0


def test_recovery_resumes_known_large_payload_without_retaining_content(tmp_path):
    from codex_usage.session_parser_models import parser_state_to_json, parser_state_from_json
    from dataclasses import replace
    from speed_test_support import append_rows, response
    path = write_source(tmp_path, count=0)
    with path.open("a") as stream:
        stream.write(json.dumps({"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": "x" * 10000}}) + "\n")
    append_rows(path, response())
    chunk = parse_session_generation(path, max_bytes=1000, strict_byte_budget=True)
    records = list(chunk.records)
    for _ in range(30):
        value = parser_state_to_json(chunk.checkpoint.state)
        assert len(value) < 12000 and "x" * 100 not in value
        checkpoint = replace(chunk.checkpoint, state=parser_state_from_json(value, path))
        chunk = parse_session_append(path, checkpoint, stop_offset=path.stat().st_size,
                                     max_bytes=1000, strict_byte_budget=True)
        assert chunk.bytes_read <= 1000 + 4 * 64 * 1024 + 1
        records.extend(chunk.records)
        if chunk.checkpoint.byte_offset == path.stat().st_size:
            break
    assert len(records) == 1
    assert chunk.checkpoint.byte_offset == path.stat().st_size


def test_media_over_slice_budget_preserves_later_samples_and_accounting(tmp_path, monkeypatch):
    from codex_usage.session_cache import refresh_cached_session_data
    from codex_usage.ledger_sync import synchronize_parser_workset
    from codex_usage.speed_recovery import SLICE_BYTES
    from codex_usage.speed_parser import SpeedParser
    from speed_test_support import append_rows, response
    path = write_source(tmp_path, count=0)
    append_rows(path, [{"type": "response_item", "payload": {"type": "message", "role": "user",
        "content": [{"type": "input_image", "image_url": "data:image/png;base64," + "x" * (SLICE_BYTES + 100)}]}}])
    for index in range(5):
        append_rows(path, response(index))
    full = parse_session_generation(path)
    assert sum(not fact.reason for fact in full.speed_facts) == 5
    db = ledger_database_path(tmp_path)
    with open_ledger(db):
        pass
    with monkeypatch.context() as legacy:
        legacy.setattr(SpeedParser, "observe", lambda *args: None)
        refresh_cached_session_data([tmp_path / "sessions"], cache_database_path=db, max_workers=1)
    synchronize_parser_workset(db)
    downgrade_timing(db)
    with open_ledger(db) as connection:
        before = [tuple(r) for r in connection.execute("select * from ledger_usage_events order by event_id")]
        revision = connection.execute("select value from ledger_meta where key='ledger_revision'").fetchone()[0]
    first = run_speed_recovery_slice(db)
    assert first.source_bytes <= SLICE_BYTES + 640 * 1024 and first.source_opens <= 4
    with open_ledger(db) as connection:
        row = connection.execute("select status,checkpoint_json from speed_recovery").fetchone()
        assert row[0] == "pending" and len(row[1]) < 12000 and "x" * 100 not in row[1]
    second = run_speed_recovery_slice(db)
    assert second.source_bytes <= SLICE_BYTES + 640 * 1024 and second.source_opens <= 4
    with open_ledger(db) as connection:
        assert connection.execute("select status from speed_recovery").fetchone()[0] == "complete"
        assert connection.execute("select count(*) from ledger_speed_facts where reason='' ").fetchone()[0] == 5
        assert [tuple(r) for r in connection.execute("select * from ledger_usage_events order by event_id")] == before
        assert connection.execute("select value from ledger_meta where key='ledger_revision'").fetchone()[0] == revision


def test_shared_four_slot_budget_preserves_image_progress(monkeypatch):
    from codex_usage import capture_recovery
    from codex_usage.image_backfill import ImageBackfillResult
    calls = []
    def image(*args):
        calls.append("image")
        return ImageBackfillResult(True, "pending", 1, 1, 0, 0, 1)
    def speed(*args):
        calls.append("speed")
        return None
    monkeypatch.setattr(capture_recovery, "run_image_backfill_slice", image)
    monkeypatch.setattr(capture_recovery, "run_speed_recovery_slice", speed)
    capture_recovery.run_historical_recovery(None, None)
    assert calls == ["image", "speed", "image", "image"]


def test_inventory_and_unavailable_sources_are_bounded(tmp_path):
    from codex_usage.session_cache import refresh_cached_session_data
    from codex_usage.ledger_sync import synchronize_parser_workset
    from codex_usage.speed_recovery import speed_status
    paths = [write_source(tmp_path, task=f"task-{index}", count=1) for index in range(140)]
    db = ledger_database_path(tmp_path)
    with open_ledger(db):
        pass
    refresh_cached_session_data([tmp_path / "sessions"], cache_database_path=db, max_workers=1)
    synchronize_parser_workset(db)
    downgrade_timing(db)
    for path in paths:
        path.unlink()
    first = run_speed_recovery_slice(db)
    assert first.sources == 1 and first.source_opens <= 1
    with open_ledger(db) as connection:
        assert connection.execute("select count(*) from speed_recovery").fetchone()[0] == 128
        assert speed_status(connection)["pending"] == 139
    run_speed_recovery_slice(db)
    with open_ledger(db) as connection:
        assert connection.execute("select count(*) from speed_recovery").fetchone()[0] == 140
        assert speed_status(connection)["unmeasurable"] == 2
        assert speed_status(connection)["reasons"] == {"missing_source": 2}


def test_final_changed_source_guard_cannot_promote_facts(tmp_path, monkeypatch):
    from codex_usage.session_cache import refresh_cached_session_data
    from codex_usage.ledger_sync import synchronize_parser_workset
    from codex_usage import speed_recovery
    write_source(tmp_path)
    db = ledger_database_path(tmp_path)
    with open_ledger(db):
        pass
    refresh_cached_session_data([tmp_path / "sessions"], cache_database_path=db, max_workers=1)
    synchronize_parser_workset(db)
    downgrade_timing(db)
    original = speed_recovery.verify_generation
    calls = []
    def verify(*args):
        calls.append(1)
        if len(calls) == 3:
            raise ValueError("changed at promotion boundary")
        return original(*args)
    monkeypatch.setattr(speed_recovery, "verify_generation", verify)
    assert run_speed_recovery_slice(db).sources == 1
    with open_ledger(db) as connection:
        assert connection.execute("select count(*) from ledger_speed_facts").fetchone()[0] == 0
        assert connection.execute("select checkpoint_json from speed_recovery").fetchone()[0] == ""
