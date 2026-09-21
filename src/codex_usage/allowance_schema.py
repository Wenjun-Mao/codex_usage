"""Additive quota storage, separate from language and image accounting."""
import sqlite3


def create_allowance_schema(connection: sqlite3.Connection) -> None:
    for sql in (
        """create table quota_reads (
            read_id integer primary key, capture_run_id integer,
            timestamp text not null, plan text not null,
            lifetime_tokens integer, diagnostics text not null)""",
        """create table quota_observations (
            observation_key text primary key, timestamp text not null,
            last_timestamp text not null, sample_count integer not null,
            limit_id text not null, slot text not null, plan text not null,
            used_percent real not null, duration_minutes integer,
            resets_at integer, reset_credits integer, timestamps_blob blob)""",
        """create table quota_provenance (
            observation_key text not null references quota_observations(observation_key),
            source_key text not null, provenance text not null,
            primary key(observation_key, source_key, provenance))""",
        "create index quota_time_idx on quota_observations(timestamp)",
        """create table quota_recovery (
            source_key text primary key, size_bytes integer not null,
            mtime_ns integer not null, status text not null,
            bytes_read integer not null, observations integer not null,
            source_device text not null, source_inode text not null)""",
    ):
        connection.execute(sql)


def create_quota_cache(connection: sqlite3.Connection) -> None:
    connection.execute("""create table quota_cache (
        file_key text not null, observation_key text not null,
        observation_json text not null,
        primary key (file_key, observation_key))""")


def backup_parser_cache(connection, prior_version):
    if prior_version not in {"8", "9"}:
        return
    from datetime import UTC, datetime
    from pathlib import Path
    from codex_usage.agent_private_files import ensure_private_file

    row = next((row for row in connection.execute("pragma database_list") if row[1] == "main"), None)
    if row is None or not row[2]:
        return
    path = Path(row[2])
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = path.with_name(f"{path.name}.parser-{prior_version}-backup-{stamp}")
    with sqlite3.connect(backup_path) as backup:
        connection.backup(backup)
    ensure_private_file(backup_path)
