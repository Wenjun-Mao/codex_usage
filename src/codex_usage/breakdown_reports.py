"""Snapshot-pinned partitioned breakdown cache over the existing valued report."""
import hashlib
import json
from datetime import UTC, datetime
from time import monotonic
from bisect import bisect_right
from itertools import chain

from codex_usage.aggregation import (
    filter_records_by_project_keys, resolve_report_range,
    resolve_timezone, value_records,
)
from codex_usage.agent_paths import ledger_database_path
from codex_usage.allowance_index import indexed_allowance_report
from codex_usage.allowance_queries import allowance_status
from codex_usage.breakdown_aggregation import aggregate
from codex_usage.breakdown_evidence import prepare_evidence, weekly_anchors
from codex_usage.breakdown_intervals import BreakdownInterval
from codex_usage.breakdown_balances import balance_partitions
from codex_usage.breakdown_commands import BreakdownScopeExpired, issued_action, receipt, prune_receipts, RECEIPT_PREFIX
from codex_usage.ledger_queries import query_ledger_records, query_ledger_status, query_ledger_transitions
from codex_usage.ledger_schema import ledger_revision, open_ledger
from codex_usage.ledger_usage_ranges import subtract_bounds
from codex_usage.parser import finalize_session_records
from codex_usage.project_transitions import apply_project_transitions

BREAKDOWN_REVISION = 3


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def load(connection, key):
    row = connection.execute("select html from rendered_reports where cache_key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else None


def store(path, revision, payloads):
    from codex_usage.agent_reports import PRICING_REVISION
    with open_ledger(path) as writer:
        writer.execute("begin immediate")
        if ledger_revision(writer) != revision:
            return
        writer.executemany("insert or replace into rendered_reports values (?,?,?,?,?)",
            [(k, revision, PRICING_REVISION, datetime.now(UTC).isoformat(), json.dumps(v))
             for k, v in payloads.items()])
        prune_receipts(writer)
        writer.commit()


def prepare(connection, path, report_range, keys, timezone, status, kwargs, sink):
    from codex_usage.agent_reports import PRICING_REVISION
    report = sink.get("allowance") or indexed_allowance_report(connection, path,
        revision=status.revision, pricing_revision=PRICING_REVISION,
        coverage_complete=status.coverage.complete)
    report["status"] = allowance_status(connection, now=kwargs["now"])
    evidence = prepare_evidence(connection, report, kwargs["now"])
    extent = connection.execute("""select min(e.timestamp_us), max(e.timestamp_us)
        from ledger_usage_events e join ledger_generations g using(generation_id)
        where g.status='trusted'""").fetchone() if report_range.bounds.start_us is None or report_range.bounds.end_us is None else ()
    # All-time bounds belong to captured account context, not a project subset.
    account_times = [datetime.fromisoformat(p["timestamp"]).timestamp() for p in evidence["points"]]
    account_times.extend(datetime.fromisoformat(p["timestamp"]).timestamp() for p in evidence["balances"])
    captured_times = list(account_times)
    captured_times.extend(v / 1e6 for v in extent if v is not None)
    cycle = evidence["cycle"]
    metadata = {"evidence": evidence, "ranges": {}, "complete": status.coverage.complete}
    partitions = {}
    transitions = query_ledger_transitions(connection) if kwargs.get("auto_transitions", True) else []
    def valued_query(**query):
        records = finalize_session_records([query_ledger_records(connection, **query)])
        if transitions:
            records = apply_project_transitions(records, transitions)
        return value_records(filter_records_by_project_keys(records, keys))
    # Reuse calendar valuation and seek only the missing observed-window union.
    # Today must not decode/value years before the first weekly observation.
    selected = sink["valued"] if "valued" in sink else valued_query(bounds=report_range.bounds)
    scopes = {"selected": None, **evidence["windows"]}
    if cycle:
        scopes["cycle"] = cycle
    required = [BreakdownInterval(datetime.fromisoformat(window["start"]).timestamp(),
        datetime.fromisoformat(window["end"]).timestamp(), causal=True).sql_bounds
        for window in scopes.values() if window]
    missing = subtract_bounds(required, report_range.bounds)
    history = sorted(chain(selected, valued_query(bounds_union=missing) if missing else ()),
        key=lambda item: item.record.timestamp)
    times = [item.record.timestamp.timestamp() for item in history]
    for basis, window in scopes.items():
        if basis == "cycle":
            alias = next((key for key, candidate in evidence["windows"].items()
                if all(candidate[field] == cycle[field] for field in
                    ("start", "end", "limit_id", "plan", "boundary", "full_at"))), None)
            if alias:
                metadata["ranges"][basis] = {**metadata["ranges"][alias], "partition_basis": alias}
                continue
        if basis == "selected":
            bounds = report_range.bounds
            start = bounds.start_us / 1e6 if bounds.start_us is not None else min(captured_times, default=kwargs["now"].timestamp())
            end = bounds.end_us / 1e6 if bounds.end_us is not None else max(captured_times, default=start) + .000001
            interval = BreakdownInterval(start, end)
        else:
            interval = BreakdownInterval(datetime.fromisoformat(window["start"]).timestamp(),
                datetime.fromisoformat(window["end"]).timestamp(), causal=True)
        if basis == "selected":
            valued = selected
        else:
            if interval.causal:
                valued = history[bisect_right(times, interval.start):bisect_right(times, interval.end)]
            else:
                valued = history
        start, end = interval.start, interval.end
        scoped_evidence = {**evidence, "cycle": window} if basis != "selected" else evidence
        info, data = aggregate(valued, timezone, scoped_evidence, start=start, end=end,
                               complete=status.coverage.complete, causal=interval.causal)
        info["min_date"] = datetime.fromtimestamp(start, timezone).date().isoformat()
        info["max_date"] = datetime.fromtimestamp(max(start, end - .000001), timezone).date().isoformat()
        observed = [d for d in info["daily"]]
        if interval.causal:
            # Historical endpoints are actual captures, unlike calendar ends.
            latest_at = interval.occurrence_time(end) if end > start else start
            observed.append(datetime.fromtimestamp(latest_at, timezone).date().isoformat())
        else:
            observed.extend(datetime.fromtimestamp(at, timezone).date().isoformat()
                for at in account_times if interval.contains(at))
        fallback = kwargs["now"].astimezone(timezone).date().isoformat()
        info["latest_day"] = min(info["max_date"], max(info["min_date"], max(observed, default=fallback)))
        # Metadata is a scope directory, never an all-history composition body.
        metadata["ranges"][basis] = {key: info[key] for key in
            ("min_date", "max_date", "latest_day", "start", "end")}
        metadata["ranges"][basis]["partition_basis"] = basis
        partitions[basis + ":summary"] = info
        partitions.update({basis + ":" + k: v for k, v in data.items()})
    # Raw history is partitioned by local day; warm navigation never decodes it.
    for point in evidence.pop("points"):
        day = datetime.fromisoformat(point["timestamp"]).astimezone(timezone).date().isoformat()
        partitions.setdefault("meter:" + day, []).append(point)
    partitions.update(balance_partitions(evidence.pop("balances"), timezone))
    return metadata, partitions


def initial_state(metadata, live_status):
    reason = metadata["evidence"]["reason"]
    cycle = metadata["evidence"]["cycle"]
    weekly = weekly_anchors(live_status)
    if cycle and (live_status["probe_status"] != "fresh" or len(weekly) != 1):
        reason = "weekly live anchor stale, partial or ambiguous"
    if cycle and weekly and (weekly[0].resets_at is None or weekly[0].resets_at <= live_status["now"]):
        reason = "weekly reset deadline elapsed or unavailable"
    basis = "cycle" if cycle and not reason else "selected"
    info = metadata["ranges"][basis]
    return {"basis": basis, "view": "hour", "metric": "cost", "group": "model",
            "day": info["latest_day"], "detail": ""}, reason


def render_breakdown_report(codex_home, *, breakdown_action=None, **kwargs):
    from codex_usage.agent_reports import PRICING_REVISION, RenderedLedgerReport
    from codex_usage.report_usage_breakdown import render_breakdown
    from codex_usage.speed_reports import render_speed_report
    started = monotonic()
    kwargs["now"] = kwargs.get("now") or datetime.now(UTC)
    timezone = resolve_timezone(kwargs["timezone_name"])
    report_range = resolve_report_range(kwargs["range_name"], timezone,
        start_date=kwargs.get("start_date"), end_date=kwargs.get("end_date"), now=kwargs["now"])
    keys = sorted(set(kwargs["project_keys"] or []))
    path = ledger_database_path(codex_home)
    writes, sink = {}, {}
    with open_ledger(path, read_only=True) as connection:
        connection.execute("begin")
        status = query_ledger_status(connection)
        from codex_usage.allowance_index import ALLOWANCE_INDEX_REVISION, ALLOWANCE_REPORT_REVISION
        identity = [status.revision, PRICING_REVISION, BREAKDOWN_REVISION,
                    ALLOWANCE_INDEX_REVISION, ALLOWANCE_REPORT_REVISION, report_range.cache_identity,
                    keys, str(timezone), kwargs.get("auto_transitions", True), status.coverage.complete]
        prefix = "breakdown:" + digest(identity) + ":"
        metadata = load(connection, prefix + "metadata")
        live = allowance_status(connection, now=kwargs["now"])
        live["now"] = kwargs["now"].timestamp()
        args = None
        if breakdown_action is not None:
            args = issued_action(connection, breakdown_action, load)
            allowed = load(connection, prefix + "nav:" + args["scope"])
            reason = initial_state(metadata, live)[1] if metadata else None
            if not metadata or not allowed or allowed["reason"] != reason:
                raise BreakdownScopeExpired("Issued breakdown scope expired; reload without chart commands")
            if args not in allowed["actions"]:
                raise ValueError("Unsupported breakdown command")
        base = render_speed_report(codex_home, _snapshot=connection, _prepared_sink=sink, **kwargs)
        cold_seconds = 0.0
        if metadata is None:
            cold_start = monotonic()
            metadata, partitions = prepare(connection, path, report_range, keys, timezone, status, kwargs, sink)
            writes.update({prefix + k: v for k, v in partitions.items()})
            cold_seconds = monotonic() - cold_start
            metadata["cold_seconds"] = cold_seconds
            writes[prefix + "metadata"] = metadata
        state, reason = initial_state(metadata, live)
        if args is not None:
            state = args["state"]
            if state["basis"] == "cycle" and reason:
                raise BreakdownScopeExpired("Weekly evidence expired; reload the dashboard")
        def partition(name, default):
            if name.startswith(state["basis"] + ":"):
                name = metadata["ranges"][state["basis"]]["partition_basis"] + name[len(state["basis"]):]
            key = prefix + name
            return writes[key] if key in writes else load(connection, key) or default
        info = partition(state["basis"] + ":summary", {})
        scope = digest([identity, metadata["evidence"], reason, state])
        nav = {"scope": scope, "state": state, "actions": [], "evidence_state": {
            "probe_status": live["probe_status"], "deadline_elapsed": any(
                p.resets_at is not None and p.resets_at <= live["now"] for p in weekly_anchors(live))}}
        section = render_breakdown(metadata, info, state, nav, reason, timezone, partition,
                                   global_filtered=bool(keys))
        writes[prefix + "nav:" + scope] = {"reason": reason, "actions": nav["actions"]}
        writes[RECEIPT_PREFIX + scope] = receipt(nav["actions"])
        rendered = base.html
        # The speed section replaces its placeholder; place breakdown after the
        # heatmap's enclosing section without changing monetary report markup.
        rendered = rendered.replace('<section class="section observed-speed"', section + '<section class="section observed-speed"', 1)
    store(path, status.revision, writes)
    return RenderedLedgerReport(rendered, base.ledger_revision, base.cache_hit and not cold_seconds,
        monotonic() - started, base.status, base.speed_navigation, nav)
