"""Fact-level medians, offset-aware calendars and revision-keyed ledger-only cache."""
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
import hashlib
import json
from statistics import median, quantiles

from codex_usage.aggregation import filter_records_by_project_keys
from codex_usage.ledger_queries import _row_to_usage_record, query_ledger_transitions
from codex_usage.project_transitions import apply_project_transitions
from codex_usage.speed_models import METRIC_VERSION, MIN_OUTPUT_TOKENS
from codex_usage.speed_store import revision


def describe(samples: list[dict]) -> dict:
    n = len(samples)
    result = {"n": n, "tasks": len({s["task"] for s in samples}),
              "sources": len({s["source"] for s in samples}), "small": 5 <= n < 20,
              "median": None, "p25": None, "p75": None}
    if n >= 5:
        values = [s["rate"] for s in samples]
        p25, _, p75 = quantiles(values, n=4, method="inclusive")
        result.update(median=median(values), p25=p25, p75=p75)
    return result


def cache_key(connection, report_range, project_keys, timezone, auto_transitions) -> str:
    from codex_usage.ledger_schema import ledger_revision
    identity = [revision(connection), ledger_revision(connection), METRIC_VERSION,
                report_range.cache_identity, sorted(project_keys), str(timezone), auto_transitions]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def speed_aggregates(connection, report_range, project_keys, timezone, *, auto_transitions=True) -> tuple[dict, bool]:
    key = cache_key(connection, report_range, project_keys, timezone, auto_transitions)
    cached = connection.execute("select report_json from speed_report_cache where cache_key=?", (key,)).fetchone()
    if cached:
        return json.loads(cached[0]), True
    clauses = ["g.status='trusted'"]
    args = []
    for bound, sign in ((report_range.bounds.start_us, ">="), (report_range.bounds.end_us, "<")):
        if bound is not None:
            clauses.append(f"f.timestamp_us {sign} ?")
            args.append(bound)
    rows = connection.execute(f"""select e.*, m.model_key, p.project_key, p.label project_label,
        c.project_aliases_json, c.cwd, c.repository_url, c.git_branch, c.effort,
        c.collaboration_mode, s.path file_path, s.source_id,
        f.evidence_json, f.reason, coalesce(i.conflict, 0) conflict,
        i.generation_id winner_generation, i.record_index winner_index
        from ledger_speed_facts f join ledger_generations g using(generation_id)
        join ledger_sources s using(source_id)
        join ledger_usage_events e on e.generation_id=f.generation_id and e.source_record_index=f.record_index
        join ledger_models m on m.model_id=e.model_id
        join ledger_contexts c on c.context_id=e.context_id
        join ledger_projects p on p.project_id=c.project_id
        left join ledger_speed_identities i on i.response_id=f.response_id
        where {' and '.join(clauses)} order by f.timestamp_us, f.generation_id, f.record_index""", args).fetchall()
    records = [_row_to_usage_record(row) for row in rows]
    # Normalized events already follow the parser's verified ownership rebuild;
    # temporal transitions must still be applied before any project filter.
    if auto_transitions:
        records = apply_project_transitions(records, query_ledger_transitions(connection))
    selected = set(project_keys)
    groups, daily, hourly = defaultdict(list), defaultdict(list), defaultdict(list)
    reasons = Counter()
    for row, record in zip(rows, records):
        if selected and not filter_records_by_project_keys([record], project_keys):
            continue
        fact = json.loads(row["evidence_json"])
        reason = "conflicting_response_identity" if row["conflict"] else row["reason"]
        if not reason and (row["generation_id"] != row["winner_generation"] or row["source_record_index"] != row["winner_index"]):
            reason = "equivalent_duplicate"
        if not reason and fact["usage"][3] < MIN_OUTPUT_TOKENS:
            reason = "short_response"
        if reason:
            reasons[reason] += 1
            continue
        sample = {"rate": fact["usage"][3] * 1000 / (fact["end_ms"] - fact["start_ms"]),
                  "task": record.session_id, "source": row["source_id"]}
        local = record.timestamp.astimezone(timezone)
        day = local.date().isoformat()
        hour = local.replace(minute=0, second=0, microsecond=0).isoformat()
        groups[record.model].append(sample)
        daily[(record.model, day)].append(sample)
        hourly[(record.model, hour)].append(sample)
    result = {
        "summaries": {model: describe(samples) for model, samples in sorted(groups.items())},
        "daily": [{"model": m, "bucket": b, **describe(s)} for (m, b), s in sorted(daily.items())],
        "hourly": [{"model": m, "bucket": b, **describe(s)} for (m, b), s in sorted(hourly.items())],
        "reasons": dict(sorted(reasons.items())), "cache_key": key,
    }
    return result, False


def store_aggregates(connection, aggregates):
    connection.execute("insert or replace into speed_report_cache values (?, ?)",
                       (aggregates["cache_key"], json.dumps(aggregates, separators=(",", ":"))))


def chart_navigation(connection, report_range, project_keys, timezone, now, granularity=None, window_start=None, window_scope=None):
    if granularity not in {None, "daily", "hourly"}:
        raise ValueError("speed granularity must be daily or hourly")
    granularity = granularity or ("hourly" if report_range.kind in {"today", "yesterday"} else "daily")
    start = report_range.start_date
    end = report_range.end_date or now.astimezone(timezone).date()
    if start is None:
        earliest = connection.execute("select min(timestamp_us) from ledger_usage_events").fetchone()[0]
        start = datetime.fromtimestamp(earliest / 1_000_000, UTC).astimezone(timezone).date() if earliest else end
    scope = hashlib.sha256(json.dumps([report_range.cache_identity, sorted(project_keys), str(timezone)]).encode()).hexdigest()
    if window_scope is not None and (not isinstance(window_scope, str) or len(window_scope) != 64 or any(c not in "0123456789abcdef" for c in window_scope)):
        raise ValueError("invalid speed window scope")
    latest_start = max(start, end - timedelta(days=6))
    chosen = date.fromisoformat(window_start) if window_start else latest_start
    if window_scope and window_scope != scope:
        # Saved chart state can cross a rolling range's local-midnight boundary.
        chosen = min(end, max(start, chosen))
    if not start <= chosen <= end:
        raise ValueError("speed window is outside the selected range")
    window_end = min(chosen + timedelta(days=6), end)
    return {"scope": scope, "granularity": granularity, "min_date": start.isoformat(),
            "max_date": end.isoformat(), "window_start": chosen.isoformat(), "window_end": window_end.isoformat(),
            "previous": max(start, chosen - timedelta(days=7)).isoformat() if chosen > start else None,
            "next": min(latest_start, chosen + timedelta(days=7)).isoformat() if window_end < end else None}


def calendar_buckets(navigation, timezone):
    start = date.fromisoformat(navigation["window_start"] if navigation["granularity"] == "hourly" else navigation["min_date"])
    end = date.fromisoformat(navigation["window_end"] if navigation["granularity"] == "hourly" else navigation["max_date"])
    if navigation["granularity"] == "daily":
        return [(start + timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]
    first = datetime.combine(start, datetime.min.time(), timezone).astimezone(UTC)
    stop = datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone).astimezone(UTC)
    result = []
    while first < stop:
        result.append(first.astimezone(timezone).isoformat())
        first += timedelta(hours=1)
    return result
