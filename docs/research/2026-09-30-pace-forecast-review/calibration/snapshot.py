"""Export only quota metadata from one read-only SQLite transaction."""
import argparse
import json
import sqlite3
import time
import zlib
from datetime import UTC, datetime
from pathlib import Path


def normalize(row, *, source, read_id=None, timestamp=None):
    stamp = timestamp or row["timestamp"]
    return {
        "timestamp": stamp,
        "seconds": datetime.fromisoformat(stamp).timestamp(),
        "used": row["used_percent"],
        "reset": row["resets_at"],
        "credits": row["reset_credits"],
        "plan": row["plan"],
        "slot": row["slot"],
        "source": source,
        "read_id": read_id,
    }


def extract(ledger, *, since, limit_id, duration):
    started = time.perf_counter()
    queries = Path(__file__).parent
    with sqlite3.connect(ledger.resolve().as_uri() + "?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("pragma query_only=on")
        connection.execute("begin")
        revision = connection.execute(
            "select value from ledger_meta where key='ledger_revision'"
        ).fetchone()[0]
        reads = [dict(row) for row in connection.execute(
            "select read_id,timestamp,plan,diagnostics from quota_reads "
            "where timestamp >= ? order by read_id", (since,)
        )]
        parameters = (limit_id, duration, since)
        live = [normalize(row, source="live", read_id=row["read_id"])
                for row in connection.execute((queries / "live.sql").read_text(), parameters)]
        stored = connection.execute((queries / "observations.sql").read_text(), parameters).fetchall()
        points = []
        for row in stored:
            times = json.loads(zlib.decompress(row["timestamps_blob"])) if row["timestamps_blob"] else [row["timestamp"]]
            origins = sorted(json.loads(row["origins"]))
            source = ",".join(origins)
            for stamp in times:
                if stamp >= since:
                    points.append(normalize(row, source=source, timestamp=stamp))
        assert connection.total_changes == 0
        connection.rollback()
    return {
        "meta": {
            "ledger_revision": int(revision), "scope": {"limit_id": limit_id, "duration": duration},
            "since": since, "latest_read_at": reads[-1]["timestamp"] if reads else None,
            "extracted_at": datetime.now(UTC).isoformat(),
            "read_only": True, "sqlite_changes": 0,
            "elapsed_seconds": time.perf_counter() - started,
            "reads": len(reads), "live_points": len(live), "stored_rows": len(stored),
            "expanded_points": len(points),
        },
        "reads": reads, "live": live, "points": points,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--since", default="2026-09-01T00:00:00+00:00")
    parser.add_argument("--limit-id", default="codex")
    parser.add_argument("--duration", type=int, default=10080)
    args = parser.parse_args()
    payload = extract(args.ledger, since=args.since, limit_id=args.limit_id, duration=args.duration)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload))
    args.output.chmod(0o600)
    print(json.dumps(payload["meta"], indent=2))


if __name__ == "__main__":
    main()
