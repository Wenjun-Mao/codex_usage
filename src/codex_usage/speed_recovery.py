"""Bounded, resumable generation replay on the collector's existing I/O lane."""
from dataclasses import dataclass
import json
from pathlib import Path

from codex_usage.image_backfill import _checkpoint_from_dict, _checkpoint_to_dict
from codex_usage.ledger_schema import open_ledger
from codex_usage.parser import parse_session_append, parse_session_generation
from codex_usage.session_parser_safety import digest_range
from codex_usage.session_row_relevance import CHECKPOINT_DIGEST_BYTES
from codex_usage.speed_store import cache_speed, synchronize_speed, touch

SLICE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class SpeedRecoveryResult:
    changed: bool = False
    source_opens: int = 0
    source_bytes: int = 0
    sources: int = 0

    def plus(self, other):
        return SpeedRecoveryResult(self.changed or other.changed, self.source_opens + other.source_opens,
            self.source_bytes + other.source_bytes, self.sources + other.sources)


def inventory(connection) -> bool:
    changed = False
    served = connection.execute("select coalesce(max(served), 0) from speed_recovery").fetchone()[0]
    phase = connection.execute("select value from ledger_meta where key='speed_inventory_phase'").fetchone()
    phase = int(phase[0]) if phase else 0
    ordering = "latest_us desc, g.generation_id desc" if phase % 2 == 0 else "g.generation_id"
    for row in connection.execute(f"""select g.generation_id, g.captured_size, g.record_count,
        (select coalesce(max(timestamp_us), 0) from ledger_usage_events e where e.generation_id=g.generation_id) latest_us,
        s.source_key from ledger_generations g join ledger_sources s using(source_id)
        left join speed_recovery r using(generation_id)
        where g.status='trusted' and r.generation_id is null order by {ordering} limit 128""").fetchall():
        count = connection.execute("select count(*) from speed_cache_facts where file_key=?", (row["source_key"],)).fetchone()[0]
        status = "complete" if count >= row["record_count"] else "pending"
        reason = ""
        if status == "complete" and not connection.execute("select 1 from ledger_speed_facts where generation_id=? and reason='' limit 1", (row["generation_id"],)).fetchone():
            status, reason = "unmeasurable", "no_usable_timing"
        connection.execute("insert into speed_recovery(generation_id, target_offset, status, reason, served, latest_us) values (?, ?, ?, ?, ?, ?)",
                           (row["generation_id"], row["captured_size"], status, reason, served, row["latest_us"]))
        changed = True
    if changed:
        connection.execute("insert or replace into ledger_meta values ('speed_inventory_phase', ?)", (str(phase + 1),))
        touch(connection)
    return changed


def run_speed_recovery_slice(ledger_path: Path) -> SpeedRecoveryResult:
    with open_ledger(ledger_path) as connection:
        connection.execute("begin immediate")
        changed = inventory(connection)
        row = connection.execute("""select r.*, g.captured_size, g.head_sha256, g.boundary_sha256,
            s.source_key, s.path, s.source_inode, s.is_missing
            from speed_recovery r join ledger_generations g using(generation_id)
            join ledger_sources s using(source_id)
            where g.status='trusted' and r.status='pending'
            order by r.served, r.latest_us desc, g.generation_id desc limit 1""").fetchone()
        connection.commit()
    if row is None:
        return SpeedRecoveryResult(changed)
    path = Path(row["path"])
    parsed = None
    reason = ""
    source_bytes = 0
    source_opens = 0
    try:
        if row["is_missing"]:
            raise FileNotFoundError
        source_opens += 1
        source_bytes += verify_generation(path, row)
        stop = row["target_offset"]
        source_opens += 1
        if row["checkpoint_json"]:
            checkpoint = _checkpoint_from_dict(json.loads(row["checkpoint_json"]), path)
            parsed = parse_session_append(path, checkpoint, stop_offset=stop, max_bytes=SLICE_BYTES,
                                          strict_byte_budget=True)
        else:
            parsed = parse_session_generation(path, stop_offset=stop, max_bytes=SLICE_BYTES,
                                              strict_byte_budget=True)
        source_bytes += parsed.bytes_read
        source_opens += 1
        source_bytes += verify_generation(path, row)
    except FileNotFoundError:
        reason = "missing_source"
    except (OSError, ValueError) as error:
        source_bytes += getattr(error, "bytes_read", 0)
        reason = "unverifiable_or_oversize_source"
    with open_ledger(ledger_path) as connection:
        connection.execute("begin immediate")
        current = connection.execute("select * from ledger_generations where generation_id=? and status='trusted'",
                                     (row["generation_id"],)).fetchone()
        if current is None or current["captured_size"] != row["captured_size"] or current["boundary_sha256"] != row["boundary_sha256"]:
            return SpeedRecoveryResult(changed, source_opens, source_bytes, 1)
        if parsed is not None and not reason:
            try:
                source_opens += 1
                source_bytes += verify_generation(path, row)
            except (OSError, ValueError):
                # No facts are promoted if the final source guard changed.
                return SpeedRecoveryResult(changed, source_opens, source_bytes, 1)
            cache_speed(connection, row["source_key"], parsed)
            synchronize_speed(connection)
            complete = parsed.checkpoint.byte_offset >= row["target_offset"]
            status = "complete" if complete else "pending"
            checkpoint_json = "" if complete else json.dumps(_checkpoint_to_dict(parsed.checkpoint))
            if complete and not connection.execute("select 1 from ledger_speed_facts where generation_id=? and reason='' limit 1",
                                                   (row["generation_id"],)).fetchone():
                status, reason = "unmeasurable", "no_usable_timing"
        else:
            status, checkpoint_json = "unmeasurable", ""
        order = connection.execute("select coalesce(max(served), 0)+1 from speed_recovery").fetchone()[0]
        connection.execute("update speed_recovery set status=?, reason=?, checkpoint_json=?, served=? where generation_id=?",
                           (status, reason, checkpoint_json, order, row["generation_id"]))
        touch(connection)
        connection.commit()
    return SpeedRecoveryResult(True, source_opens, source_bytes, 1)


def verify_generation(path, row) -> int:
    with path.open("rb") as handle:
        import os
        opened = os.fstat(handle.fileno())
        size = row["captured_size"]
        if opened.st_size < size or str(opened.st_ino) != row["source_inode"]:
            raise ValueError("generation identity changed")
        head, head_bytes = digest_range(handle, 0, min(CHECKPOINT_DIGEST_BYTES, size))
        boundary, boundary_bytes = digest_range(handle, max(0, size - CHECKPOINT_DIGEST_BYTES), size)
        current = path.stat()
        if head != row["head_sha256"] or boundary != row["boundary_sha256"] or (current.st_dev, current.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("generation guards changed")
        return head_bytes + boundary_bytes


def speed_status(connection) -> dict:
    from codex_usage.speed_store import revision
    result = {"revision": revision(connection), "metric_version": 1,
              "complete": 0, "pending": 0, "unmeasurable": 0}
    for row in connection.execute("""select r.status, count(*) n from speed_recovery r
        join ledger_generations g using(generation_id) where g.status='trusted' group by r.status"""):
        result[row["status"]] = row["n"]
    result["pending"] += connection.execute("""select count(*) from ledger_generations g
        left join speed_recovery r using(generation_id) where g.status='trusted' and r.generation_id is null""").fetchone()[0]
    result["reasons"] = {row[0]: row[1] for row in connection.execute("""select r.reason, count(*) from speed_recovery r
        join ledger_generations g using(generation_id) where g.status='trusted' and r.reason!='' group by r.reason""")}
    return result
