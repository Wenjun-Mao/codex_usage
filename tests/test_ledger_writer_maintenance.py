"""Writer upgrades require quiescence and a verified, nonoverwriting backup."""
import sqlite3
from time import monotonic

import pytest
from filelock import FileLock

import codex_usage.ledger_schema as schema
from codex_usage.agent_paths import agent_lock_path, ledger_database_path
from codex_usage.cache_refresh_lock import cache_refresh_lock_path
from codex_usage.ledger_maintenance import LedgerMaintenanceBusyError
from codex_usage.ledger_repair_snapshot import verify_repair_snapshot
from codex_usage.ledger_writer_contract import PROTECTED_TABLES, TRIGGER_PREFIX
from codex_usage.ledger_writer_contract import LedgerCompatibilityError
from ledger_writer_test_support import make_legacy_writer_fixture


def legacy(tmp_path):
    path = ledger_database_path(tmp_path / "home")
    make_legacy_writer_fixture(path)
    return path


def version(path):
    with schema.open_ledger(path, read_only=True) as connection:
        return connection.execute("select value from ledger_meta where key='schema_version'").fetchone()[0]


@pytest.mark.parametrize("owner", ["agent", "parser"])
def test_busy_owner_refuses_before_backup_or_journal_mutation_and_releases_owned_locks(tmp_path, owner):
    path = legacy(tmp_path)
    with sqlite3.connect(path) as raw:
        raw.execute("pragma journal_mode=delete")
    lock_path = agent_lock_path(tmp_path / "home") if owner == "agent" else cache_refresh_lock_path(path)
    with FileLock(lock_path):
        started = monotonic()
        with pytest.raises(LedgerMaintenanceBusyError, match="stopped collector and idle parser"):
            with schema.open_ledger(path):
                pass
        assert monotonic() - started < 2
        assert version(path) == "6"
        assert not list(path.parent.glob("*backup*"))
        with sqlite3.connect(path) as raw:
            assert raw.execute("pragma journal_mode").fetchone()[0] == "delete"
    with schema.open_ledger(path):
        pass
    assert version(path) == "7"


@pytest.mark.parametrize("state", ["unheld", "wrong", "owned"])
def test_startup_may_borrow_only_its_held_home_agent_lock(tmp_path, state):
    path = legacy(tmp_path)
    expected = agent_lock_path(tmp_path / "home")
    lock = FileLock(tmp_path / "wrong.lock" if state == "wrong" else expected)
    if state != "unheld":
        lock.acquire(timeout=0)
    try:
        if state == "owned":
            with schema.open_ledger(path, maintenance_agent_lock=lock):
                pass
            assert lock.is_locked and version(path) == "7"
        else:
            with pytest.raises(LedgerMaintenanceBusyError, match="owned home-agent lock"):
                with schema.open_ledger(path, maintenance_agent_lock=lock):
                    pass
            assert version(path) == "6"
    finally:
        lock.release()


def test_failed_fence_install_rolls_back_version_epoch_and_every_guard(tmp_path, monkeypatch):
    path = legacy(tmp_path)
    install = schema.install_writer_contract

    def fail_after_guards(connection):
        install(connection)
        raise RuntimeError("synthetic failure after writer guards")

    with monkeypatch.context() as patch:
        patch.setattr(schema, "install_writer_contract", fail_after_guards)
        with pytest.raises(RuntimeError, match="synthetic failure"):
            with schema.open_ledger(path):
                pass
    assert version(path) == "6"
    with schema.open_ledger(path, read_only=True) as reader:
        assert not reader.execute("select 1 from sqlite_master where type='trigger' and name like ?", (TRIGGER_PREFIX+"%",)).fetchone()
        assert not reader.execute("select 1 from ledger_meta where key='accounting_writer_epoch'").fetchone()
    first = next(path.parent.glob("*backup*"))
    assert verify_repair_snapshot(first / "snapshot.json")["schema_version"] == 6
    with schema.open_ledger(path):
        pass
    assert version(path) == "7" and len(list(path.parent.glob("*backup*"))) == 2


def test_verified_upgrade_preserves_existing_accounting_and_private_backup(tmp_path):
    from test_history_dependency_invalidation import capture
    from test_paginated_history import corpus

    home = tmp_path / "home"
    corpus(home / "sessions", opening=120)
    capture(home)
    path = ledger_database_path(home)
    make_legacy_writer_fixture(path)
    with schema.open_ledger(path, read_only=True) as reader:
        before = {table: [tuple(row) for row in reader.execute(f'SELECT * FROM "{table}"')]
                  for table in PROTECTED_TABLES if table != "ledger_meta"}
    with schema.open_ledger(path) as current:
        after = {table: [tuple(row) for row in current.execute(f'SELECT * FROM "{table}"')]
                 for table in before}
        assert after == before
    directory = next(path.parent.glob("*backup*"))
    receipt = verify_repair_snapshot(directory / "snapshot.json")
    assert receipt["schema_version"] == 6 and receipt["usage_events"] > 0
    assert directory.stat().st_mode & 0o777 == 0o700
    assert (directory / "ledger.sqlite3").stat().st_mode & 0o777 == 0o600


def test_backup_failure_does_not_enter_schema_migration(tmp_path, monkeypatch):
    path = legacy(tmp_path)

    def fail(*_args):
        raise RuntimeError("synthetic private backup failure")

    monkeypatch.setattr(schema, "_backup_before_migration", fail)
    with pytest.raises(RuntimeError, match="private backup failure"):
        with schema.open_ledger(path):
            pass
    assert version(path) == "6"
    assert not list(path.parent.glob("*backup*"))


def test_reported_symlink_ledger_cannot_bypass_the_managed_home_lock(tmp_path, monkeypatch):
    from pathlib import Path
    import shutil

    path = legacy(tmp_path)
    alias = tmp_path / "alias.sqlite3"
    shutil.copyfile(path, alias)
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda candidate: candidate == alias or original(candidate))
    with pytest.raises(LedgerCompatibilityError, match="canonical nonsymlink"):
        with schema.open_ledger(alias):
            pass
    assert version(path) == "6"


def test_writer_upgrade_marks_old_checkpoint_history_pending_without_rewriting_facts(tmp_path):
    import json
    from codex_usage.agent_rebuild import pending_incremental_source_count
    from codex_usage.ledger_queries import load_ledger_status
    from codex_usage.history_upgrade_receipts import decision
    from test_history_dependency_invalidation import capture, KEY
    from test_paginated_history import corpus

    home = tmp_path / "home"
    corpus(home / "sessions", opening=120)
    capture(home)
    path = ledger_database_path(home)
    with schema.open_ledger(path) as current:
        state = json.loads(current.execute("select state_json from parser_checkpoints where file_key=?", (KEY,)).fetchone()[0])
        state.pop("history_dependencies")
        current.execute("update parser_checkpoints set state_json=? where file_key=?", (json.dumps(state), KEY))
        before = [tuple(row) for row in current.execute("select * from ledger_usage_events")]
        current.commit()
    make_legacy_writer_fixture(path)
    with schema.open_ledger(path) as upgraded:
        assert [tuple(row) for row in upgraded.execute("select * from ledger_usage_events")] == before
        assert decision(upgraded, KEY)["reason"] == "budget"
    assert pending_incremental_source_count(path) >= 1
    assert load_ledger_status(path).coverage.stale_sources == 1


@pytest.mark.parametrize("write", ["revision", "unrevisioned row"])
def test_commit_after_backup_before_write_admission_refuses_the_upgrade(tmp_path, monkeypatch, write):
    path = legacy(tmp_path)
    migrate = schema._migrate_schema

    def intervening_commit(connection, old_version, *, backup=None):
        with sqlite3.connect(path) as obsolete:
            if write == "revision":
                obsolete.execute("update ledger_meta set value='99' where key='ledger_revision'")
            else:
                obsolete.execute("insert into ledger_models(model_key) values ('late-unrevisioned-row')")
        return migrate(connection, old_version, backup=backup)

    monkeypatch.setattr(schema, "_migrate_schema", intervening_commit)
    with pytest.raises(RuntimeError, match="changed after its verified migration backup"):
        with schema.open_ledger(path):
            pass
    assert version(path) == "6"
    directory = next(path.parent.glob("*backup*"))
    assert verify_repair_snapshot(directory / "snapshot.json")["ledger_revision"] == 0
    with sqlite3.connect(directory / "ledger.sqlite3") as before:
        assert not before.execute("select 1 from ledger_models where model_key='late-unrevisioned-row'").fetchone()


def test_no_legacy_commit_can_interleave_after_the_transactional_backup_check(tmp_path, monkeypatch):
    path = legacy(tmp_path)
    install = schema.install_writer_contract
    blocked = []

    def try_commit_during_install(connection):
        obsolete = sqlite3.connect(path, timeout=0)
        try:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                obsolete.execute("insert into ledger_models(model_key) values ('must-not-commit')")
            blocked.append(True)
            obsolete.rollback()
        finally:
            obsolete.close()
        install(connection)

    monkeypatch.setattr(schema, "install_writer_contract", try_commit_during_install)
    with schema.open_ledger(path) as current:
        assert not current.execute("select 1 from ledger_models where model_key='must-not-commit'").fetchone()
    assert blocked == [True] and version(path) == "7"


def test_additive_parser_upgrade_and_writer_install_share_rollback(tmp_path, monkeypatch):
    path = legacy(tmp_path)
    with sqlite3.connect(path) as before:
        before.execute("update schema_meta set value='10' where key='schema_version'")
    install = schema.install_writer_contract

    def fail(connection):
        install(connection)
        raise RuntimeError("synthetic fence failure after parser migration")

    monkeypatch.setattr(schema, "install_writer_contract", fail)
    with pytest.raises(RuntimeError, match="after parser migration"):
        with schema.open_ledger(path):
            pass
    with schema.open_ledger(path, read_only=True) as reader:
        assert reader.execute("select value from schema_meta where key='schema_version'").fetchone()[0] == "10"
        assert reader.execute("select value from ledger_meta where key='schema_version'").fetchone()[0] == "6"
