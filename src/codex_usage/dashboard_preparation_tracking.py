"""Independent transactional generations for staged dashboard preparation.

The fit cache owns its dirty spans. These counters never consume them and
continue firing for older collectors, whose trigger namespace is separate.
"""
import sqlite3
from codex_usage import history_quota_journal as journal

TABLE = "dashboard_preparation_state"
PREFIX = "dashboard_preparation_"
TABLE_SQL = f"CREATE TABLE {TABLE} (epoch text not null, generation integer not null, quota_generation integer not null)"
SOURCE_TABLES = (
    "ledger_usage_events", "ledger_generations", "ledger_sources", "ledger_models",
    "quota_observations", "quota_provenance", "quota_reads", "quota_recovery", "credit_observations",
)


def definitions():
    return {f"{PREFIX}{table}_{event}":
            f"CREATE TRIGGER {PREFIX}{table}_{event} after {event} on {table} begin "
            f"update {TABLE} set generation=generation+1, quota_generation=quota_generation+"
            f"{int(table in ('quota_observations', 'quota_provenance'))}; "
            f"{journal.mutation_sql(table, event, TABLE)} end"
            for table in SOURCE_TABLES for event in ("insert", "update", "delete")}


def token(connection):
    expected = definitions()
    installed = dict(connection.execute("select name, sql from sqlite_master where type='trigger' and name glob ?",
                                        (PREFIX + "*",)))
    table = connection.execute("select sql from sqlite_master where type='table' and name=?", (TABLE,)).fetchone()
    changes = connection.execute("select sql from sqlite_master where type='table' and name=?", (journal.TABLE,)).fetchone()
    if (installed != expected or not table or table[0] != TABLE_SQL
            or not changes or changes[0] != journal.TABLE_SQL):
        return None
    try:
        rows = connection.execute(f"select epoch, generation, quota_generation from {TABLE}").fetchall()
    except sqlite3.DatabaseError:
        return None
    if len(rows) != 1 or not isinstance(rows[0][0], str) or any(type(v) is not int for v in rows[0][1:]):
        return None
    return tuple(rows[0])


def ensure_tracking(connection):
    if token(connection) is not None:
        return
    for name, in connection.execute("select name from sqlite_master where type='trigger' and name glob ?",
                                    (PREFIX + "*",)).fetchall():
        connection.execute('drop trigger "' + name.replace('"', '""') + '"')
    connection.execute(f"drop table if exists {TABLE}")
    connection.execute(TABLE_SQL)
    connection.execute(f"drop table if exists {journal.TABLE}")
    connection.execute(journal.TABLE_SQL)
    connection.execute(f"insert into {TABLE} values (lower(hex(randomblob(16))), 0, 0)")
    for definition in definitions().values():
        connection.execute(definition)


def prepare_writer(connection):
    connection.execute("begin immediate")
    try:
        ensure_tracking(connection)
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
