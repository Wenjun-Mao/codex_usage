"""Fail closed for old DML, wrong epochs and damaged writer/schema contracts."""
import sqlite3

import pytest

from codex_usage.ledger_schema import open_ledger
from codex_usage.ledger_writer_contract import (
    LEDGER_SCHEMA_VERSION, PROTECTED_TABLES, TRIGGER_PREFIX, WRITER_EPOCH_KEY,
    WRITER_FUNCTION, LedgerCompatibilityError,
)
from codex_usage.session_cache import _open_cache_connection
from codex_usage.session_cache_schema import _ensure_schema
from ledger_writer_test_support import make_legacy_writer_fixture


@pytest.mark.parametrize("table", sorted(PROTECTED_TABLES))
@pytest.mark.parametrize("operation", ["INSERT", "UPDATE", "DELETE"])
def test_unregistered_connection_cannot_prepare_mutation_of_a_protected_table(tmp_path, table, operation):
    path = tmp_path / "ledger.sqlite3"
    with open_ledger(path):
        pass
    with sqlite3.connect(path) as legacy:
        column = legacy.execute(f'pragma table_info("{table}")').fetchone()[1]
        sql = {"INSERT": f'INSERT INTO "{table}" SELECT * FROM "{table}" WHERE 0',
               "UPDATE": f'UPDATE "{table}" SET "{column}"="{column}" WHERE 0',
               "DELETE": f'DELETE FROM "{table}" WHERE 0'}[operation]
        with pytest.raises(sqlite3.OperationalError, match="no such function: codex_usage_writer_epoch"):
            legacy.execute(sql)


def test_preexisting_legacy_connection_is_fenced_after_atomic_upgrade(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    make_legacy_writer_fixture(path)
    legacy = sqlite3.connect(path)
    try:
        assert legacy.execute("select value from ledger_meta where key='schema_version'").fetchone()[0] == "6"
        with open_ledger(path) as current:
            assert current.execute("select value from ledger_meta where key='schema_version'").fetchone()[0] == "7"
        with pytest.raises(sqlite3.OperationalError, match="no such function"):
            legacy.execute("update ledger_meta set value='0' where key='ledger_revision'")
    finally:
        legacy.close()


def test_wrong_registered_epoch_is_refused_and_current_writer_still_works(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    with open_ledger(path) as current:
        current.execute("update ledger_meta set value='4' where key='ledger_revision'")
        current.commit()
    with sqlite3.connect(path) as obsolete:
        obsolete.create_function(WRITER_FUNCTION, 0, lambda: 0)
        with pytest.raises(sqlite3.IntegrityError, match="unsupported.*writer epoch"):
            obsolete.execute("update ledger_meta set value='0' where key='ledger_revision'")
    with _open_cache_connection(path) as current:
        assert current.execute("select value from ledger_meta where key='ledger_revision'").fetchone()[0] == "4"


@pytest.mark.parametrize("damage", ["missing guard", "changed guard", "future epoch", "future schema", "missing schema"])
def test_new_writer_does_not_repair_or_reset_an_inconsistent_contract(tmp_path, damage):
    path = tmp_path / "ledger.sqlite3"
    with open_ledger(path) as current:
        if damage.endswith("guard"):
            name = TRIGGER_PREFIX+"ledger_meta_update"
            current.execute(f'DROP TRIGGER "{name}"')
            if damage.startswith("changed"):
                current.execute(f'CREATE TRIGGER "{name}" BEFORE UPDATE ON ledger_meta BEGIN SELECT 1; END')
        elif damage == "future epoch":
            current.execute("update ledger_meta set value='2' where key=?", (WRITER_EPOCH_KEY,))
        elif damage == "future schema":
            current.execute("update ledger_meta set value=? where key='schema_version'", (str(LEDGER_SCHEMA_VERSION+1),))
        else:
            current.execute("delete from ledger_meta where key='schema_version'")
        current.commit()
    with pytest.raises(LedgerCompatibilityError):
        with _open_cache_connection(path):
            pass
    with pytest.raises(ValueError):
        with open_ledger(path):
            pass


def test_ledger_parser_mismatch_is_not_a_disposable_cache_reset(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    with open_ledger(path) as current:
        current.execute("insert into ledger_meta values ('retained-proof','keep')")
        current.execute("update schema_meta set value='0' where key='parser_version'")
        current.commit()
    with pytest.raises(LedgerCompatibilityError, match="refusing disposable cache reset"):
        with open_ledger(path):
            pass
    with open_ledger(path, read_only=True) as reader:
        assert reader.execute("select value from ledger_meta where key='retained-proof'").fetchone()[0] == "keep"
        assert reader.execute("select value from schema_meta where key='parser_version'").fetchone()[0] == "0"
    assert not list(tmp_path.glob("*backup*"))


def test_new_parser_refuses_a_future_ledger_even_if_cache_versions_match(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    with open_ledger(path) as current:
        current.execute("update ledger_meta set value='8' where key='schema_version'")
        current.commit()
    with sqlite3.connect(path) as raw:
        raw.row_factory = sqlite3.Row
        with pytest.raises(LedgerCompatibilityError, match="newer than supported"):
            _ensure_schema(raw)


def test_missing_ledger_metadata_never_turns_accounting_into_a_disposable_cache(tmp_path):
    path = tmp_path / "ledger.sqlite3"
    with open_ledger(path) as current:
        current.execute("drop table ledger_meta")
        current.commit()
    with pytest.raises(LedgerCompatibilityError, match="metadata is missing"):
        with _open_cache_connection(path):
            pass
    with pytest.raises(LedgerCompatibilityError, match="metadata is missing"):
        with open_ledger(path):
            pass
    with sqlite3.connect(path) as raw:
        raw.row_factory = sqlite3.Row
        with pytest.raises(LedgerCompatibilityError, match="metadata is missing"):
            _ensure_schema(raw)
        assert raw.execute("select count(*) from ledger_usage_events").fetchone()[0] == 0
