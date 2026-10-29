"""Disposable ledger-derived cost index for account-wide allowance reports."""
import json
import sqlite3

from codex_usage.allowance_queries import _build_from_costs, build_allowance_report
from codex_usage.allowance_costs import allowance_cost_components
from codex_usage.allowance_report_codec import REPORT_CACHE_FORMAT_REVISION, decode_report, encode_report
from codex_usage.allowance_history_overview import OVERVIEW_SUFFIX, encode_overview
from codex_usage.ledger_schema import ledger_revision, open_ledger
from codex_usage.models import TokenUsage
from codex_usage.parser import parse_timestamp
from codex_usage.pricing import estimate_cost

ALLOWANCE_INDEX_REVISION = 2
ALLOWANCE_REPORT_REVISION = 11


def indexed_allowance_report(snapshot, ledger_path, *, revision, pricing_revision,
                             coverage_complete, status=None, preparation=None, include_history=True):
    owned = not snapshot.in_transaction
    if owned:
        snapshot.execute("begin")
    try:
        return _indexed_allowance_report(snapshot, ledger_path, revision=revision,
            pricing_revision=pricing_revision, coverage_complete=coverage_complete,
            status=status, preparation=preparation, include_history=include_history)
    finally:
        if owned:
            snapshot.rollback()


def _indexed_allowance_report(snapshot, ledger_path, *, revision, pricing_revision,
                              coverage_complete, status=None, preparation=None, include_history=True):
    """Use a revision-pinned result or build it from priced trusted events.

    A simultaneous capture may advance the writer beyond the caller's read
    snapshot. In that case the snapshot's full estimator is the safe fallback.
    """
    pricing_revision, report_revision = _revisions(pricing_revision)
    from codex_usage.allowance_on_demand import DEFERRED_SUFFIX, decode_deferred, encode_deferred
    cache_revision = report_revision if include_history else report_revision + DEFERRED_SUFFIX
    status = _status(snapshot) if status is None else status
    if snapshot.execute("select 1 from quota_observations limit 1").fetchone() is None:
        return _build_from_costs(snapshot, (), coverage_complete=coverage_complete,
                                 status=status, preparation=preparation, include_history=include_history)
    key = (revision, cache_revision, int(coverage_complete))
    try:
        cached = snapshot.execute("""select report_json from allowance_report_cache
            where ledger_revision = ? and pricing_revision = ? and coverage_complete = ?""", key).fetchone()
    except sqlite3.OperationalError as error:
        if "no such table: allowance_report_cache" not in str(error):
            raise
        # A read-only report can precede the next capture's schema migration.
        return build_allowance_report(snapshot, coverage_complete=coverage_complete,
                                      status=status, preparation=preparation, include_history=include_history)
    if cached:
        try:
            report = _decode_cached_report(cached[0]) if include_history else decode_deferred(cached[0])
        except (ValueError, TypeError, KeyError, IndexError, OverflowError):
            pass  # Disposable corruption is a miss; rebuild under the same snapshot fence.
        else:
            report["status"] = status
            return report
    from codex_usage.allowance_window_cache import WindowCalculationCache
    from codex_usage.dashboard_preparation_tracking import token
    from codex_usage.allowance_preparation import AllowancePreparation
    preparation = preparation or AllowancePreparation(snapshot)
    dependency = token(snapshot)
    calculations = WindowCalculationCache(snapshot, pricing_revision, report_revision, coverage_complete)
    established = snapshot.execute("""select 1 from sqlite_master where
        name glob 'allowance_window_*' or name glob 'allowance_windows_*' limit 1""").fetchone()
    trust_prices = calculations.trusted or not established
    pending = _price_missing_events(snapshot, pricing_revision, trust_cache=trust_prices)
    pending_by_id = {row[0]: row[2:] for row in pending}
    rows = snapshot.execute("""
            select e.timestamp_us, c.total_usd, c.unpriced_tokens, e.event_id
            from ledger_usage_events e
            join ledger_generations g using(generation_id)
            join ledger_sources s using(source_id)
            left join allowance_event_costs c on c.event_id=e.event_id and c.pricing_revision=?
            where g.status = 'trusted'
            order by e.timestamp_us, s.source_key, e.source_record_index
        """, (pricing_revision,))
    report = _build_from_costs(snapshot, (
            (row[0] / 1_000_000, *pending_by_id.get(row[3], (row[1], row[2]))) for row in rows
        ), coverage_complete=coverage_complete, status=status, preparation=preparation,
            window_cache=calculations, include_history=include_history)
    payload = encode_report(report) if include_history else encode_deferred(report)
    overview = encode_overview(report) if include_history else None
    pace = json.dumps({"paces": report.get("paces", [])})
    with open_ledger(ledger_path) as writer:
        writer.execute("begin immediate")
        if dependency is None or ledger_revision(writer) != revision or token(writer) != dependency:
            writer.rollback()
            return report
        calculations.finish(writer)
        if preparation is not None:
            preparation.history_cache.finish(writer)
        writer.execute("delete from allowance_event_costs where pricing_revision != ?", (pricing_revision,))
        writer.executemany("insert or replace into allowance_event_costs values (?,?,?,?)", pending)
        writer.execute("""insert or replace into allowance_report_cache values (?,?,?,?)""",
                       (*key, payload))
        writer.execute("""insert or replace into allowance_report_cache values (?,?,?,?)""",
                       (revision, report_revision + ":pace-state", int(coverage_complete),
                        pace))
        if overview is not None:
            writer.execute("insert or replace into allowance_report_cache values (?,?,?,?)",
                           (revision, report_revision + OVERVIEW_SUFFIX, int(coverage_complete), overview))
        writer.execute("""delete from allowance_report_cache where ledger_revision != ?
                       or pricing_revision not in (?, ?, ?, ?)""",
                       (revision, report_revision, report_revision + ":pace-state", report_revision + OVERVIEW_SUFFIX,
                        report_revision + DEFERRED_SUFFIX))
        writer.commit()
    report["status"] = status
    return report


def _revisions(pricing_revision):
    pricing = f"{pricing_revision}:allowance-index-{ALLOWANCE_INDEX_REVISION}"
    return pricing, f"{pricing}:report-{ALLOWANCE_REPORT_REVISION}:cache-format-{REPORT_CACHE_FORMAT_REVISION}"


def cached_allowance_pace(snapshot, *, revision, pricing_revision, coverage_complete):
    """Read compact clock state without touching the historical report payload.

    Both cache rows are written atomically under the same revision/coverage key.
    A missing state row is a cold lookup, never permission to reuse old HTML.
    """
    if snapshot.execute("select 1 from quota_observations limit 1").fetchone() is None:
        return {"paces": []}
    _, report_revision = _revisions(pricing_revision)
    try:
        row = snapshot.execute("""select report_json from allowance_report_cache
            where ledger_revision = ? and pricing_revision = ? and coverage_complete = ?""",
            (revision, report_revision + ":pace-state", int(coverage_complete))).fetchone()
    except sqlite3.OperationalError as error:
        if "no such table: allowance_report_cache" not in str(error):
            raise
        return None
    return _decode_cached_pace(row[0]) if row else None


def _decode_cached_report(payload):
    """Keep derived-cache decoding inspectable separately from evidence loading."""
    report = decode_report(payload)
    if 'history_deferred' in report:
        raise ValueError('Deferred allowance result cannot satisfy an eager consumer')
    return report


def _decode_cached_pace(payload):
    """Decode only compact state; historical decoding has a separate boundary."""
    return json.loads(payload)


def _status(connection):
    from codex_usage.allowance_queries import allowance_status
    return allowance_status(connection)


def _price_missing_events(connection, pricing_revision, *, trust_cache=True):
    rows = connection.execute("""
        select e.event_id, e.timestamp, e.input_tokens, e.cached_input_tokens,
               e.cache_write_input_tokens, e.output_tokens,
               e.reasoning_output_tokens, e.total_tokens, m.model_key
        from ledger_usage_events e
        join ledger_generations g using(generation_id)
        join ledger_models m using(model_id)
        left join allowance_event_costs c on c.event_id=e.event_id and c.pricing_revision=?
        where g.status = 'trusted' and (c.event_id is null or ?)
    """, (pricing_revision, not trust_cache))
    values = []
    for row in rows:
        usage = TokenUsage(
            input_tokens=row[2], cached_input_tokens=row[3],
            cache_write_input_tokens=row[4], output_tokens=row[5],
            reasoning_output_tokens=row[6], total_tokens=row[7],
        )
        at = parse_timestamp(row[1])
        cost = estimate_cost(usage, row[8], at=at)
        values.append((row[0], pricing_revision, *allowance_cost_components(
            cost, model=row[8], at=at, total_tokens=usage.total_tokens,
        )))
    return values
