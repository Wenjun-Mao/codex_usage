"""A missing physical copy is retained evidence, not another consumed stream."""
import pytest
from dataclasses import fields, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from codex_usage.aggregation import RangeBounds
from codex_usage.ledger_queries import load_ledger_records, load_ledger_status
from codex_usage.ledger_schema import open_ledger
from codex_usage.ledger_sync import synchronize_parser_workset
from codex_usage.session_cache import load_cached_session_data

from test_paginated_history import corpus
from test_paginated_replicas import append, use_legacy_replica_accounting
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.replica_accounting_proof import fact


def legacy_overlap(tmp_path, monkeypatch, *, normalize=True, primary=False):
    sessions, archived = tmp_path / "sessions", tmp_path / "archived_sessions"
    root, page, _ = corpus(sessions)
    page = root if primary else page
    archived.mkdir()
    mirror = archived / page.name
    mirror.write_bytes(page.read_bytes())
    append(mirror, 150 if primary else 200)
    database = tmp_path / "ledger.sqlite3"
    directories = [sessions, archived]
    with monkeypatch.context() as patch:
        use_legacy_replica_accounting(patch)
        load_cached_session_data(directories, cache_database_path=database,
            auto_transitions=False, max_workers=1)
        if normalize:
            synchronize_parser_workset(database)
    if normalize:
        assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == (300 if primary else 250)
    return directories, database, page, mirror


@pytest.mark.parametrize("all_missing", [False, True])
def test_retained_complete_accounting_prefix_is_not_an_additive_charge(tmp_path, monkeypatch, all_missing):
    directories, database, page, mirror = legacy_overlap(tmp_path, monkeypatch)
    mirror.unlink()
    if all_missing:
        page.unlink()
    for bounds in (None, RangeBounds(None, None), RangeBounds(0, 2**63-1)):
        result = load_cached_session_data(directories, cache_database_path=database,
            auto_transitions=False, max_workers=1, range_bounds=bounds)
        synchronize_parser_workset(database)
        assert sum(r.usage.total_tokens for r in result.records) == 200
        assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 200
    with open_ledger(database, read_only=True) as connection:
        # Neither old normalized generation is deleted to make totals match.
        assert connection.execute("select count(*) from ledger_generations").fetchone()[0] >= 3


@pytest.mark.parametrize("change", ["model", "cached_split", "timestamp", "turn", "missing_index",
                                  "normalized_only", "lineage", "partial", "images"])
def test_incomparable_or_incomplete_facts_are_retained_but_not_added(tmp_path, monkeypatch, change):
    directories, database, page, mirror = legacy_overlap(tmp_path, monkeypatch)
    page.unlink()
    mirror.unlink()
    with open_ledger(database) as connection:
        key = connection.execute("select file_key from files where path=?", (str(mirror),)).fetchone()[0]
        generation = connection.execute("""select g.generation_id from ledger_generations g
            join ledger_sources s using(source_id) where s.source_key=? and status='trusted'""", (key,)).fetchone()[0]
        if change in {"model", "cached_split", "timestamp", "turn"}:
            cache_update, normalized_update = {
                "model": ("model='different-model'", "model_id=(select model_id from ledger_models where model_key='different-model')"),
                "cached_split": ("cached_input_tokens=cached_input_tokens-1", "cached_input_tokens=cached_input_tokens-1"),
                "timestamp": ("timestamp='2026-10-13T02:02:01+00:00',timestamp_us=timestamp_us+1000000",
                              "timestamp='2026-10-13T02:02:01+00:00',timestamp_us=timestamp_us+1000000"),
                "turn": ("turn_id='different-turn'", "turn_id='different-turn'"),
            }[change]
            connection.execute("insert or ignore into ledger_models(model_key) values ('different-model')")
            connection.execute(f"update usage_records set {cache_update} where file_key=? and record_index=0", (key,))
            connection.execute(f"update ledger_usage_events set {normalized_update} where generation_id=? and source_record_index=0",
                               (generation,))
        elif change == "missing_index":
            connection.execute("delete from usage_records where file_key=? and record_index=0", (key,))
        elif change == "normalized_only":
            connection.execute("update ledger_usage_events set cached_input_tokens=cached_input_tokens-1 where generation_id=?",
                               (generation,))
        elif change == "lineage":
            connection.execute("update parser_checkpoints set state_json=json_set(state_json,'$.history_boundary_digest','different') where file_key=?", (key,))
        elif change == "partial":
            connection.execute("update parser_checkpoints set state_json=json_set(state_json,'$.row_drain',json('{\"pending\":true}')) where file_key=?", (key,))
        else:
            connection.execute("""insert into image_operations(file_key,tool_call_id,timestamp,timestamp_us,task_id,
                root_task_id,usage_role,turn_id,project_key,project_label,kind,outcome,output_count,
                output_format,quality,evidence_json,usage_json)
                values (?,'image','2026-10-13T03:00:00Z',0,'task','task','root','turn','project','project',
                    'generate','succeeded',1,'png','auto','{}','{}')""", (key,))
        connection.commit()
    generations = None
    for _ in range(2):
        result = load_cached_session_data(directories, cache_database_path=database,
            auto_transitions=False, max_workers=1)
        synchronize_parser_workset(database)
        assert any("paginated_accounting_" in error for error in result.file_errors.values())
        assert sum(r.usage.total_tokens for r in result.records) == 100
        assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 100
        assert load_ledger_status(database).coverage.stale_sources >= 2
        with open_ledger(database, read_only=True) as connection:
            assert connection.execute("select count(*) from parser_checkpoints").fetchone()[0] == 3
            assert connection.execute("select count(*) from ledger_usage_events").fetchone()[0] == 4
            count = connection.execute("select count(*) from ledger_generations").fetchone()[0]
            assert generations is None or generations == count
            generations = count


def test_normalized_fact_change_under_same_generation_id_invalidates_authority(tmp_path, monkeypatch):
    directories, database, page, mirror = legacy_overlap(tmp_path, monkeypatch)
    page.unlink()
    mirror.unlink()
    load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
    synchronize_parser_workset(database)
    before = load_ledger_status(database).revision
    with open_ledger(database) as connection:
        generation = connection.execute("""select g.generation_id from ledger_generations g join ledger_sources s using(source_id)
            where s.path=? and g.status='trusted'""", (str(mirror),)).fetchone()[0]
        connection.execute("update ledger_usage_events set cached_input_tokens=cached_input_tokens-1 where generation_id=?",
                           (generation,))
        connection.commit()
    synchronize_parser_workset(database)
    assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 100
    assert load_ledger_status(database).revision > before
    assert load_ledger_status(database).coverage.stale_sources >= 2


def test_accounting_selection_does_not_rebind_checkpoints_and_recovers_by_raw_proof(tmp_path, monkeypatch):
    directories, database, page, mirror = legacy_overlap(tmp_path, monkeypatch)
    body = mirror.read_bytes()
    with open_ledger(database, read_only=True) as connection:
        before = [tuple(row) for row in connection.execute("select * from parser_checkpoints order by file_key")]
    mirror.unlink()
    result = load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
    synchronize_parser_workset(database)
    assert sum(r.usage.total_tokens for r in result.records) == 200
    with open_ledger(database, read_only=True) as connection:
        assert [tuple(row) for row in connection.execute("select * from parser_checkpoints order by file_key")] == before
    page.write_bytes(body)
    append(page, 225)
    recovered = load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
    synchronize_parser_workset(database)
    assert not recovered.file_errors
    assert sum(r.usage.total_tokens for r in recovered.records) == 225
    assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 225
    assert load_ledger_status(database).coverage.complete


def test_forced_normalized_rebuild_keeps_superseded_accounting_evidence(tmp_path, monkeypatch):
    directories, database, page, mirror = legacy_overlap(tmp_path, monkeypatch)
    page.unlink()
    mirror.unlink()
    load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
    synchronize_parser_workset(database)
    with open_ledger(database, read_only=True) as connection:
        before = [tuple(row) for row in connection.execute("""select e.* from ledger_usage_events e
            join ledger_generations g using(generation_id) where g.status='superseded' order by event_id""")]
    synchronize_parser_workset(database, force_normalized_ownership=True)
    assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 200
    with open_ledger(database, read_only=True) as connection:
        after = [tuple(row) for row in connection.execute("""select e.* from ledger_usage_events e
            join ledger_generations g using(generation_id) where g.status='superseded' order by event_id""")]
        assert after == before and after


@pytest.mark.parametrize("quarantined", [False, True])
def test_unchanged_accounting_decision_does_not_invalidate_ledger_revision(tmp_path, monkeypatch, quarantined):
    directories, database, page, mirror = legacy_overlap(tmp_path, monkeypatch)
    page.unlink()
    mirror.unlink()
    if quarantined:
        with open_ledger(database) as connection:
            key = connection.execute("select file_key from files where path=?", (str(mirror),)).fetchone()[0]
            connection.execute("update usage_records set cached_input_tokens=cached_input_tokens-1 where file_key=?", (key,))
            connection.commit()
    load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
    synchronize_parser_workset(database)
    before = load_ledger_status(database).revision
    warm = load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
    synchronize_parser_workset(database)
    assert warm.stats.source_bytes_read == 0
    assert load_ledger_status(database).revision == before


@pytest.mark.parametrize("established", [False, True])
@pytest.mark.parametrize("selected_member", [False, True])
@pytest.mark.parametrize("malformed", ["missing_checkpoint", "identity", "invalid_json"])
def test_malformed_members_never_disappear_from_accounting_obligations(
        tmp_path, monkeypatch, established, selected_member, malformed):
    directories, database, page, mirror = legacy_overlap(tmp_path, monkeypatch)
    page.unlink()
    mirror.unlink()
    if established:
        load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
        synchronize_parser_workset(database)
    target = mirror if selected_member else page
    with open_ledger(database) as connection:
        key = connection.execute("select file_key from files where path=?", (str(target),)).fetchone()[0]
        if malformed == "missing_checkpoint":
            connection.execute("delete from parser_checkpoints where file_key=?", (key,))
        elif malformed == "identity":
            connection.execute("update parser_checkpoints set state_json=json_set(state_json,'$.root_metadata.session_id','wrong') where file_key=?", (key,))
        else:
            connection.execute("update parser_checkpoints set state_json='not-json' where file_key=?", (key,))
        connection.commit()
    for _ in range(2):
        result = load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
        synchronize_parser_workset(database)
        expected = 200 if established and not selected_member else 100
        assert sum(r.usage.total_tokens for r in result.records) == expected
        assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == expected
        assert any("accounting_" in error for error in result.file_errors.values())


def test_rebuild_cannot_erase_an_unresolved_normalized_conflict(tmp_path, monkeypatch):
    directories, database, page, mirror = legacy_overlap(tmp_path, monkeypatch)
    page.unlink()
    mirror.unlink()
    load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
    synchronize_parser_workset(database)
    with open_ledger(database) as connection:
        generation = connection.execute("""select generation_id from ledger_generations g join ledger_sources s using(source_id)
            where s.path=? and status='trusted'""", (str(mirror),)).fetchone()[0]
        connection.execute("update ledger_usage_events set cached_input_tokens=cached_input_tokens-1 where generation_id=?", (generation,))
        before = [tuple(row) for row in connection.execute("select * from ledger_usage_events where generation_id=? order by event_id", (generation,))]
        connection.commit()
    synchronize_parser_workset(database, force_normalized_ownership=True)
    assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 100
    with open_ledger(database, read_only=True) as connection:
        assert [tuple(row) for row in connection.execute("select * from ledger_usage_events where generation_id=? order by event_id", (generation,))] == before


def test_missing_cache_capture_normalizes_in_one_sync_without_a_prior_receipt(tmp_path, monkeypatch):
    directories, database, page, mirror = legacy_overlap(tmp_path, monkeypatch, normalize=False)
    page.unlink()
    mirror.unlink()
    with open_ledger(database) as connection:
        connection.execute("update files set is_missing=1 where path in (?,?)", (str(page), str(mirror)))
        connection.commit()
    synchronize_parser_workset(database)
    assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 200


def test_financial_projection_covers_every_nondisplay_record_field():
    record = UsageRecord(datetime(2026, 10, 13, tzinfo=UTC), TokenUsage(), "task", Path("source"), "root")
    baseline = fact(record)
    for field in fields(record):
        if field.name in {"file_path", "project_label", "project_previous_label"}:
            value = Path("different") if field.name == "file_path" else "different"
            assert fact(replace(record, **{field.name: value})) == baseline, field.name
        elif field.name == "usage":
            for component in fields(record.usage):
                changed = replace(record.usage, **{component.name: 1})
                assert fact(replace(record, usage=changed)) != baseline, component.name
        else:
            value = (record.timestamp+timedelta(seconds=1) if field.name == "timestamp" else
                     ("alias",) if field.name == "project_aliases" else
                     "subagent" if field.name == "usage_role" else "different")
            assert fact(replace(record, **{field.name: value})) != baseline, field.name


def test_mutable_project_label_does_not_change_financial_authority(tmp_path, monkeypatch):
    directories, database, page, mirror = legacy_overlap(tmp_path, monkeypatch)
    page.unlink()
    mirror.unlink()
    load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
    synchronize_parser_workset(database)
    with open_ledger(database) as connection:
        connection.execute("update ledger_projects set label='Renamed display label'")
        connection.commit()
    synchronize_parser_workset(database)
    assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 200


def test_different_physical_rollouts_with_matching_facts_stay_independent(tmp_path):
    from test_paginated_history import rollout_name

    sessions = tmp_path / "sessions"
    _, page, _ = corpus(sessions)
    other = sessions / rollout_name(physical="33333333-3333-4333-8333-333333333333")
    other.write_bytes(page.read_bytes())
    append(other, 200)
    database = tmp_path / "ledger.sqlite3"
    first = load_cached_session_data([sessions], cache_database_path=database, auto_transitions=False, max_workers=1)
    synchronize_parser_workset(database)
    assert sum(r.usage.total_tokens for r in first.records) == 250
    other.unlink()
    again = load_cached_session_data([sessions], cache_database_path=database, auto_transitions=False, max_workers=1)
    synchronize_parser_workset(database)
    assert sum(r.usage.total_tokens for r in again.records) == 250
    assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 250


@pytest.mark.parametrize("primary", [False, True])
@pytest.mark.parametrize("malformed", ["missing", "invalid_json", "identity"])
def test_initial_family_with_no_eligible_checkpoint_is_quarantined(tmp_path, monkeypatch, primary, malformed):
    directories, database, page, mirror = legacy_overlap(tmp_path, monkeypatch, primary=primary)
    page.unlink()
    mirror.unlink()
    with open_ledger(database) as connection:
        keys = [r[0] for r in connection.execute("select file_key from files where path in (?,?)", (str(page), str(mirror)))]
        for key in keys:
            if malformed == "missing":
                connection.execute("delete from parser_checkpoints where file_key=?", (key,))
            elif malformed == "invalid_json":
                connection.execute("update parser_checkpoints set state_json='not-json' where file_key=?", (key,))
            else:
                connection.execute("update parser_checkpoints set state_json=json_set(state_json,'$.root_metadata.session_id','wrong') where file_key=?", (key,))
        connection.commit()
    for _ in range(2):
        result = load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
        synchronize_parser_workset(database)
        expected = 50 if primary else 100
        assert sum(r.usage.total_tokens for r in result.records) == expected
        assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == expected
        assert any("accounting_" in error for error in result.file_errors.values())
        assert not load_ledger_status(database).coverage.complete


@pytest.mark.parametrize("malformed", ["missing_bindings", "version", "projection", "foreign_selection"])
def test_unqualified_receipt_cannot_authorize_accounting_reads(tmp_path, monkeypatch, malformed):
    from codex_usage.replica_accounting import authorize_retained_snapshot
    from codex_usage.replica_accounting_proof import AccountingProofError
    from codex_usage.session_cache_queries import load_records_for_task_ids
    from test_paginated_history import THREAD

    directories, database, page, mirror = legacy_overlap(tmp_path, monkeypatch)
    page.unlink()
    mirror.unlink()
    load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
    synchronize_parser_workset(database)
    with open_ledger(database) as connection:
        key = connection.execute("select file_key from files where path=?", (str(mirror),)).fetchone()[0]
        update = {"missing_bindings": "json_remove(value,'$.bindings')",
                  "version": "json_set(value,'$.version',999)",
                  "projection": "json_set(value,'$.projection',999)",
                  "foreign_selection": "json_set(value,'$.selected','"+THREAD+"')"}[malformed]
        connection.execute(f"update schema_meta set value={update} where key like 'retained-accounting:%'")
        assert sum(r.usage.total_tokens for r in load_records_for_task_ids(connection, {THREAD})) == 100
        with pytest.raises(AccountingProofError, match="not_selected"):
            authorize_retained_snapshot(connection, key)
