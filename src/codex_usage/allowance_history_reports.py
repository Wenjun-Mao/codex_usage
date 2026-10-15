"""Bounded history frames over cached allowance reports; no evidence preparation."""
import re

from codex_usage.allowance_history_navigation import (
    DEFAULT_STATE, RECEIPT_PREFIX, digest, issued_receipt, issued_state, navigation,
)
from codex_usage.allowance_index import _revisions, _decode_cached_report


def context_identity(status, kwargs, report_range, path):
    from codex_usage.agent_reports import PRICING_REVISION, REPORT_RENDER_REVISION
    return digest([str(path.resolve()), status.revision, _revisions(PRICING_REVISION), REPORT_RENDER_REVISION,
                   status.coverage.complete, status.plan_allowance["active_buckets"],
                   status.plan_allowance["probe_status"], kwargs["theme"], kwargs["timezone_name"],
                   report_range.cache_identity, sorted(set(kwargs["project_keys"] or [])),
                   kwargs.get("auto_transitions", True)])


def prepare_state(connection, payload, context):
    from codex_usage.breakdown_reports import load
    return issued_state(connection, payload, context, load) if payload is not None else dict(DEFAULT_STATE)


def render_history(connection, base_html, context, state, status, timezone, sink, writes):
    from codex_usage.agent_reports import PRICING_REVISION
    from codex_usage.breakdown_reports import load
    from codex_usage.report_allowance_history import period_history
    scope = digest([context, state])
    key = "allowance-page:" + scope
    cached = load(connection, key)
    if cached is None:
        report = sink.get("allowance")
        if report is None:
            _, revision = _revisions(PRICING_REVISION)
            row = connection.execute("""select report_json from allowance_report_cache
                where ledger_revision=? and pricing_revision=? and coverage_complete=?""",
                (status.revision, revision, int(status.coverage.complete))).fetchone()
            if row is None:
                # Empty quota histories have no indexed cache row.
                if connection.execute("select 1 from quota_observations limit 1").fetchone():
                    raise ValueError("Cached allowance history unavailable; no evidence reconstruction during navigation")
                report = dict(windows=[], display_history=dict(captures=[], periods=[], uncertain=[],
                                                              cross_boundary_fit_indices=[]))
            else:
                report = _decode_cached_report(row[0])
        nav = navigation(report, context, state)
        section = period_history(report, timezone, nav=nav)
        cached = dict(section=section, navigation=nav)
        writes[key] = cached
    nav = cached["navigation"]
    writes[RECEIPT_PREFIX + scope] = issued_receipt(nav, context)
    # Only the history slot changes; headline, pace, prices and chart state stay owned by their renderers.
    rendered = re.sub(r"<!-- allowance-history:start -->.*?<!-- allowance-history:end -->",
                      lambda _: "<!-- allowance-history:start -->" + cached["section"] + "<!-- allowance-history:end -->",
                      base_html, count=1, flags=re.DOTALL)
    if state != DEFAULT_STATE:
        rendered = rendered.replace('<details><summary>Probe, coverage, and allowance history</summary>',
                                    '<details open><summary>Probe, coverage, and allowance history</summary>', 1)
    return rendered, nav, key not in writes
