"""Snapshot-pinned partitioned breakdown cache over the existing valued report."""
import hashlib
import json
from datetime import UTC, datetime
from time import monotonic

from codex_usage.aggregation import (
    filter_records_by_project_keys, resolve_report_range,
    resolve_timezone, value_records,
)
from codex_usage.agent_paths import ledger_database_path
from codex_usage.allowance_index import indexed_allowance_report
from codex_usage.breakdown_aggregation import aggregate
from codex_usage.breakdown_evidence import prepare_evidence, weekly_anchors
from codex_usage.breakdown_intervals import BreakdownInterval
from codex_usage.breakdown_preparation import prepare_account
from codex_usage.breakdown_commands import BreakdownScopeExpired, issued_action, receipt, prune_receipts, RECEIPT_PREFIX
from codex_usage.breakdown_state import validate_state
from codex_usage.ledger_queries import query_ledger_records, query_ledger_status, query_ledger_transitions
from codex_usage.ledger_schema import ledger_revision, open_ledger
from codex_usage.parser import finalize_session_records
from codex_usage.project_transitions import apply_project_transitions

BREAKDOWN_REVISION = 7


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
            [(k, revision, PRICING_REVISION, datetime.now(UTC).isoformat(), v if isinstance(v, str) else json.dumps(v))
             for k, v in payloads.items()])
        prune_receipts(writer)
        writer.commit()


def valued_query(connection, keys, *, auto_transitions, bounds):
    records = finalize_session_records([query_ledger_records(connection, bounds=bounds)])
    transitions = query_ledger_transitions(connection) if auto_transitions else []
    if transitions:
        records = apply_project_transitions(records, transitions)
    return value_records(filter_records_by_project_keys(records, keys))


def prepare(connection, path, report_range, keys, timezone, status, kwargs, sink, account, account_prefix):
    evidence = account["evidence"]
    extent = connection.execute("""select min(e.timestamp_us), max(e.timestamp_us)
        from ledger_usage_events e join ledger_generations g using(generation_id)
        where g.status='trusted'""").fetchone() if report_range.bounds.start_us is None or report_range.bounds.end_us is None else ()
    # All-time bounds belong to captured account context, not a project subset.
    captured_times = list(account["extent"])
    captured_times.extend(v / 1e6 for v in extent if v is not None)
    metadata = {"evidence": evidence, "ranges": dict(account["ranges"]), "complete": status.coverage.complete,
                "account_prefix": account_prefix,
                "default_grain": "hourly" if kwargs["range_name"] in {"today", "yesterday"} else "daily"}
    selected = sink["valued"] if "valued" in sink else valued_query(connection, keys,
        auto_transitions=kwargs.get("auto_transitions", True), bounds=report_range.bounds)
    bounds = report_range.bounds
    start = bounds.start_us / 1e6 if bounds.start_us is not None else min(captured_times, default=kwargs["now"].timestamp())
    end = bounds.end_us / 1e6 if bounds.end_us is not None else max(captured_times, default=start) + .000001
    interval = BreakdownInterval(start, end)
    info, data = aggregate(selected, timezone, evidence, start=start, end=end, complete=status.coverage.complete)
    info["min_date"] = datetime.fromtimestamp(start, timezone).date().isoformat()
    info["max_date"] = datetime.fromtimestamp(max(start, end - .000001), timezone).date().isoformat()
    observed = list(info["daily"])
    observed.extend(day for day, at in account["days"].items() if interval.contains(at))
    fallback = kwargs["now"].astimezone(timezone).date().isoformat()
    info["latest_day"] = min(info["max_date"], max(info["min_date"], max(observed, default=fallback)))
    metadata["ranges"]["selected"] = {key: info[key] for key in
        ("min_date", "max_date", "latest_day", "start", "end")}
    metadata["ranges"]["selected"]["partition_basis"] = "selected"
    return metadata, {"selected:summary": info, **{"selected:" + k: v for k, v in data.items()}}


def prepare_interval(connection, metadata, basis, keys, timezone, auto_transitions):
    """Exact capture-causal composition is paid for only by an issued inspection."""
    evidence = metadata["evidence"]
    window = evidence["cycle"] if basis == "cycle" else evidence["windows"][basis]
    directory = metadata["ranges"][basis]
    interval = BreakdownInterval(directory["start"], directory["end"], causal=True)
    # Preserve the historical stream's accumulation order for exact cost parity.
    valued = sorted(valued_query(connection, keys, auto_transitions=auto_transitions,
        bounds=interval.sql_bounds), key=lambda item: item.record.timestamp)
    info, data = aggregate(valued, timezone, {**evidence, "cycle": window},
        start=interval.start, end=interval.end, complete=metadata["complete"], causal=True)
    info.update({k: v for k, v in directory.items() if k != "partition_basis"})
    return {basis + ":summary": info, **{basis + ":" + k: v for k, v in data.items()}}


def initial_state(metadata, live_status):
    reason = metadata["evidence"]["reason"]
    cycle = metadata["evidence"]["cycle"]
    weekly = weekly_anchors(live_status)
    if cycle and (live_status["probe_status"] != "fresh" or len(weekly) != 1):
        reason = "weekly live anchor stale, partial or ambiguous"
    if cycle and weekly and (weekly[0].resets_at is None or weekly[0].resets_at <= live_status["now"]):
        reason = "weekly reset deadline elapsed or unavailable"
    basis = "selected"
    info = metadata["ranges"][basis]
    return {"basis": basis, "view": "time", "grain": metadata["default_grain"],
            "overlay": "weekly", "metric": "cost", "group": "model",
            "day": info["latest_day"], "project": "", "detail": ""}, reason


def live_evidence_state(live):
    return {"probe_status": live["probe_status"], "deadline_elapsed": any(
        p.resets_at is not None and p.resets_at <= live["now"] for p in weekly_anchors(live))}


def render_breakdown_report(codex_home, *, breakdown_action=None, **kwargs):
    from codex_usage.agent_reports import PRICING_REVISION, REPORT_RENDER_REVISION, RenderedLedgerReport
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
        status = query_ledger_status(connection, now=kwargs["now"])
        sink["status"] = status
        from codex_usage.allowance_index import ALLOWANCE_INDEX_REVISION, ALLOWANCE_REPORT_REVISION
        live = dict(status.plan_allowance)
        live["now"] = kwargs["now"].timestamp()
        account_identity = [status.revision, PRICING_REVISION, BREAKDOWN_REVISION,
            ALLOWANCE_INDEX_REVISION, ALLOWANCE_REPORT_REVISION, str(timezone), status.coverage.complete,
            live_evidence_state(live), any(datetime.fromisoformat(p.timestamp).timestamp() > live["now"]
                for p in weekly_anchors(live))]
        account_prefix = "breakdown-account:" + digest(account_identity) + ":"
        history_prefix = "breakdown-history:" + digest([account_identity, keys, kwargs.get("auto_transitions", True)]) + ":"
        identity = [status.revision, PRICING_REVISION, BREAKDOWN_REVISION,
                    ALLOWANCE_INDEX_REVISION, ALLOWANCE_REPORT_REVISION, report_range.cache_identity,
                    keys, str(timezone), kwargs.get("auto_transitions", True), status.coverage.complete,
                    account_identity]
        prefix = "breakdown:" + digest(identity) + ":"
        metadata = load(connection, prefix + "metadata")
        args = None
        if breakdown_action is not None:
            args = issued_action(connection, breakdown_action, load)
            allowed = load(connection, prefix + "nav:" + args["scope"])
            reason = initial_state(metadata, live)[1] if metadata else None
            if not metadata or not allowed or allowed["reason"] != reason or allowed.get("evidence_state") != live_evidence_state(live):
                raise BreakdownScopeExpired("Issued breakdown scope expired; reload without chart commands")
            if args not in allowed["actions"]:
                raise ValueError("Unsupported breakdown command")
        base = render_speed_report(codex_home, _snapshot=connection, _prepared_sink=sink, **kwargs)
        cold_seconds = 0.0
        if metadata is None:
            cold_start = monotonic()
            account = load(connection, account_prefix + "metadata")
            if account is None:
                report = sink.get("allowance") or indexed_allowance_report(connection, path,
                    revision=status.revision, pricing_revision=PRICING_REVISION,
                    coverage_complete=status.coverage.complete)
                report["status"] = live
                account, partitions = prepare_account(prepare_evidence(connection, report, kwargs["now"]), timezone)
                writes.update({account_prefix + k: v for k, v in partitions.items()})
                writes[account_prefix + "metadata"] = account
            metadata, partitions = prepare(connection, path, report_range, keys, timezone, status, kwargs, sink, account, account_prefix)
            metadata["history_prefix"] = history_prefix
            writes.update({prefix + k: v for k, v in partitions.items()})
            cold_seconds = monotonic() - cold_start
            metadata["cold_seconds"] = cold_seconds
            writes[prefix + "metadata"] = metadata
        state, reason = initial_state(metadata, live)
        if args is not None:
            state = validate_state(args["state"])
        def partition(name, default):
            nonlocal cold_seconds
            if name.startswith(("meter:", "meter-display:", "balance:", "balance-display:")):
                key = metadata["account_prefix"] + name
            elif name.startswith(("window:", "cycle:")):
                basis = name.rsplit(":summary", 1)[0]
                target = metadata["ranges"][basis]["partition_basis"]
                key = metadata["history_prefix"] + target + ":summary"
                cached = writes.get(key) if key in writes else load(connection, key)
                if cached is None:
                    interval_start = monotonic()
                    data = prepare_interval(connection, metadata, target, keys, timezone, kwargs.get("auto_transitions", True))
                    writes.update({metadata["history_prefix"] + k: v for k, v in data.items()})
                    cold_seconds += monotonic() - interval_start
                    cached = writes[key]
                return cached
            else:
                key = prefix + name
            return writes[key] if key in writes else load(connection, key) or default
        info = partition(state["basis"] + ":summary", {})
        scope = digest([identity, REPORT_RENDER_REVISION, metadata["evidence"], reason, live_evidence_state(live), state])
        nav = {"scope": scope, "state": state, "actions": [], "evidence_state": live_evidence_state(live)}
        section_key = prefix + "section:" + scope
        cached_section = connection.execute("select html from rendered_reports where cache_key=?", (section_key,)).fetchone()
        cached_nav = load(connection, prefix + "nav:" + scope) if cached_section else None
        if cached_section is None or cached_nav is None:
            section = render_breakdown(metadata, info, state, nav, reason, timezone, partition,
                                       global_filtered=bool(keys))
            writes[section_key] = section
        else:
            section = cached_section[0]
            nav["actions"] = cached_nav["actions"]
        writes[prefix + "nav:" + scope] = {"reason": reason, "actions": nav["actions"], "evidence_state": nav["evidence_state"]}
        writes[RECEIPT_PREFIX + scope] = receipt(nav["actions"])
        rendered = base.html
        # The speed section replaces its placeholder; place breakdown after the
        # heatmap's enclosing section without changing monetary report markup.
        rendered = rendered.replace('<section class="section observed-speed"', section + '<section class="section observed-speed"', 1)
    store(path, status.revision, writes)
    return RenderedLedgerReport(rendered, base.ledger_revision, base.cache_hit and not cold_seconds,
        monotonic() - started, base.status, base.speed_navigation, nav)
