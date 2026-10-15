"""Source-key retirement cannot erase a truncated or changed captured prefix."""
import hashlib

import pytest

from codex_usage.ledger_schema import open_ledger
from codex_usage.ledger_source_relocations import retire_relocated_generations
from codex_usage.session_row_relevance import CHECKPOINT_DIGEST_BYTES


def insert(connection, table, **values):
    keys = tuple(values)
    return connection.execute(f"insert into {table} ({','.join(keys)}) values ({','.join('?' for _ in keys)})",
                              tuple(values[key] for key in keys)).lastrowid


@pytest.mark.parametrize("change,retired", [("same", True), ("grown", True), ("truncated", False), ("tail", False)])
@pytest.mark.parametrize("old_size", [1000, 200000])
def test_retire_only_when_replacement_covers_old_checkpoint_guards(tmp_path, change, retired, old_size):
    path = tmp_path / "source.jsonl"
    original = (b"a"*CHECKPOINT_DIGEST_BYTES + b"b"*150_000)[:old_size]
    current = {"same": original, "grown": original+b"c"*50_000,
               "truncated": original[:old_size//2], "tail": original[:-1]+b"x"}[change]
    path.write_bytes(current)
    stat = path.stat()
    def digest(data):
        return hashlib.sha256(data).hexdigest()
    with open_ledger(tmp_path / "ledger.sqlite3") as connection:
        for index, (key, body) in enumerate((("old-key", original), ("new-key", current))):
            source = insert(connection, "ledger_sources", source_key=key, path=str(path), session_dir=str(tmp_path),
                storage_state="active", source_device=str(stat.st_dev), source_inode=str(stat.st_ino),
                size_bytes=len(body), mtime_ns=stat.st_mtime_ns, last_seen_at="synthetic", is_missing=1-index,
                is_stale=0, stale_reason="", error="")
            insert(connection, "ledger_generations", source_id=source, generation_key="occurrence:1",
                generation_number=1, status="trusted", captured_size=len(body), captured_mtime_ns=stat.st_mtime_ns,
                head_sha256=digest(body[:CHECKPOINT_DIGEST_BYTES]), boundary_sha256=digest(body[-CHECKPOINT_DIGEST_BYTES:]),
                record_count=0, captured_at="synthetic")
        insert(connection, "files", file_key="new-key", path=str(path), session_dir=str(tmp_path),
            storage_state="active", size_bytes=len(current), mtime_ns=stat.st_mtime_ns,
            parsed_at="synthetic", last_seen_at="synthetic", is_missing=0, session_id="synthetic", error="")
        insert(connection, "parser_checkpoints", file_key="new-key", byte_offset=len(current),
            next_record_index=0, next_candidate_index=0, source_device=str(stat.st_dev), source_inode=str(stat.st_ino),
            head_sha256=digest(current[:CHECKPOINT_DIGEST_BYTES]), boundary_sha256=digest(current[-CHECKPOINT_DIGEST_BYTES:]),
            session_id="synthetic", state_json="{}")
        assert retire_relocated_generations(connection) is retired
        statuses = [row[0] for row in connection.execute("select status from ledger_generations order by generation_id")]
        assert statuses == ["superseded" if retired else "trusted", "trusted"]
        assert connection.execute("select count(*) from ledger_generations").fetchone()[0] == 2
