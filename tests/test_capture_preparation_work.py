"""Bounded transition reads retain the full-history inference oracle."""
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import sqlite3
from unittest.mock import patch
from zoneinfo import ZoneInfo

from codex_usage import session_transition_records as sparse
from codex_usage.project_transition_evidence import RepoPathObservation
from codex_usage.project_transitions import infer_project_transitions
from codex_usage.session_cache_queries import load_records_for_task_ids
from codex_usage.session_cache_schema import _ensure_schema, _schema_matches
from test_incremental_transitions import (
    append_ignored_event, write_multi_task_transition_corpus,
)
from codex_usage.session_cache import CACHE_DB_NAME, load_cached_session_data


def test_sparse_predecessors_match_full_history_with_ties_and_side_chats(tmp_path):
    corpus = write_multi_task_transition_corpus(tmp_path, count=1)
    load_cached_session_data([corpus.sessions], cache_dir=corpus.cache, max_workers=1)
    with sqlite3.connect(corpus.cache / CACHE_DB_NAME) as connection:
        connection.row_factory = sqlite3.Row
        original = dict(connection.execute('select * from usage_records limit 1').fetchone())
        columns = list(original)
        at = datetime(2026, 8, 3, 12, tzinfo=UTC)
        rows = []
        for i in range(2000):
            stamp = at + timedelta(microseconds=i // 3)
            row = dict(original, record_index=i + 10, timestamp=stamp.isoformat(),
                timestamp_us=int(stamp.timestamp() * 1e6), session_id='side-chat' if i % 7 == 0 else 'thread-0',
                turn_id=f'turn-{i % 3}', project_key=f'project-{i % 5}',
                project_label=f'Label-{i % 11}', project_aliases_json='["alias"]')
            rows.append(tuple(row[k] for k in columns))
        connection.executemany(f'insert into usage_records ({", ".join(columns)}) '
            f'values ({", ".join("?" for _ in columns)})', rows)
        # Duplicate archive rows are not members of the current generation.
        file = dict(connection.execute('select * from files limit 1').fetchone())
        file['file_key'] = 'archive-copy'
        connection.execute(f'insert into files ({", ".join(file)}) values ({", ".join("?" for _ in file)})', tuple(file.values()))
        duplicate = dict(original, file_key='archive-copy', record_index=0)
        connection.execute(f'insert into usage_records ({", ".join(columns)}) '
            f'values ({", ".join("?" for _ in columns)})', tuple(duplicate[k] for k in columns))
        observations = [RepoPathObservation(timestamp=at + timedelta(microseconds=i),
            thread_id=task, project_key=key, project_label=key, resolved_path='/repo',
            source='function_call', raw_path='/repo')
            for i in (-1, 0, 1, 333, 334, 667, 999)
            for task in ('thread-0', 'side-chat', 'missing') for key in ('target', 'alias')]
        observations += [replace(observations[4], timestamp=observations[4].timestamp.astimezone(
            ZoneInfo('America/Toronto')))]
        full = load_records_for_task_ids(connection, {p.thread_id for p in observations})
        with patch.object(sparse, 'row_to_usage_record', wraps=sparse.row_to_usage_record) as converted:
            selected = sparse.load_transition_predecessors(connection, observations)
        assert converted.call_count < 100
        assert infer_project_transitions(selected, observations) == infer_project_transitions(full, observations)
        assert sparse.load_transition_predecessors(connection, []) == []


def test_capture_transition_reconciliation_never_loads_whole_task_histories(tmp_path):
    corpus = write_multi_task_transition_corpus(tmp_path, count=2)
    initial = load_cached_session_data([corpus.sessions], cache_dir=corpus.cache, max_workers=1)
    append_ignored_event(corpus.paths[0])
    with patch('codex_usage.session_cache_queries.load_records_for_task_ids',
               side_effect=AssertionError('Full task history loaded')):
        updated = load_cached_session_data([corpus.sessions], cache_dir=corpus.cache, max_workers=1)
    assert updated.project_transitions == initial.project_transitions


def test_role_integrity_checks_use_sparse_indexes_and_still_detect_corruption(tmp_path):
    corpus = write_multi_task_transition_corpus(tmp_path, count=1)
    load_cached_session_data([corpus.sessions], cache_dir=corpus.cache, max_workers=1)
    with sqlite3.connect(corpus.cache / CACHE_DB_NAME) as connection:
        connection.row_factory = sqlite3.Row
        _ensure_schema(connection)
        for table in ('usage_records', 'storage_files'):
            plan = connection.execute(f"explain query plan select 1 from {table} "
                "where coalesce(usage_role, '') not in ('root', 'subagent') limit 1").fetchall()
            assert any(f'{table}_invalid_role_idx' in row['detail'] for row in plan)
        assert _schema_matches(connection)
        connection.execute('pragma ignore_check_constraints=on')
        for table in ('usage_records', 'storage_files'):
            assert connection.execute(f"update {table} set usage_role='invalid'").rowcount
            assert not _schema_matches(connection)
            connection.execute(f"update {table} set usage_role='root'")
            assert _schema_matches(connection)
        from codex_usage.session_cache_validation import ensure_role_validation_indexes
        connection.execute('drop index usage_records_invalid_role_idx')
        ensure_role_validation_indexes(connection)
        assert _schema_matches(connection)


def test_checkout_discovery_is_shared_only_within_one_reconciliation(tmp_path):
    from types import SimpleNamespace
    import codex_usage.project_identity as identity
    from codex_usage.session_cache_project_identity import refresh_cached_project_identities
    from test_incremental_transitions import write_task_session
    corpus = write_multi_task_transition_corpus(tmp_path, count=2)
    write_task_session(corpus.paths[1], thread_id='thread-1',
        source_repo=corpus.source_repos[0], target_repo=None)
    load_cached_session_data([corpus.sessions], cache_dir=corpus.cache, max_workers=1)
    with sqlite3.connect(corpus.cache / CACHE_DB_NAME) as connection:
        connection.row_factory = sqlite3.Row
        inventory = [SimpleNamespace(file_key=r['file_key'], path=r['path']) for r in
            connection.execute('select file_key, path from files')]
        with patch.object(identity, '_checkout_from_cwd', wraps=identity._checkout_from_cwd) as lookup:
            refresh_cached_project_identities(connection, inventory)
            assert lookup.call_count == 1
            (corpus.source_repos[0] / '.git/config').write_text(
                '[remote "origin"]\nurl = https://github.com/example/changed.git\n')
            refresh_cached_project_identities(connection, inventory)
            assert lookup.call_count == 2
