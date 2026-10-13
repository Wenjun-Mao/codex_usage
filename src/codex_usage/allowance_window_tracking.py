"""Bounded, transactional invalidation for disposable allowance calculations."""
import hashlib
import json


def _mark(kind, start, end):
    return f"""insert into allowance_window_dirty values ('{kind}', {start}, {end})
        on conflict(kind) do update set
        start=min(start, excluded.start), end=max(end, excluded.end);"""


def _usage(stamp):
    return _mark("usage", f"coalesce(({stamp}) / 1000000.0, 1e300)", "1e300")


def _quota(row):
    # SQL second precision encloses fractional timestamps. Unsupported formats
    # fail closed. Compressed timestamps cannot be inspected by SQLite; their
    # lexical endpoints need not enclose mixed-offset interior timestamps.
    start, end = _quota_bounds(row + ".")
    return _mark("quota", start, end)


def _quota_bounds(prefix):
    return (f"case when {prefix}timestamps_blob is not null then -1e300 else "
            f"coalesce(cast(strftime('%s', {prefix}timestamp) as real)-1, -1e300) end",
            f"case when {prefix}timestamps_blob is not null then 1e300 else "
            f"coalesce(cast(strftime('%s', {prefix}last_timestamp) as real)+1, 1e300) end")


def trigger_definitions():
    definitions = {}

    def add(name, event, table, body, when=""):
        name = "allowance_windows_" + name
        definitions[name] = f"CREATE TRIGGER {name} after {event} on {table} {when} begin {body} end"

    start, end = _quota_bounds("")
    def origin(row):
        return f"""insert into allowance_window_dirty select 'quota', {start}, {end}
            from quota_observations where observation_key={row}.observation_key
            on conflict(kind) do update set start=min(start, excluded.start), end=max(end, excluded.end);"""

    for event, row in (("insert", "new"), ("delete", "old")):
        add("usage_"+event, event, "ledger_usage_events", _usage(f"{row}.timestamp_us"))
        add("quota_"+event, event, "quota_observations", _quota(row))
        add("origin_"+event, event, "quota_provenance", origin(row))
    add("usage_update", "update", "ledger_usage_events",
        _usage("old.timestamp_us") + _usage("new.timestamp_us") +
        "delete from allowance_event_costs where event_id in (old.event_id, new.event_id);")
    fields = ("observation_key", "timestamp", "last_timestamp", "sample_count", "limit_id", "slot",
              "plan", "used_percent", "duration_minutes", "resets_at", "reset_credits", "timestamps_blob")
    add("quota_update", "update", "quota_observations", _quota("old")+_quota("new"),
        "when " + " or ".join(f"old.{field} is not new.{field}" for field in fields))
    for row in ("old", "new"):
        add("origin_update_"+row, "update", "quota_provenance", origin(row))
    for name, table, field, foreign_key in (
        ("generation", "ledger_generations", "status", "generation_id"),
        ("generation_source", "ledger_generations", "source_id", "generation_id"),
        ("model", "ledger_models", "model_key", "model_id"),
    ):
        body = _usage(f"select min(timestamp_us) from ledger_usage_events where {foreign_key}=old.{foreign_key}")
        if name == "model":
            body += "delete from allowance_event_costs where event_id in (select event_id from ledger_usage_events where model_id=old.model_id);"
        add(name, "update of "+field, table, body, f"when old.{field} is not new.{field}")
    add("source", "update of source_key", "ledger_sources", _usage("""select min(e.timestamp_us)
        from ledger_usage_events e join ledger_generations g using(generation_id)
        where g.source_id=old.source_id"""), "when old.source_key is not new.source_key")
    return definitions


def ensure_tracking(connection):
    """Called inside the report's guarded writer transaction, before pricing.

    Missing/replaced tracking is not evidence of unchanged inputs. Discard
    derived results and prices, then establish a new observation boundary.
    A first installation has no historical fits to trust and retains the
    independently versioned price index, just as the pre-cache report did.
    """
    definitions = trigger_definitions()
    contract = hashlib.sha256(json.dumps(definitions, sort_keys=True).encode()).hexdigest()
    connection.execute("create table if not exists allowance_window_tracking (contract text not null)")
    previous = connection.execute("select contract from allowance_window_tracking").fetchone()
    installed = dict(connection.execute(
        "select name, sql from sqlite_master where type='trigger' and substr(name,1,18)='allowance_windows_'"))
    tables = {row[0] for row in connection.execute("select name from sqlite_master where type='table'")}
    if (previous and previous[0] == contract and installed == definitions
            and {"allowance_window_cache", "allowance_window_dirty"} <= tables):
        return
    established = previous or installed or {"allowance_window_cache", "allowance_window_dirty"} & tables
    for name in installed:
        connection.execute('drop trigger "' + name.replace('"', '""') + '"')
    connection.execute("drop table if exists allowance_window_cache")
    connection.execute("drop table if exists allowance_window_dirty")
    if established:
        connection.execute("delete from allowance_event_costs")
    connection.execute("delete from allowance_report_cache")
    connection.execute("""create table allowance_window_cache (
        cache_key text primary key, report_json text not null, start real not null,
        end real not null, last_used integer not null)""")
    connection.execute("create table allowance_window_dirty (kind text primary key, start real not null, end real not null)")
    connection.execute("delete from allowance_window_tracking")
    connection.execute("insert into allowance_window_tracking values (?)", (contract,))
    for sql in definitions.values():
        connection.execute(sql)


def repair_existing_tracking(connection):
    """Recover optional tracking before a writable connection can capture.

    First-time readers install lazily. Existing triggers must never depend on a
    missing derived table, even when an earlier read hit the full-report cache.
    """
    if not connection.execute("""select 1 from sqlite_master
        where substr(name,1,17)='allowance_window_' or substr(name,1,18)='allowance_windows_' limit 1""").fetchone():
        return
    connection.execute("begin immediate")
    try:
        ensure_tracking(connection)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
