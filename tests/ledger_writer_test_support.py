"""Explicit fixture construction for ledgers predating connection-scoped writers."""
from codex_usage.ledger_schema import open_ledger
from codex_usage.ledger_writer_contract import TRIGGER_PREFIX, WRITER_EPOCH_KEY


def make_legacy_writer_fixture(path, *, version=6):
    with open_ledger(path) as connection:
        legacy_writer_fixture(connection, version=version)
        connection.commit()


def legacy_writer_fixture(connection, *, version):
    for row in connection.execute("select name from sqlite_master where type='trigger' and name like ?",
                                  (TRIGGER_PREFIX+"%",)).fetchall():
        connection.execute(f'DROP TRIGGER "{row[0]}"')
    connection.execute("delete from ledger_meta where key=?", (WRITER_EPOCH_KEY,))
    connection.execute("update ledger_meta set value=? where key='schema_version'", (str(version),))
