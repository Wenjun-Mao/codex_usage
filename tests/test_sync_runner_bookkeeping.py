import json
from pathlib import Path

import codex_usage.sync.bookkeeping as bookkeeping_module
import codex_usage.sync.runner as runner_module
from codex_usage.session_cache import load_cached_session_data
from codex_usage.sync import ProjectResolutionRequest, pull_sync, push_sync
from codex_usage.sync.errors import ConcurrentLocalChangeError
from codex_usage.sync.state import LocalStateStore


def test_verified_pull_state_failure_is_reported_and_repaired_without_recopy(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_sessions, target_sessions, sync_dir, source_path = _seed_remote(tmp_path)
    original_record = LocalStateStore.record_success

    def fail_state(*args, **kwargs) -> None:
        raise ConcurrentLocalChangeError("local state write failed")

    monkeypatch.setattr(LocalStateStore, "record_success", fail_state)
    failed = _pull(target_sessions, sync_dir, tmp_path / "target-cache")

    target_path = target_sessions / source_path.relative_to(source_sessions)
    assert failed.outcome == "issue"
    assert failed.pulled == ("thread-1",)
    assert failed.issues[-1].message == "local state write failed"
    assert target_path.read_bytes() == source_path.read_bytes()
    assert LocalStateStore(target_sessions, sync_dir).read("thread-1") is None
    assert not (target_sessions.parent / "session_index.jsonl").exists()

    monkeypatch.setattr(LocalStateStore, "record_success", original_record)
    monkeypatch.setattr(runner_module, "atomic_copy", _fail_conversation_copy)
    progress = []
    repaired = _pull(
        target_sessions,
        sync_dir,
        tmp_path / "target-cache",
        progress,
    )

    assert repaired.outcome == "completed"
    assert repaired.pulled == repaired.pushed == ()
    assert progress == []
    assert LocalStateStore(target_sessions, sync_dir).read("thread-1") is not None
    assert _index_entry(target_sessions.parent)["thread_name"] == "Remote title"

    monkeypatch.setattr(LocalStateStore, "write", _fail_bookkeeping_write)
    monkeypatch.setattr(
        bookkeeping_module, "merge_session_index", _fail_bookkeeping_write
    )
    settled = _pull(target_sessions, sync_dir, tmp_path / "target-cache")
    assert settled.outcome == "completed"


def test_verified_pull_index_failure_reports_pull_and_rerun_repairs_bookkeeping(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source_sessions, target_sessions, sync_dir, _ = _seed_remote(tmp_path)
    original_merge = runner_module.merge_session_index

    def fail_merge(*args, **kwargs) -> None:
        raise ConcurrentLocalChangeError("local session index merge failed")

    monkeypatch.setattr(runner_module, "merge_session_index", fail_merge)
    failed = _pull(target_sessions, sync_dir, tmp_path / "target-cache")

    assert failed.outcome == "issue"
    assert failed.pulled == ("thread-1",)
    assert failed.issues[-1].message == "local session index merge failed"
    assert LocalStateStore(target_sessions, sync_dir).read("thread-1") is not None
    assert not (target_sessions.parent / "session_index.jsonl").exists()

    monkeypatch.setattr(runner_module, "merge_session_index", original_merge)
    monkeypatch.setattr(runner_module, "atomic_copy", _fail_conversation_copy)
    repaired = _pull(target_sessions, sync_dir, tmp_path / "target-cache")

    assert repaired.outcome == "completed"
    assert repaired.pulled == repaired.pushed == ()
    assert LocalStateStore(target_sessions, sync_dir).read("thread-1") is not None
    assert _index_entry(target_sessions.parent)["thread_name"] == "Remote title"


def test_verified_push_state_failure_is_reported_and_rerun_repairs_index_and_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    sync_dir = tmp_path / "sync"
    source = _write_session(sessions, "thread-1", tmp_path / "repo")
    _write_index(home, "Remote title")
    original_record = LocalStateStore.record_success

    def fail_state(*args, **kwargs) -> None:
        raise ConcurrentLocalChangeError("local state write failed")

    monkeypatch.setattr(LocalStateStore, "record_success", fail_state)
    failed = _push(sessions, sync_dir, tmp_path / "cache", "source")

    remote_path = sync_dir / "tasks" / "thread-1.jsonl"
    assert failed.outcome == "issue"
    assert failed.pushed == ("thread-1",)
    assert failed.issues[-1].message == "local state write failed"
    assert remote_path.read_bytes() == source.read_bytes()
    assert not (sync_dir / "sync-index.json").exists()
    assert LocalStateStore(sessions, sync_dir).read("thread-1") is None

    monkeypatch.setattr(LocalStateStore, "record_success", original_record)
    monkeypatch.setattr(runner_module, "atomic_copy", _fail_conversation_copy)
    repaired = _push(sessions, sync_dir, tmp_path / "cache", "source")

    assert repaired.outcome == "completed"
    assert repaired.pulled == repaired.pushed == ()
    assert LocalStateStore(sessions, sync_dir).read("thread-1") is not None
    remote_index = json.loads(
        (sync_dir / "sync-index.json").read_text(encoding="utf-8")
    )
    assert remote_index["threads"]["thread-1"]["sha256"]


def test_current_noop_run_does_not_rewrite_local_bookkeeping(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    sync_dir = tmp_path / "sync"
    _write_session(sessions, "thread-1", tmp_path / "repo")
    _write_index(home, "Remote title")
    _push(sessions, sync_dir, tmp_path / "cache", "source")

    monkeypatch.setattr(LocalStateStore, "write", _fail_bookkeeping_write)
    monkeypatch.setattr(
        bookkeeping_module, "merge_session_index", _fail_bookkeeping_write
    )
    progress = []
    result = _push(sessions, sync_dir, tmp_path / "cache", "source", progress)

    assert result.outcome == "completed"
    assert result.pulled == result.pushed == ()
    assert progress == []


def test_noop_bookkeeping_repair_revalidates_matching_local_bytes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    sync_dir = tmp_path / "sync"
    source = _write_session(sessions, "thread-1", tmp_path / "repo")
    _write_index(home, "Remote title")
    _push(sessions, sync_dir, tmp_path / "cache", "source")
    state_store = LocalStateStore(sessions, sync_dir)
    state_store.path_for("thread-1").unlink()
    original_pushes = runner_module.execute_pushes

    def change_local_after_preflight(*args, **kwargs):
        execution = original_pushes(*args, **kwargs)
        source.write_bytes(source.read_bytes() + b"\n")
        return execution

    monkeypatch.setattr(runner_module, "execute_pushes", change_local_after_preflight)
    result = _push(sessions, sync_dir, tmp_path / "cache", "source")

    assert result.outcome == "issue"
    assert result.issues[-1].code == "concurrent_local_change"
    assert state_store.read("thread-1") is None


def test_noop_bookkeeping_remote_change_uses_task_diagnostic(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "codex"
    sessions = home / "sessions"
    sync_dir = tmp_path / "sync"
    _write_session(sessions, "thread-1", tmp_path / "repo")
    _write_index(home, "Remote title")
    _push(sessions, sync_dir, tmp_path / "cache", "source")
    remote_path = sync_dir / "tasks" / "thread-1.jsonl"
    original_pushes = runner_module.execute_pushes

    def change_remote_after_preflight(*args, **kwargs):
        execution = original_pushes(*args, **kwargs)
        remote_path.write_bytes(remote_path.read_bytes() + b"\n")
        return execution

    monkeypatch.setattr(
        runner_module,
        "execute_pushes",
        change_remote_after_preflight,
    )

    result = _push(sessions, sync_dir, tmp_path / "cache", "source")

    assert result.outcome == "issue"
    assert result.issues[-1].message == (
        "Remote task changed before bookkeeping repair for thread 'thread-1'"
    )


def _seed_remote(tmp_path: Path) -> tuple[Path, Path, Path, Path]:
    source_home = tmp_path / "source"
    source_sessions = source_home / "sessions"
    target_sessions = tmp_path / "target" / "sessions"
    target_sessions.mkdir(parents=True)
    sync_dir = tmp_path / "sync"
    project = tmp_path / "repo"
    project.mkdir()
    (target_sessions.parent / ".codex-global-state.json").write_text(
        json.dumps({"electron-saved-workspace-roots": [str(project)]}),
        encoding="utf-8",
    )
    source_path = _write_session(source_sessions, "thread-1", project)
    _write_index(source_home, "Remote title")
    pushed = _push(source_sessions, sync_dir, tmp_path / "source-cache", "source")
    assert pushed.pushed == ("thread-1",)
    return source_sessions, target_sessions, sync_dir, source_path


def _push(
    sessions: Path,
    sync_dir: Path,
    cache_dir: Path,
    machine_id: str,
    progress: list | None = None,
):
    data = load_cached_session_data([sessions], cache_dir=cache_dir)
    return push_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        machine_id=machine_id,
        on_progress=progress.append if progress is not None else None,
    )


def _pull(
    sessions: Path,
    sync_dir: Path,
    cache_dir: Path,
    progress: list | None = None,
):
    data = load_cached_session_data([sessions], cache_dir=cache_dir)
    return pull_sync(
        data=data,
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        project_resolution=ProjectResolutionRequest(),
        on_progress=progress.append if progress is not None else None,
    )


def _write_session(sessions: Path, thread_id: str, cwd: Path) -> Path:
    day = sessions / "2026" / "07" / "14"
    day.mkdir(parents=True, exist_ok=True)
    path = day / f"rollout-2026-07-14T10-00-00-{thread_id}.jsonl"
    rows = [
        {
            "timestamp": "2026-07-14T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": thread_id,
                "timestamp": "2026-07-14T10:00:00Z",
                "cwd": str(cwd),
            },
        },
        {
            "timestamp": "2026-07-14T10:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {"total_tokens": 10}},
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
    return path


def _write_index(home: Path, title: str) -> None:
    home.mkdir(parents=True, exist_ok=True)
    entry = {
        "id": "thread-1",
        "thread_name": title,
        "updated_at": "2026-07-14T10:00:02Z",
    }
    (home / "session_index.jsonl").write_text(
        json.dumps(entry) + "\n", encoding="utf-8"
    )


def _index_entry(home: Path) -> dict[str, object]:
    return json.loads((home / "session_index.jsonl").read_text(encoding="utf-8"))


def _fail_conversation_copy(*args, **kwargs):
    raise AssertionError("matching conversation bytes must not be copied again")


def _fail_bookkeeping_write(*args, **kwargs) -> None:
    raise AssertionError("current bookkeeping must not be rewritten")
