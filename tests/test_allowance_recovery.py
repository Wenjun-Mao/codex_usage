import json
import sqlite3
import zlib

from codex_usage.allowance_models import rollout_observations
from codex_usage.allowance_recovery import END_BYTES, bounded_observations, recover_allowance
from codex_usage.allowance_store import store_observations
from codex_usage.ledger_schema import open_ledger


def row(second=0, used=31):
    return {"type": "event_msg", "timestamp": f"2026-09-21T00:00:{second:02d}Z", "payload": {
        "type": "token_count", "rate_limits": {"plan_type": "pro", "primary": {
            "used_percent": used, "window_minutes": 10080, "resets_at": 2000000000}}, "prompt": "PRIVATE"}}


def write(path, rows):
    path.write_bytes(b"".join(json.dumps(r).encode() + b"\n" for r in rows))


def register(connection, path):
    stat = path.stat()
    connection.execute("""insert or replace into ledger_sources values(
        ?,?,?,?,?,?,?,?,?,?,null,0,0,'','')""", (
        1, "source", str(path), str(path.parent), "active", str(stat.st_dev), str(stat.st_ino),
        stat.st_size, stat.st_mtime_ns, "2026-09-21T00:00:00Z"))


def test_endpoint_budget_and_discarded_partial_rows(tmp_path):
    path = tmp_path / "source.jsonl"
    head = json.dumps(row()).encode() + b"\n"
    tail = json.dumps(row(1)).encode() + b"\n"
    path.write_bytes(head + b'x' * (END_BYTES * 3) + b"\n" + tail)
    points, consumed = bounded_observations(path, path.stat().st_size)
    assert consumed == 2 * END_BYTES
    assert [p.used_percent for p in points] == [31, 31]


def test_recovery_resume_change_compression_and_no_content(tmp_path):
    path = tmp_path / "source.jsonl"
    write(path, [row(i) for i in range(40)])
    ledger = tmp_path / "ledger.sqlite3"
    with open_ledger(ledger) as connection:
        register(connection, path)
        assert recover_allowance(connection, budget=10) == 0
        assert recover_allowance(connection) == path.stat().st_size
        assert recover_allowance(connection) == 0
        saved = connection.execute("select * from quota_observations").fetchall()
        assert len(saved) == 1 and saved[0]["sample_count"] == 40
        assert len(json.loads(zlib.decompress(saved[0]["timestamps_blob"]))) == 40
        assert "PRIVATE" not in str(saved[0][:])
        write(path, [row(i) for i in range(41)])
        register(connection, path)
        recover_allowance(connection)
        assert connection.execute("select sample_count from quota_observations").fetchone()[0] == 41


def test_dedup_preserves_all_source_provenance(tmp_path):
    with open_ledger(tmp_path / "ledger") as connection:
        points = rollout_observations(row())
        for source in ("one", "two", "one"):
            store_observations(connection, points, source_key=source, provenance="recovered")
        assert connection.execute("select count(*) from quota_observations").fetchone()[0] == 1
        assert connection.execute("select count(*) from quota_provenance").fetchone()[0] == 2


def test_v2_ledger_migration_preserves_data_and_backup(tmp_path):
    ledger = tmp_path / "ledger"
    with open_ledger(ledger) as connection:
        for table in ("quota_provenance", "quota_observations", "quota_recovery", "quota_reads"):
            connection.execute(f"drop table {table}")
        connection.execute("update ledger_meta set value='2' where key='schema_version'")
        connection.execute("insert into ledger_models(model_key) values ('sentinel')")
        connection.commit()
    with open_ledger(ledger) as connection:
        assert connection.execute("select model_key from ledger_models").fetchone()[0] == "sentinel"
        assert connection.execute("select count(*) from quota_reads").fetchone()[0] == 0
    backups = list(tmp_path.glob("ledger.schema-2-backup-*"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("select value from ledger_meta where key='schema_version'").fetchone()[0] == "2"


def test_recovery_orders_newest_first_and_hard_caps_eight_mib(tmp_path):
    from codex_usage.allowance_recovery import RECOVERY_BUDGET
    with open_ledger(tmp_path / "ledger") as connection:
        for index in range(66):
            path = tmp_path / f"{index}.jsonl"
            path.write_bytes(b"\n" * (END_BYTES * 2 + 1))
            import os
            os.utime(path, ns=(index + 1, index + 1))
            stat = path.stat()
            connection.execute("""insert into ledger_sources values(
                ?,?,?,?,?,?,?,?,?,?,null,0,0,'','')""", (
                index + 1, f"source-{index}", str(path), str(tmp_path), "active",
                str(stat.st_dev), str(stat.st_ino), stat.st_size, index + 1, "2026-09-21T00:00:00Z"))
        assert recover_allowance(connection) == RECOVERY_BUDGET
        assert connection.execute("select count(*) from quota_recovery").fetchone()[0] == 64
        assert connection.execute("select 1 from quota_recovery where source_key='source-0'").fetchone() is None
        assert recover_allowance(connection) == 4 * END_BYTES


def test_boundary_fragment_that_looks_like_json_is_discarded(tmp_path):
    path = tmp_path / "source"
    encoded = json.dumps(row()).encode() + b"\n"
    # Tail starts in the middle of a larger row. A valid-looking JSON suffix
    # cannot be interpreted as an event by the endpoint sampler.
    path.write_bytes(b"x" * (3 * END_BYTES - len(encoded)) + encoded)
    points, _ = bounded_observations(path, path.stat().st_size)
    assert points == []


def test_missing_source_is_durable_unavailable(tmp_path):
    path = tmp_path / "source"
    write(path, [row()])
    with open_ledger(tmp_path / "ledger") as connection:
        register(connection, path)
        path.unlink()
        recover_allowance(connection)
        assert connection.execute("select status from quota_recovery").fetchone()[0] == "unavailable"
        assert recover_allowance(connection) == 0


def test_parser_cache_upgrade_preserves_checkpoint_and_private_backup(tmp_path):
    from codex_usage.session_cache_schema import _ensure_schema
    path = tmp_path / "cache"
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_schema(connection)
        connection.execute("drop table quota_cache")
        connection.execute("update schema_meta set value='9' where key='schema_version'")
        connection.execute("update schema_meta set value='7' where key='parser_version'")
        connection.execute("insert into parser_checkpoints values ('sentinel',42,3,0,'1','2','head','tail','task','{}')")
        connection.commit()
        assert not _ensure_schema(connection).reset
        assert connection.execute("select byte_offset from parser_checkpoints").fetchone()[0] == 42
    backups = list(tmp_path.glob("cache.parser-9-backup-*"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("select value from schema_meta where key='schema_version'").fetchone()[0] == "9"


def test_source_replacement_rejected_before_read(tmp_path):
    import pytest
    path = tmp_path / "source"
    write(path, [row()])
    with pytest.raises(OSError, match="source_changed"):
        bounded_observations(path, path.stat().st_size, expected=("wrong", "identity", 0))


def test_future_parser_collects_quota_without_token_info_and_in_file_interior(tmp_path):
    from codex_usage.parser import parse_session_generation
    path = tmp_path / "source.jsonl"
    padding = {"type": "response_item", "payload": {"type": "message", "content": "PRIVATE" * 15000}}
    write(path, [padding, row(), padding])
    generation = parse_session_generation(path)
    assert len(generation.quota_observations) == 1
    assert generation.quota_observations[0].used_percent == 31
    assert generation.records == ()
    assert "PRIVATE" not in str(generation.quota_observations)
    recovered, _ = bounded_observations(path, path.stat().st_size)
    assert recovered == []


def test_complete_unterminated_final_row_is_recovered(tmp_path):
    path = tmp_path / "source"
    path.write_text(json.dumps(row()))
    points, consumed = bounded_observations(path, path.stat().st_size)
    assert len(points) == 1 and consumed == path.stat().st_size
    path.write_text(json.dumps(row())[:-4])
    assert bounded_observations(path, path.stat().st_size)[0] == []
