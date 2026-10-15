"""Page identity, inherited baselines and cache/ledger coexistence."""
import json
import sqlite3
from dataclasses import replace
from uuid import UUID

from codex_usage.ledger_queries import load_ledger_records
from codex_usage.ledger_schema import open_ledger
from codex_usage.ledger_sync import synchronize_parser_workset
from codex_usage.parser import parse_session_files
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data
from codex_usage.session_cache_generations import replace_file_generation
from codex_usage.session_history import PAGE_KEY_PREFIX, HistoryBaseline
from codex_usage.session_inventory import collect_session_file_inventory
from codex_usage.models import TokenUsage
from codex_usage.parser import parse_session_generation

from test_paginated_history import THREAD, corpus, meta, rollout_name, tokens, write_rows


def test_full_cache_and_ledger_keep_legacy_and_page_as_distinct_sources(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    legacy, page, _ = corpus(sessions, 120)
    assert sum(r.usage.total_tokens for r in parse_session_files([legacy, page])) == 150
    inventory = collect_session_file_inventory([sessions])
    assert len(inventory) == 2
    assert len({entry.file_key for entry in inventory}) == 2
    cache = tmp_path / "cache"
    result = load_cached_session_data([sessions], cache_dir=cache, auto_transitions=False, max_workers=1)
    assert len(result.files) == 2
    assert not result.file_errors
    assert sum(r.usage.total_tokens for r in result.records) == 150
    database = cache / CACHE_DB_NAME
    with open_ledger(database):
        pass
    synchronize_parser_workset(database)
    assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 150
    with sqlite3.connect(database) as connection:
        keys = {row[0] for row in connection.execute("select source_key from ledger_sources")}
        assert THREAD in keys and len(keys) == 2
        assert sum(key.startswith(PAGE_KEY_PREFIX) for key in keys) == 1


def test_warm_and_append_capture_do_not_reopen_inherited_history(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    legacy, page, _ = corpus(sessions, 120)
    cache = tmp_path / "cache"
    first = load_cached_session_data([sessions], cache_dir=cache, auto_transitions=False, max_workers=1)
    assert not first.file_errors
    def forbid_resolution(*_args):
        raise AssertionError("warm/append capture resolved old history")
    monkeypatch.setattr("codex_usage.session_parser_incremental.resolve_baseline", forbid_resolution)
    warm = load_cached_session_data([sessions], cache_dir=cache, auto_transitions=False, max_workers=1)
    assert warm.stats.files_parsed == 0
    assert sum(r.usage.total_tokens for r in warm.records) == 150
    with page.open("a") as handle:
        handle.write(json.dumps(tokens(175, "2026-10-13T02:03:00Z")) + "\n")
    appended = load_cached_session_data([sessions], cache_dir=cache, auto_transitions=False, max_workers=1)
    assert appended.stats.files_appended == 1
    assert not appended.file_errors
    assert len(appended.files) == 2
    assert sum(r.usage.total_tokens for r in appended.records) == 175


def test_missing_baseline_is_retried_when_owned_history_appears(tmp_path):
    legacy, page, _ = corpus(tmp_path, 120)
    content = legacy.read_bytes()
    legacy.unlink()
    cache = tmp_path / "cache"
    first = load_cached_session_data([tmp_path], cache_dir=cache, auto_transitions=False, max_workers=1)
    assert not first.records
    assert any("paginated_history_source_unavailable" in error for error in first.file_errors.values())
    legacy.write_bytes(content)
    recovered = load_cached_session_data([tmp_path], cache_dir=cache, auto_transitions=False, max_workers=1)
    assert not recovered.file_errors
    assert sum(r.usage.total_tokens for r in recovered.records) == 150


def test_rebuilt_page_generation_does_not_append_the_inherited_prefix(tmp_path):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    legacy, page, base = corpus(sessions, 120)
    cache = tmp_path / "cache"
    first = load_cached_session_data([sessions], cache_dir=cache, auto_transitions=False, max_workers=1)
    assert sum(r.usage.total_tokens for r in first.records) == 150
    write_rows(page, [meta(stamp="2026-10-13T02:00:00Z", base=base),
        tokens(125, "2026-10-13T02:01:00Z"), tokens(175, "2026-10-13T02:02:00Z")])
    rebuilt = load_cached_session_data([sessions], cache_dir=cache, auto_transitions=False, max_workers=1)
    assert not rebuilt.file_errors
    assert sum(r.usage.total_tokens for r in rebuilt.records) == 175


def test_upgrade_source_rekeys_retire_aliases_but_retain_missing_history(tmp_path, monkeypatch):
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    legacy, page, _ = corpus(sessions, 120)
    database = tmp_path / "ledger.sqlite3"
    entries = collect_session_file_inventory([sessions], read_metadata=False)
    by_path = {entry.path: entry for entry in entries}
    # Reconstruct the old parser's loss of page metadata and inherited baseline
    # without changing the raw source header or its fingerprint.
    with monkeypatch.context() as patch:
        patch.setattr("codex_usage.session_parser_incremental.resolve_baseline",
            lambda *_: HistoryBaseline(TokenUsage(), 0, ""))
        old = parse_session_generation(page)
    metadata = replace(old.metadata, history_mode="", history_base=None)
    state = replace(old.checkpoint.state, metadata=metadata, root_metadata=metadata,
        history_baseline_pending=False, history_boundary_digest="")
    old = replace(old, metadata=metadata, checkpoint=replace(old.checkpoint, state=state))
    with open_ledger(database) as connection:
        replace_file_generation(connection, [sessions], by_path[legacy], parse_session_generation(legacy))
        replace_file_generation(connection, [sessions], replace(by_path[page],
            file_key=THREAD, file_key_is_fallback=False), old)
        connection.commit()
    synchronize_parser_workset(database)
    assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 250
    # Targeted upgrade forces this page through the corrected parser. Unchanged
    # unrelated generations remain reusable; no global parser reset is involved.
    with open_ledger(database) as connection:
        connection.execute("delete from parser_checkpoints where file_key=?", (THREAD,))
        connection.commit()
    for _ in range(2):
        result = load_cached_session_data([sessions], cache_database_path=database,
            auto_transitions=False, max_workers=1)
        assert not result.file_errors
        synchronize_parser_workset(database)
        assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 150
    # A physically missing page is retained, not confused with a source-key alias.
    page.unlink()
    load_cached_session_data([sessions], cache_database_path=database, auto_transitions=False, max_workers=1)
    synchronize_parser_workset(database)
    assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 150
    with sqlite3.connect(database) as connection:
        assert connection.execute("select count(*) from ledger_meta where key like 'source-key-relocation:%'").fetchone()[0] >= 1


def test_extra_history_budget_defers_pages_without_starving_later_work(tmp_path, monkeypatch):
    from codex_usage.session_history import HISTORY_READ_BUDGET

    sessions = tmp_path / "sessions"
    sessions.mkdir()
    for index in range(3):
        thread = str(UUID(int=index + 1))
        legacy = write_rows(sessions / rollout_name(thread), [
            meta(thread, history_mode="paginated"), tokens(100, ordinal=1)])
        base = {"thread_id": thread, "end_ordinal_exclusive": 2,
                "end_byte_offset": legacy.stat().st_size}
        write_rows(sessions / rollout_name(thread, str(UUID(int=index + 100))), [
            meta(thread, stamp="2026-10-13T02:00:00Z", base=base),
            tokens(120, "2026-10-13T02:01:00Z"), tokens(150, "2026-10-13T02:02:00Z")])
    # One page proof fits per batch. Unselected discovered sources must remain
    # pending, then drain as earlier successful pages become reusable.
    monkeypatch.setattr("codex_usage.session_history_requests.HISTORY_EXTRA_READ_BUDGET",
        HISTORY_READ_BUDGET + 10_000)
    cache = tmp_path / "cache"
    pending = []
    for _ in range(3):
        result = load_cached_session_data([sessions], cache_dir=cache,
            auto_transitions=False, max_workers=1)
        assert not result.file_errors
        pending.append(result.stats.pending_files)
    assert pending == [2, 1, 0]
    assert len(result.files) == 6
    assert sum(r.usage.total_tokens for r in result.records) == 450
