"""Disposable ledger-derived cost index for account-wide allowance reports."""
import json
import sqlite3

from codex_usage.allowance_queries import _build_from_costs, build_allowance_report
from codex_usage.ledger_schema import ledger_revision, open_ledger
from codex_usage.models import TokenUsage
from codex_usage.parser import parse_timestamp
from codex_usage.pricing import estimate_cost

ALLOWANCE_INDEX_REVISION = 1


def indexed_allowance_report(snapshot, ledger_path, *, revision, pricing_revision,
                             coverage_complete):
    """Use a revision-pinned result or build it from priced trusted events.

    A simultaneous capture may advance the writer beyond the caller's read
    snapshot. In that case the snapshot's full estimator is the safe fallback.
    """
    pricing_revision = f"{pricing_revision}:allowance-index-{ALLOWANCE_INDEX_REVISION}"
    if snapshot.execute("select 1 from quota_observations limit 1").fetchone() is None:
        return _build_from_costs(snapshot, (), coverage_complete=coverage_complete)
    key = (revision, pricing_revision, int(coverage_complete))
    try:
        cached = snapshot.execute("""select report_json from allowance_report_cache
            where ledger_revision = ? and pricing_revision = ? and coverage_complete = ?""", key).fetchone()
    except sqlite3.OperationalError as error:
        if "no such table: allowance_report_cache" not in str(error):
            raise
        # A read-only report can precede the next capture's schema migration.
        return build_allowance_report(snapshot, coverage_complete=coverage_complete)
    if cached:
        report = json.loads(cached[0])
        report["status"] = _status(snapshot)
        return report
    with open_ledger(ledger_path) as writer:
        writer.execute("begin immediate")
        if ledger_revision(writer) != revision:
            writer.rollback()
            return build_allowance_report(snapshot, coverage_complete=coverage_complete)
        # Pricing revisions change the meaning of every cached dollar. The
        # replacement occurs atomically with the new report materialization.
        writer.execute("delete from allowance_event_costs where pricing_revision != ?",
                       (pricing_revision,))
        _price_missing_events(writer, pricing_revision)
        rows = writer.execute("""
            select e.timestamp_us, c.total_usd, c.unpriced_tokens
            from allowance_event_costs c
            join ledger_usage_events e using(event_id)
            join ledger_generations g using(generation_id)
            join ledger_sources s using(source_id)
            where g.status = 'trusted' and c.pricing_revision = ?
            order by e.timestamp_us, s.source_key, e.source_record_index
        """, (pricing_revision,))
        report = _build_from_costs(writer, (
            (row[0] / 1_000_000, row[1], row[2]) for row in rows
        ), coverage_complete=coverage_complete)
        writer.execute("""insert or replace into allowance_report_cache values (?,?,?,?)""",
                       (*key, json.dumps(report)))
        writer.execute("delete from allowance_report_cache where ledger_revision != ? or pricing_revision != ?",
                       (revision, pricing_revision))
        writer.commit()
    report["status"] = _status(snapshot)
    return report


def _status(connection):
    from codex_usage.allowance_queries import allowance_status
    return allowance_status(connection)


def _price_missing_events(connection, pricing_revision):
    rows = connection.execute("""
        select e.event_id, e.timestamp, e.input_tokens, e.cached_input_tokens,
               e.cache_write_input_tokens, e.output_tokens,
               e.reasoning_output_tokens, e.total_tokens, m.model_key
        from ledger_usage_events e
        join ledger_generations g using(generation_id)
        join ledger_models m using(model_id)
        left join allowance_event_costs c using(event_id)
        where g.status = 'trusted' and c.event_id is null
    """)
    values = []
    for row in rows:
        usage = TokenUsage(
            input_tokens=row[2], cached_input_tokens=row[3],
            cache_write_input_tokens=row[4], output_tokens=row[5],
            reasoning_output_tokens=row[6], total_tokens=row[7],
        )
        cost = estimate_cost(usage, row[8], at=parse_timestamp(row[1]))
        values.append((row[0], pricing_revision, cost.total_usd if cost else 0.0,
                       cost.unpriced_tokens if cost else usage.total_tokens))
        if len(values) >= 4096:
            connection.executemany("insert into allowance_event_costs values (?,?,?,?)", values)
            values.clear()
    if values:
        connection.executemany("insert into allowance_event_costs values (?,?,?,?)", values)
