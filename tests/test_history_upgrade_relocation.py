"""Missing legacy input can be replayed from a proven copy, not blindly rebound."""
import json
import os
from pathlib import Path

import pytest

import codex_usage.agent_rebuild as rebuild
from codex_usage.agent_rebuild_authority import load_rebuild_source
from codex_usage.history_upgrade_discovery import discover_accounting_upgrades, DISCOVERY_BYTES
from codex_usage.history_upgrade_receipts import decision
from codex_usage.history_upgrade_relocation import PREFIX
from codex_usage.ledger_queries import load_ledger_status
from codex_usage.ledger_queries import load_ledger_records
from codex_usage.ledger_schema import open_ledger
from codex_usage.session_inventory import collect_session_file_inventory
from test_history_upgrade_discovery import old_capture, refresh, checkpoints
from test_paginated_history import PAGE, THREAD, tokens
from test_paginated_upgrade_rebuild import finish, total
from codex_usage.parser import parse_session_files
from codex_usage.replica_accounting_proof import fact
from codex_usage.pricing import estimate_cost, estimate_codex_credits


def moved_capture(tmp_path, monkeypatch):
    home, ledger, original = old_capture(tmp_path, monkeypatch)
    copy = home / "sessions" / "mirror" / original.name
    copy.parent.mkdir()
    copy.write_bytes(original.read_bytes())
    original.unlink()
    return home, ledger, original, copy


def current_source(ledger):
    with open_ledger(ledger, read_only=True) as connection:
        return load_rebuild_source(connection, THREAD)


def test_byte_proven_move_replays_before_atomic_path_and_identity_install(tmp_path, monkeypatch):
    home, ledger, original, copy = moved_capture(tmp_path, monkeypatch)
    before = checkpoints(ledger)
    result = refresh(home, ledger)
    assert result.stats.files_parsed == 0
    assert 0 < result.stats.source_bytes_read <= DISCOVERY_BYTES
    assert checkpoints(ledger) == before and total(ledger) == 250
    assert rebuild.stale_source_keys(ledger) == (THREAD,)
    source = current_source(ledger)
    assert source["path"] == str(copy) and source["captured_path"] == str(original)
    assert refresh(home, ledger).stats.source_bytes_read == 0
    stage = rebuild._staging_path(home, THREAD, recovery_id=source["recovery_id"])
    first = rebuild.rebuild_stale_source_slice(home, THREAD, max_bytes=384)
    assert not first.complete and stage.exists()
    assert checkpoints(ledger) == before and total(ledger) == 250
    assert finish(home)[-1].complete
    assert total(ledger) == 150 and not stage.exists() and not original.exists()
    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute("select path from files where file_key=?", (f"codex-usage:page:{PAGE}",)).fetchone()[0] == str(copy)
        assert connection.execute("select value from schema_meta where key=?", (PREFIX+THREAD,)).fetchone() is None
        assert connection.execute("select count(*) from ledger_generations where status='superseded'").fetchone()[0] > 0
    refresh(home, ledger)
    assert load_ledger_status(ledger).coverage.complete
    actual = sorted(load_ledger_records(ledger), key=fact)
    expected = sorted(parse_session_files(sorted((home / "sessions").rglob("*.jsonl"))), key=fact)
    assert list(map(fact, actual)) == list(map(fact, expected))
    for price in (estimate_cost, estimate_codex_credits):
        assert [price(record.usage, record.model, record.timestamp) for record in actual] == [
            price(record.usage, record.model, record.timestamp) for record in expected]


@pytest.mark.parametrize("mutation", ["shorter", "wrong_head", "changed_tail", "different_physical"])
def test_unproven_copy_stays_a_gap_and_never_changes_capture(tmp_path, monkeypatch, mutation):
    home, ledger, original, copy = moved_capture(tmp_path, monkeypatch)
    if mutation == "shorter":
        copy.write_bytes(b"".join(copy.read_bytes().splitlines(keepends=True)[:-1]))
    elif mutation == "wrong_head":
        copy.write_bytes(copy.read_bytes().replace(THREAD.encode(), b"33333333-3333-4333-8333-333333333333"))
    elif mutation == "changed_tail":
        copy.write_bytes(copy.read_bytes().replace(b'"total_tokens": 150', b'"total_tokens": 151'))
    else:
        copy.rename(copy.with_name(copy.name.replace(PAGE, "33333333-3333-4333-8333-333333333333")))
    before = checkpoints(ledger)
    refresh(home, ledger)
    if mutation == "different_physical":
        # An independent physical stream is not recovery of the missing owner.
        assert all(row in checkpoints(ledger) for row in before)
        assert total(ledger) == 300
    else:
        assert checkpoints(ledger) == before and total(ledger) == 250
    assert not rebuild.stale_source_keys(ledger) and current_source(ledger) is None
    assert not original.exists()


def test_zero_budget_cannot_authorize_a_missing_capture(tmp_path, monkeypatch):
    home, ledger, _, _ = moved_capture(tmp_path, monkeypatch)
    entries = collect_session_file_inventory([home / "sessions"], read_metadata=False)
    with open_ledger(ledger) as connection:
        result = discover_accounting_upgrades(connection, entries, max_bytes=0)
        assert result.bytes_read == 0
        assert connection.execute("select value from schema_meta where key=?", (PREFIX+THREAD,)).fetchone() is None
    assert total(ledger) == 250


@pytest.mark.parametrize("mutation", ["append", "restored_mtime"])
def test_changed_recovery_source_requires_new_capture_and_uses_a_distinct_stage(tmp_path, monkeypatch, mutation):
    home, ledger, _, copy = moved_capture(tmp_path, monkeypatch)
    refresh(home, ledger)
    source = current_source(ledger)
    old_stage = rebuild._staging_path(home, THREAD, recovery_id=source["recovery_id"])
    rebuild.rebuild_stale_source_slice(home, THREAD, max_bytes=384)
    if mutation == "append":
        with copy.open("a") as handle:
            handle.write(json.dumps(tokens(175, "2026-10-13T03:00:00Z", ordinal=6))+"\n")
    else:
        before = copy.stat()
        copy.write_bytes(copy.read_bytes())
        os.utime(copy, ns=(before.st_atime_ns, before.st_mtime_ns))
    with pytest.raises(OSError, match="relocation source changed"):
        rebuild.rebuild_stale_source_slice(home, THREAD, max_bytes=384)
    assert total(ledger) == 250 and old_stage.exists()
    refresh(home, ledger)
    source = current_source(ledger)
    new_stage = rebuild._staging_path(home, THREAD, recovery_id=source["recovery_id"])
    assert old_stage != new_stage
    assert finish(home)[-1].complete
    assert total(ledger) == (175 if mutation == "append" else 150)
    assert old_stage.exists() and not new_stage.exists()


@pytest.mark.parametrize("failure", ["copy", "capture_changed", "source_changed"])
def test_failed_install_retains_original_capture_and_recovery_stage(tmp_path, monkeypatch, failure):
    home, ledger, original, copy = moved_capture(tmp_path, monkeypatch)
    refresh(home, ledger)
    source = current_source(ledger)
    stage = rebuild._staging_path(home, THREAD, recovery_id=source["recovery_id"])
    before = checkpoints(ledger)
    replace_rows = rebuild._replace_workset_rows
    install = rebuild._install_completed_rebuild

    def fail_copy(connection, *args):
        replace_rows(connection, *args)
        if failure == "source_changed":
            with copy.open("ab") as handle:
                handle.write(b"{}\n")
        else:
            raise RuntimeError("synthetic install failure")

    def change_capture(*args):
        with open_ledger(ledger) as connection:
            connection.execute("update parser_checkpoints set next_record_index=next_record_index+1 where file_key=?", (THREAD,))
            connection.commit()
        return install(*args)

    monkeypatch.setattr(rebuild, "_install_completed_rebuild", change_capture if failure == "capture_changed" else install)
    monkeypatch.setattr(rebuild, "_replace_workset_rows", fail_copy if failure != "capture_changed" else replace_rows)
    with pytest.raises((RuntimeError, OSError), match="identity|synthetic|source changed"):
        finish(home)
    assert total(ledger) == 250 and stage.exists() and not original.exists()
    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute("select path from files where file_key=?", (THREAD,)).fetchone()[0] == str(original)
    if failure != "capture_changed":
        assert checkpoints(ledger) == before


@pytest.mark.parametrize("damage", ["invalid_json", "missing", "wrong_capture"])
def test_malformed_or_unbound_receipt_cannot_supply_a_rebuild_source(tmp_path, monkeypatch, damage):
    home, ledger, _, _ = moved_capture(tmp_path, monkeypatch)
    refresh(home, ledger)
    with open_ledger(ledger) as connection:
        if damage == "missing":
            connection.execute("delete from schema_meta where key=?", (PREFIX+THREAD,))
        else:
            value = "not-json" if damage == "invalid_json" else json.dumps(dict(version=1, capture="a"*64, entry={}))
            connection.execute("update schema_meta set value=? where key=?", (value, PREFIX+THREAD))
        connection.commit()
    assert current_source(ledger) is None and not rebuild.stale_source_keys(ledger)
    assert total(ledger) == 250


def test_unchanged_qualified_relocation_does_not_read_raw_sources(tmp_path, monkeypatch):
    home, ledger, _, _ = moved_capture(tmp_path, monkeypatch)
    refresh(home, ledger)
    original = Path.open

    def no_jsonl(path, *args, **kwargs):
        if path.suffix == ".jsonl":
            raise AssertionError("warm relocation must reuse its guarded receipt")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_jsonl)
    assert refresh(home, ledger).stats.source_bytes_read == 0


def test_conflicting_sibling_copy_cannot_be_ignored_for_recovery(tmp_path, monkeypatch):
    home, ledger, _, copy = moved_capture(tmp_path, monkeypatch)
    sibling = copy.parent / "other" / copy.name
    sibling.parent.mkdir()
    sibling.write_bytes(copy.read_bytes().replace(b'"total_tokens": 150', b'"total_tokens": 151'))
    before = checkpoints(ledger)
    refresh(home, ledger)
    assert current_source(ledger) is None and not rebuild.stale_source_keys(ledger)
    assert checkpoints(ledger) == before and total(ledger) == 250


def test_failed_missing_source_discovery_rotates_behind_unseen_sources(tmp_path, monkeypatch):
    home, ledger, original, _ = moved_capture(tmp_path, monkeypatch)
    root = next(path for path in (home / "sessions").rglob("*.jsonl") if path.parent.name != "mirror")
    copy = home / "sessions" / "mirror" / root.name
    copy.write_bytes(root.read_bytes())
    root.unlink()
    inspected = []

    def invalid(entry, *_args):
        inspected.append(entry.path)
        return "pending", "invalid-metadata", "synthetic unavailable metadata", 0

    monkeypatch.setattr("codex_usage.history_upgrade_discovery._inspect", invalid)
    entries = collect_session_file_inventory([home / "sessions"], read_metadata=False)
    for _ in range(2):
        with open_ledger(ledger) as connection:
            discover_accounting_upgrades(connection, entries, max_files=1)
    assert len(inspected) == 2 and len(set(inspected)) == 2
    assert not original.exists() and total(ledger) == 250


@pytest.mark.parametrize("timing", ["before_install", "during_copy"])
def test_recorded_sibling_change_cannot_retire_old_capture(tmp_path, monkeypatch, timing):
    home, ledger, _, copy = moved_capture(tmp_path, monkeypatch)
    sibling = copy.parent / "other" / copy.name
    sibling.parent.mkdir()
    sibling.write_bytes(copy.read_bytes())
    refresh(home, ledger)
    source = current_source(ledger)
    install = rebuild._install_completed_rebuild
    loser = next(Path(row["path"]) for row in source["recovery_snapshots"] if row["path"] != source["path"])

    def change_sibling(*args):
        loser.write_bytes(loser.read_bytes().replace(b'"total_tokens": 150', b'"total_tokens": 151'))
        return install(*args)

    replace_rows = rebuild._replace_workset_rows

    def change_after_copy(*args):
        replace_rows(*args)
        loser.write_bytes(loser.read_bytes().replace(b'"total_tokens": 150', b'"total_tokens": 151'))

    if timing == "before_install":
        monkeypatch.setattr(rebuild, "_install_completed_rebuild", change_sibling)
    else:
        monkeypatch.setattr(rebuild, "_replace_workset_rows", change_after_copy)
    with pytest.raises(OSError, match="relocation source changed"):
        finish(home)
    assert total(ledger) == 250


def test_present_failure_does_not_starve_an_unseen_relocation(tmp_path, monkeypatch):
    home, ledger, _, _ = moved_capture(tmp_path, monkeypatch)
    root = next(path for path in (home / "sessions").rglob("*.jsonl") if path.parent.name != "mirror")
    before = root.stat()
    os.utime(root, ns=(before.st_atime_ns, before.st_mtime_ns+1_000_000_000))
    from codex_usage import history_upgrade_discovery as discovery
    inspect = discovery._inspect
    inspected = []

    def root_unavailable(entry, *args):
        inspected.append(entry.path)
        return ("pending", "unavailable", "synthetic unavailable header", 0) if entry.path == root else inspect(entry, *args)

    monkeypatch.setattr(discovery, "_inspect", root_unavailable)
    monkeypatch.setattr("codex_usage.session_cache_refresh.discover_accounting_upgrades",
        lambda connection, inventory, **kwargs: discover_accounting_upgrades(connection, inventory, max_files=1, **kwargs))
    refresh(home, ledger)
    refresh(home, ledger)
    assert inspected[0] == root and len(set(inspected)) == 2
    assert current_source(ledger) is not None


def test_budget_pending_missing_capture_schedules_discovery_continuation(tmp_path, monkeypatch):
    home, ledger, _, _ = moved_capture(tmp_path, monkeypatch)
    root = next(path for path in (home / "sessions").rglob("*.jsonl") if path.parent.name != "mirror")
    (home / "sessions" / "mirror" / root.name).write_bytes(root.read_bytes())
    root.unlink()
    monkeypatch.setattr("codex_usage.session_cache_refresh.discover_accounting_upgrades",
        lambda connection, inventory, **kwargs: discover_accounting_upgrades(connection, inventory, max_files=1, **kwargs))
    refresh(home, ledger)
    assert rebuild.pending_incremental_source_count(ledger) == 1
    refresh(home, ledger)
    assert rebuild.pending_incremental_source_count(ledger) == 0
    assert len(rebuild.stale_source_keys(ledger)) == 2


def test_family_exceeding_a_whole_batch_is_a_gap_not_an_automatic_retry_loop(tmp_path, monkeypatch):
    home, ledger, _, copy = moved_capture(tmp_path, monkeypatch)
    sibling = copy.parent / "other" / copy.name
    sibling.parent.mkdir()
    sibling.write_bytes(copy.read_bytes())
    monkeypatch.setattr("codex_usage.session_cache_refresh.discover_accounting_upgrades",
        lambda connection, inventory, **kwargs: discover_accounting_upgrades(connection, inventory, max_files=1, **kwargs))
    refresh(home, ledger)
    with open_ledger(ledger, read_only=True) as connection:
        assert decision(connection, THREAD)["diagnostic"] == "relocation_exceeds_discovery_budget"
    assert rebuild.pending_incremental_source_count(ledger) == 0
    assert current_source(ledger) is None and total(ledger) == 250
