"""Resumable endpoint recovery of registered sources, on the capture I/O lane."""
import json
import os
from pathlib import Path

from codex_usage.allowance_models import rollout_observations
from codex_usage.allowance_store import store_observations

END_BYTES = 64 * 1024
RECOVERY_BUDGET = 8 * 1024 * 1024


def bounded_observations(path: Path, size: int, *, expected=None):
    points = []
    consumed = 0
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        if before.st_size != size or (expected is not None and expected != (
            str(before.st_dev), str(before.st_ino), before.st_mtime_ns
        )):
            raise OSError("source_changed")
        ranges = [(0, size)] if size <= 2 * END_BYTES else [(0, END_BYTES), (size - END_BYTES, END_BYTES)]
        for offset, length in ranges:
            stream.seek(offset)
            data = stream.read(length)
            consumed += len(data)
            # Boundary rows are deliberately discarded: no extra read outside
            # the budget and no attempt to interpret a suffix as a full event.
            if offset:
                data = data.partition(b"\n")[2]
            if offset + length < size:
                data = data.rpartition(b"\n")[0]
            for line in data.splitlines():
                if b'"rate_limits"' not in line:
                    continue
                try:
                    points.extend(rollout_observations(json.loads(line)))
                except (ValueError, RecursionError):
                    continue
        after = path.stat()
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
        ):
            raise OSError("source_changed")
    return points, consumed


def recover_allowance(connection, *, budget=RECOVERY_BUDGET):
    consumed = 0
    rows = connection.execute("""
        select s.* from ledger_sources s left join quota_recovery r using(source_key)
        where r.source_key is null or r.size_bytes != s.size_bytes or r.mtime_ns != s.mtime_ns
        order by s.mtime_ns desc, s.source_key
    """).fetchall()
    for row in rows:
        required = min(row["size_bytes"], 2 * END_BYTES)
        if required > budget - consumed:
            break
        status = "complete"
        points = []
        read_bytes = required
        try:
            points, read_bytes = bounded_observations(Path(row["path"]), row["size_bytes"],
                expected=(row["source_device"], row["source_inode"], row["mtime_ns"]))
        except OSError:
            status = "unavailable"
        consumed += read_bytes
        store_observations(connection, points, source_key=row["source_key"], provenance="recovered")
        connection.execute("insert or replace into quota_recovery values (?,?,?,?,?,?)", (
            row["source_key"], row["size_bytes"], row["mtime_ns"], status, read_bytes, len(points),
        ))
    return consumed
