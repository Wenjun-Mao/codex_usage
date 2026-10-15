"""Replicas of one physical rollout share one cumulative parser checkpoint."""
import json

import pytest

from codex_usage.ledger_queries import load_ledger_records
from codex_usage.ledger_sync import synchronize_parser_workset
from codex_usage.ledger_schema import open_ledger
from codex_usage.session_cache import load_cached_session_data, refresh_cached_session_data

from test_paginated_history import corpus, tokens


def use_legacy_replica_accounting(patch):
    from codex_usage.session_replica_selection import ReplicaSelection

    patch.setattr("codex_usage.session_cache_refresh.select_replicas",
        lambda *_a, **_k: ReplicaSelection({}, 0, frozenset()))
    patch.setattr("codex_usage.ledger_sync.skip_proven_page_mirror", lambda *_: (False, False))
    patch.setattr("codex_usage.session_cache_refresh.reconcile_accounting", lambda *_: False)
    patch.setattr("codex_usage.ledger_sync.reconcile_accounting", lambda *_: False)


def capture(directories, database):
    result = load_cached_session_data(directories, cache_database_path=database,
        auto_transitions=False, max_workers=1)
    synchronize_parser_workset(database)
    return result, sum(r.usage.total_tokens for r in load_ledger_records(database))


def append(path, total):
    with path.open("a") as handle:
        handle.write(json.dumps(tokens(total, "2026-10-13T03:00:00Z", ordinal=6))+"\n")


@pytest.mark.parametrize("warm", [False, True])
def test_longest_compatible_replica_owns_the_complete_suffix(tmp_path, warm):
    sessions, archived = tmp_path / "sessions", tmp_path / "archived_sessions"
    _, page, _ = corpus(sessions)
    database = tmp_path / "ledger.sqlite3"
    directories = [sessions, archived]
    if warm:
        result, normalized = capture(directories, database)
        assert sum(r.usage.total_tokens for r in result.records) == normalized == 150
    archived.mkdir()
    mirror = archived / page.name
    mirror.write_bytes(page.read_bytes())
    append(mirror, 200)
    result, normalized = capture(directories, database)
    assert not result.file_errors
    assert sum(r.usage.total_tokens for r in result.records) == normalized == 200
    if warm:
        assert result.stats.files_appended == 1
    unchanged, normalized = capture(directories, database)
    assert not unchanged.file_errors
    assert sum(r.usage.total_tokens for r in unchanged.records) == normalized == 200
    assert unchanged.stats.source_bytes_read == 0


def test_conflicting_replica_retains_trusted_facts_and_names_the_gap(tmp_path):
    sessions, archived = tmp_path / "sessions", tmp_path / "archived_sessions"
    _, page, _ = corpus(sessions)
    database = tmp_path / "ledger.sqlite3"
    directories = [sessions, archived]
    capture(directories, database)
    archived.mkdir()
    mirror = archived / page.name
    mirror.write_bytes(page.read_bytes().replace(b'"total_tokens": 150', b'"total_tokens": 160'))
    append(mirror, 200)
    result, normalized = capture(directories, database)
    assert any("replica_prefix_conflict" in error for error in result.file_errors.values())
    assert sum(r.usage.total_tokens for r in result.records) == normalized == 150


def test_missing_longest_copy_does_not_replace_captured_usage_with_shorter_copy(tmp_path):
    sessions, archived = tmp_path / "sessions", tmp_path / "archived_sessions"
    _, page, _ = corpus(sessions)
    archived.mkdir()
    mirror = archived / page.name
    mirror.write_bytes(page.read_bytes())
    append(mirror, 200)
    database = tmp_path / "ledger.sqlite3"
    directories = [sessions, archived]
    capture(directories, database)
    mirror.unlink()
    for _ in range(2):
        result, normalized = capture(directories, database)
        assert any("shorter_than_retained_prefix" in error for error in result.file_errors.values())
        assert sum(r.usage.total_tokens for r in result.records) == normalized == 200


@pytest.mark.parametrize("missing_donor", [False, True])
def test_larger_legacy_fallback_generation_is_adopted_and_retired_once(tmp_path, monkeypatch, missing_donor):
    sessions, archived = tmp_path / "sessions", tmp_path / "archived_sessions"
    _, page, _ = corpus(sessions)
    archived.mkdir()
    mirror = archived / page.name
    mirror.write_bytes(page.read_bytes())
    append(mirror, 200)
    database = tmp_path / "ledger.sqlite3"
    directories = [sessions, archived]
    # Seed the former active-first, independently-normalized mirror state.
    with monkeypatch.context() as patch:
        use_legacy_replica_accounting(patch)
        _, normalized = capture(directories, database)
        assert normalized == 250
    if missing_donor:
        # Another available copy covers the retained donor, but not its path.
        page.write_bytes(mirror.read_bytes())
        mirror.unlink()
    for index in range(2):
        result, normalized = capture(directories, database)
        assert not result.file_errors
        assert sum(r.usage.total_tokens for r in result.records) == normalized == 200
        if index:
            assert result.stats.source_bytes_read == 0
    with open_ledger(database, read_only=True) as connection:
        assert connection.execute("""select count(*) from ledger_meta
            where key like 'source-mirror:%' or key like 'source-key-relocation:%'""").fetchone()[0] == 1


def test_partial_checkpoint_can_handoff_again_without_replaying_its_prefix(tmp_path):
    sessions, archived = tmp_path / "sessions", tmp_path / "archived_sessions"
    _, page, _ = corpus(sessions)
    database = tmp_path / "ledger.sqlite3"
    directories = [sessions, archived]
    capture(directories, database)
    archived.mkdir()
    mirror = archived / page.name
    mirror.write_bytes(page.read_bytes())
    append(mirror, 175)
    append(mirror, 200)
    first = refresh_cached_session_data(directories, cache_database_path=database,
        auto_transitions=False, max_workers=1, max_parse_bytes=1)
    assert first.stats.files_appended == first.stats.pending_files == 1
    synchronize_parser_workset(database)
    assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 175
    newer = sessions / "newer" / page.name
    newer.parent.mkdir()
    newer.write_bytes(mirror.read_bytes())
    append(newer, 225)
    for total in (200, 225):
        outcome = refresh_cached_session_data(directories, cache_database_path=database,
            auto_transitions=False, max_workers=1, max_parse_bytes=1)
        assert outcome.stats.files_appended == 1
        synchronize_parser_workset(database)
        assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == total
    warm, normalized = capture(directories, database)
    assert sum(r.usage.total_tokens for r in warm.records) == normalized == 225
    assert warm.stats.source_bytes_read == 0


def test_replica_validation_shares_the_existing_history_read_budget(tmp_path, monkeypatch):
    sessions, archived = tmp_path / "sessions", tmp_path / "archived_sessions"
    _, page, _ = corpus(sessions)
    database = tmp_path / "ledger.sqlite3"
    directories = [sessions, archived]
    capture(directories, database)
    archived.mkdir()
    mirror = archived / page.name
    mirror.write_bytes(page.read_bytes())
    append(mirror, 200)
    with monkeypatch.context() as patch:
        patch.setattr("codex_usage.session_history_requests.HISTORY_EXTRA_READ_BUDGET", 100)
        blocked, normalized = capture(directories, database)
        assert blocked.stats.source_bytes_read <= 100
        assert any("replica_read_budget" in error for error in blocked.file_errors.values())
        assert sum(r.usage.total_tokens for r in blocked.records) == normalized == 150
    recovered, normalized = capture(directories, database)
    assert not recovered.file_errors
    assert sum(r.usage.total_tokens for r in recovered.records) == normalized == 200


def test_original_physical_root_replica_is_not_confused_with_a_secondary_page(tmp_path):
    sessions, archived = tmp_path / "sessions", tmp_path / "archived_sessions"
    root, _, _ = corpus(sessions)
    archived.mkdir()
    mirror = archived / root.name
    mirror.write_bytes(root.read_bytes())
    append(mirror, 150)
    result, normalized = capture([sessions, archived], tmp_path / "ledger.sqlite3")
    assert not result.file_errors
    assert sum(r.usage.total_tokens for r in result.records) == normalized == 200


def test_unchanged_replica_set_never_reopens_headers_or_prefixes(tmp_path, monkeypatch):
    sessions, archived = tmp_path / "sessions", tmp_path / "archived_sessions"
    _, page, _ = corpus(sessions)
    archived.mkdir()
    mirror = archived / page.name
    mirror.write_bytes(page.read_bytes())
    append(mirror, 200)
    directories, database = [sessions, archived], tmp_path / "ledger.sqlite3"
    capture(directories, database)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("unchanged physical replicas reopened historical evidence")

    for function in ("read_session_metadata_bounded", "capture_prefix", "prove_prefixes"):
        monkeypatch.setattr("codex_usage.session_replica_selection."+function, forbidden)
    result, normalized = capture(directories, database)
    assert not result.file_errors
    assert sum(r.usage.total_tokens for r in result.records) == normalized == 200


def test_uncovered_missing_legacy_fallback_is_not_falsely_retired(tmp_path, monkeypatch):
    sessions, archived = tmp_path / "sessions", tmp_path / "archived_sessions"
    _, page, _ = corpus(sessions)
    archived.mkdir()
    mirror = archived / page.name
    mirror.write_bytes(page.read_bytes())
    append(mirror, 200)
    database = tmp_path / "ledger.sqlite3"
    directories = [sessions, archived]
    with monkeypatch.context() as patch:
        use_legacy_replica_accounting(patch)
        capture(directories, database)
    mirror.unlink()
    blocked, _ = capture(directories, database)
    assert any("shorter_than_retained_prefix" in error for error in blocked.file_errors.values())
    with open_ledger(database, read_only=True) as connection:
        # This is an explicitly unqualified overlap, not authority to drop the
        # missing copy's longer captured suffix or claim repaired totals.
        assert connection.execute("select count(*) from parser_checkpoints").fetchone()[0] == 3
        assert connection.execute("select count(*) from ledger_meta where key like 'source-mirror:%'").fetchone()[0] == 0


@pytest.mark.parametrize("handoff", [False, True])
def test_alias_obligation_survives_append_before_normalization(tmp_path, monkeypatch, handoff):
    sessions, archived = tmp_path / "sessions", tmp_path / "archived_sessions"
    _, page, _ = corpus(sessions)
    archived.mkdir()
    mirror = archived / page.name
    mirror.write_bytes(page.read_bytes())
    append(mirror, 200)
    database = tmp_path / "ledger.sqlite3"
    directories = [sessions, archived]
    with monkeypatch.context() as patch:
        use_legacy_replica_accounting(patch)
        capture(directories, database)
    page.write_bytes(mirror.read_bytes())
    mirror.unlink()
    # Adopt the donor's complete cached generation, but delay normalization.
    load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
    if handoff:
        newer = sessions / "newer" / page.name
        newer.parent.mkdir()
        newer.write_bytes(page.read_bytes())
        page.unlink()
        page = newer
    append(page, 225)
    load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
    append(page, 250)
    result, normalized = capture(directories, database)
    assert not result.file_errors
    assert sum(r.usage.total_tokens for r in result.records) == normalized == 250
    warm, normalized = capture(directories, database)
    assert not warm.file_errors
    assert sum(r.usage.total_tokens for r in warm.records) == normalized == 250
    assert warm.stats.source_bytes_read == 0
