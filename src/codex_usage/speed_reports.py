"""Layer timing presentation over the cached monetary report, never reprice it."""
import hashlib
import html
import json
from datetime import UTC, datetime
import re
from contextlib import nullcontext
from time import monotonic

from codex_usage.aggregation import resolve_report_range, resolve_timezone
from codex_usage.agent_paths import ledger_database_path
from codex_usage.ledger_schema import ledger_revision, open_ledger
from codex_usage.report_speed import render_speed, summary_html
from codex_usage.speed_queries import chart_navigation, speed_aggregates, store_aggregates
from codex_usage.speed_store import revision


def render_speed_report(codex_home, *, speed_granularity=None, speed_window_start=None, speed_window_scope=None, _snapshot=None, **kwargs):
    from codex_usage.agent_reports import _render_base_ledger_report, RenderedLedgerReport
    started = monotonic()
    kwargs["now"] = kwargs.get("now") or datetime.now(UTC)
    timezone = resolve_timezone(kwargs["timezone_name"])
    report_range = resolve_report_range(kwargs["range_name"], timezone,
        start_date=kwargs.get("start_date"), end_date=kwargs.get("end_date"), now=kwargs["now"])
    keys = sorted({k for k in kwargs["project_keys"] or [] if k})
    path = ledger_database_path(codex_home)
    with (nullcontext(_snapshot) if _snapshot is not None else open_ledger(path, read_only=True)) as connection:
        if _snapshot is None:
            connection.execute("begin")
        base = _render_base_ledger_report(codex_home, _snapshot=connection, **kwargs)
        speed_revision = revision(connection)
        nav = chart_navigation(connection, report_range, keys, timezone, kwargs["now"], speed_granularity, speed_window_start, speed_window_scope)
        identity = [hashlib.sha256(base.html.encode()).hexdigest(), speed_revision, nav, base.status.speed]
        key = "html:" + hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        cached = connection.execute("select html from speed_html_cache where cache_key=?", (key,)).fetchone()
        if cached:
            return RenderedLedgerReport(cached[0], base.ledger_revision, True,
                monotonic() - started, base.status, nav)
        aggregates, aggregate_hit = speed_aggregates(connection, report_range, keys, timezone,
                                                    auto_transitions=kwargs.get("auto_transitions", True))
    def replace_summary(match):
        model = html.unescape(match.group(1))
        return summary_html(aggregates["summaries"].get(model))
    rendered = re.sub(r'<span data-speed-model="([^"]*)">Unavailable</span>', replace_summary, base.html)
    rendered = rendered.replace("<!-- observed-speed -->", render_speed(aggregates, nav, base.status.speed, timezone))
    with open_ledger(path) as connection:
        connection.execute("begin immediate")
        if revision(connection) == speed_revision and ledger_revision(connection) == base.ledger_revision:
            if not aggregate_hit:
                store_aggregates(connection, aggregates)
            connection.execute("insert or replace into speed_html_cache values (?, ?)", (key, rendered))
            connection.commit()
    return RenderedLedgerReport(rendered, base.ledger_revision, False, monotonic() - started, base.status, nav)
