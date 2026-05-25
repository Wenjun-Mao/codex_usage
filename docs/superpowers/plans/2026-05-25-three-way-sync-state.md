# Three-Way Sync State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace hash-mismatch sync conflicts with three-way, prefix-aware sync planning so normal one-machine conversation continuation pulls or pushes automatically.

**Architecture:** Keep Python as the sync engine and VS Code as the scheduler/UI wrapper. Add local per-sync-folder base state under `.codex-sync-state`, plan every selected conversation before copying files, and make `sync status`, `sync import`, and `sync export` use the same planner. The planner auto-resolves local-only, remote-only, and byte-prefix fast-forward cases, while preserving both sides for true non-prefix divergence.

**Tech Stack:** Python standard library (`dataclasses`, `hashlib`, `json`, `pathlib`, `shutil`, `tempfile`), existing pytest suite, existing TypeScript core parser tests, VSIX packaging with the current npm/PyInstaller scripts.

---

## File Structure

- Modify `src/codex_usage/sync.py`
  - Add sync-state dataclasses and helpers near the existing sync result dataclasses.
  - Add `plan_sync(...)` as the shared planning API.
  - Add byte-prefix comparison helpers.
  - Update `sync_status(...)`, `import_threads(...)`, and `export_threads(...)` to use the planner.
  - Keep existing public function names and CLI command names.
- Modify `tests/test_sync.py`
  - Add focused planner tests before changing implementation.
  - Update older conflict tests so expected behavior matches prefix-aware planning.
  - Add import/export state-update tests.
- Modify `extensions/vscode/src/core.ts`
  - Teach `parseSyncStatusSummary` about new status states.
- Modify `extensions/vscode/test/core.test.js`
  - Add summary parsing tests for local-ahead, remote-ahead, fast-forward, and conflict counts.
- Modify docs/version files
  - `CHANGELOG.md`
  - `README.md`
  - `extensions/vscode/README.md`
  - `pyproject.toml`
  - `uv.lock`
  - `extensions/vscode/package.json`
  - `extensions/vscode/package-lock.json`

---

## Task 1: Add Failing Python Planner Tests

**Files:**
- Modify: `tests/test_sync.py`
- Test-only import target: `codex_usage.sync.plan_sync`

- [ ] **Step 1: Extend sync imports in `tests/test_sync.py`**

Change the import block from:

```python
from codex_usage.sync import (
    export_threads,
    import_threads,
    list_threads,
    sync_status,
)
```

to:

```python
from codex_usage.sync import (
    export_threads,
    import_threads,
    list_threads,
    plan_sync,
    sync_status,
)
```

- [ ] **Step 2: Add append helper functions at the bottom of `tests/test_sync.py`**

Add these helpers after `_write_session_jsonl(...)` and before `_write_json(...)`:

```python
def _append_token_event(path: Path, timestamp: str, total: int) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n" + json.dumps(_token_count_event(timestamp, total)))


def _copy_remote_session_to_local(sync_dir: Path, sessions_dir: Path, thread_id: str) -> Path:
    manifest = json.loads((sync_dir / "threads" / thread_id / "manifest.json").read_text(encoding="utf-8"))
    relative_path = str(manifest["source_relative_path"])
    target = sessions_dir / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes((sync_dir / "threads" / thread_id / "session.jsonl").read_bytes())
    return target
```

- [ ] **Step 3: Add failing tests for first-sync one-sided states**

Append this test after `test_import_thread_rejects_manifest_path_traversal`:

```python
def test_plan_sync_handles_first_sync_local_and_remote_only(tmp_path: Path) -> None:
    local_home = tmp_path / "local"
    remote_home = tmp_path / "remote"
    sync_dir = tmp_path / "sync"
    local_sessions = local_home / "sessions"
    remote_sessions = remote_home / "sessions"
    _write_session(local_sessions, "local-thread", tmp_path / "repo", total=120)
    _write_session(remote_sessions, "remote-thread", tmp_path / "repo", total=220)

    export_threads(
        session_dirs=[remote_sessions],
        sync_dir=sync_dir,
        thread_ids=["remote-thread"],
        machine_id="remote-machine",
    )

    plan = plan_sync(
        session_dirs=[local_sessions],
        sync_dir=sync_dir,
        thread_ids=["local-thread", "remote-thread"],
    )
    rows = {item["thread_id"]: item for item in plan.threads}

    assert rows["local-thread"]["state"] == "local_only"
    assert rows["local-thread"]["action"] == "push"
    assert rows["remote-thread"]["state"] == "remote_only"
    assert rows["remote-thread"]["action"] == "pull"
```

- [ ] **Step 4: Add failing tests for base-aware local and remote changes**

Append:

```python
def test_plan_sync_uses_base_state_for_local_ahead_and_remote_ahead(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sync_dir = tmp_path / "sync"
    sessions = home / "sessions"
    session_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)

    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")
    synced = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])
    assert synced.threads[0]["state"] == "synced"

    _append_token_event(session_path, "2026-04-29T10:00:03Z", 180)
    local_ahead = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])
    assert local_ahead.threads[0]["state"] == "local_ahead"
    assert local_ahead.threads[0]["action"] == "push"

    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")
    remote_path = sync_dir / "threads" / "thread-1" / "session.jsonl"
    _append_token_event(remote_path, "2026-04-29T10:00:04Z", 240)
    remote_ahead = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])

    assert remote_ahead.threads[0]["state"] == "remote_ahead"
    assert remote_ahead.threads[0]["action"] == "pull"
```

- [ ] **Step 5: Add failing tests for prefix fast-forwards and true conflict**

Append:

```python
def test_plan_sync_fast_forwards_prefix_changes_and_stops_on_divergence(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sync_dir = tmp_path / "sync"
    sessions = home / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)

    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")
    remote_path = sync_dir / "threads" / "thread-1" / "session.jsonl"

    _append_token_event(local_path, "2026-04-29T10:00:03Z", 180)
    fast_push = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])
    assert fast_push.threads[0]["state"] == "local_ahead"
    assert fast_push.threads[0]["action"] == "push"

    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")
    local_path.write_bytes(remote_path.read_bytes())
    _append_token_event(remote_path, "2026-04-29T10:00:04Z", 240)
    fast_pull = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])
    assert fast_pull.threads[0]["state"] == "remote_ahead"
    assert fast_pull.threads[0]["action"] == "pull"

    _append_token_event(local_path, "2026-04-29T10:00:05Z", 300)
    _append_token_event(remote_path, "2026-04-29T10:00:06Z", 360)
    conflict = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])

    assert conflict.threads[0]["state"] == "conflict"
    assert conflict.threads[0]["action"] == "conflict"
    assert "diverged" in str(conflict.threads[0]["reason"])
```

- [ ] **Step 6: Add failing test for missing base state prefix fallback**

Append:

```python
def test_plan_sync_without_base_state_uses_prefix_fallback(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sync_dir = tmp_path / "sync"
    sessions = home / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)

    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")
    state_root = home / ".codex-sync-state"
    if state_root.exists():
        import shutil

        shutil.rmtree(state_root)
    _append_token_event(local_path, "2026-04-29T10:00:03Z", 180)

    plan = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"])

    assert plan.threads[0]["state"] == "fast_forward_push"
    assert plan.threads[0]["action"] == "push"
```

- [ ] **Step 7: Run the new tests and verify they fail**

Run:

```powershell
uv run pytest tests/test_sync.py -q
```

Expected:

- Fails with `ImportError` or `AttributeError` because `plan_sync` does not exist yet.

---

## Task 2: Add Sync State Models, Prefix Helpers, And Planner

**Files:**
- Modify: `src/codex_usage/sync.py`
- Test: `tests/test_sync.py`

- [ ] **Step 1: Add planner dataclasses after `SyncStatus`**

In `src/codex_usage/sync.py`, after the `SyncStatus` dataclass, add:

```python
@dataclass(frozen=True)
class SyncFileSnapshot:
    path: Path | None
    exists: bool
    sha256: str = ""
    size_bytes: int = 0
    updated_at: str = ""


@dataclass(frozen=True)
class LocalSyncState:
    thread_id: str
    sync_dir_fingerprint: str
    base_sha256: str
    base_size_bytes: int
    base_updated_at: str
    last_remote_sha256: str
    last_local_sha256: str
    source_relative_path: str
    project_key: str
    project_label: str
    synced_at: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LocalSyncState | None":
        thread_id = str(value.get("thread_id") or "").strip()
        fingerprint = str(value.get("sync_dir_fingerprint") or "").strip()
        base_sha256 = str(value.get("base_sha256") or "").strip()
        if not thread_id or not fingerprint or not base_sha256:
            return None
        return cls(
            thread_id=thread_id,
            sync_dir_fingerprint=fingerprint,
            base_sha256=base_sha256,
            base_size_bytes=int(value.get("base_size_bytes") or 0),
            base_updated_at=str(value.get("base_updated_at") or ""),
            last_remote_sha256=str(value.get("last_remote_sha256") or ""),
            last_local_sha256=str(value.get("last_local_sha256") or ""),
            source_relative_path=str(value.get("source_relative_path") or ""),
            project_key=str(value.get("project_key") or ""),
            project_label=str(value.get("project_label") or ""),
            synced_at=str(value.get("synced_at") or ""),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "sync_version": SYNC_VERSION,
            "thread_id": self.thread_id,
            "sync_dir_fingerprint": self.sync_dir_fingerprint,
            "base_sha256": self.base_sha256,
            "base_size_bytes": self.base_size_bytes,
            "base_updated_at": self.base_updated_at,
            "last_remote_sha256": self.last_remote_sha256,
            "last_local_sha256": self.last_local_sha256,
            "source_relative_path": self.source_relative_path,
            "project_key": self.project_key,
            "project_label": self.project_label,
            "synced_at": self.synced_at,
        }
```

- [ ] **Step 2: Add sync-state path helpers before `_safe_session_target_path`**

Add:

```python
def _sync_dir_fingerprint(sync_dir: Path) -> str:
    normalized = str(sync_dir.resolve(strict=False)).replace("\\", "/").casefold()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _sync_state_path(session_dir: Path, sync_dir: Path, thread_id: str) -> Path:
    return (
        _codex_home_from_session_dir(session_dir)
        / ".codex-sync-state"
        / _sync_dir_fingerprint(sync_dir)
        / "threads"
        / f"{thread_id}.json"
    )


def _read_local_sync_state(session_dir: Path, sync_dir: Path, thread_id: str) -> LocalSyncState | None:
    value = _read_json_object(_sync_state_path(session_dir, sync_dir, thread_id))
    if value is None:
        return None
    state = LocalSyncState.from_dict(value)
    if state is None or state.sync_dir_fingerprint != _sync_dir_fingerprint(sync_dir):
        return None
    return state


def _write_local_sync_state(
    session_dir: Path,
    sync_dir: Path,
    *,
    thread_id: str,
    local_snapshot: SyncFileSnapshot,
    remote_snapshot: SyncFileSnapshot,
    source_relative_path: str,
    project_key: str,
    project_label: str,
) -> None:
    base_hash = local_snapshot.sha256 or remote_snapshot.sha256
    if not base_hash:
        return
    state = LocalSyncState(
        thread_id=thread_id,
        sync_dir_fingerprint=_sync_dir_fingerprint(sync_dir),
        base_sha256=base_hash,
        base_size_bytes=local_snapshot.size_bytes or remote_snapshot.size_bytes,
        base_updated_at=local_snapshot.updated_at or remote_snapshot.updated_at,
        last_remote_sha256=remote_snapshot.sha256,
        last_local_sha256=local_snapshot.sha256,
        source_relative_path=source_relative_path,
        project_key=project_key,
        project_label=project_label,
        synced_at=_now_iso(),
    )
    _atomic_write_json(_sync_state_path(session_dir, sync_dir, thread_id), state.to_dict())
```

- [ ] **Step 3: Add file snapshot and prefix helpers before `_file_size`**

Add:

```python
def _snapshot_file(path: Path | None) -> SyncFileSnapshot:
    if path is None or not path.is_file():
        return SyncFileSnapshot(path=path, exists=False)
    return SyncFileSnapshot(
        path=path,
        exists=True,
        sha256=_sha256_file(path),
        size_bytes=_file_size(path),
        updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat().replace("+00:00", "Z"),
    )


def _is_byte_prefix(prefix_path: Path, full_path: Path) -> bool:
    prefix_size = prefix_path.stat().st_size
    full_size = full_path.stat().st_size
    if prefix_size > full_size:
        return False
    with prefix_path.open("rb") as prefix, full_path.open("rb") as full:
        while True:
            prefix_chunk = prefix.read(1024 * 1024)
            if not prefix_chunk:
                return True
            if full.read(len(prefix_chunk)) != prefix_chunk:
                return False


def _prefix_relationship(local: SyncFileSnapshot, remote: SyncFileSnapshot) -> str:
    if not local.path or not remote.path or not local.exists or not remote.exists:
        return ""
    if local.sha256 == remote.sha256:
        return "equal"
    if _is_byte_prefix(remote.path, local.path):
        return "remote_prefix_of_local"
    if _is_byte_prefix(local.path, remote.path):
        return "local_prefix_of_remote"
    return "diverged"
```

- [ ] **Step 4: Add `plan_sync` and `_plan_thread_sync` before `export_threads`**

Add:

```python
def plan_sync(*, session_dirs: list[Path], sync_dir: Path, thread_ids: list[str]) -> SyncStatus:
    target_session_dir = session_dirs[0]
    local_threads = {thread.thread_id: thread for thread in list_threads(session_dirs)}
    statuses = [
        _plan_thread_sync(target_session_dir, sync_dir, thread_id, local_threads.get(thread_id)).to_dict()
        for thread_id in _dedupe(thread_ids)
    ]
    return SyncStatus(threads=statuses)


@dataclass(frozen=True)
class SyncPlanItem:
    thread_id: str
    state: str
    action: str
    reason: str
    local_path: str
    remote_path: str
    local_sha256: str
    remote_sha256: str
    base_sha256: str
    updated_at: str
    source_relative_path: str
    project_key: str
    project_label: str
    memory_database_rows: int

    def to_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "thread_id": self.thread_id,
            "state": self.state,
            "action": self.action,
            "reason": self.reason,
            "local_path": self.local_path,
            "remote_path": self.remote_path,
            "local_sha256": self.local_sha256,
            "remote_sha256": self.remote_sha256,
            "base_sha256": self.base_sha256,
            "updated_at": self.updated_at,
            "source_relative_path": self.source_relative_path,
            "project_key": self.project_key,
            "project_label": self.project_label,
            "memory_database_rows": self.memory_database_rows,
        }
        if self.memory_database_rows:
            value["memory_note"] = "memory database rows detected, not synced by this beta"
        return value
```

Then add the planner helper:

```python
def _plan_thread_sync(
    target_session_dir: Path,
    sync_dir: Path,
    thread_id: str,
    local_thread: ThreadInfo | None,
) -> SyncPlanItem:
    thread_dir = sync_dir / "threads" / thread_id
    manifest = _read_json_object(thread_dir / "manifest.json") or {}
    remote_path = thread_dir / "session.jsonl"
    relative_path = str(manifest.get("source_relative_path") or _fallback_session_relative_path(thread_id))
    manifest_target_path = _safe_session_target_path(target_session_dir, relative_path)
    local_path = local_thread.session_path if local_thread is not None else manifest_target_path
    local = _snapshot_file(local_path)
    remote = _snapshot_file(remote_path)
    state_record = _read_local_sync_state(target_session_dir, sync_dir, thread_id)
    base_hash = state_record.base_sha256 if state_record else ""
    local_changed = local.exists and (not base_hash or local.sha256 != base_hash)
    remote_changed = remote.exists and (not base_hash or remote.sha256 != base_hash)
    relation = _prefix_relationship(local, remote)

    if local.exists and remote.exists and local.sha256 == remote.sha256:
        state, action, reason = "synced", "none", "local and remote match"
    elif local.exists and not remote.exists:
        state, action, reason = "local_only", "push", "local conversation is not in the sync folder"
    elif remote.exists and not local.exists:
        state, action, reason = "remote_only", "pull", "sync folder conversation is not local"
    elif not local.exists and not remote.exists:
        state, action, reason = "missing", "skip", "conversation is missing locally and remotely"
    elif base_hash and local_changed and not remote_changed:
        state, action, reason = "local_ahead", "push", "local changed since last sync"
    elif base_hash and remote_changed and not local_changed:
        state, action, reason = "remote_ahead", "pull", "remote changed since last sync"
    elif relation == "remote_prefix_of_local":
        state, action, reason = "fast_forward_push", "push", "local extends remote"
    elif relation == "local_prefix_of_remote":
        state, action, reason = "fast_forward_pull", "pull", "remote extends local"
    else:
        state, action, reason = "conflict", "conflict", "local and remote diverged"

    project_key = local_thread.project_key if local_thread else str(manifest.get("project_key") or "")
    project_label = local_thread.project_label if local_thread else str(manifest.get("project_label") or "")
    return SyncPlanItem(
        thread_id=thread_id,
        state=state,
        action=action,
        reason=reason,
        local_path=str(local.path) if local.path else "",
        remote_path=str(remote.path) if remote.path else "",
        local_sha256=local.sha256,
        remote_sha256=remote.sha256,
        base_sha256=base_hash,
        updated_at=str(manifest.get("updated_at") or (local_thread.updated_at if local_thread else "")),
        source_relative_path=relative_path,
        project_key=project_key,
        project_label=project_label,
        memory_database_rows=_memory_row_count(target_session_dir, thread_id),
    )
```

- [ ] **Step 5: Change `sync_status` to delegate to `plan_sync`**

Replace the entire `sync_status(...)` function with:

```python
def sync_status(*, session_dirs: list[Path], sync_dir: Path, thread_ids: list[str]) -> SyncStatus:
    return plan_sync(session_dirs=session_dirs, sync_dir=sync_dir, thread_ids=thread_ids)
```

- [ ] **Step 6: Run planner tests**

Run:

```powershell
uv run pytest tests/test_sync.py -q
```

Expected:

- Some new planner tests pass.
- Existing import/export tests may fail because import/export do not yet update state or respect plan actions.

---

## Task 3: Update Export To Push Planned Local Changes And Write Base State

**Files:**
- Modify: `src/codex_usage/sync.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Add failing test that export writes local sync state and manifest size**

Append after the new planner tests:

```python
def test_export_writes_sync_state_and_extended_manifest(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sync_dir = tmp_path / "sync"
    sessions = home / "sessions"
    session_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)

    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")

    manifest = json.loads((sync_dir / "threads" / "thread-1" / "manifest.json").read_text(encoding="utf-8"))
    status = plan_sync(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"]).threads[0]

    assert manifest["session_size_bytes"] == session_path.stat().st_size
    assert status["state"] == "synced"
    assert status["base_sha256"] == status["local_sha256"] == status["remote_sha256"]
```

- [ ] **Step 2: Update `export_threads` to plan and skip non-push actions**

Inside `export_threads`, after `threads = ...`, add:

```python
    planned = {
        item["thread_id"]: item
        for item in plan_sync(session_dirs=session_dirs, sync_dir=sync_dir, thread_ids=thread_ids).threads
    }
```

Inside the loop, after resolving `thread`, add:

```python
        plan_item = planned.get(thread_id, {})
        if plan_item.get("action") not in {"push", "none"}:
            skipped.append(thread_id)
            continue
```

Do not skip `none`; identical exports should refresh metadata and base state without rewriting local files.

- [ ] **Step 3: Add `session_size_bytes` to manifest**

In the manifest dict inside `export_threads`, add:

```python
            "session_size_bytes": thread.session_bytes,
```

directly after `"session_sha256": session_hash,`.

- [ ] **Step 4: Write local sync state after export copy**

After `_atomic_write_json(thread_dir / "index-entry.json", ...)`, add:

```python
        local_snapshot = _snapshot_file(thread.session_path)
        remote_snapshot = _snapshot_file(thread_dir / "session.jsonl")
        _write_local_sync_state(
            session_dir,
            sync_dir,
            thread_id=thread_id,
            local_snapshot=local_snapshot,
            remote_snapshot=remote_snapshot,
            source_relative_path=relative_path,
            project_key=thread.project_key,
            project_label=thread.project_label,
        )
```

- [ ] **Step 5: Run export-focused tests**

Run:

```powershell
uv run pytest tests/test_sync.py::test_export_writes_sync_state_and_extended_manifest tests/test_sync.py::test_plan_sync_uses_base_state_for_local_ahead_and_remote_ahead -q
```

Expected:

- Both tests pass.

- [ ] **Step 6: Commit export changes**

Run:

```powershell
git add src/codex_usage/sync.py tests/test_sync.py
git commit -m "Add sync planning state for exports"
```

---

## Task 4: Update Import To Pull Planned Remote Changes And Preserve True Conflicts

**Files:**
- Modify: `src/codex_usage/sync.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Add failing test for fast-forward pull import**

Append:

```python
def test_import_fast_forward_pull_updates_local_and_state(tmp_path: Path) -> None:
    source_home = tmp_path / "source"
    target_home = tmp_path / "target"
    sync_dir = tmp_path / "sync"
    source_sessions = source_home / "sessions"
    target_sessions = target_home / "sessions"
    source_path = _write_session(source_sessions, "thread-1", tmp_path / "repo", total=120)
    export_threads(session_dirs=[source_sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="source")
    target_path = _copy_remote_session_to_local(sync_dir, target_sessions, "thread-1")
    export_threads(session_dirs=[target_sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="target")

    _append_token_event(source_path, "2026-04-29T10:00:03Z", 220)
    export_threads(session_dirs=[source_sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="source")

    before = plan_sync(session_dirs=[target_sessions], sync_dir=sync_dir, thread_ids=["thread-1"]).threads[0]
    assert before["state"] == "remote_ahead"
    result = import_threads(session_dirs=[target_sessions], sync_dir=sync_dir, thread_ids=["thread-1"])
    after = plan_sync(session_dirs=[target_sessions], sync_dir=sync_dir, thread_ids=["thread-1"]).threads[0]

    assert result.imported == ["thread-1"]
    assert result.conflicts == []
    assert target_path.read_bytes() == (sync_dir / "threads" / "thread-1" / "session.jsonl").read_bytes()
    assert after["state"] == "synced"
```

- [ ] **Step 2: Add failing test that true conflict does not overwrite local**

Append:

```python
def test_import_true_conflict_preserves_local_and_saves_remote_candidate(tmp_path: Path) -> None:
    home = tmp_path / "codex"
    sync_dir = tmp_path / "sync"
    sessions = home / "sessions"
    local_path = _write_session(sessions, "thread-1", tmp_path / "repo", total=120)
    export_threads(session_dirs=[sessions], sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="machine-a")
    remote_path = sync_dir / "threads" / "thread-1" / "session.jsonl"

    _append_token_event(local_path, "2026-04-29T10:00:03Z", 180)
    local_before = local_path.read_bytes()
    _append_token_event(remote_path, "2026-04-29T10:00:04Z", 240)

    result = import_threads(
        session_dirs=[sessions],
        sync_dir=sync_dir,
        thread_ids=["thread-1"],
        backup_label="true-conflict",
    )

    assert result.imported == []
    assert result.conflicts == ["thread-1"]
    assert local_path.read_bytes() == local_before
    assert result.backup_dir is not None
    assert (result.backup_dir / "thread-1" / "remote-conflict-session.jsonl").is_file()
```

- [ ] **Step 3: Refactor `import_threads` to use planned actions**

Inside `import_threads`, after `local_threads = ...`, add:

```python
    planned = {
        item["thread_id"]: item
        for item in plan_sync(session_dirs=[target_session_dir], sync_dir=sync_dir, thread_ids=thread_ids).threads
    }
```

Inside the loop, after `thread_id = ...` and before reading manifest, add:

```python
        plan_item = planned.get(thread_id, {})
        action = str(plan_item.get("action") or "")
        if action == "conflict" and conflict_policy != "remote":
            _save_conflict_candidate(backup_dir, thread_id, sync_dir / "threads" / thread_id / "session.jsonl")
            conflicts.append(thread_id)
            continue
        if action not in {"pull", "none"} and conflict_policy != "remote":
            skipped.append(thread_id)
            continue
```

Keep `conflict_policy="remote"` as the explicit override for legacy tests and future resolution commands.

- [ ] **Step 4: Preserve existing duplicate-path safety with planner actions**

Keep the existing block:

```python
        if local_thread_path is not None and not _same_path(local_thread_path, target_path):
```

but change the conflict branch condition from:

```python
            if conflict_policy != "remote":
```

to:

```python
            if conflict_policy != "remote" and action != "pull":
```

This lets remote-ahead imports update the actual local thread path, while still preventing accidental second files for ambiguous manual imports.

- [ ] **Step 5: Remove the old blanket hash-mismatch conflict**

Replace:

```python
        if local_exists and local_hash != remote_hash and conflict_policy != "remote":
            _save_conflict_candidate(backup_dir, thread_id, thread_dir / "session.jsonl")
            conflicts.append(thread_id)
            continue
```

with:

```python
        if local_exists and local_hash != remote_hash and action not in {"pull", "none"} and conflict_policy != "remote":
            _save_conflict_candidate(backup_dir, thread_id, thread_dir / "session.jsonl")
            conflicts.append(thread_id)
            continue
```

- [ ] **Step 6: Write local sync state after successful import**

After any needed `_atomic_copy(...)`, add:

```python
        local_snapshot = _snapshot_file(target_path)
        remote_snapshot = _snapshot_file(thread_dir / "session.jsonl")
        _write_local_sync_state(
            target_session_dir,
            sync_dir,
            thread_id=thread_id,
            local_snapshot=local_snapshot,
            remote_snapshot=remote_snapshot,
            source_relative_path=relative_path,
            project_key=str(plan_item.get("project_key") or manifest.get("project_key") or ""),
            project_label=str(plan_item.get("project_label") or manifest.get("project_label") or ""),
        )
```

- [ ] **Step 7: Run import-focused tests**

Run:

```powershell
uv run pytest tests/test_sync.py::test_import_fast_forward_pull_updates_local_and_state tests/test_sync.py::test_import_true_conflict_preserves_local_and_saves_remote_candidate -q
```

Expected:

- Both tests pass.

- [ ] **Step 8: Run full sync tests**

Run:

```powershell
uv run pytest tests/test_sync.py -q
```

Expected:

- All `tests/test_sync.py` tests pass.
- The duplicate-path tests continue to pass because they guard the rule that one thread id must not create a second local session file.

- [ ] **Step 9: Commit import changes**

Run:

```powershell
git add src/codex_usage/sync.py tests/test_sync.py
git commit -m "Make sync imports prefix aware"
```

---

## Task 5: Improve Status Summary Parsing In The VS Code Wrapper

**Files:**
- Modify: `extensions/vscode/src/core.ts`
- Modify: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Add failing TypeScript status summary test**

In `extensions/vscode/test/core.test.js`, after `test("parseSyncStatusSummary counts states and memory warnings", ...)`, add:

```js
test("parseSyncStatusSummary describes planned pull push and fast-forward states", () => {
  const summary = parseSyncStatusSummary(
    JSON.stringify({
      threads: [
        { thread_id: "a", state: "local_ahead" },
        { thread_id: "b", state: "remote_ahead" },
        { thread_id: "c", state: "fast_forward_push" },
        { thread_id: "d", state: "fast_forward_pull" },
        { thread_id: "e", state: "synced" },
      ],
    }),
  );

  assert.equal(summary.total, 5);
  assert.equal(summary.synced, 1);
  assert.match(summary.message, /1 local change/);
  assert.match(summary.message, /1 remote change/);
  assert.match(summary.message, /2 fast-forward/);
});
```

- [ ] **Step 2: Extend the summary type in `extensions/vscode/src/core.ts`**

Find `export type SyncStatusSummary = { ... }` and add:

```ts
  localChanges: number;
  remoteChanges: number;
  fastForwards: number;
```

- [ ] **Step 3: Count new states in `parseSyncStatusSummary`**

Inside `parseSyncStatusSummary`, initialize:

```ts
  let localChanges = 0;
  let remoteChanges = 0;
  let fastForwards = 0;
```

In the state loop, add:

```ts
    } else if (state === "local_ahead" || state === "local_only") {
      localChanges += 1;
    } else if (state === "remote_ahead" || state === "remote_only") {
      remoteChanges += 1;
    } else if (state === "fast_forward_push" || state === "fast_forward_pull") {
      fastForwards += 1;
```

- [ ] **Step 4: Add summary message parts**

After the existing `synced` part and before conflicts, add:

```ts
  if (localChanges) {
    parts.push(`${localChanges} local change${localChanges === 1 ? "" : "s"}`);
  }
  if (remoteChanges) {
    parts.push(`${remoteChanges} remote change${remoteChanges === 1 ? "" : "s"}`);
  }
  if (fastForwards) {
    parts.push(`${fastForwards} fast-forward${fastForwards === 1 ? "" : "s"}`);
  }
```

Return the new counts:

```ts
  return {
    total,
    synced,
    conflicts,
    missing,
    memoryWarnings,
    localChanges,
    remoteChanges,
    fastForwards,
    message: parts.join(", "),
  };
```

- [ ] **Step 5: Update existing parser tests**

Any existing expected object literals for `parseSyncStatusSummary` must include:

```js
localChanges: 0,
remoteChanges: 0,
fastForwards: 0,
```

- [ ] **Step 6: Run extension tests**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected:

- All extension tests pass.

- [ ] **Step 7: Commit VS Code parser changes**

Run:

```powershell
git add extensions/vscode/src/core.ts extensions/vscode/test/core.test.js
git commit -m "Summarize planned sync states"
```

---

## Task 6: Update CLI Smoke Behavior And Docs Versioning

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`

- [ ] **Step 1: Bump versions to `0.1.16`**

In `pyproject.toml`, change:

```toml
version = "0.1.15"
```

to:

```toml
version = "0.1.16"
```

In `extensions/vscode/package.json`, change:

```json
"version": "0.1.15"
```

to:

```json
"version": "0.1.16"
```

- [ ] **Step 2: Refresh locks**

Run:

```powershell
uv lock
Push-Location extensions\vscode
npm install --package-lock-only
Pop-Location
```

Expected:

- `uv.lock` updates `codex-usage` to `0.1.16`.
- `extensions/vscode/package-lock.json` updates to `0.1.16`.

- [ ] **Step 3: Add changelog entry**

Add above `0.1.15` in `CHANGELOG.md`:

```markdown
## 0.1.16 - Three-Way Sync State

- Added local sync-state tracking so Codex conversation sync can distinguish local-only, remote-only, and true divergent changes.
- Added prefix-aware fast-forward handling for append-only Codex JSONL session files.
- Improved sync status summaries for local changes, remote changes, fast-forwards, and true conflicts.
```

- [ ] **Step 4: Update root README sync section**

In `README.md`, under `## Experimental Conversation Sync`, after the manual-only paragraph, add:

```markdown
Sync uses three-way state per conversation. If one side only appends new Codex JSONL events, the beta treats it as a fast-forward and pulls or pushes automatically. If both computers append different tails to the same conversation, sync stops and preserves both sides for review.
```

- [ ] **Step 5: Update extension README sync section**

In `extensions/vscode/README.md`, under `## Experimental Sync`, after the manual-only paragraph, add:

```markdown
Conversation sync is prefix-aware. Normal append-only progress on one computer is pulled or pushed automatically; true divergent edits on two computers are reported as conflicts and neither side is overwritten.
```

- [ ] **Step 6: Commit docs and version changes**

Run:

```powershell
git add CHANGELOG.md README.md extensions/vscode/README.md pyproject.toml uv.lock extensions/vscode/package.json extensions/vscode/package-lock.json
git commit -m "Document three-way sync state"
```

---

## Task 7: Full Verification, Packaging, And Local Merge

**Files:**
- Verify generated artifact: `output/codex-usage-dashboard-win32-x64.vsix`

- [ ] **Step 1: Run full Python tests**

Run:

```powershell
uv run pytest
```

Expected:

- All Python tests pass.

- [ ] **Step 2: Run extension tests and build**

Run:

```powershell
Push-Location extensions\vscode
npm test
npm run build
Pop-Location
```

Expected:

- Node tests pass.
- TypeScript build succeeds.

- [ ] **Step 3: Run direct sync status smoke**

Run:

```powershell
uv run codex-usage sync status --sync-dir output\manual-sync-smoke --thread-id smoke-missing --json
```

Expected:

- Command exits 0.
- JSON includes one thread with `"state": "missing"` and `"action": "skip"`.

- [ ] **Step 4: Rebuild Windows VSIX**

Run:

```powershell
Push-Location extensions\vscode
npm run package:vsix:win
Pop-Location
```

Expected:

- `output/codex-usage-dashboard-win32-x64.vsix` is rebuilt.
- Package output shows version `0.1.16`.
- VSIX contains `extension/bin/win32-x64/codex-usage.exe`, `extension/out/core.js`, and `extension/out/extension.js`.

- [ ] **Step 5: Inspect package contents**

Run:

```powershell
Push-Location extensions\vscode
npx vsce ls --tree
Pop-Location
```

Expected:

- VSIX contains compiled output and bundled executable.
- VSIX excludes TypeScript source and tests.

- [ ] **Step 6: Run whitespace check**

Run:

```powershell
git diff --check
```

Expected:

- No whitespace errors. Windows line-ending warnings are acceptable if they match current repo behavior.

- [ ] **Step 7: Confirm no tracked packaging changes remain**

Run:

```powershell
git status --short
```

Expected:

- No tracked changes remain after the earlier commits.
- Ignored/generated files such as the rebuilt VSIX may exist but are not committed.

- [ ] **Step 8: Merge back to main locally**

If executing in the expected feature branch, run:

```powershell
git switch main
git pull --ff-only
git merge feature/three-way-sync-state
git branch -d feature/three-way-sync-state
```

Expected:

- Main contains the implementation.
- Feature branch is removed.
- No push is performed unless the user asks.

---

## Manual Smoke Checklist

- [ ] Install the rebuilt VSIX only when ready:

```powershell
code --install-extension output\codex-usage-dashboard-win32-x64.vsix --force
```

- [ ] On computer A, select one project/conversation and run `Sync Now`.
- [ ] On computer B, select the same conversation and run `Sync Now`; it should pull without conflict.
- [ ] Continue the Codex conversation on B, then run `Sync Now`; it should push.
- [ ] Return to A and run `Sync Now`; it should pull the append-only continuation without conflict.
- [ ] Create a deliberate divergent tail on both sides; `Sync Now` should report one true conflict and preserve local plus remote candidate backup.

## Rollback Plan

- [ ] If prefix comparison proves too permissive, keep three-way base state but remove fast-forward states; local-only and remote-only base-aware sync still improves false conflicts.
- [ ] If sync-state files become hard to reason about, add a debug command later, but do not expose raw state as a user setting.
- [ ] If direct `sync export` can still overwrite true conflicts, make export require a planner action of `push` or `none` and add a CLI warning for skipped conflict rows.
