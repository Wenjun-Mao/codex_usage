"""Old captures are discovered and staged without global cache replay."""
import json
from pathlib import Path

import pytest

from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_rebuild import pending_incremental_source_count, stale_source_keys
from codex_usage.history_upgrade_discovery import discover_accounting_upgrades, DISCOVERY_BYTES
from codex_usage.history_upgrade_receipts import decision, UpgradeDisposition, UpgradeReason
from codex_usage.ledger_queries import load_ledger_status
from codex_usage.ledger_schema import open_ledger
from codex_usage.ledger_sync import synchronize_parser_workset
from codex_usage.session_cache import refresh_cached_session_data
from codex_usage.session_inventory import collect_session_file_inventory
from codex_usage.session_cache_generations import replace_file_generation
from codex_usage.parser import parse_session_generation
from test_paginated_history import THREAD, meta, tokens, write_rows
from test_paginated_upgrade_rebuild import old_logical_capture, finish, total

NEW_STATE_FIELDS = ("history_baseline_pending", "history_boundary_digest", "root_inline_replay_possible")
NEW_META_FIELDS = ("history_mode", "history_base", "history_ordinal", "forked_from_ordinal_exclusive")


def weaken_checkpoints(ledger, *, clear_baseline=False):
    with open_ledger(ledger) as connection:
        for row in connection.execute("select file_key,state_json from parser_checkpoints").fetchall():
            state = json.loads(row["state_json"])
            for key in NEW_STATE_FIELDS:
                state.pop(key, None)
            for key in ("metadata", "root_metadata"):
                if state.get(key):
                    for field in NEW_META_FIELDS:
                        state[key].pop(field, None)
            if clear_baseline:
                state["previous_usage"] = None
            connection.execute("update parser_checkpoints set state_json=? where file_key=?",
                               (json.dumps(state), row["file_key"]))
        connection.execute("update files set error=''")
        connection.execute("delete from schema_meta where key like 'paginated-%' or key like 'retained-accounting:%'")
        connection.commit()
    synchronize_parser_workset(ledger)


def old_capture(tmp_path, monkeypatch):
    home, ledger, page = old_logical_capture(tmp_path, monkeypatch)
    weaken_checkpoints(ledger)
    assert total(ledger) == 250
    return home, ledger, page


def refresh(home, ledger):
    result = refresh_cached_session_data([home / "sessions"], cache_database_path=ledger,
        auto_transitions=False, max_workers=1, defer_full_fallback=True, refresh_storage_metadata=False)
    synchronize_parser_workset(ledger)
    return result


def checkpoints(ledger):
    with open_ledger(ledger, read_only=True) as connection:
        return [tuple(row) for row in connection.execute("select * from parser_checkpoints order by file_key")]


def test_warm_old_page_is_discovered_before_ownership_can_replace_its_slot(tmp_path, monkeypatch):
    home, ledger, page = old_capture(tmp_path, monkeypatch)
    before = checkpoints(ledger)
    result = refresh(home, ledger)
    assert result.stats.source_bytes_read <= DISCOVERY_BYTES
    assert result.stats.files_parsed == 0
    assert checkpoints(ledger) == before
    assert total(ledger) == 250
    assert stale_source_keys(ledger) == (THREAD,)
    with open_ledger(ledger, read_only=True) as connection:
        assert decision(connection, THREAD)["disposition"] == UpgradeDisposition.REBUILD
        assert connection.execute("select path from files where file_key=?", (THREAD,)).fetchone()[0] == str(page)
    assert finish(home)[-1].complete
    assert total(ledger) == 150
    refresh(home, ledger)
    assert load_ledger_status(ledger).coverage.stale_sources == 0
    original_open = Path.open

    def no_jsonl_read(path, *args, **kwargs):
        if path.suffix == ".jsonl":
            raise AssertionError("qualified unchanged discovery must not reopen logs")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_jsonl_read)
    assert refresh(home, ledger).stats.source_bytes_read == 0


def test_budget_pending_continues_discovery_but_never_enters_rebuild_queue(tmp_path, monkeypatch):
    home, ledger, _ = old_capture(tmp_path, monkeypatch)
    original = discover_accounting_upgrades
    monkeypatch.setattr("codex_usage.session_cache_refresh.discover_accounting_upgrades",
        lambda connection, inventory, **kwargs: original(connection, inventory, max_files=1, **kwargs))
    before = checkpoints(ledger)
    refresh(home, ledger)
    assert pending_incremental_source_count(ledger) == 1
    assert len(stale_source_keys(ledger)) <= 1
    assert checkpoints(ledger) == before
    refresh(home, ledger)
    assert pending_incremental_source_count(ledger) == 0
    assert stale_source_keys(ledger) == (THREAD,)
    assert checkpoints(ledger) == before


def test_failed_header_discovery_is_a_gap_not_a_full_reparse_or_auto_continuation(tmp_path, monkeypatch):
    home, ledger, page = old_capture(tmp_path, monkeypatch)
    original_open = Path.open

    def unavailable(path, *args, **kwargs):
        if path == page:
            raise OSError("synthetic unavailable header")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", unavailable)
    result = refresh(home, ledger)
    assert result.stats.files_parsed == 0
    assert THREAD not in stale_source_keys(ledger)
    assert pending_incremental_source_count(ledger) == 0
    assert total(ledger) == 250
    with open_ledger(ledger, read_only=True) as connection:
        assert decision(connection, THREAD)["reason"] == UpgradeReason.UNAVAILABLE


def test_old_null_counter_checkpoint_cannot_resume_a_phantom_whole_counter(tmp_path):
    home = tmp_path / "codex"
    path = write_rows(home / "sessions" / "ordinary.jsonl", [meta(), tokens(100),
        {"type": "event_msg", "payload": {"type": "token_count", "info": None}}])
    ledger = ledger_database_path(home)
    refresh(home, ledger)
    weaken_checkpoints(ledger, clear_baseline=True)
    assert total(ledger) == 100
    with path.open("a") as handle:
        handle.write(json.dumps(tokens(120, "2026-10-13T02:00:00Z"))+"\n")
    result = refresh(home, ledger)
    assert result.stats.files_appended == 0
    assert total(ledger) == 100
    assert stale_source_keys(ledger) == (THREAD,)
    assert finish(home)[-1].complete
    assert total(ledger) == 120


def test_zero_discovery_budget_retains_all_old_capture_evidence(tmp_path, monkeypatch):
    home, ledger, _ = old_capture(tmp_path, monkeypatch)
    before = checkpoints(ledger)
    inventory = collect_session_file_inventory([home / "sessions"], read_metadata=False)
    with open_ledger(ledger) as connection:
        by_path = {row["path"]: row["file_key"] for row in connection.execute("select path,file_key from files")}
        from dataclasses import replace
        inventory = [replace(entry, file_key=by_path[str(entry.path)]) for entry in inventory]
        outcome = discover_accounting_upgrades(connection, inventory, max_bytes=0)
    assert outcome.bytes_read == 0 and len(outcome.protected) == 2
    assert checkpoints(ledger) == before
    assert total(ledger) == 250


@pytest.mark.parametrize("claim", ["unknown-name", "same-physical-copy"])
def test_absent_old_capture_keeps_its_claim_reserved_for_new_files(tmp_path, monkeypatch, claim):
    home, ledger, page = old_capture(tmp_path, monkeypatch)
    before = checkpoints(ledger)
    raw = page.read_bytes()
    page.unlink()
    if claim == "same-physical-copy":
        replacement = home / "sessions" / "mirror" / page.name
        replacement.parent.mkdir()
        replacement.write_bytes(raw)
    else:
        write_rows(home / "sessions" / "unknown.jsonl", [meta(), tokens(20)])
    refresh(home, ledger)
    assert checkpoints(ledger) == before
    assert total(ledger) == 250
    assert stale_source_keys(ledger) == ()


def test_budget_deferral_preserves_a_previous_failed_discovery_classification(tmp_path, monkeypatch):
    home, ledger, page = old_capture(tmp_path, monkeypatch)
    original_open = Path.open
    original_discover = discover_accounting_upgrades

    def unavailable(path, *args, **kwargs):
        if path == page:
            raise OSError("synthetic unavailable header")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", unavailable)
    monkeypatch.setattr("codex_usage.session_cache_refresh.discover_accounting_upgrades",
        lambda connection, inventory, **kwargs: original_discover(connection, inventory, max_files=1, **kwargs))
    refresh(home, ledger)
    assert pending_incremental_source_count(ledger) == 1
    refresh(home, ledger)
    with open_ledger(ledger, read_only=True) as connection:
        assert decision(connection, THREAD)["reason"] == UpgradeReason.UNAVAILABLE
    assert pending_incremental_source_count(ledger) == 0


def test_cold_longer_replica_waits_for_old_accounting_then_extends_corrected_owner(tmp_path, monkeypatch):
    home, ledger, page = old_capture(tmp_path, monkeypatch)
    before = checkpoints(ledger)
    mirror = home / "sessions" / "mirror" / page.name
    mirror.parent.mkdir()
    mirror.write_bytes(page.read_bytes())
    with mirror.open("a") as handle:
        handle.write(json.dumps(tokens(175, "2026-10-13T03:00:00Z", ordinal=6))+"\n")
    refresh(home, ledger)
    assert checkpoints(ledger) == before
    assert total(ledger) == 250
    assert stale_source_keys(ledger) == (THREAD,)
    assert finish(home)[-1].complete
    assert total(ledger) == 150
    refresh(home, ledger)
    assert total(ledger) == 175


def test_discovery_reads_only_a_bounded_prefix_of_unrelated_large_origin(tmp_path, monkeypatch):
    home, ledger, page = old_capture(tmp_path, monkeypatch)
    root = next(path for path in (home / "sessions").rglob("*.jsonl") if path != page)
    with root.open("ab") as handle:
        handle.seek(0, 2)
        handle.write(b" " * (3 * 1024 * 1024))
    before = checkpoints(ledger)
    result = refresh(home, ledger)
    assert result.stats.source_bytes_read <= 2 * (64 * 1024 + 1)
    assert result.stats.files_parsed == 0
    assert checkpoints(ledger) == before


def test_header_mutation_is_recorded_as_changed_without_claiming_a_qualified_snapshot(tmp_path, monkeypatch):
    home, ledger, page = old_capture(tmp_path, monkeypatch)
    original_open = Path.open

    class RacingRead:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.handle.close()

        def fileno(self):
            return self.handle.fileno()

        def read(self, limit):
            raw = self.handle.read(limit)
            with original_open(page, "ab") as writer:
                writer.write(b"{}\n")
            return raw

    def racing(path, *args, **kwargs):
        handle = original_open(path, *args, **kwargs)
        return RacingRead(handle) if path == page and args == ("rb",) else handle

    monkeypatch.setattr(Path, "open", racing)
    refresh(home, ledger)
    with open_ledger(ledger, read_only=True) as connection:
        assert decision(connection, THREAD)["reason"] == UpgradeReason.CHANGED
    assert THREAD not in stale_source_keys(ledger)
    assert total(ledger) == 250


@pytest.mark.parametrize("weak_claimant", [False, True])
def test_logical_reservation_does_not_depend_on_the_claimants_filename_hint(tmp_path, monkeypatch, weak_claimant):
    from test_paginated_history import rollout_name

    home, ledger, page = old_capture(tmp_path, monkeypatch)
    claimant = write_rows(home / "sessions" / rollout_name("33333333-3333-4333-8333-333333333333"),
                         [meta(), tokens(20)])
    entry = next(entry for entry in collect_session_file_inventory([home / "sessions"], read_metadata=False)
                 if entry.path == claimant)
    with open_ledger(ledger) as connection:
        replace_file_generation(connection, [home / "sessions"], entry, parse_session_generation(claimant))
        connection.commit()
    if weak_claimant:
        weaken_checkpoints(ledger)
    page.unlink()
    before, before_total = checkpoints(ledger), total(ledger)
    refresh(home, ledger)
    assert checkpoints(ledger) == before
    assert total(ledger) == before_total
    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute("select path from files where file_key=?", (THREAD,)).fetchone()[0] == str(page)
