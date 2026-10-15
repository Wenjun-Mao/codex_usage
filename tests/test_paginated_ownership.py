"""Physical ownership is shared by ranges, lineage, mirrors and normalization."""
from dataclasses import replace
from datetime import UTC, datetime
import hashlib
from types import SimpleNamespace

import pytest

from codex_usage.aggregation import RangeBounds
from codex_usage.ledger_queries import load_ledger_records
from codex_usage.ledger_schema import open_ledger
from codex_usage.ledger_sync import synchronize_parser_workset
from codex_usage.parallel.usage import UsageParseRequest
from codex_usage.parser import parse_session_generation
from codex_usage.session_cache import load_cached_session_data
from codex_usage.session_cache_queries import (
    load_all_raw_candidates, load_parent_identity_records, load_raw_candidates_for_task_ids,
    load_records_for_task_ids,
)
from codex_usage.session_generation_models import RawRepoPathCandidate
from codex_usage.session_history import HISTORY_READ_BUDGET, PAGE_KEY_PREFIX
from codex_usage.session_history_requests import prepare_history_requests
from codex_usage.session_inventory import collect_session_file_inventory
from codex_usage.session_transition_records import load_transition_predecessors

from test_paginated_history import PAGE, THREAD, corpus, meta, rollout_name, tokens, write_rows
from test_paginated_replicas import use_legacy_replica_accounting


@pytest.mark.parametrize("start,end", [(None, None), (0, None), (None, 2**63-1), (0, 2**63-1)])
def test_range_and_identity_queries_include_canonical_pages_not_mirrors(tmp_path, start, end):
    sessions = tmp_path / "sessions"
    root, page, _ = corpus(sessions)
    database = tmp_path / "ledger.sqlite3"
    load_cached_session_data([sessions], cache_database_path=database, auto_transitions=False, max_workers=1)
    with open_ledger(database) as connection:
        connection.execute("update usage_records set git_repository_url='https://example.invalid/page' where file_key=?",
                           (PAGE_KEY_PREFIX+PAGE,))
        connection.execute("insert into transition_candidates values (?,0,?,?,?,?,?)",
                           (PAGE_KEY_PREFIX+PAGE, "2026-10-13T03:00:00Z", 0, THREAD, "/repo/page", "synthetic"))
        connection.commit()
        assert sum(r.usage.total_tokens for r in load_records_for_task_ids(connection, {THREAD})) == 150
        assert load_parent_identity_records(connection, {THREAD})[0].file_path == page
        assert len(load_all_raw_candidates(connection)) == len(load_raw_candidates_for_task_ids(connection, {THREAD})) == 1
        observation = RawRepoPathCandidate("/repo/new", datetime(2026, 10, 13, 4, tzinfo=UTC), THREAD, "synthetic")
        assert load_transition_predecessors(connection, [observation])[0].file_path == page
    result = load_cached_session_data([sessions], cache_database_path=database, auto_transitions=False,
        max_workers=1, range_bounds=RangeBounds(start, end))
    assert {r.file_path for r in result.records} == {root, page}
    assert sum(r.usage.total_tokens for r in result.records) == 150


@pytest.mark.parametrize("old_normalization", [False, True])
def test_page_mirrors_never_promote_into_logical_root_on_warm_capture(tmp_path, monkeypatch, old_normalization):
    sessions, archived = tmp_path / "sessions", tmp_path / "archived_sessions"
    root, page, _ = corpus(sessions)
    archived.mkdir()
    page = page.rename(archived / page.name)
    database = tmp_path / "ledger.sqlite3"
    directories = [sessions, archived]
    first = load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
    assert sum(r.usage.total_tokens for r in first.records) == 150
    synchronize_parser_workset(database)
    for index in range(2):
        mirror = sessions / str(index) / page.name
        mirror.parent.mkdir()
        mirror.write_bytes(page.read_bytes())
    if old_normalization:
        with monkeypatch.context() as patch:
            use_legacy_replica_accounting(patch)
            load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
            patch.setattr("codex_usage.ledger_sync.skip_proven_page_mirror", lambda *_: (False, False))
            synchronize_parser_workset(database)
        assert sum(r.usage.total_tokens for r in load_ledger_records(database)) > 150
    for _ in range(3):
        result = load_cached_session_data(directories, cache_database_path=database, auto_transitions=False, max_workers=1)
        assert not result.file_errors
        assert sum(r.usage.total_tokens for r in result.records) == 150
        with open_ledger(database) as connection:
            assert connection.execute("select path from files where file_key=?", (THREAD,)).fetchone()[0] == str(root)
        synchronize_parser_workset(database)
        assert sum(r.usage.total_tokens for r in load_ledger_records(database)) == 150
    if old_normalization:
        with open_ledger(database, read_only=True) as connection:
            assert connection.execute("select count(*) from ledger_meta where key like 'source-mirror:%'").fetchone()[0]


def test_possible_full_fallback_reserves_history_work_even_when_old_header_had_no_base(tmp_path):
    requests = []
    for index in range(5):
        path = write_rows(tmp_path / str(index) / rollout_name(), [meta(), tokens(100)])
        parsed = parse_session_generation(path)
        stat = path.stat()
        requests.append(UsageParseRequest(index, str(index), path, stat.st_size, stat.st_mtime_ns,
                                         checkpoint=parsed.checkpoint))
    inventory = collect_session_file_inventory([tmp_path], read_metadata=False)
    selected, metadata_bytes = prepare_history_requests(inventory, requests, {})
    assert len(selected) == 4 and metadata_bytes == 0
    assert len(selected)*HISTORY_READ_BUDGET <= 8*1024*1024
    append_only = [replace(request, defer_full_fallback=True) for request in requests]
    assert len(prepare_history_requests(inventory, append_only, {})[0]) == 5


@pytest.mark.parametrize("owner_size,current_tail,retired", [(1000, b"b", False), (2000, b"b", True),
                                                           (2000, b"x", False)])
def test_old_normalized_mirror_cannot_hide_a_larger_or_different_current_checkpoint(
        tmp_path, monkeypatch, owner_size, current_tail, retired):
    import codex_usage.ledger_source_mirrors as mirrors
    from codex_usage.models import SessionMetadata

    owner_path = tmp_path / "owner" / rollout_name(physical=PAGE)
    owner_path.parent.mkdir()
    owner_path.write_bytes((b"a"*1000+b"b"*1000)[:owner_size])
    mirror_path = tmp_path / "mirror" / owner_path.name
    key = PAGE_KEY_PREFIX+PAGE

    def checkpoint(path, body):
        metadata = SessionMetadata(THREAD, path, history_mode="paginated")
        digest = hashlib.sha256(body).hexdigest()
        return SimpleNamespace(state=SimpleNamespace(root_metadata=metadata), session_id=THREAD,
            byte_offset=len(body), head_sha256=digest, boundary_sha256=digest)

    owner = checkpoint(owner_path, owner_path.read_bytes())
    current = checkpoint(mirror_path, b"a"*1000+current_tail*1000)
    old = dict(generation_id=1, captured_size=1000, head_sha256=hashlib.sha256(b"a"*1000).hexdigest(),
               boundary_sha256=hashlib.sha256(b"a"*1000).hexdigest())
    statements = []

    class Connection:
        def execute(self, sql, _parameters):
            statements.append(sql)
            return self

        def fetchone(self):
            return old

    monkeypatch.setattr(mirrors, "load_parser_checkpoint", lambda _c, k, _p: owner if k == key else current)
    stat = owner_path.stat()
    row = dict(file_key="fallback-mirror", path=str(mirror_path), session_id=THREAD, error="", is_missing=0)
    owner_row = dict(path=str(owner_path), byte_offset=owner_size, error="", is_missing=0,
                     source_device=stat.st_dev, source_inode=stat.st_ino)
    assert mirrors.skip_proven_page_mirror(Connection(), row, {key: owner_row}) == (retired, retired)
    assert any(sql.startswith("update ledger_generations") for sql in statements) is retired
