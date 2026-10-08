"""Explicit additive schema for parser primitives, settled facts and recovery."""
import sqlite3


def create_speed_cache(connection: sqlite3.Connection) -> None:
    for statement in (
        """create table if not exists speed_cache_facts (
            file_key text not null, record_index integer not null,
            evidence_json text not null, start_ms real not null, end_ms real not null,
            dirty integer not null default 1, primary key(file_key, record_index))""",
        "create index if not exists speed_cache_dirty_idx on speed_cache_facts(file_key, dirty)",
        "create index if not exists speed_cache_bounds_idx on speed_cache_facts(file_key, end_ms, start_ms)",
        """create table if not exists speed_cache_tools (
            file_key text not null, start_ms real not null, end_ms real not null,
            primary key(file_key, start_ms, end_ms))""",
        "create table if not exists speed_cache_dirty (file_key text primary key)",
        """create table if not exists speed_cache_uncertain_tools (
            file_key text not null, turn_id text not null, primary key(file_key, turn_id))""",
    ):
        connection.execute(statement)


def create_speed_ledger(connection: sqlite3.Connection) -> None:
    for statement in (
        """create table if not exists ledger_speed_facts (
            generation_id integer not null references ledger_generations(generation_id),
            record_index integer not null, response_id text not null,
            timestamp_us integer not null, evidence_json text not null,
            signature text not null, reason text not null,
            primary key(generation_id, record_index))""",
        "create index if not exists speed_response_idx on ledger_speed_facts(response_id)",
        "create index if not exists speed_timestamp_idx on ledger_speed_facts(timestamp_us)",
        "create index if not exists speed_source_activity_idx on ledger_usage_events(generation_id, timestamp_us)",
        """create table if not exists ledger_speed_identities (
            response_id text primary key, generation_id integer not null,
            record_index integer not null, conflict integer not null)""",
        """create table if not exists speed_recovery (
            generation_id integer primary key references ledger_generations(generation_id),
            target_offset integer not null, checkpoint_json text not null default '',
            status text not null default 'pending', reason text not null default '',
            served integer not null default 0, latest_us integer not null default 0)""",
        """create table if not exists speed_report_cache (
            cache_key text primary key, report_json text not null)""",
        """create table if not exists speed_html_cache (
            cache_key text primary key, html text not null)""",
    ):
        connection.execute(statement)
    connection.execute("insert or ignore into ledger_meta values ('speed_revision', '0')")
    connection.execute("insert or ignore into ledger_meta values ('speed_metric_version', '1')")
