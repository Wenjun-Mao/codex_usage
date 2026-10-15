"""A resume artifact is not authority to replace a different captured source."""
import hashlib
import sqlite3

import pytest

import codex_usage.agent_rebuild as rebuild
from codex_usage.ledger_schema import open_ledger
from test_paginated_history import THREAD, meta, tokens, write_rows
from test_paginated_upgrade_rebuild import finish, old_logical_capture, total


def test_populated_stage_without_its_origin_receipt_is_not_adopted(tmp_path, monkeypatch):
    home, ledger, _ = old_logical_capture(tmp_path, monkeypatch)
    rebuild.rebuild_stale_source_slice(home, THREAD, max_bytes=384)
    with sqlite3.connect(rebuild._staging_path(home, THREAD)) as connection:
        connection.execute("delete from rebuild_authority")
    with pytest.raises(RuntimeError, match="no originating authority"):
        finish(home)
    assert total(ledger) == 250


def test_completed_stage_revalidates_live_capture_before_installation(tmp_path, monkeypatch):
    home, ledger, _ = old_logical_capture(tmp_path, monkeypatch)
    install = rebuild._install_completed_rebuild

    def invalidate_origin(*args):
        with open_ledger(ledger) as connection:
            connection.execute("update parser_checkpoints set next_record_index=next_record_index+1 where file_key=?", (THREAD,))
            connection.commit()
        return install(*args)

    monkeypatch.setattr(rebuild, "_install_completed_rebuild", invalidate_origin)
    with pytest.raises(RuntimeError, match="identity changed before installation"):
        finish(home)
    assert total(ledger) == 250


def test_missing_normalized_replacement_rolls_back_retirement(tmp_path, monkeypatch):
    home, ledger, _ = old_logical_capture(tmp_path, monkeypatch)
    monkeypatch.setattr(rebuild, "synchronize_parser_workset_in_transaction", lambda *_: (0, False))
    with pytest.raises(RuntimeError, match="replacement accounting authority"):
        finish(home)
    assert total(ledger) == 250
    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute("select count(*) from ledger_meta where key like 'source-rebuild:%'").fetchone()[0] == 0


def test_changed_stage_checkpoint_is_not_installed_using_a_previously_loaded_object(tmp_path, monkeypatch):
    home, ledger, _ = old_logical_capture(tmp_path, monkeypatch)
    install = rebuild._install_completed_rebuild

    def invalidate_stage(*args):
        with sqlite3.connect(rebuild._staging_path(home, THREAD)) as connection:
            connection.execute("update parser_checkpoints set next_candidate_index=next_candidate_index+1")
        return install(*args)

    monkeypatch.setattr(rebuild, "_install_completed_rebuild", invalidate_stage)
    with pytest.raises(RuntimeError, match="staged capture changed before installation"):
        finish(home)
    assert total(ledger) == 250


def test_legacy_unbound_staging_is_preserved_but_not_trusted(tmp_path, monkeypatch):
    home, ledger, _ = old_logical_capture(tmp_path, monkeypatch)
    stage = rebuild._staging_path(home, THREAD)
    stage.parent.mkdir(parents=True)
    legacy = stage.parent / f"{hashlib.sha256(THREAD.encode()).hexdigest()}.sqlite3"
    legacy.write_bytes(b"synthetic legacy unqualified staging")
    assert finish(home)[-1].complete
    assert total(ledger) == 150
    assert legacy.read_bytes() == b"synthetic legacy unqualified staging"


def test_saved_checkpoint_binds_header_before_reparsing_after_crash(tmp_path, monkeypatch):
    home, ledger, page = old_logical_capture(tmp_path, monkeypatch)
    with monkeypatch.context() as patch:
        def crash_before_validation(*_args):
            raise RuntimeError("synthetic interruption before header persistence")

        patch.setattr(rebuild, "validate_staged_capture", crash_before_validation)
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            rebuild.rebuild_stale_source_slice(home, THREAD, max_bytes=384)
    write_rows(page, [meta(), tokens(40)])
    with pytest.raises(RuntimeError, match="staged capture identity"):
        finish(home)
    assert total(ledger) == 250


def test_unbound_provenance_is_checked_before_destructive_schema_reset(tmp_path, monkeypatch):
    home, ledger, _ = old_logical_capture(tmp_path, monkeypatch)
    rebuild.rebuild_stale_source_slice(home, THREAD, max_bytes=384)
    stage = rebuild._staging_path(home, THREAD)
    with sqlite3.connect(stage) as connection:
        connection.execute("delete from rebuild_authority")
        connection.execute("update schema_meta set value='-1' where key='parser_version'")
        before = connection.execute("select state_json from parser_checkpoints").fetchone()[0]
    with pytest.raises(RuntimeError, match="no originating authority"):
        finish(home)
    with sqlite3.connect(stage) as connection:
        assert connection.execute("select state_json from parser_checkpoints").fetchone()[0] == before
        assert connection.execute("select value from schema_meta where key='parser_version'").fetchone()[0] == "-1"
    assert total(ledger) == 250


def test_invalid_unbound_header_checkpoint_is_not_erased_to_authorize_changed_source(tmp_path, monkeypatch):
    home, ledger, page = old_logical_capture(tmp_path, monkeypatch)
    with monkeypatch.context() as patch:
        def interrupted(*_args):
            raise RuntimeError("synthetic interruption")

        patch.setattr(rebuild, "validate_staged_capture", interrupted)
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            rebuild.rebuild_stale_source_slice(home, THREAD, max_bytes=384)
    stage = rebuild._staging_path(home, THREAD)
    with sqlite3.connect(stage) as connection:
        connection.execute("update parser_checkpoints set state_json='{}'")
        connection.execute("update schema_meta set value='-1' where key='parser_version'")
    write_rows(page, [meta(), tokens(40)])
    with pytest.raises(RuntimeError, match="invalid saved checkpoint"):
        finish(home)
    assert total(ledger) == 250
    with sqlite3.connect(stage) as connection:
        assert connection.execute("select state_json from parser_checkpoints").fetchone()[0] == "{}"
