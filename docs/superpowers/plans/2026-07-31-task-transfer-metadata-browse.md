# Task Transfer Metadata Browse Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Task Transfer list only user-visible root tasks and open its picker without parsing or hashing complete Codex histories.

**Architecture:** Add structured session provenance to shared metadata, then build a transfer-specific `LocalTransferProbe` directly from active `session_meta`, index, and filesystem metadata. Browse inventory protocol version 3 combines lightweight local and remote metadata only; the existing planner and byte hashing remain mandatory after the user selects task IDs.

**Tech Stack:** Python 3.13, dataclasses, pytest, TypeScript 5.7, VS Code Quick Pick APIs, Node test runner.

## Global Constraints

- Task Transfer includes only active sessions with valid `session_meta` and no structured `payload.source.subagent` object.
- Spawned subagents, guardians, and automatic reviews are silently omitted from Import, Export, and Review, while their usage remains counted.
- Archived root tasks remain available to usage reporting and excluded from Task Transfer.
- `session_index.jsonl` supplies preferred display metadata but is not an eligibility requirement.
- Transfer browsing must not call the usage parser, mutate the usage cache, hash complete task files, or invoke the synchronization planner.
- Complete identity, containment, hash, prefix, baseline, and conflict checks remain mandatory for selected task IDs before mutation.
- Remote transfer format remains version 3; browse inventory protocol advances from version 2 to version 3.
- Task Transfer intentionally does not apply usage-oriented automatic project-transition inference; Git identity, declared aliases, saved roots, candidate roots, and explicit import bindings remain the transfer identity contract.
- Preserve Windows x64 and macOS Apple Silicon behavior and path guards.
- Use `uv run pytest` for Python tests and `npm test` in `extensions/vscode` for extension tests.

---

### Task 1: Structured Session Provenance

**Files:**
- Create: `src/codex_usage/session_provenance.py`
- Create: `tests/test_session_provenance.py`
- Modify: `src/codex_usage/models.py:81-98`
- Modify: `src/codex_usage/session_files.py:12-40`
- Modify: `src/codex_usage/parser.py:37-179`
- Modify: `src/codex_usage/sync/remote_reconciliation.py:255-278`

**Interfaces:**
- Produces: `is_structured_subagent(payload: dict[str, object]) -> bool`.
- Produces: `parent_thread_id_from_source(payload: dict[str, object]) -> str`.
- Produces: `SessionMetadata.is_subagent: bool = False`.
- Preserves: `parse_session_file(path: Path) -> list[UsageRecord]` includes subagent usage records.

- [ ] **Step 1: Write failing provenance and accounting tests**

Create `tests/test_session_provenance.py` with compact JSONL fixtures covering a spawned child, a parentless guardian, a root task, and token accounting:

```python
from __future__ import annotations

import json
from pathlib import Path

from codex_usage.parser import parse_session_file
from codex_usage.session_files import read_session_metadata
from codex_usage.session_provenance import (
    is_structured_subagent,
    parent_thread_id_from_source,
)


def _write_session(path: Path, source: object) -> None:
    rows = [
        {
            "timestamp": "2026-07-31T12:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": path.stem,
                "cwd": "/repo/demo",
                "source": source,
            },
        },
        {
            "timestamp": "2026-07-31T12:00:01Z",
            "type": "turn_context",
            "payload": {"model": "gpt-5.6-sol"},
        },
        {
            "timestamp": "2026-07-31T12:00:02Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {"total_token_usage": {"input_tokens": 80, "output_tokens": 20, "total_tokens": 100}},
            },
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def test_structured_subagent_classifies_spawn_and_parentless_guardian() -> None:
    spawned = {"source": {"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}}}
    guardian = {"source": {"subagent": {"other": "guardian"}}}
    assert is_structured_subagent(spawned)
    assert is_structured_subagent(guardian)
    assert parent_thread_id_from_source(spawned) == "parent"
    assert parent_thread_id_from_source(guardian) == ""


def test_non_object_subagent_marker_does_not_change_root_classification() -> None:
    assert not is_structured_subagent({"source": "cli"})
    assert not is_structured_subagent({"source": {"subagent": "not-structured"}})


def test_metadata_marks_subagent_but_usage_parser_keeps_its_tokens(tmp_path: Path) -> None:
    path = tmp_path / "child.jsonl"
    _write_session(path, {"subagent": {"other": "review"}})
    metadata = read_session_metadata(path)
    assert metadata is not None and metadata.is_subagent
    assert sum(record.usage.total_tokens for record in parse_session_file(path)) == 100
```

- [ ] **Step 2: Run the tests and verify the contract is absent**

Run: `uv run pytest tests/test_session_provenance.py -q`

Expected: collection fails because `codex_usage.session_provenance` and `SessionMetadata.is_subagent` do not exist.

- [ ] **Step 3: Add the shared structured provenance helpers**

Create `src/codex_usage/session_provenance.py`:

```python
from __future__ import annotations

from typing import Any


def is_structured_subagent(payload: dict[str, Any]) -> bool:
    source = payload.get("source")
    return isinstance(source, dict) and isinstance(source.get("subagent"), dict)


def parent_thread_id_from_source(payload: dict[str, Any]) -> str:
    source = payload.get("source")
    if not isinstance(source, dict):
        return ""
    subagent = source.get("subagent")
    if not isinstance(subagent, dict):
        return ""
    thread_spawn = subagent.get("thread_spawn")
    if not isinstance(thread_spawn, dict):
        return ""
    return str(thread_spawn.get("parent_thread_id") or "")
```

Append `is_subagent: bool = False` to `SessionMetadata`. In `read_session_metadata`, `_parse_session_metadata`, and `_session_metadata_from_bytes`, populate it with `is_structured_subagent(payload)` and replace duplicate parent-ID extractors with `parent_thread_id_from_source(payload)`. Do not add any usage filter to `parse_session_file`.

- [ ] **Step 4: Run focused parser and metadata regression tests**

Run: `uv run pytest tests/test_session_provenance.py tests/test_session_files.py tests/test_parser_aggregation.py -q`

Expected: PASS, including the assertion that a subagent's 100 tokens are still accounted for.

- [ ] **Step 5: Commit the provenance contract**

```bash
git add src/codex_usage/session_provenance.py src/codex_usage/models.py src/codex_usage/session_files.py src/codex_usage/parser.py src/codex_usage/sync/remote_reconciliation.py tests/test_session_provenance.py
git commit -m "feat: classify structured Codex subagents"
```

### Task 2: Metadata-Only Local Transfer Probe

**Files:**
- Rewrite: `src/codex_usage/sync/local_session_probe.py`
- Create: `tests/test_sync_local_transfer_probe.py`
- Modify: `src/codex_usage/sync/__init__.py`

**Interfaces:**
- Consumes: `SessionMetadata.is_subagent` from Task 1.
- Produces: `LocalTransferProbe(inventory: LocalInventory, issues: tuple[SyncIssue, ...])`.
- Produces: `load_local_transfer_probe(session_dirs: list[Path]) -> LocalTransferProbe`.
- Removes from production: `load_sync_session_data_read_only(session_dirs: list[Path], *, auto_transitions: bool) -> CachedSessionData`.

- [ ] **Step 1: Write failing local browse tests**

Create `tests/test_sync_local_transfer_probe.py`. Use a helper that writes only a `session_meta` line and assert all product rules:

```python
def _write_meta(
    path: Path,
    thread_id: str,
    *,
    cwd: str = "/repo/demo",
    source: object = "cli",
    timestamp: str = "2026-07-31T12:00:00Z",
    repo: str = "",
    trailing_bytes: int = 0,
) -> None:
    payload: dict[str, object] = {
        "id": thread_id,
        "timestamp": timestamp,
        "cwd": cwd,
        "source": source,
    }
    if repo:
        payload["git"] = {"repository_url": repo}
    event = {"timestamp": timestamp, "type": "session_meta", "payload": payload}
    path.write_text(
        json.dumps(event) + "\n" + ("x" * trailing_bytes),
        encoding="utf-8",
    )


def test_local_probe_lists_only_active_root_tasks(tmp_path: Path) -> None:
    active = tmp_path / ".codex" / "sessions"
    archived = tmp_path / ".codex" / "archived_sessions"
    active.mkdir(parents=True)
    archived.mkdir(parents=True)
    _write_meta(active / "root.jsonl", "root", source="cli")
    _write_meta(active / "spawned.jsonl", "spawned", source={"subagent": {"thread_spawn": {"parent_thread_id": "root"}}})
    _write_meta(active / "guardian.jsonl", "guardian", source={"subagent": {"other": "guardian"}})
    _write_meta(archived / "archived.jsonl", "archived", source="cli")

    probe = load_local_transfer_probe([active, archived])

    assert list(probe.inventory.threads) == ["root"]
    assert probe.inventory.discovered_count == 1
    assert probe.issues == ()


def test_local_probe_does_not_require_session_index(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(sessions / "root.jsonl", "root", cwd="/repo/demo", source="cli")
    thread = load_local_transfer_probe([sessions]).inventory.threads["root"]
    assert thread.title == "demo"
    assert thread.total_tokens == 0


def test_local_probe_never_calls_usage_parser_or_hasher(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(sessions / "root.jsonl", "root", source="cli", trailing_bytes=2_000_000)
    monkeypatch.setattr(parser_module, "parse_session_file", lambda path: pytest.fail("usage parser called"))
    monkeypatch.setattr(sync_io, "snapshot_file", lambda path: pytest.fail("full hash called"))
    assert list(load_local_transfer_probe([sessions]).inventory.threads) == ["root"]
```

Add named tests with these exact assertions:

```python
def _sessions_with_root(tmp_path: Path, thread_id: str, *, cwd: str) -> Path:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(sessions / f"{thread_id}.jsonl", thread_id, cwd=cwd, source="cli")
    return sessions


def _write_index(path: Path, thread_id: str, title: str, updated_at: str) -> None:
    path.write_text(
        json.dumps({"id": thread_id, "thread_name": title, "updated_at": updated_at}) + "\n",
        encoding="utf-8",
    )


def test_local_probe_prefers_index_display_metadata(tmp_path: Path) -> None:
    sessions = _sessions_with_root(tmp_path, "root", cwd="/repo/demo")
    _write_index(tmp_path / ".codex" / "session_index.jsonl", "root", "Indexed title", "2026-07-31T13:00:00Z")
    thread = load_local_transfer_probe([sessions]).inventory.threads["root"]
    assert (thread.title, thread.updated_at) == ("Indexed title", "2026-07-31T13:00:00Z")


def test_local_probe_reports_malformed_metadata(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "broken.jsonl").write_text("not-json\n", encoding="utf-8")
    probe = load_local_transfer_probe([sessions])
    assert probe.inventory.threads == {}
    assert [issue.code for issue in probe.issues] == ["local_session_metadata_unreadable"]


def test_local_probe_keeps_newest_duplicate_active_identity(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(sessions / "old.jsonl", "root", timestamp="2026-07-30T12:00:00Z", source="cli")
    _write_meta(sessions / "new.jsonl", "root", timestamp="2026-07-31T12:00:00Z", source="cli")
    assert load_local_transfer_probe([sessions]).inventory.threads["root"].session_path.name == "new.jsonl"


def test_local_probe_uses_portable_git_identity_for_windows_cwd(tmp_path: Path) -> None:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    _write_meta(
        sessions / "root.jsonl",
        "root",
        cwd=r"D:\Projects\Demo",
        repo="https://github.com/Example/Demo.git",
    )
    thread = load_local_transfer_probe([sessions]).inventory.threads["root"]
    assert thread.project_key == "https://github.com/example/demo"
    assert thread.project_label == "demo"
    assert "d:/projects/demo" in thread.project_aliases
```

- [ ] **Step 2: Run focused tests and verify they fail**

Run: `uv run pytest tests/test_sync_local_transfer_probe.py -q`

Expected: FAIL because `LocalTransferProbe` and `load_local_transfer_probe` are missing.

- [ ] **Step 3: Replace the usage-oriented loader with a metadata probe**

Implement the public contract in `local_session_probe.py` without importing `parser`, `session_cache`, or `project_transitions`:

```python
from dataclasses import dataclass
from datetime import UTC, datetime


_ESTIMATED_SYNC_METADATA_BYTES = 4096


@dataclass(frozen=True)
class LocalTransferProbe:
    inventory: LocalInventory
    issues: tuple[SyncIssue, ...]


def load_local_transfer_probe(session_dirs: list[Path]) -> LocalTransferProbe:
    index_entries = load_all_index_entries(session_dirs)
    threads: dict[str, ThreadInfo] = {}
    metadata_timestamps: dict[str, datetime] = {}
    issues: list[SyncIssue] = []
    for session_dir in session_dirs:
        if storage_state_for_session_dir(session_dir) != "active" or not session_dir.is_dir():
            continue
        for path in sorted(session_dir.rglob("*.jsonl"), key=lambda item: str(item).casefold()):
            if not path.is_file():
                continue
            metadata = read_session_metadata(path)
            if metadata is None:
                issues.append(SyncIssue("local_session_metadata_unreadable", f"Local task {path} has no readable session_meta identity"))
                continue
            if metadata.is_subagent:
                continue
            identity = resolve_project_identity(metadata)
            index_entry = index_entries.get(metadata.session_id, {})
            size = file_size(path)
            thread = ThreadInfo(
                thread_id=metadata.session_id,
                title=str(index_entry.get("thread_name") or index_entry.get("title") or identity.label or metadata.session_id),
                updated_at=str(index_entry.get("updated_at") or session_updated_at(path, metadata.timestamp)),
                session_path=path,
                project_key=identity.key,
                project_label=identity.label,
                project_aliases=identity.aliases,
                total_tokens=0,
                session_bytes=size,
                estimated_sync_bytes=size + _ESTIMATED_SYNC_METADATA_BYTES,
                memory_mode=metadata.memory_mode,
                has_base_instructions=metadata.has_base_instructions,
                cwd=metadata.cwd,
            )
            metadata_timestamp = metadata.timestamp or datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            previous_timestamp = metadata_timestamps.get(thread.thread_id)
            if previous_timestamp is None or metadata_timestamp >= previous_timestamp:
                threads[thread.thread_id] = thread
                metadata_timestamps[thread.thread_id] = metadata_timestamp
    inventory = LocalInventory(
        session_dirs=tuple(session_dirs),
        threads=threads,
        index_entries=index_entries,
        discovered_count=len(threads),
        project_roots=discover_project_roots(tuple(session_dirs)),
    )
    return LocalTransferProbe(inventory, tuple(issues))
```

Export the two new names from `codex_usage.sync`. Keep `sync/inventory.py::build_local_inventory` temporarily as a fixture adapter for existing unit tests, but remove it from every production Task Transfer call path in Task 3.

- [ ] **Step 4: Run the local probe and transfer inventory tests**

Run: `uv run pytest tests/test_sync_local_transfer_probe.py tests/test_sync_inventory.py -q`

Expected: PASS. The no-parser/no-hasher guard test must pass with a large irrelevant suffix.

- [ ] **Step 5: Commit the local probe**

```bash
git add src/codex_usage/sync/local_session_probe.py src/codex_usage/sync/__init__.py tests/test_sync_local_transfer_probe.py
git commit -m "perf: build transfer inventory from session metadata"
```

### Task 3: Give Transfer Execution a `LocalInventory` Contract

**Files:**
- Modify: `src/codex_usage/sync/runner.py:10-175`
- Modify: `src/codex_usage/sync_cli.py:9-268`
- Modify: `src/codex_usage/cli.py:38,277-290`
- Modify: `tests/test_sync_cli.py`
- Modify: `tests/test_sync_cli_inventory.py`
- Modify: `tests/test_sync_runner.py`
- Modify: `tests/test_sync_runner_bookkeeping.py`
- Modify: `tests/test_sync_runner_reconciliation.py`
- Modify: `tests/test_sync_runner_timing.py`
- Modify: `tests/test_sync_runner_validation.py`
- Modify: `tests/test_sync_scope_read_only.py`
- Modify: `tests/test_sync_project_resolution_security.py`
- Modify: `tests/test_sync_existing_counterpart_security.py`
- Modify: `tests/test_sync_inventory.py`

**Interfaces:**
- Consumes: `load_local_transfer_probe(session_dirs) -> LocalTransferProbe` from Task 2.
- Produces: runner entry points with `local: LocalInventory`, never `data: CachedSessionData`.
- Produces: `TransferInventoryLoader.__call__(session_dirs: list[Path]) -> LocalTransferProbe`.
- Removes from sync-only CLI: `--no-auto-transitions` and transfer calls to project-transition inference.

- [ ] **Step 1: Update runner tests to express the new boundary**

Change representative calls from:

```python
result = push_sync(data=data, sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="a", project_key="repo")
```

to:

```python
local = build_local_inventory(data)
result = push_sync(local=local, sync_dir=sync_dir, thread_ids=["thread-1"], machine_id="a", project_key="repo")
```

Add `assert "build_local_inventory" not in runner_module.__dict__` in `tests/test_sync_scope_read_only.py`. Update CLI fake loaders to accept only `paths: list[Path]` and return `LocalTransferProbe(local, ())`.

- [ ] **Step 2: Run runner and CLI tests to verify the signature mismatch**

Run: `uv run pytest tests/test_sync_cli.py tests/test_sync_cli_inventory.py tests/test_sync_runner.py tests/test_sync_scope_read_only.py -q`

Expected: FAIL because runner functions still require `data` and CLI loaders still pass `auto_transitions`.

- [ ] **Step 3: Refactor runner entry points to consume `LocalInventory` directly**

Use these exact signatures and wrappers; `sync_status` keeps its existing error-to-plan conversion while starting from the supplied inventory:

```python
def sync_status(*, local: LocalInventory, sync_dir: Path, thread_ids: Iterable[str], project_resolution: ProjectResolutionRequest) -> SyncPlan:
    store = RemoteStore(sync_dir)
    try:
        _, plan = prepare_status_plan(local, store, sync_dir, thread_ids, project_resolution)
    except SyncStoreError as error:
        return _load_failure_plan(local, error)
    return plan

def pull_sync(*, local: LocalInventory, sync_dir: Path, thread_ids: Iterable[str], project_resolution: ProjectResolutionRequest, project_key: str, discovery_ms: int = 0, on_progress: Callable[[SyncProgressEvent], None] | None = None) -> SyncRunResult:
    return _run_direction(direction="pull", local=local, sync_dir=sync_dir, thread_ids=thread_ids, project_resolution=project_resolution, project_key=project_key, machine_id="", discovery_ms=discovery_ms, on_progress=on_progress)

def push_sync(*, local: LocalInventory, sync_dir: Path, thread_ids: Iterable[str], machine_id: str, project_key: str, project_resolution: ProjectResolutionRequest = ProjectResolutionRequest(), discovery_ms: int = 0, on_progress: Callable[[SyncProgressEvent], None] | None = None) -> SyncRunResult:
    return _run_direction(direction="push", local=local, sync_dir=sync_dir, thread_ids=thread_ids, project_resolution=project_resolution, project_key=project_key, machine_id=machine_id, discovery_ms=discovery_ms, on_progress=on_progress)
```

Pass `local` into `_run_direction` and delete the `CachedSessionData` and `build_local_inventory` imports and planning-time conversion. Keep `PhaseTimer.discovery_ms` measured around the metadata probe.

- [ ] **Step 4: Refactor sync CLI loading and remove transfer transition inference**

Define:

```python
class TransferInventoryLoader(Protocol):
    def __call__(self, session_dirs: list[Path]) -> LocalTransferProbe: ...


def _load_local_transfer_probe(
    *, create_sessions: bool, load_inventory: TransferInventoryLoader
) -> tuple[LocalTransferProbe, int]:
    session_dirs = _sync_session_dirs(create=create_sessions)
    _emit_sync_progress(SyncProgressEvent("sync_progress", "scanning"))
    started = perf_counter()
    probe = load_inventory(session_dirs)
    return probe, max(0, int((perf_counter() - started) * 1000))
```

Update handlers to pass `probe.inventory` as `local`; inventory also passes `probe.issues` into Task 5's browse loader. Remove `--no-auto-transitions` from `add_sync_common_options` and stop reading settings in `sync_cli.py`. Update `cli.py` to inject `load_local_transfer_probe` into all four transfer handlers. Usage/report commands retain their existing `--no-auto-transitions` setting and behavior.

- [ ] **Step 5: Update all runner fixtures and run the complete sync suite**

Use `rg -n "push_sync\(.*data=|pull_sync\(.*data=|sync_status\(.*data=|build_local_inventory" tests src/codex_usage/sync` to locate stale production and fixture calls. Fixture-only uses of `build_local_inventory` are allowed; production uses are not.

Run: `uv run pytest tests/test_sync*.py -q`

Expected: PASS.

- [ ] **Step 6: Commit the transfer execution boundary**

```bash
git add src/codex_usage/sync/runner.py src/codex_usage/sync_cli.py src/codex_usage/cli.py tests/test_sync_cli.py tests/test_sync_cli_inventory.py tests/test_sync_runner.py tests/test_sync_runner_bookkeeping.py tests/test_sync_runner_reconciliation.py tests/test_sync_runner_timing.py tests/test_sync_runner_validation.py tests/test_sync_scope_read_only.py tests/test_sync_project_resolution_security.py tests/test_sync_existing_counterpart_security.py tests/test_sync_inventory.py
git commit -m "refactor: decouple task transfer from usage data"
```

### Task 4: Metadata-Only Remote Browse Probe

**Files:**
- Modify: `src/codex_usage/sync/io.py:57-70`
- Modify: `src/codex_usage/sync/remote_reconciliation.py:30-190,237-278`
- Modify: `src/codex_usage/sync/remote_inventory_probe.py:36-110,178-202`
- Modify: `src/codex_usage/sync/store.py:78-90`
- Modify: `tests/test_sync_selection_inventory_loading.py`
- Create: `tests/test_sync_remote_reconciliation.py`

**Interfaces:**
- Consumes: `SessionMetadata.is_subagent` from Task 1.
- Produces: `metadata_snapshot(path: Path | None) -> SyncFileSnapshot` with existence and size but blank SHA-256.
- Produces: `probe_remote_inventory(root: Path, *, metadata_only: bool = False) -> RemoteInventory`.
- Produces: `RemoteStore.probe_inventory(*, metadata_only: bool = False) -> RemoteInventory`.
- Produces: `materialize_remote_metadata_for_selection(root: Path, inventory: RemoteInventory) -> RemoteInventory`.
- Preserves: default execution probes and selected-task materialization still hash full selected files.

- [ ] **Step 1: Add failing operation-count and remote-subagent tests**

In `tests/test_sync_selection_inventory_loading.py`, add version-3 cases that write a large irrelevant suffix after `session_meta`, monkeypatch `sync_io.snapshot_file` and `remote_reconciliation.read_bytes_with_snapshot` to fail for the indexed task, and assert metadata-only browse still returns it. Add a remote source fixture with `{"subagent": {"other": "guardian"}}` and assert the task is absent with no warning.

Replace the existing version-3 unreadable-file test's full-byte monkeypatch with `remote_reconciliation.read_session_metadata` returning `None` for the indexed path; assert the task is omitted with one `unindexed_unreadable` issue. This keeps the failure fixture aligned with the new streaming read layer.

In `tests/test_sync_remote_reconciliation.py`, add:

```python
def _write_session_meta(path: Path, thread_id: str, *, source: object) -> None:
    path.write_text(
        json.dumps({
            "timestamp": "2026-07-31T12:00:00Z",
            "type": "session_meta",
            "payload": {"id": thread_id, "cwd": "/repo/demo", "source": source},
        }) + "\n",
        encoding="utf-8",
    )


def _remote_entry(thread_id: str, file: str) -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id=thread_id,
        file=file,
        source_relative_path=f"2026/07/31/{thread_id}.jsonl",
        index_entry={"id": thread_id, "thread_name": "Review"},
        project_key="https://github.com/example/demo",
        project_label="demo",
        project_aliases=(),
        sha256="indexed-sha",
        size_bytes=1,
        session_updated_at="2026-07-31T12:00:00Z",
        exported_at="2026-07-31T12:00:00Z",
        source_machine_id="machine-a",
    )


def test_selected_remote_subagent_is_rejected_from_execution(tmp_path: Path) -> None:
    root = tmp_path / "sync"
    path = root / "tasks" / "review.jsonl"
    path.parent.mkdir(parents=True)
    _write_session_meta(path, "review", source={"subagent": {"other": "review"}})
    entry = _remote_entry("review", "tasks/review.jsonl")
    index = RemoteIndex(REMOTE_TRANSFER_FORMAT_VERSION, "", {"review": entry})
    remote = RemoteInventory(index, index, SyncFileSnapshot(None, False), {}, (), ())
    materialized = materialize_selected_remote(
        root,
        remote,
        ("review",),
        lambda candidate: guard_task_file(root, candidate),
    )
    assert any(issue.code == "subagent_not_transferable" and issue.thread_id == "review" for issue in materialized.issues)
```

Also assert an unindexed version-3 root can be reconstructed for browsing with a blank `sha256`, while default execution reconstruction still has a real 64-character SHA-256.

- [ ] **Step 2: Run remote probe tests and confirm full reads occur**

Run: `uv run pytest tests/test_sync_selection_inventory_loading.py tests/test_sync_remote_reconciliation.py -q`

Expected: FAIL because the browse path calls `read_bytes_with_snapshot` for indexed tasks and lacks structured subagent rejection.

- [ ] **Step 3: Add a retrying metadata snapshot primitive**

In `sync/io.py`, add a stat-only helper using the existing transient filesystem retry predicate:

```python
@retry(
    retry=retry_if_exception(_is_transient_filesystem_error),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.5),
    stop=stop_after_attempt(4),
    reraise=True,
)
def metadata_snapshot(path: Path | None) -> SyncFileSnapshot:
    if path is None:
        return SyncFileSnapshot(path=None, exists=False)
    try:
        size_bytes = path.stat().st_size
    except (FileNotFoundError, IsADirectoryError):
        return SyncFileSnapshot(path=path, exists=False)
    return SyncFileSnapshot(path=path, exists=True, size_bytes=size_bytes)
```

- [ ] **Step 4: Parameterize discovery and add indexed metadata materialization**

Thread `metadata_only: bool = False` from `RemoteStore.probe_inventory` through `probe_remote_inventory`, `_reconcile`, and `reconcile_remote_discovery`. For unindexed version-3 files, metadata-only mode must call `read_session_metadata(path)` plus `metadata_snapshot(path)` instead of `read_bytes_with_snapshot`.

Implement indexed browse classification:

```python
def materialize_remote_metadata_for_selection(
    root: Path,
    inventory: RemoteInventory,
) -> RemoteInventory:
    files = dict(inventory.files)
    threads = dict(inventory.index.threads)
    issues = list(inventory.issues)
    for thread_id, entry in tuple(threads.items()):
        snapshot = files.get(thread_id)
        if snapshot is not None and not snapshot.exists:
            continue
        path = snapshot.path if snapshot is not None else root / entry.file
        if path is None:
            continue
        _guard_for_format(root, inventory.index.format_version, path)
        metadata = read_session_metadata(path)
        if metadata is not None and metadata.is_subagent:
            threads.pop(thread_id, None)
            files.pop(thread_id, None)
            continue
        if metadata is None or metadata.session_id != thread_id:
            files.pop(thread_id, None)
            issues.append(_indexed_metadata_issue(entry, metadata))
            continue
        if snapshot is None:
            files[thread_id] = metadata_snapshot(path)
    return replace(inventory, index=replace(inventory.index, threads=threads), files=files, issues=tuple(issues))
```

Define the format guard used above in the same module:

```python
def _guard_for_format(root: Path, format_version: int, path: Path) -> None:
    if format_version == LEGACY_REMOTE_TRANSFER_FORMAT_VERSION:
        guard_legacy_file(root, path)
    else:
        guard_task_file(root, path)
```

For legacy format version 2, preserve the existing full read-only validation path because it is migration compatibility, not the current format. In `materialize_selected_remote`, add `subagent_not_transferable` before accepting selected remote metadata. Browse omits subagents silently; explicit execution selection returns a structured blocking issue.

- [ ] **Step 5: Prove browse is metadata-only and selected execution still hashes**

Run: `uv run pytest tests/test_sync_selection_inventory_loading.py tests/test_sync_remote_reconciliation.py tests/test_sync_scope_read_only.py -q`

Expected: PASS. The v3 browse guard must fail the test if any complete-content helper is called; selected execution tests must still observe complete SHA-256 snapshots.

- [ ] **Step 6: Commit remote metadata probing**

```bash
git add src/codex_usage/sync/io.py src/codex_usage/sync/remote_reconciliation.py src/codex_usage/sync/remote_inventory_probe.py src/codex_usage/sync/store.py tests/test_sync_selection_inventory_loading.py tests/test_sync_remote_reconciliation.py
git commit -m "perf: probe remote transfer metadata without hashing"
```

### Task 5: Browse Inventory Protocol Version 3

**Files:**
- Modify: `src/codex_usage/sync/selection_inventory.py`
- Modify: `tests/test_sync_selection_inventory.py`
- Modify: `tests/test_sync_selection_inventory_loading.py`
- Modify: `tests/test_sync_cli_inventory.py`

**Interfaces:**
- Consumes: `LocalTransferProbe` from Task 2 and metadata-only remote probes from Task 4.
- Produces: `INVENTORY_VERSION = 3`.
- Produces: `SyncTaskInventoryItem(thread_id, title, updated_at, estimated_sync_bytes, availability)` with no `state` or `action`.
- Produces: `load_sync_selection_inventory(local_probe: LocalTransferProbe, sync_dir: Path, *, candidate_roots: tuple[Path, ...] = ()) -> SyncSelectionInventory`.
- Guarantees: `build_sync_selection_inventory` never calls `build_sync_plan`.

- [ ] **Step 1: Rewrite inventory tests for the browse-only contract**

Change strict payload expectations to:

```python
{
    "inventory_version": 3,
    "projects": [{
        "project_key": "repo",
        "project_label": "Repo",
        "identity_kind": "path",
        "candidate_roots": [],
        "tasks": [{
            "thread_id": "local",
            "title": "Local",
            "updated_at": "2026-07-14T12:00:00Z",
            "estimated_sync_bytes": 4196,
            "availability": "local",
        }],
    }],
    "issues": [],
}
```

Delete assertions about exact `state`/`action`. Add a test that monkeypatches `codex_usage.sync.planner.build_sync_plan` and `codex_usage.sync.io.snapshot_file` to raise, then calls browse inventory and receives local/remote/both rows. Add a test that local probe issues and remote issues are preserved exactly once.

- [ ] **Step 2: Run inventory tests and verify version/shape failures**

Run: `uv run pytest tests/test_sync_selection_inventory.py tests/test_sync_selection_inventory_loading.py tests/test_sync_cli_inventory.py -q`

Expected: FAIL because protocol version 2 still emits `state` and `action` and invokes the planner.

- [ ] **Step 3: Remove planner state from browse construction**

Set `INVENTORY_VERSION = 3`, delete `_materialize_remote_for_selection`, and remove imports of `CachedSessionData`, `build_local_inventory`, `build_sync_plan`, and plan snapshots used only for state. Build `remote_entries` from existing metadata snapshots, merge by thread ID, retain the current project identity/alias preference and candidate-root resolution, and emit only availability.

The load function becomes:

```python
def load_sync_selection_inventory(
    local_probe: LocalTransferProbe,
    sync_dir: Path,
    *,
    candidate_roots: tuple[Path, ...] = (),
) -> SyncSelectionInventory:
    store = RemoteStore(sync_dir)
    remote = store.probe_inventory(metadata_only=True)
    if remote.index.format_version == LEGACY_REMOTE_TRANSFER_FORMAT_VERSION:
        remote = store.materialize_probed(remote, tuple(remote.index.threads))
    else:
        remote = materialize_remote_metadata_for_selection(sync_dir, remote)
    return build_sync_selection_inventory(
        local_probe.inventory,
        remote,
        candidate_roots=candidate_roots,
        local_issues=local_probe.issues,
    )
```

Remove the unused `sync_dir` parameter from `build_sync_selection_inventory`; it existed only for full planning. Return `issues=(*local_issues, *remote.issues)`.

- [ ] **Step 4: Run browse, CLI, and planner regression tests**

Run: `uv run pytest tests/test_sync_selection_inventory.py tests/test_sync_selection_inventory_loading.py tests/test_sync_cli_inventory.py tests/test_sync_planner.py -q`

Expected: PASS. Planner tests remain unchanged because execution retains exact state.

- [ ] **Step 5: Commit protocol version 3 on the Python side**

```bash
git add src/codex_usage/sync/selection_inventory.py tests/test_sync_selection_inventory.py tests/test_sync_selection_inventory_loading.py tests/test_sync_cli_inventory.py
git commit -m "refactor: make task inventory a browse contract"
```

### Task 6: VS Code Browse Protocol and Availability-Only Picker

**Files:**
- Modify: `extensions/vscode/src/syncInventory.ts`
- Modify: `extensions/vscode/src/syncTaskPicker.ts`
- Modify: `extensions/vscode/src/syncProtocol.ts`
- Modify: `extensions/vscode/src/syncCommandArgs.ts`
- Modify: `extensions/vscode/src/taskTransfer.ts`
- Modify: `extensions/vscode/src/taskTransferVscode.ts`
- Modify: `extensions/vscode/src/extension.ts`
- Modify: `extensions/vscode/test/syncInventory.test.js`
- Modify: `extensions/vscode/test/syncTaskPicker.test.js`
- Modify: `extensions/vscode/test/syncProtocol.test.js`
- Modify: `extensions/vscode/test/taskTransfer.test.js`
- Modify: `extensions/vscode/test/taskTransferConcurrency.test.js`
- Modify: `extensions/vscode/test/taskTransferNotifications.test.js`
- Modify: `extensions/vscode/test/taskTransferRegistration.test.js`
- Modify: `extensions/vscode/test/taskTransferVscode.test.js`
- Modify: `extensions/vscode/test/taskTransferProjectResolution.test.js`
- Modify: `extensions/vscode/test/syncProcess.test.js`

**Interfaces:**
- Consumes: Python browse inventory protocol version 3 from Task 5.
- Produces: `SyncInventoryTask` without `state` or `action`.
- Produces: transfer command options without `autoTransitions`.
- Preserves: two-stage, one-project picker; zero tasks selected by default; Back navigation; search limited to the active project's tasks.

- [ ] **Step 1: Add failing TypeScript contract and picker tests**

Update the valid fixture to protocol version 3 and remove `state`/`action`. Add strict parser cases that reject either old field as unknown. Assert task rows render:

```javascript
assert.equal(rows.find((row) => row.kind === "task").description, "On this computer");
```

for local availability, with existing labels for remote and both. Keep these behavioral assertions:

```javascript
assert.deepEqual(initialTaskPickerSelection("export"), {
  activeProjectKey: undefined,
  selectedThreadIds: [],
});
assert.deepEqual(visibleTaskPickerItems(rows, activated, "export").map((row) => row.kind), ["task", "task"]);
```

Update command tests so no Task Transfer argument builder emits `--no-auto-transitions` and option fixtures no longer require `autoTransitions`.

Keep the existing inventory-issue behavior test: one concise `taskInventoryWarningMessage()` notification is shown while every issue is still written to the output log. Keep the execution-order test proving the selected-task checking status begins only after task confirmation.

- [ ] **Step 2: Run extension tests and verify protocol failures**

Run: `cd extensions/vscode && npm run build && npm run typecheck:contracts && node --test --test-name-pattern='inventory|picker|transfer|protocol' test/*.test.js`

Expected: FAIL because the parser requires version 2 plus `state`/`action` and transfer options still require `autoTransitions`.

- [ ] **Step 3: Update the strict decoder and picker copy**

Use:

```typescript
export type SyncInventoryTask = {
  threadId: string;
  title: string;
  updatedAt: string;
  estimatedSyncBytes: number;
  availability: SyncTaskAvailability;
};

export type SyncInventory = {
  inventoryVersion: 3;
  projects: SyncInventoryProject[];
  issues: SyncInventoryIssue[];
};
```

Set `TASK_KEYS` to the five browse fields, require `inventory_version === 3`, and return `inventoryVersion: 3`. In `syncTaskPicker.ts`, remove `taskStateLabel` and set `description: taskAvailabilityLabel(task.availability)`. Do not weaken `exactRecord`; old or extra fields must fail loudly.

- [ ] **Step 4: Remove usage transition options from Task Transfer wiring**

Delete `autoTransitions` from `SyncCommandOptions`, `SyncInventoryCommandOptions`, `TransferRequestContext`, the `TaskTransferController` constructor, `extension.ts` construction, and all sync argument builders. Update every `new TaskTransferController(port, () => true|false)` fixture to `new TaskTransferController(port)`. Retain `codexUsage.projectTransitions.autoDetect` for dashboard usage commands in `core.ts`; only Task Transfer stops consuming it.

- [ ] **Step 5: Run all extension tests and type contracts**

Run: `cd extensions/vscode && npm test`

Expected: PASS, including strict protocol, two-stage picker, project resolution, and execution progress tests.

- [ ] **Step 6: Commit the VS Code protocol update**

```bash
git add extensions/vscode/src/syncInventory.ts extensions/vscode/src/syncTaskPicker.ts extensions/vscode/src/syncProtocol.ts extensions/vscode/src/syncCommandArgs.ts extensions/vscode/src/taskTransfer.ts extensions/vscode/src/taskTransferVscode.ts extensions/vscode/src/extension.ts extensions/vscode/test/syncInventory.test.js extensions/vscode/test/syncTaskPicker.test.js extensions/vscode/test/syncProtocol.test.js extensions/vscode/test/taskTransfer.test.js extensions/vscode/test/taskTransferConcurrency.test.js extensions/vscode/test/taskTransferNotifications.test.js extensions/vscode/test/taskTransferRegistration.test.js extensions/vscode/test/taskTransferVscode.test.js extensions/vscode/test/taskTransferProjectResolution.test.js extensions/vscode/test/syncProcess.test.js
git commit -m "feat: show user tasks in metadata-only picker"
```

### Task 7: Durable Contract Record and End-to-End Verification

**Files:**
- Create: `docs/adr/0018-user-visible-task-transfer-inventory.md`
- Modify: `docs/adr/README.md`
- Modify: `scripts/packaged_sync_smoke_validation.py`
- Modify: `scripts/smoke-test-packaged-sync.py`
- Test: full Python and extension suites

**Interfaces:**
- Documents: root-task eligibility, usage/transfer divergence, metadata-only browse, selected-only validation, and rejected index-membership/parent-ID alternatives.
- Preserves: packaged version-3 push/pull smoke on both supported platforms.

- [ ] **Step 1: Extend packaged smoke fixtures with an internal subagent**

Add one local subagent JSONL beside the root smoke task using structured `source.subagent.other`, then assert inventory still contains exactly the expected root task. Add a remote subagent entry/file and assert it is omitted before the smoke selects and transfers the root task. Do not include private local session data.

- [ ] **Step 2: Build the macOS executable and run its packaged smoke gate**

Run: `cd extensions/vscode && npm run build:python:mac`

Expected: PyInstaller succeeds and the build script prints `Packaged Task Transfer smoke passed` after the root-only inventory assertions pass.

- [ ] **Step 3: Write ADR 0018**

Create `docs/adr/0018-user-visible-task-transfer-inventory.md` with these sections and decisions:

```markdown
# ADR 0018: User-Visible Task Transfer Inventory

## Status
Accepted

## Context
Codex stores user tasks and internal subagent sessions in the same JSONL tree. Task Transfer also reused usage parsing and full synchronization planning before selection, causing incorrect counts and multi-minute browse latency.

## Decision
Task Transfer exposes only active sessions with valid `session_meta` and no structured `payload.source.subagent` object. Usage accounting continues to include every session. Browse inventory reads metadata, index display fields, file size, and project roots only; complete identity and content validation runs for selected IDs only.

Automatic project-transition inference remains a usage-report feature. Transfer identity uses Git metadata, declared aliases, saved roots, candidate roots, and explicit bindings so browsing never needs event-history parsing.

## Rejected Alternatives
- Parent-thread ID filtering misses parentless guardians and reviews.
- Requiring session-index membership hides valid imports during index lag.
- Exact preflight state in the picker requires hashing every task.
- Deleting old remote subagent files would make read-only browsing mutate user storage.

## Consequences
Task counts match the Codex UI, browse work scales with metadata rather than task history, and stale or changed selected files remain protected by the existing planner. Old remote subagent files remain untouched and hidden.
```

Link ADR 0018 from `docs/adr/README.md`.

- [ ] **Step 4: Run source-size and dependency boundary checks**

Run:

```bash
wc -l src/codex_usage/sync/*.py src/codex_usage/*.py
rg -n "CachedSessionData|parse_session_file|collect_repo_path_observations|build_sync_plan|snapshot_file" src/codex_usage/sync/local_session_probe.py src/codex_usage/sync/selection_inventory.py src/codex_usage/sync_cli.py
```

Expected: no modified module exceeds 500 lines; the second command returns no forbidden browse-path dependency. `selection_inventory.py` may refer to neither `build_sync_plan` nor `snapshot_file`.

- [ ] **Step 5: Run all automated tests**

Run:

```bash
uv run pytest -q
cd extensions/vscode && npm test
```

Expected: both suites PASS.

- [ ] **Step 6: Run a local real-data browse acceptance check**

With a temporary empty transfer directory, time the JSON inventory command and inspect only aggregate project/task counts:

```bash
tmp_dir="$(mktemp -d)"
time uv run codex-usage sync inventory --json --sync-dir "$tmp_dir" > "$tmp_dir/inventory.json"
uv run python -c 'import json,sys; p=json.load(open(sys.argv[1])); print({x["project_label"]: len(x["tasks"]) for x in p["projects"] if x["project_label"] in {"codex_usage", "ebook_translate"}})' "$tmp_dir/inventory.json"
rm -rf "$tmp_dir"
```

Expected on the measured Mac: `codex_usage` and `ebook_translate` each report one task, and browse finishes in seconds rather than minutes. Do not commit the generated inventory.

- [ ] **Step 7: Commit the ADR and smoke guardrails**

```bash
git add docs/adr/0018-user-visible-task-transfer-inventory.md docs/adr/README.md scripts/packaged_sync_smoke_validation.py scripts/smoke-test-packaged-sync.py
git commit -m "docs: record user-visible transfer task contract"
```

## Plan Completion Gate

Before starting the usage-parser plan, verify:

- `git status --short` contains no unintended files.
- Task Transfer browse code has no usage parser/cache dependency.
- Root-only counts match the local Codex UI for `codex_usage` and `ebook_translate`.
- Browse does not hash indexed version-3 tasks.
- Explicitly selected execution still performs complete hashes and conservative planning.
- Python and VS Code suites pass.
