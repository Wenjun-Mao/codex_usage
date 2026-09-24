"""Ledger-only account-wide status and estimates, independent of report filters."""
import json
import math
import zlib
from bisect import bisect_right
from dataclasses import replace
from datetime import UTC, datetime

from codex_usage.allowance_estimation import estimate_window
from codex_usage.allowance_models import QuotaObservation
from codex_usage.allowance_windows import segment_windows


def allowance_highlights(windows):
    """Select the latest window without substituting older qualified history."""
    qualified = [w for w in windows if w["completed"] and w["estimate"]["confidence"] in {"High", "Medium"}]
    latest = windows[-1] if windows else None
    estimate = latest["estimate"] if latest else None
    headline = (latest if estimate and estimate["confidence"] in {"High", "Medium", "Low/provisional"}
                and isinstance(estimate["value"], (int, float))
                and math.isfinite(estimate["value"]) and estimate["value"] > 0 else None)
    return qualified, headline


def allowance_status(connection):
    read = connection.execute("select * from quota_reads order by read_id desc limit 1").fetchone()
    recovered = connection.execute("""select count(*) total,
        sum(r.status = 'complete' and r.size_bytes = s.size_bytes and r.mtime_ns = s.mtime_ns and r.source_device = s.source_device and r.source_inode = s.source_inode) complete,
        sum(r.status = 'unavailable' and r.size_bytes = s.size_bytes and r.mtime_ns = s.mtime_ns and r.source_device = s.source_device and r.source_inode = s.source_inode) unavailable
        from ledger_sources s left join quota_recovery r using(source_key)""").fetchone()
    observed_read = connection.execute("""
        select r.* from quota_reads r where exists (
            select 1 from quota_provenance p where p.source_key = 'read:' || r.read_id
            and p.provenance = 'live') order by r.read_id desc limit 1
    """).fetchone()
    buckets = []
    if observed_read:
        buckets = [dict(row) for row in connection.execute("""
            select o.timestamp, o.limit_id, o.slot, o.plan, o.used_percent,
                   o.duration_minutes, o.resets_at, o.reset_credits
            from quota_observations o join quota_provenance p using(observation_key)
            where p.source_key = ? and p.provenance = 'live'
            order by limit_id, duration_minutes
        """, (f"read:{observed_read['read_id']}",))]
    stamp = observed_read["timestamp"] if observed_read else ""
    age = max(0, (datetime.now(UTC) - datetime.fromisoformat(stamp)).total_seconds()) if stamp else None
    complete = int(recovered["complete"] or 0)
    unavailable = int(recovered["unavailable"] or 0)
    return {
        "plan": (read["plan"] or (observed_read["plan"] if observed_read else "")) if read else "", "active_buckets": buckets,
        "last_probe_at": read["timestamp"] if read else "", "last_observed_at": stamp, "probe_age_seconds": age,
        "probe_status": ("unavailable" if not buckets else "stale" if age > 3600 or read["read_id"] != observed_read["read_id"] else
                         "partial" if read["diagnostics"] else "fresh"),
        "diagnostics": read["diagnostics"] if read else "not_captured",
        "lifetime_tokens": read["lifetime_tokens"] if read else None,
        "recovery": {"total": recovered["total"], "complete": complete,
                     "unavailable": unavailable, "pending": max(0, recovered["total"] - complete - unavailable)},
    }


def build_allowance_report(connection, *, coverage_complete=True):
    from codex_usage.aggregation import value_records
    from codex_usage.ledger_queries import query_ledger_records

    status = allowance_status(connection)
    rows = connection.execute("select * from quota_observations order by timestamp").fetchall()
    points = []
    provenance = {}
    for row in rows:
        point = QuotaObservation(**{key: row[key] for key in QuotaObservation.__dataclass_fields__})
        times = json.loads(zlib.decompress(row["timestamps_blob"])) if row["timestamps_blob"] else [point.timestamp]
        for stamp in times:
            selected = replace(point, timestamp=stamp)
            points.append(selected)
            provenance.setdefault(selected, set()).add("Recovered" if row["timestamps_blob"] else "Captured")
    if not points:
        return {"status": status, "windows": [], "qualified": [], "headline": None}
    valued = sorted(value_records(query_ledger_records(connection)), key=lambda v: v.record.timestamp)
    times, costs, unpriced = [], [0.0], [0]
    for item in valued:
        times.append(item.record.timestamp.timestamp())
        costs.append(costs[-1] + item.summary.cost.total_usd)
        unpriced.append(unpriced[-1] + item.summary.cost.unpriced_tokens)
    windows = []
    for window in segment_windows(points):
        indices = [bisect_right(times, datetime.fromisoformat(p.timestamp).timestamp()) for p in window.points]
        cumulative = [costs[i] - costs[indices[0]] for i in indices]
        fully_priced = unpriced[indices[-1]] == unpriced[indices[0]]
        estimate = estimate_window(window, cumulative,
            fully_priced=fully_priced,
            coverage_complete=coverage_complete)
        first = window.points[0]
        windows.append({
            "limit_id": first.limit_id, "plan": first.plan, "duration_minutes": first.duration_minutes,
            "start": first.timestamp, "end": window.points[-1].timestamp,
            "completed": window.completed, "closure": window.closure,
            "corrections": window.corrections, "estimate": estimate.to_dict(),
            "fully_priced": fully_priced, "coverage_complete": coverage_complete,
            "points": [dict(p.to_dict(), provenance=", ".join(sorted(provenance[p]))) for p in window.points],
        })
    windows.sort(key=lambda w: w["end"])
    qualified, headline = allowance_highlights(windows)
    return {"status": status, "windows": windows, "qualified": qualified, "headline": headline}
