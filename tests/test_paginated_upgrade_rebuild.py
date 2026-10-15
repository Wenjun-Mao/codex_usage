"""A staged accounting upgrade can replace an old logical ownership slot."""
from dataclasses import asdict, replace
import os
import json
import sqlite3

import pytest

import codex_usage.agent_rebuild as rebuild
from codex_usage.agent_paths import ledger_database_path
from codex_usage.ledger_queries import load_ledger_records, load_ledger_status
from codex_usage.ledger_schema import ledger_revision, open_ledger
from codex_usage.ledger_sync import synchronize_parser_workset
from codex_usage.models import TokenUsage
from codex_usage.parser import parse_session_files, parse_session_generation
from codex_usage.pricing import estimate_codex_credits, estimate_cost
from codex_usage.session_cache_generations import rekey_file_generation, replace_file_generation
from codex_usage.session_cache_store import record_file_stale
from codex_usage.session_history import HistoryBaseline
from codex_usage.session_inventory import collect_session_file_inventory
from test_paginated_history import PAGE, THREAD, corpus, meta, tokens, write_rows


def old_logical_capture(tmp_path, monkeypatch):
    home = tmp_path / "codex"
    sessions = home / "sessions"
    root, page, _ = corpus(sessions, opening=120)
    ledger = ledger_database_path(home)
    entries = {entry.path: entry for entry in collect_session_file_inventory([sessions], read_metadata=False)}
    with monkeypatch.context() as patch:
        patch.setattr("codex_usage.session_parser_incremental.resolve_baseline",
                      lambda *_: HistoryBaseline(TokenUsage(), 0, ""))
        old = parse_session_generation(page)
    metadata = replace(old.metadata, history_mode="", history_base=None)
    state = replace(old.checkpoint.state, metadata=metadata, root_metadata=metadata,
                    history_baseline_pending=False, history_boundary_digest="")
    old = replace(old, metadata=metadata, checkpoint=replace(old.checkpoint, state=state))
    entry = replace(entries[page], file_key=THREAD, file_key_is_fallback=False)
    with open_ledger(ledger) as connection:
        replace_file_generation(connection, [sessions], entries[root], parse_session_generation(root))
        replace_file_generation(connection, [sessions], entry, old)
        connection.commit()
    synchronize_parser_workset(ledger)
    assert total(ledger) == 250
    with open_ledger(ledger) as connection:
        record_file_stale(connection, [sessions], entry, "paginated_history_accounting_upgrade_required")
        connection.commit()
    synchronize_parser_workset(ledger)
    return home, ledger, page


def total(ledger):
    return sum(record.usage.total_tokens for record in load_ledger_records(ledger))


def finish(home, *, max_bytes=384, source_key=THREAD):
    outcomes = []
    for _ in range(32):
        result = rebuild.rebuild_stale_source_slice(home, source_key, max_bytes=max_bytes)
        outcomes.append(result)
        if result.complete:
            return outcomes
    raise AssertionError("staged physical-key upgrade did not converge")


def test_old_logical_owner_advances_under_the_discovered_physical_key(tmp_path, monkeypatch):
    home, ledger, page = old_logical_capture(tmp_path, monkeypatch)
    with open_ledger(ledger, read_only=True) as connection:
        old_events = [tuple(row) for row in connection.execute("select * from ledger_usage_events")]
    first = rebuild.rebuild_stale_source_slice(home, THREAD, max_bytes=384)
    assert not first.complete and first.captured_bytes > 0
    assert total(ledger) == 250
    outcomes = [first, *finish(home)]
    assert all(b.captured_bytes > a.captured_bytes for a, b in zip(outcomes, outcomes[1:]))
    assert outcomes[-1].complete
    assert total(ledger) == 150
    assert load_ledger_status(ledger).coverage.stale_sources == 0
    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute("select file_key from files where path=?", (str(page),)).fetchone()[0] == f"codex-usage:page:{PAGE}"
        assert all(tuple(row) in [tuple(r) for r in connection.execute("select * from ledger_usage_events")]
                   for row in old_events)
        receipt = json.loads(connection.execute("select value from ledger_meta where key like 'source-rebuild:%'").fetchone()[0])
        assert len(receipt["origin_fingerprint"]) == len(receipt["header_fingerprint"]) == 64
        assert receipt["history_boundary_digest"]
        assert connection.execute("select count(*) from schema_meta where key=?", (f"paginated-physical:{PAGE}",)).fetchone()[0] == 1
    assert not rebuild._staging_path(home, THREAD).exists()


@pytest.mark.parametrize("failure_stage", ["copy", "normalization"])
def test_rebuild_copy_and_normalization_commit_atomically_and_retry_after_failure(tmp_path, monkeypatch, failure_stage):
    home, ledger, _ = old_logical_capture(tmp_path, monkeypatch)
    with open_ledger(ledger, read_only=True) as connection:
        before_revision = ledger_revision(connection)
    observed = []
    name = "_replace_workset_rows" if failure_stage == "copy" else "synchronize_parser_workset_in_transaction"
    original = getattr(rebuild, name)

    def fail_after_copy(connection, *args):
        original(connection, *args)
        observed.append(total(ledger))
        raise RuntimeError("synthetic failure before normalized accounting")

    with monkeypatch.context() as patch:
        patch.setattr(rebuild, name, fail_after_copy)
        with pytest.raises(RuntimeError, match="synthetic failure"):
            finish(home)
    assert observed == [250]
    assert total(ledger) == 250
    with open_ledger(ledger, read_only=True) as connection:
        assert ledger_revision(connection) == before_revision
        assert connection.execute("select count(*) from files where file_key=?", (THREAD,)).fetchone()[0] == 1
    assert rebuild._staging_path(home, THREAD).exists()
    assert finish(home)[-1].complete
    assert total(ledger) == 150


def test_same_key_same_row_count_semantic_repair_replaces_normalized_values(tmp_path, monkeypatch):
    home, ledger, page = old_logical_capture(tmp_path, monkeypatch)
    key = f"codex-usage:page:{PAGE}"
    entry = next(entry for entry in collect_session_file_inventory([home / "sessions"], read_metadata=False)
                 if entry.path == page)
    with open_ledger(ledger) as connection:
        rekey_file_generation(connection, replace(entry, file_key=THREAD), replace(entry, file_key=key))
        # Reproduce an already-normalized physical key with old parser semantics.
        connection.execute("update ledger_sources set source_key=? where source_key=?", (key, THREAD))
        connection.commit()
    synchronize_parser_workset(ledger)
    assert total(ledger) == 250
    with open_ledger(ledger, read_only=True) as connection:
        before = tuple(connection.execute("""select g.generation_id, g.record_count
            from ledger_generations g join ledger_sources s using(source_id)
            where s.source_key=? and g.status='trusted'""", (key,)).fetchone())
    assert finish(home, source_key=key)[-1].complete
    assert total(ledger) == 150
    with open_ledger(ledger, read_only=True) as connection:
        after = tuple(connection.execute("""select g.generation_id, g.record_count
            from ledger_generations g join ledger_sources s using(source_id)
            where s.source_key=? and g.status='trusted'""", (key,)).fetchone())
        assert after[0] != before[0] and after[1] == before[1]
        assert connection.execute("select status from ledger_generations where generation_id=?", (before[0],)).fetchone()[0] == "superseded"


def test_identity_target_with_retained_facts_is_not_overwritten(tmp_path, monkeypatch):
    home, ledger, _ = old_logical_capture(tmp_path, monkeypatch)
    with open_ledger(ledger) as connection:
        connection.execute("""insert into files
            select ?, path || '.other', session_dir, storage_state, size_bytes,
                mtime_ns, parsed_at, last_seen_at, missing_since, is_missing, session_id, error
            from files where file_key=?""", (f"codex-usage:page:{PAGE}", THREAD))
        connection.commit()
    with pytest.raises(RuntimeError, match="identity target"):
        finish(home)
    assert total(ledger) == 250
    assert rebuild._staging_path(home, THREAD).exists()


def test_identity_target_with_only_normalized_evidence_is_not_overwritten(tmp_path, monkeypatch):
    home, ledger, _ = old_logical_capture(tmp_path, monkeypatch)
    key = f"codex-usage:page:{PAGE}"
    with open_ledger(ledger) as connection:
        source = dict(connection.execute("select * from ledger_sources where source_key=?", (THREAD,)).fetchone())
        source.pop("source_id")
        source.update(source_key=key, is_missing=1)
        columns = ",".join(source)
        values = ",".join("?" for _ in source)
        destination = connection.execute(f"insert into ledger_sources ({columns}) values ({values})", tuple(source.values())).lastrowid
        generation = dict(connection.execute("""select g.* from ledger_generations g
            join ledger_sources s using(source_id) where s.source_key=? and g.status='trusted'""", (THREAD,)).fetchone())
        old_id = generation.pop("generation_id")
        generation.update(source_id=destination, status="staging")
        columns = ",".join(generation)
        values = ",".join("?" for _ in generation)
        retained_id = connection.execute(f"insert into ledger_generations ({columns}) values ({values})", tuple(generation.values())).lastrowid
        for row in connection.execute("select * from ledger_usage_events where generation_id=?", (old_id,)).fetchall():
            event = dict(row)
            event.pop("event_id")
            event["generation_id"] = retained_id
            columns = ",".join(event)
            values = ",".join("?" for _ in event)
            connection.execute(f"insert into ledger_usage_events ({columns}) values ({values})", tuple(event.values()))
        connection.commit()
    with pytest.raises(RuntimeError, match="identity target"):
        finish(home)
    assert total(ledger) == 250
    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute("select count(*) from ledger_usage_events where generation_id=?", (retained_id,)).fetchone()[0] == 2
        assert connection.execute("select count(*) from files where file_key=?", (key,)).fetchone()[0] == 0


@pytest.mark.parametrize("change", ["append", "rewrite_with_restored_mtime"])
def test_source_change_during_install_rolls_back_the_accounting_swap(tmp_path, monkeypatch, change):
    home, ledger, page = old_logical_capture(tmp_path, monkeypatch)
    original_copy = rebuild._replace_workset_rows

    def append_after_copy(connection, *args):
        original_copy(connection, *args)
        if change == "append":
            with page.open("ab") as handle:
                handle.write(b"{}\n")
        else:
            before = page.stat()
            page.write_bytes(page.read_bytes().replace(b'"total_tokens": 120', b'"total_tokens": 121'))
            os.utime(page, ns=(before.st_atime_ns, before.st_mtime_ns))

    monkeypatch.setattr(rebuild, "_replace_workset_rows", append_after_copy)
    with pytest.raises((OSError, RuntimeError), match="source changed"):
        finish(home)
    assert total(ledger) == 250
    with sqlite3.connect(ledger) as connection:
        assert connection.execute("select count(*) from files where file_key=?", (THREAD,)).fetchone()[0] == 1


def test_shorter_paginated_source_cannot_discard_a_retained_suffix(tmp_path, monkeypatch):
    home, ledger, page = old_logical_capture(tmp_path, monkeypatch)
    lines = page.read_bytes().splitlines(keepends=True)
    page.write_bytes(b"".join(lines[:-1]))
    with pytest.raises(RuntimeError, match="does not cover retained capture"):
        finish(home)
    assert total(ledger) == 250
    assert rebuild._staging_path(home, THREAD).exists()


def test_quota_cache_follows_the_staged_key_without_mutating_account_readings(tmp_path, monkeypatch):
    home, ledger, _ = old_logical_capture(tmp_path, monkeypatch)
    first = rebuild.rebuild_stale_source_slice(home, THREAD, max_bytes=384)
    assert not first.complete
    key = f"codex-usage:page:{PAGE}"
    with sqlite3.connect(rebuild._staging_path(home, THREAD)) as connection:
        connection.execute("insert into quota_cache values (?,?,?)", (key, "synthetic-retained", "{}"))
    with open_ledger(ledger, read_only=True) as connection:
        before = {table: [tuple(row) for row in connection.execute(f"select * from {table}")]
                  for table in ("quota_reads", "quota_observations", "quota_provenance", "credit_observations")}
    assert finish(home)[-1].complete
    with open_ledger(ledger, read_only=True) as connection:
        assert tuple(connection.execute("select * from quota_cache where observation_key='synthetic-retained'").fetchone()) == (key, "synthetic-retained", "{}")
        assert {table: [tuple(row) for row in connection.execute(f"select * from {table}")]
                for table in before} == before


def test_rebuilt_response_context_components_and_prices_match_direct_parser(tmp_path, monkeypatch):
    home, ledger, _ = old_logical_capture(tmp_path, monkeypatch)
    expected = parse_session_files(sorted((home / "sessions").rglob("*.jsonl")))
    assert finish(home)[-1].complete
    actual = load_ledger_records(ledger)
    def ordered(records):
        return sorted(records, key=lambda record: (record.timestamp, record.file_path))

    assert list(map(asdict, ordered(actual))) == list(map(asdict, ordered(expected)))
    for price in (estimate_cost, estimate_codex_credits):
        assert [price(record.usage, record.model, record.timestamp) for record in ordered(actual)] == [
            price(record.usage, record.model, record.timestamp) for record in ordered(expected)]


def test_errored_stage_with_retained_complete_checkpoint_cannot_retire_accounting(tmp_path, monkeypatch):
    home, ledger, page = old_logical_capture(tmp_path, monkeypatch)
    with monkeypatch.context() as patch:
        def failed_install(*_args):
            raise RuntimeError("synthetic install refusal")

        patch.setattr(rebuild, "_replace_workset_rows", failed_install)
        with pytest.raises(RuntimeError, match="synthetic install refusal"):
            finish(home)
    root = next(path for path in (home / "sessions").rglob("*.jsonl") if path != page)
    original = root.read_bytes()
    root.unlink()
    before = page.stat()
    os.utime(page, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
    with pytest.raises(RuntimeError, match="staged capture"):
        rebuild.rebuild_stale_source_slice(home, THREAD, max_bytes=384)
    assert total(ledger) == 250
    assert rebuild._staging_path(home, THREAD).exists()
    root.write_bytes(original)
    assert finish(home)[-1].complete
    assert total(ledger) == 150


@pytest.mark.parametrize("replacement_thread", [THREAD, "33333333-3333-4333-8333-333333333333"])
def test_cross_slice_header_identity_change_does_not_inherit_rebuild_authority(tmp_path, monkeypatch, replacement_thread):
    home, ledger, page = old_logical_capture(tmp_path, monkeypatch)
    first = rebuild.rebuild_stale_source_slice(home, THREAD, max_bytes=384)
    assert not first.complete and first.captured_bytes
    write_rows(page, [meta(thread=replacement_thread), tokens(40)])
    for _ in range(2):
        with pytest.raises(RuntimeError, match="staged capture identity"):
            finish(home)
        assert total(ledger) == 250
    with open_ledger(ledger, read_only=True) as connection:
        assert connection.execute("select count(*) from ledger_meta where key like 'source-rebuild:%'").fetchone()[0] == 0
