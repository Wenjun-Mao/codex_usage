"""Ancestor replacement cannot leave a reusable continuation baseline behind."""
from pathlib import Path
from dataclasses import replace
import json

import pytest

import codex_usage.agent_rebuild as rebuild
from codex_usage.agent_paths import ledger_database_path
from codex_usage.ledger_queries import load_ledger_records, load_ledger_status
from codex_usage.ledger_schema import ledger_revision, open_ledger
from codex_usage.ledger_sync import synchronize_parser_workset
from codex_usage.session_cache import refresh_cached_session_data
from codex_usage.session_cache_generations import append_file_generation, rekey_file_generation, replace_file_generation
from codex_usage.session_cache_checkpoints import load_parser_checkpoint
from codex_usage.session_cache_requests import StaleAppendCheckpointError, assert_current_append_checkpoint
from codex_usage.session_history import source_identity
from codex_usage.session_history_invalidation import invalidation_epoch, pending_invalidation
from codex_usage.session_inventory import collect_session_file_inventory
from codex_usage.parser import parse_session_append, parse_session_generation
from test_paginated_history import PAGE, THREAD, corpus, meta, owned, rollout_name, tokens, write_rows
from test_paginated_upgrade_rebuild import finish

KEY = f"codex-usage:page:{PAGE}"


def capture(home, *, defer=True):
    ledger = ledger_database_path(home)
    result = refresh_cached_session_data([home / "sessions"], cache_database_path=ledger,
        auto_transitions=False, max_workers=1, defer_full_fallback=defer, refresh_storage_metadata=False)
    synchronize_parser_workset(ledger)
    return result


@pytest.mark.parametrize("staged", [False, True])
def test_replacing_an_ancestor_marks_unchanged_child_stale_until_bounded_rebuild(tmp_path, monkeypatch, staged):
    home = tmp_path / "home"
    root, page, _ = corpus(home / "sessions", opening=120)
    ledger = ledger_database_path(home)
    capture(home)
    with open_ledger(ledger, read_only=True) as connection:
        before = tuple(connection.execute("select * from parser_checkpoints where file_key=?", (KEY,)).fetchone())
    write_rows(root, [meta(history_mode="paginated"), tokens(101, ordinal=1)])
    capture(home, defer=staged)
    if staged:
        assert finish(home, source_key=THREAD)[-1].complete
    with open_ledger(ledger, read_only=True) as connection:
        assert "history_dependency_changed" in connection.execute("select error from files where file_key=?", (KEY,)).fetchone()[0]
        assert tuple(connection.execute("select * from parser_checkpoints where file_key=?", (KEY,)).fetchone()) == before
    assert load_ledger_status(ledger).coverage.stale_sources == 1
    assert finish(home, source_key=KEY)[-1].complete
    assert sum(r.usage.total_tokens for r in load_ledger_records(ledger) if r.file_path == page) == 49
    assert load_ledger_status(ledger).coverage.stale_sources == 0
    original_open = Path.open

    def forbid_history(path, *args, **kwargs):
        if path.suffix == ".jsonl":
            raise AssertionError("warm capture must not reopen ancestor history")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", forbid_history)
    assert capture(home).stats.source_bytes_read == 0


def test_transitive_ancestors_survive_an_uncaptured_middle_page(tmp_path):
    home = tmp_path / "home"
    root, middle, _ = corpus(home / "sessions", opening=120)
    leaf = write_rows(home / "sessions" / rollout_name(physical="33333333-3333-4333-8333-333333333333"),
        [meta(base={"thread_id": PAGE, "end_ordinal_exclusive": 6, "end_byte_offset": middle.stat().st_size}),
         tokens(150, ordinal=7), tokens(175, ordinal=8)])
    ledger = ledger_database_path(home)
    entries = {entry.path: entry for entry in collect_session_file_inventory([home / "sessions"], read_metadata=False)}
    with open_ledger(ledger) as connection:
        for path in (root, leaf):
            generation = parse_session_generation(path, history_sources=(owned(root), owned(middle)))
            entry = replace(entries[path], file_key=source_identity(generation.metadata), file_key_is_fallback=False)
            replace_file_generation(connection, [home / "sessions"], entry, generation)
        connection.commit()
    synchronize_parser_workset(ledger)
    leaf_key = source_identity(parse_session_generation(leaf, history_sources=(owned(root), owned(middle))).metadata)
    with open_ledger(ledger, read_only=True) as connection:
        assert not connection.execute("select 1 from files where path=?", (str(middle),)).fetchone()
        state = json.loads(connection.execute("select state_json from parser_checkpoints where file_key=?", (leaf_key,)).fetchone()[0])
        assert [reference["thread_id"] for reference in state["history_dependencies"]] == [PAGE, THREAD]
    write_rows(root, [meta(history_mode="paginated"), tokens(101, ordinal=1)])
    with open_ledger(ledger) as connection:
        entry = replace(entries[root], file_key=THREAD, file_key_is_fallback=False)
        replace_file_generation(connection, [home / "sessions"], entry, parse_session_generation(root))
        connection.commit()
    synchronize_parser_workset(ledger)
    with open_ledger(ledger, read_only=True) as connection:
        assert invalidation_epoch(connection, leaf_key) == 1
        assert connection.execute("select is_stale from ledger_sources where source_key=?", (leaf_key,)).fetchone()[0]


def test_ancestor_append_does_not_invalidate_or_reopen_a_captured_prefix(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root, _, _ = corpus(home / "sessions", opening=120)
    capture(home)
    with root.open("a") as handle:
        handle.write(json.dumps(tokens(200, ordinal=2)) + "\n")

    def no_resolution(*_args):
        raise AssertionError("append must not reopen inherited history")

    monkeypatch.setattr("codex_usage.session_parser_incremental.resolve_baseline", no_resolution)
    capture(home)
    with open_ledger(ledger_database_path(home), read_only=True) as connection:
        assert invalidation_epoch(connection, KEY) == 0
        assert not connection.execute("select is_stale from ledger_sources where source_key=?", (KEY,)).fetchone()[0]


def test_parent_repair_invalidation_and_normalization_roll_back_together(tmp_path, monkeypatch):
    home = tmp_path / "home"
    root, _, _ = corpus(home / "sessions", opening=120)
    ledger = ledger_database_path(home)
    capture(home)
    write_rows(root, [meta(history_mode="paginated"), tokens(101, ordinal=1)])
    capture(home)
    with open_ledger(ledger, read_only=True) as connection:
        revision = ledger_revision(connection)
    sync = rebuild.synchronize_parser_workset_in_transaction

    def fail_after_invalidation(connection):
        sync(connection)
        raise RuntimeError("synthetic post-normalization failure")

    with monkeypatch.context() as patch:
        patch.setattr(rebuild, "synchronize_parser_workset_in_transaction", fail_after_invalidation)
        with pytest.raises(RuntimeError, match="synthetic post-normalization"):
            finish(home, source_key=THREAD)
    with open_ledger(ledger, read_only=True) as connection:
        assert ledger_revision(connection) == revision
        assert invalidation_epoch(connection, KEY) == 0
        assert connection.execute("select error from files where file_key=?", (KEY,)).fetchone()[0] == ""
    assert finish(home, source_key=THREAD)[-1].complete
    with open_ledger(ledger, read_only=True) as connection:
        assert invalidation_epoch(connection, KEY) == 1


def test_changed_dependency_epoch_does_not_resume_the_old_child_stage(tmp_path):
    home = tmp_path / "home"
    root, page, _ = corpus(home / "sessions", opening=120)
    ledger = ledger_database_path(home)
    capture(home)
    write_rows(root, [meta(history_mode="paginated"), tokens(101, ordinal=1)])
    capture(home)
    finish(home, source_key=THREAD)
    first = rebuild.rebuild_stale_source_slice(home, KEY, max_bytes=384)
    assert not first.complete
    prior_stage = rebuild._staging_path(home, KEY, history_epoch=1)
    assert prior_stage.exists()
    write_rows(root, [meta(history_mode="paginated"), tokens(102, ordinal=1)])
    capture(home)
    finish(home, source_key=THREAD)
    with open_ledger(ledger, read_only=True) as connection:
        assert invalidation_epoch(connection, KEY) == 2
    assert finish(home, source_key=KEY)[-1].complete
    assert prior_stage.exists()
    assert not rebuild._staging_path(home, KEY, history_epoch=2).exists()
    assert sum(r.usage.total_tokens for r in load_ledger_records(ledger) if r.file_path == page) == 48


@pytest.mark.parametrize("defer", [False, True])
def test_growing_invalidated_child_remains_pending_until_authorized_repair(tmp_path, defer):
    home = tmp_path / "home"
    root, page, _ = corpus(home / "sessions", opening=120)
    ledger = ledger_database_path(home)
    capture(home)
    with open_ledger(ledger, read_only=True) as connection:
        checkpoint = load_parser_checkpoint(connection, KEY, page)
    with page.open("a") as handle:
        handle.write(json.dumps(tokens(160, ordinal=6)) + "\n")
    old_append = parse_session_append(page, checkpoint, stop_offset=page.stat().st_size)
    write_rows(root, [meta(history_mode="paginated"), tokens(101, ordinal=1)])
    capture(home)
    finish(home, source_key=THREAD)
    entry = next(entry for entry in collect_session_file_inventory([home / "sessions"], read_metadata=False) if entry.path == page)
    entry = replace(entry, file_key=KEY, file_key_is_fallback=False)
    with open_ledger(ledger) as connection:
        with pytest.raises(StaleAppendCheckpointError):
            assert_current_append_checkpoint(connection, file_key=KEY, path=page, expected=checkpoint)
        with pytest.raises(RuntimeError, match="cannot resume append"):
            append_file_generation(connection, [home / "sessions"], entry, old_append)
        before = load_parser_checkpoint(connection, KEY, page)
    capture(home, defer=defer)
    with open_ledger(ledger, read_only=True) as connection:
        assert pending_invalidation(connection, KEY)
        assert load_parser_checkpoint(connection, KEY, page) == before
    assert finish(home, source_key=KEY)[-1].complete
    with open_ledger(ledger, read_only=True) as connection:
        assert not pending_invalidation(connection, KEY)
    assert sum(r.usage.total_tokens for r in load_ledger_records(ledger) if r.file_path == page) == 59


@pytest.mark.parametrize("bad", ["malformed", 123, {}, [{"thread_id": "missing endpoints"}],
    [{"thread_id": THREAD, "end_ordinal_exclusive": 2, "end_byte_offset": 1}, None]])
def test_malformed_unrelated_dependencies_are_quarantined_without_blocking_repair(tmp_path, bad):
    home = tmp_path / "home"
    root, _, _ = corpus(home / "sessions", opening=120)
    unrelated = "44444444-4444-4444-8444-444444444444"
    write_rows(home / "sessions" / rollout_name(thread=unrelated), [meta(thread=unrelated), tokens(20)])
    ledger = ledger_database_path(home)
    capture(home)
    with open_ledger(ledger) as connection:
        state = json.loads(connection.execute("select state_json from parser_checkpoints where file_key=?", (unrelated,)).fetchone()[0])
        state["history_dependencies"] = bad
        connection.execute("update parser_checkpoints set state_json=? where file_key=?", (json.dumps(state), unrelated))
        connection.commit()
    write_rows(root, [meta(history_mode="paginated"), tokens(101, ordinal=1)])
    capture(home)
    assert finish(home, source_key=THREAD)[-1].complete
    with open_ledger(ledger, read_only=True) as connection:
        assert pending_invalidation(connection, unrelated)
        assert "history_dependencies_invalid" in connection.execute("select error from files where file_key=?", (unrelated,)).fetchone()[0]
        assert pending_invalidation(connection, KEY)
    assert finish(home, source_key=unrelated)[-1].complete
    with open_ledger(ledger, read_only=True) as connection:
        assert not pending_invalidation(connection, unrelated)


def test_dependency_epoch_and_pending_state_follow_an_ownership_rekey(tmp_path):
    home = tmp_path / "home"
    root, page, _ = corpus(home / "sessions", opening=120)
    ledger = ledger_database_path(home)
    capture(home)
    write_rows(root, [meta(history_mode="paginated"), tokens(101, ordinal=1)])
    capture(home)
    finish(home, source_key=THREAD)
    entry = next(entry for entry in collect_session_file_inventory([home / "sessions"], read_metadata=False) if entry.path == page)
    entry = replace(entry, file_key=KEY, file_key_is_fallback=False)
    replacement = replace(entry, file_key="synthetic-relocated-key")
    with open_ledger(ledger) as connection:
        rekey_file_generation(connection, entry, replacement)
        assert invalidation_epoch(connection, replacement.file_key) == 1
        assert pending_invalidation(connection, replacement.file_key)
        assert not pending_invalidation(connection, KEY)
        assert invalidation_epoch(connection, KEY) == 0


@pytest.mark.parametrize("error", ["", "ValueError: synthetic retained parse diagnostic"])
def test_pending_authority_survives_cleared_or_preserved_errors_and_allows_repair(tmp_path, error):
    home = tmp_path / "home"
    root, _, _ = corpus(home / "sessions", opening=120)
    ledger = ledger_database_path(home)
    capture(home)
    write_rows(root, [meta(history_mode="paginated"), tokens(101, ordinal=1)])
    capture(home)
    finish(home, source_key=THREAD)
    with open_ledger(ledger) as connection:
        connection.execute("update files set error=? where file_key=?", (error, KEY))
        connection.commit()
    synchronize_parser_workset(ledger)
    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute("select is_stale from ledger_sources where source_key=?", (KEY,)).fetchone()[0]
        assert connection.execute("select error from files where file_key=?", (KEY,)).fetchone()[0] == (error or "stale append checkpoint: history_dependency_changed")
    assert finish(home, source_key=KEY)[-1].complete
    assert load_ledger_status(ledger).coverage.stale_sources == 0


def test_pending_repair_cannot_be_rebound_to_another_replica_during_capture(tmp_path):
    home = tmp_path / "home"
    root, page, _ = corpus(home / "sessions", opening=120)
    ledger = ledger_database_path(home)
    capture(home)
    write_rows(root, [meta(history_mode="paginated"), tokens(101, ordinal=1)])
    capture(home)
    finish(home, source_key=THREAD)
    with open_ledger(ledger, read_only=True) as connection:
        before = tuple(connection.execute("select * from parser_checkpoints where file_key=?", (KEY,)).fetchone())
    clone = home / "sessions" / "mirror" / page.name
    clone.parent.mkdir()
    clone.write_bytes(page.read_bytes() + b"{}\n")
    capture(home)
    with open_ledger(ledger, read_only=True) as connection:
        assert tuple(connection.execute("select * from parser_checkpoints where file_key=?", (KEY,)).fetchone()) == before
        assert connection.execute("select path from files where file_key=?", (KEY,)).fetchone()[0] == str(page)
        assert pending_invalidation(connection, KEY)
    assert capture(home).stats.source_bytes_read == 0


def test_repair_refreshes_cached_reports_economics_credits_and_allowance_costs(tmp_path, monkeypatch):
    from dataclasses import asdict
    from datetime import UTC, datetime
    from codex_usage.agent_reports import PRICING_REVISION, render_ledger_report
    from codex_usage.aggregation import summarize_valued_records, value_records
    from codex_usage.allowance_index import indexed_allowance_report
    from codex_usage.allowance_models import QuotaObservation
    from codex_usage.allowance_queries import build_allowance_report
    from codex_usage.allowance_store import store_observations
    from codex_usage.parser import parse_session_files
    from codex_usage.project_economics import build_project_economics

    home = tmp_path / "home"
    root, _, _ = corpus(home / "sessions", opening=120)
    ledger = ledger_database_path(home)
    capture(home)
    now = datetime(2026, 10, 13, 3, tzinfo=UTC)
    with open_ledger(ledger) as connection:
        store_observations(connection, [QuotaObservation(f"2026-10-13T02:0{i}:00+00:00", "codex", "primary",
            "pro", i * 10, 10080, int(now.timestamp()) + 604800) for i in range(4)],
            source_key="synthetic-dependency", provenance="live")
        connection.commit()
        official = [tuple(row) for row in connection.execute("select * from quota_observations")]

    def render():
        return render_ledger_report(home, range_name="all", project_keys=[], theme="night",
                                    timezone_name="UTC", now=now)

    before = render()
    assert render().cache_hit
    write_rows(root, [meta(history_mode="paginated"), tokens(101, ordinal=1)])
    capture(home)
    finish(home, source_key=THREAD)
    assert render().status.coverage.stale_sources == 1
    finish(home, source_key=KEY)
    expected = value_records(parse_session_files(sorted((home / "sessions").rglob("*.jsonl"))))
    actual = value_records(load_ledger_records(ledger))
    assert summarize_valued_records(actual).to_dict() == summarize_valued_records(expected).to_dict()
    assert asdict(build_project_economics(actual)) == asdict(build_project_economics(expected))
    with open_ledger(ledger, read_only=True) as connection:
        full = build_allowance_report(connection)
        indexed = indexed_allowance_report(connection, ledger, revision=ledger_revision(connection),
            pricing_revision=PRICING_REVISION, coverage_complete=True, status=full["status"])
        assert indexed == full
        assert [tuple(row) for row in connection.execute("select * from quota_observations")] == official
    original_open = Path.open

    def no_history(path, *args, **kwargs):
        if path.suffix == ".jsonl":
            raise AssertionError("report invalidation cannot read raw histories")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", no_history)
    after = render()
    assert not after.cache_hit and after.ledger_revision > before.ledger_revision
    assert after.html != before.html and after.status.coverage.complete
    assert render().cache_hit
