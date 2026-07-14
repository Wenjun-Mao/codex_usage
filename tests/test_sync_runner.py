import json
from pathlib import Path

import codex_usage.sync.runner as runner_module
import pytest
from codex_usage.session_cache import load_cached_session_data
from codex_usage.sync import run_sync
from codex_usage.sync.errors import ConcurrentRemoteChangeError
from codex_usage.sync.runner import sync_status as transaction_status
from codex_usage.sync.store import RemoteStore


def test_run_sync_pushes_flat_bytes_and_one_index(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    source = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")

    result = run_sync(
        data=data,
        sync_dir=tmp_path / "sync",
        thread_ids=["thread-1"],
        machine_id="a",
    )

    assert result.outcome == "completed"
    assert result.pushed == ("thread-1",)
    assert (
        tmp_path / "sync" / "conversations" / "thread-1.jsonl"
    ).read_bytes() == source.read_bytes()
    assert (tmp_path / "sync" / "sync-index.json").is_file()
    assert not (tmp_path / "sync" / "threads").exists()


def test_new_task_in_same_project_remains_excluded_after_initial_selection(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "sessions"
    _write_session(sessions, "selected-a", tmp_path / "repo", total=100)
    _write_session(sessions, "selected-b", tmp_path / "repo", total=100)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")

    first = run_sync(
        data=data,
        sync_dir=tmp_path / "sync",
        thread_ids=["selected-a", "selected-b"],
        machine_id="a",
    )

    _write_session(sessions, "future", tmp_path / "repo", total=100)
    refreshed = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    second = run_sync(
        data=refreshed,
        sync_dir=tmp_path / "sync",
        thread_ids=["selected-a", "selected-b"],
        machine_id="a",
    )

    assert set(first.pushed) == {"selected-a", "selected-b"}
    assert second.pushed == ()
    assert not (tmp_path / "sync" / "conversations" / "future.jsonl").exists()


def test_run_sync_pulls_before_pushes_in_one_transaction(tmp_path: Path) -> None:
    source_sessions = tmp_path / "source" / "sessions"
    target_sessions = tmp_path / "target" / "sessions"
    sync_dir = tmp_path / "sync"
    source_path = _write_session(
        source_sessions, "remote-thread", tmp_path / "remote-repo", total=120
    )
    source_data = load_cached_session_data(
        [source_sessions], cache_dir=tmp_path / "source-cache"
    )
    run_sync(
        data=source_data,
        sync_dir=sync_dir,
        thread_ids=["remote-thread"],
        machine_id="source",
    )
    target_path = _write_session(
        target_sessions, "local-thread", tmp_path / "local-repo", total=240
    )
    target_data = load_cached_session_data(
        [target_sessions], cache_dir=tmp_path / "target-cache"
    )
    progress = []

    result = run_sync(
        data=target_data,
        sync_dir=sync_dir,
        thread_ids=["remote-thread", "local-thread"],
        machine_id="target",
        on_progress=progress.append,
    )

    pulled_path = target_sessions / source_path.relative_to(source_sessions)
    assert result.outcome == "completed"
    assert result.pulled == ("remote-thread",)
    assert result.pushed == ("local-thread",)
    assert [event.phase for event in progress] == ["pulling", "pushing"]
    assert pulled_path.read_bytes() == source_path.read_bytes()
    assert (
        sync_dir / "conversations" / "local-thread.jsonl"
    ).read_bytes() == target_path.read_bytes()
    remote_index = json.loads(
        (sync_dir / "sync-index.json").read_text(encoding="utf-8")
    )
    assert set(remote_index["threads"]) == {"local-thread", "remote-thread"}


def test_conflict_preflight_changes_no_authoritative_files(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    sync_dir = tmp_path / "sync"
    initial = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    run_sync(
        data=initial,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )
    remote_path = sync_dir / "conversations" / "thread-1.jsonl"
    _append_token_event(local_path, "2026-07-13T12:01:00Z", 180)
    _append_token_event(remote_path, "2026-07-13T12:02:00Z", 240)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    local_before = local_path.read_bytes()
    remote_before = remote_path.read_bytes()
    index_before = (sync_dir / "sync-index.json").read_bytes()

    result = run_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )

    assert result.outcome == "conflict"
    assert local_path.read_bytes() == local_before
    assert remote_path.read_bytes() == remote_before
    assert (sync_dir / "sync-index.json").read_bytes() == index_before
    conflict_candidates = list(
        (home / ".codex-sync-backups").rglob("remote-conflict-session.jsonl")
    )
    assert len(conflict_candidates) == 1
    assert conflict_candidates[0].read_bytes() == remote_before


def test_conflict_result_includes_completed_planning_timing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    sync_dir = tmp_path / "sync"
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    run_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )
    _append_token_event(local_path, "2026-07-13T12:01:00Z", 180)
    _append_token_event(
        sync_dir / "conversations" / "thread-1.jsonl", "2026-07-13T12:02:00Z", 240
    )
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    clock = iter((1_000_000, 3_000_000, 4_000_000, 9_000_000))
    monkeypatch.setattr(runner_module, "perf_counter_ns", lambda: next(clock))

    result = run_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )

    assert result.timings_ms.planning == 7


def test_runner_public_interfaces_are_keyword_only(tmp_path: Path) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")

    with pytest.raises(TypeError):
        run_sync(data, tmp_path / "sync", ["thread-1"], "a")
    with pytest.raises(TypeError):
        transaction_status(data, tmp_path / "sync", ["thread-1"])


def test_pull_backs_up_local_and_merges_remote_session_index(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    sync_dir = tmp_path / "sync"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    original_index = {
        "id": "thread-1",
        "thread_name": "Original",
        "updated_at": "2026-04-29T10:05:00Z",
    }
    _write_index(home, original_index)
    initial = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    run_sync(
        data=initial,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )
    remote_path = sync_dir / "conversations" / "thread-1.jsonl"
    _append_token_event(remote_path, "2026-07-13T12:02:00Z", 240)
    before_pull = local_path.read_bytes()
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")

    result = run_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )

    assert result.pulled == ("thread-1",)
    assert local_path.read_bytes() == remote_path.read_bytes()
    local_backups = list((home / ".codex-sync-backups").rglob("thread-1/session.jsonl"))
    index_backups = list((home / ".codex-sync-backups").rglob("session_index.jsonl"))
    assert len(local_backups) == 1
    assert local_backups[0].read_bytes() == before_pull
    assert len(index_backups) == 1
    assert json.loads(index_backups[0].read_text(encoding="utf-8")) == original_index
    merged_entries = [
        json.loads(line)
        for line in (home / "session_index.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert merged_entries == [original_index]


def test_pull_rejects_mismatched_remote_index_identity_before_local_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_sessions = tmp_path / "source" / "sessions"
    target_sessions = tmp_path / "target" / "sessions"
    sync_dir = tmp_path / "sync"
    source_path = _write_session(
        source_sessions,
        "task-a",
        tmp_path / "repo",
        total=120,
    )
    source_data = load_cached_session_data(
        [source_sessions], cache_dir=tmp_path / "source-cache"
    )
    run_sync(
        data=source_data,
        sync_dir=sync_dir,
        thread_ids=["task-a"],
        machine_id="source",
    )
    target_data = load_cached_session_data(
        [target_sessions], cache_dir=tmp_path / "target-cache"
    )
    original_validate = RemoteStore.validate_selected

    def corrupt_nested_identity_after_validation(
        self: RemoteStore,
        expected_entries,
        expected_files,
    ) -> None:
        original_validate(self, expected_entries, expected_files)
        entry = expected_entries["task-a"]
        assert entry is not None
        entry.index_entry["id"] = "task-b"

    monkeypatch.setattr(
        RemoteStore,
        "validate_selected",
        corrupt_nested_identity_after_validation,
    )
    target_path = target_sessions / source_path.relative_to(source_sessions)

    with pytest.raises(ValueError, match=r"index_entry\.id.*match"):
        run_sync(
            data=target_data,
            sync_dir=sync_dir,
            thread_ids=["task-a"],
            machine_id="target",
        )

    assert not target_path.exists()
    assert not (target_sessions.parent / "session_index.jsonl").exists()
    assert not (target_sessions.parent / ".codex-sync-state").exists()


def test_run_sync_returns_typed_issue_when_local_changes_after_planning(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    original_validate = RemoteStore.validate_selected

    def change_local_after_planning(self, expected_entries, expected_files) -> None:
        original_validate(self, expected_entries, expected_files)
        _append_token_event(local_path, "2026-07-13T12:03:00Z", 180)

    monkeypatch.setattr(RemoteStore, "validate_selected", change_local_after_planning)

    result = run_sync(
        data=data,
        sync_dir=tmp_path / "sync",
        thread_ids=["thread-1"],
        machine_id="a",
    )

    assert result.outcome == "issue"
    assert result.pushed == ()
    assert result.issues[-1].code == "concurrent_local_change"
    assert not (tmp_path / "sync" / "conversations" / "thread-1.jsonl").exists()


def test_run_sync_returns_typed_issue_for_visible_remote_change(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    sync_dir = tmp_path / "sync"
    initial = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    run_sync(
        data=initial,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )
    _append_token_event(local_path, "2026-07-13T12:03:00Z", 180)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    remote_path = sync_dir / "conversations" / "thread-1.jsonl"
    original_validate = runner_module.validate_local_selected

    def change_remote_after_planning(plan) -> None:
        original_validate(plan)
        _append_token_event(remote_path, "2026-07-13T12:04:00Z", 240)

    monkeypatch.setattr(
        runner_module, "validate_local_selected", change_remote_after_planning
    )

    result = run_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )

    assert result.outcome == "issue"
    assert result.pushed == ()
    assert result.issues[-1].code == "concurrent_remote_change"


def test_interrupted_unindexed_jsonl_is_repaired_on_next_run(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    sync_dir = tmp_path / "sync"
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    original_commit = RemoteStore.commit_index

    def interrupt_index(*_args, **_kwargs):
        raise ConcurrentRemoteChangeError("index interrupted")

    monkeypatch.setattr(RemoteStore, "commit_index", interrupt_index)
    interrupted = run_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )
    monkeypatch.setattr(RemoteStore, "commit_index", original_commit)

    remote_path = sync_dir / "conversations" / "thread-1.jsonl"
    assert interrupted.outcome == "issue"
    assert interrupted.pushed == ("thread-1",)
    assert remote_path.read_bytes() == local_path.read_bytes()
    assert not (sync_dir / "sync-index.json").exists()

    repaired = run_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )

    assert repaired.outcome == "completed"
    assert repaired.pushed == ()
    index = json.loads((sync_dir / "sync-index.json").read_text(encoding="utf-8"))
    assert index["threads"]["thread-1"]["sha256"]


def test_interrupted_index_commit_repairs_complete_newer_local_metadata(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    sync_dir = tmp_path / "sync"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    initial_entry = {
        "id": "thread-1",
        "thread_name": "Initial title",
        "updated_at": "2026-04-29T10:05:00Z",
    }
    _write_index(home, initial_entry)
    initial_data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    run_sync(
        data=initial_data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )

    _append_token_event(local_path, "2026-07-13T12:03:00Z", 180)
    newer_entry = {
        "id": "thread-1",
        "thread_name": "Recovered richer title",
        "updated_at": "2026-07-13T12:04:00Z",
    }
    _write_index(home, newer_entry)
    newer_data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    original_commit = RemoteStore.commit_index

    def interrupt_index(*_args, **_kwargs):
        raise ConcurrentRemoteChangeError("index interrupted")

    monkeypatch.setattr(RemoteStore, "commit_index", interrupt_index)
    interrupted = run_sync(
        data=newer_data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )
    monkeypatch.setattr(RemoteStore, "commit_index", original_commit)
    assert interrupted.outcome == "issue"
    assert interrupted.pushed == ("thread-1",)

    repaired = run_sync(
        data=newer_data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )

    remote_entry = json.loads(
        (sync_dir / "sync-index.json").read_text(encoding="utf-8")
    )["threads"]["thread-1"]
    assert repaired.outcome == "completed"
    assert repaired.pushed == ()
    assert remote_entry["index_entry"] == newer_entry
    assert remote_entry["session_updated_at"] == newer_entry["updated_at"]
    assert remote_entry["source_relative_path"] == local_path.relative_to(sessions).as_posix()
    assert remote_entry["project_key"]
    assert remote_entry["project_label"] == "repo"


def test_matching_local_bytes_do_not_replace_newer_remote_metadata(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    sync_dir = tmp_path / "sync"
    _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    local_entry = {
        "id": "thread-1",
        "thread_name": "Local title",
        "updated_at": "2026-04-29T10:05:00Z",
    }
    _write_index(home, local_entry)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    run_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )
    index_path = sync_dir / "sync-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    newer_remote_entry = {
        "id": "thread-1",
        "thread_name": "Newer remote title",
        "updated_at": "2026-07-13T13:00:00Z",
    }
    index["threads"]["thread-1"]["index_entry"] = newer_remote_entry
    index["threads"]["thread-1"]["session_updated_at"] = "2026-07-13T13:00:00Z"
    index_path.write_text(json.dumps(index), encoding="utf-8")

    result = run_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )

    retained = json.loads(index_path.read_text(encoding="utf-8"))["threads"]["thread-1"]
    assert result.outcome == "completed"
    assert retained["index_entry"] == newer_remote_entry
    assert retained["session_updated_at"] == "2026-07-13T13:00:00Z"


def test_selected_remote_materialization_skips_unrelated_indexed_bytes_and_reads_unindexed_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_sessions = tmp_path / "source" / "sessions"
    sync_dir = tmp_path / "sync"
    for thread_id in ("thread-1", "thread-2"):
        _write_session(source_sessions, thread_id, tmp_path / thread_id, total=120)
    source_data = load_cached_session_data(
        [source_sessions], cache_dir=tmp_path / "source-cache"
    )
    run_sync(
        data=source_data,
        sync_dir=sync_dir,
        thread_ids=["thread-1", "thread-2"],
        machine_id="source",
    )
    unindexed_source = _write_session(
        tmp_path / "orphan" / "sessions", "thread-3", tmp_path / "thread-3", total=120
    )
    unindexed_path = sync_dir / "conversations" / "unindexed.jsonl"
    unindexed_path.write_bytes(unindexed_source.read_bytes())
    selected_path = sync_dir / "conversations" / "thread-1.jsonl"
    unrelated_path = sync_dir / "conversations" / "thread-2.jsonl"
    read_counts = {selected_path: 0, unrelated_path: 0, unindexed_path: 0}
    original_read_bytes = Path.read_bytes

    def count_remote_reads(path: Path) -> bytes:
        if path in read_counts:
            read_counts[path] += 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", count_remote_reads)
    target_sessions = tmp_path / "target" / "sessions"
    target_sessions.mkdir(parents=True)
    target_data = load_cached_session_data(
        [target_sessions], cache_dir=tmp_path / "target-cache"
    )

    plan = transaction_status(
        data=target_data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
    )

    assert plan.items[0].action == "pull"
    assert read_counts == {selected_path: 1, unrelated_path: 0, unindexed_path: 1}


def test_final_commit_validates_pulled_remote_file_during_simultaneous_push(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_sessions = tmp_path / "source" / "sessions"
    target_sessions = tmp_path / "target" / "sessions"
    sync_dir = tmp_path / "sync"
    _write_session(source_sessions, "remote-thread", tmp_path / "remote-repo", total=120)
    source_data = load_cached_session_data(
        [source_sessions], cache_dir=tmp_path / "source-cache"
    )
    run_sync(
        data=source_data,
        sync_dir=sync_dir,
        thread_ids=["remote-thread"],
        machine_id="source",
    )
    _write_session(target_sessions, "local-thread", tmp_path / "local-repo", total=240)
    target_data = load_cached_session_data(
        [target_sessions], cache_dir=tmp_path / "target-cache"
    )
    remote_path = sync_dir / "conversations" / "remote-thread.jsonl"
    original_repair = runner_module.repair_matching_bookkeeping

    def change_pulled_remote_before_commit(*args, **kwargs) -> None:
        original_repair(*args, **kwargs)
        _append_token_event(remote_path, "2026-07-13T12:10:00Z", 360)

    monkeypatch.setattr(
        runner_module, "repair_matching_bookkeeping", change_pulled_remote_before_commit
    )

    result = run_sync(
        data=target_data,
        sync_dir=sync_dir,
        thread_ids=["remote-thread", "local-thread"],
        machine_id="target",
    )

    assert result.outcome == "issue"
    assert result.pulled == ("remote-thread",)
    assert result.pushed == ("local-thread",)
    assert result.issues[-1].code == "concurrent_remote_change"


def test_run_sync_builds_each_inventory_once_and_emits_only_push_phase(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    for number in range(20):
        _write_session(
            sessions, f"thread-{number}", tmp_path / f"repo-{number}", total=number
        )
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    calls = {"local": 0, "remote": 0}
    original_local = runner_module.build_local_inventory
    original_remote = RemoteStore.load_inventory

    def count_local_inventory(cached_data):
        calls["local"] += 1
        return original_local(cached_data)

    def count_remote_inventory(self):
        assert self._lock.is_locked
        calls["remote"] += 1
        return original_remote(self)

    monkeypatch.setattr(runner_module, "build_local_inventory", count_local_inventory)
    monkeypatch.setattr(RemoteStore, "load_inventory", count_remote_inventory)
    progress = []

    result = run_sync(
        data=data,
        sync_dir=tmp_path / "sync",
        thread_ids=[f"thread-{number}" for number in range(20)],
        machine_id="a",
        on_progress=progress.append,
    )

    assert calls == {"local": 1, "remote": 1}
    assert result.counts.pulled == 0
    assert result.counts.pushed == 20
    assert [event.phase for event in progress] == ["pushing"]


def test_sync_status_is_read_only_and_builds_local_inventory_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")
    calls = 0
    original_local = runner_module.build_local_inventory
    original_remote = RemoteStore.load_inventory

    def count_local_inventory(cached_data):
        nonlocal calls
        calls += 1
        return original_local(cached_data)

    def assert_unlocked(self):
        assert not self._lock.is_locked
        return original_remote(self)

    monkeypatch.setattr(runner_module, "build_local_inventory", count_local_inventory)
    monkeypatch.setattr(RemoteStore, "load_inventory", assert_unlocked)

    plan = transaction_status(
        data=data,
        sync_dir=tmp_path / "sync",
        thread_ids=["thread-1"],
    )

    assert calls == 1
    assert plan.items[0].action == "push"
    assert not (tmp_path / "sync").exists()


def test_unselected_remote_diagnostic_does_not_block_selected_push(
    tmp_path: Path,
) -> None:
    sessions = tmp_path / "codex" / "sessions"
    _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    sync_dir = tmp_path / "sync"
    conversations = sync_dir / "conversations"
    conversations.mkdir(parents=True)
    (conversations / "unreadable.jsonl").write_text(
        "not session metadata\n", encoding="utf-8"
    )
    data = load_cached_session_data([sessions], cache_dir=tmp_path / "cache")

    result = run_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id="a",
    )

    assert result.outcome == "completed"
    assert result.pushed == ("thread-1",)
    assert [issue.code for issue in result.issues] == ["unindexed_unreadable"]


def _write_session(sessions_dir: Path, thread_id: str, cwd: Path, total: int) -> Path:
    day_dir = sessions_dir / "2026" / "04" / "29"
    day_dir.mkdir(parents=True, exist_ok=True)
    path = day_dir / f"rollout-2026-04-29T10-00-00-{thread_id}.jsonl"
    rows = [
        {
            "timestamp": "2026-04-29T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": thread_id,
                "timestamp": "2026-04-29T10:00:00Z",
                "cwd": str(cwd),
                "memory_mode": "enabled",
                "base_instructions": {"text": "instructions"},
            },
        },
        {
            "timestamp": "2026-04-29T10:00:01Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.5"},
        },
        _token_count_event("2026-04-29T10:00:02Z", total),
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _append_token_event(path: Path, timestamp: str, total: int) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps(_token_count_event(timestamp, total)))


def _token_count_event(timestamp: str, total: int) -> dict[str, object]:
    usage = {
        "input_tokens": total,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "reasoning_output_tokens": 0,
        "total_tokens": total,
    }
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "token_count", "info": {"total_token_usage": usage}},
    }


def _write_index(codex_home: Path, entry: dict[str, str]) -> None:
    codex_home.mkdir(parents=True, exist_ok=True)
    with (codex_home / "session_index.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry) + "\n")
