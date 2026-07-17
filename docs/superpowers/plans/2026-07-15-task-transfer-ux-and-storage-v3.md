# Task Transfer UX And Storage V3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the extension's persistent Sync setup with deliberate Import, Export, and Review operations; migrate portable folders from version-2 `conversations/` storage to version-3 `tasks/`; and make imports work from VS Code workspace roots without requiring the Codex desktop app.

**Architecture:** Keep the Python sync engine and its technical `sync pull`, `sync push`, `sync status`, `thread_id`, and three-way planning contracts as private implementation details. Separate remote format versioning from local baseline versioning, add a lock-protected migration module, pass transient project candidates and bindings through the private CLI, and enforce directional preflight in Python. Replace extension setup state with one remembered folder, drive every operation through a fresh picker, and split transfer orchestration and presentation out of oversized extension modules.

**Tech Stack:** Python 3.13, pytest, TypeScript 5.7, VS Code 1.90 APIs, Node's built-in test runner, uv, Ruff, PyInstaller, vsce, GitHub Actions, Windows x64, and macOS Apple Silicon.

## Global Constraints

- The approved design in `docs/superpowers/specs/2026-07-15-task-transfer-ux-design.md` is authoritative.
- Current user-facing copy says **Task Transfer**, **Import Tasks**, **Export Tasks**, **Review Transfer Status**, **task**, **Task ID**, **this computer**, and **transfer folder**.
- Technical contracts retain `sync pull`, `sync push`, `sync status`, `thread_id`, `threadIds`, `--thread-id`, `sync-index.json`, and its `threads` map.
- Persist only the transfer-folder path under the existing `syncDir` global-state key. Never persist selected task ids or project bindings.
- Remove and ignore `codexUsage.sync.enabled`, `syncThreadIds`, `syncSelectionVersion`, paused state, and setup transactions.
- Every Import, Export, and Review starts with an empty selection. Project rows select only the currently visible tasks for that operation.
- Archived local tasks remain excluded. Do not change usage accounting for `archived_sessions`.
- Import must work when `.codex-global-state.json` is absent. Never write that file, Codex SQLite, or another private Codex registry.
- A destination project folder must already exist. Task Transfer does not clone repositories.
- Existing local task counterparts keep their native local `cwd`; destination mappings apply only to remote-only tasks in the current Import.
- Import and Export preflight the entire selected batch. Conflict, issue, unsafe structure, or an opposite-direction action blocks all selected copies.
- Remote format version becomes `3`; local paired-baseline state remains version `2`.
- A valid version-2 folder is migrated automatically and safely. Format version 1 remains unsupported.
- Add no runtime dependency. Reuse the current atomic I/O, lock, snapshot, hash, identity, and path-safety primitives.
- Keep Python and TypeScript files under 500 lines. Extract responsibilities before adding to `runner.py`, `core.ts`, or `extension.ts`.
- Do not add Linux packaging in this release. Keep Windows x64 and macOS Apple Silicon as the only publication targets.
- Use TDD. Run each focused failing test before implementation, then run the focused suite after implementation.
- When execution uses subagents, every subagent must use `gpt-5.6-sol` with medium reasoning effort or higher.
- Do not stage `.env`, secrets, generated executables, VSIX files, transfer folders, or user task JSONLs.

---

## Implementation Map

### Python contracts

- `REMOTE_TRANSFER_FORMAT_VERSION = 3`
- `LEGACY_REMOTE_TRANSFER_FORMAT_VERSION = 2`
- `LOCAL_BASELINE_STATE_VERSION = 2`
- `TRANSFER_TASKS_DIRNAME = "tasks"`
- `LEGACY_TRANSFER_CONVERSATIONS_DIRNAME = "conversations"`
- `ProjectBinding(project_key, path, confirmed_unverified=False)`
- `ProjectResolutionRequest(candidate_roots=(), bindings=())`
- CLI roots: repeatable `--candidate-project-root PATH`
- CLI bindings: repeatable `--project-binding PROJECT_KEY PATH`
- CLI confirmation: repeatable `--confirm-unverified-project PROJECT_KEY`
- Directional blocker codes: `pull_requires_push` and `push_requires_pull`
- Inventory payload version: `2`

### Extension modules

- `transferPresentation.ts`: pure menu, labels, transient status, and result formatting.
- `taskTransferState.ts`: folder-only state and idempotent obsolete-state cleanup.
- `syncTaskPicker.ts`: pure operation filtering and project/task selection.
- `taskTransfer.ts`: pure operation controller behind a port interface.
- `taskTransferVscode.ts`: VS Code dialogs, workspace roots, process calls, and command adapter.
- `dashboardWebview.ts`: mechanical extraction of HTML injection/rendering from `core.ts` if required to keep `core.ts` under 500 lines.

### Stable command ids with new displayed titles

| Command id | Displayed title |
| --- | --- |
| `codexUsage.openSyncMenu` | `Codex Usage: Task Transfer` |
| `codexUsage.configureSync` | `Codex Usage: Choose Transfer Folder` |
| `codexUsage.selectSyncTasks` | `Codex Usage: Task Transfer` |
| `codexUsage.pullTasks` | `Codex Usage: Import Tasks` |
| `codexUsage.pushTasks` | `Codex Usage: Export Tasks` |
| `codexUsage.syncStatus` | `Codex Usage: Review Transfer Status` |
| `codexUsage.openSyncFolder` | `Codex Usage: Open Transfer Folder` |

---

### Task 1: Separate Remote Format V3 From Local Baseline V2

**Files:**
- Modify: `src/codex_usage/sync/constants.py`
- Modify: `src/codex_usage/sync/models.py`
- Modify: `src/codex_usage/sync/paths.py`
- Modify: `src/codex_usage/sync/store.py`
- Modify: `src/codex_usage/sync/planner.py`
- Modify: `src/codex_usage/sync/runner.py`
- Modify: `src/codex_usage/sync/remote_reconciliation.py`
- Modify: `src/codex_usage/sync/errors.py`
- Modify: `tests/test_sync_state.py`
- Modify: `tests/test_sync_store.py`
- Modify: `tests/test_sync_planner.py`
- Modify: `tests/test_sync_runner.py`

**Interfaces:**

```python
REMOTE_TRANSFER_FORMAT_VERSION = 3
LEGACY_REMOTE_TRANSFER_FORMAT_VERSION = 2
LOCAL_BASELINE_STATE_VERSION = 2
SYNC_INDEX_FILENAME = "sync-index.json"
TRANSFER_TASKS_DIRNAME = "tasks"
LEGACY_TRANSFER_CONVERSATIONS_DIRNAME = "conversations"
```

Rename private direct-child and store APIs to task terminology:

```python
def is_direct_task_path(value: str, directory: str) -> bool: ...

class RemoteStore:
    tasks_path: Path

    def write_task(
        self,
        source: Path,
        filename: str,
        expected_target: SyncFileSnapshot,
    ) -> SyncFileSnapshot: ...
```

`RemoteIndex` accepts only supported migration/current versions when constructed, while each reader states the version it expects:

```python
@classmethod
def from_dict(
    cls,
    value: dict[str, Any],
    *,
    expected_format_version: int = REMOTE_TRANSFER_FORMAT_VERSION,
) -> RemoteIndex: ...
```

- [ ] **Step 1: Write failing version-separation tests**

Add this focused contract test to `tests/test_sync_state.py`:

```python
from codex_usage.sync.constants import (
    LOCAL_BASELINE_STATE_VERSION,
    REMOTE_TRANSFER_FORMAT_VERSION,
    TRANSFER_TASKS_DIRNAME,
)


def test_remote_format_v3_does_not_invalidate_local_v2_baseline() -> None:
    state = LocalSyncState(
        thread_id="task-1",
        sync_dir_fingerprint="folder",
        base_sha256="base",
        base_size_bytes=10,
        base_updated_at="2026-07-15T00:00:00Z",
        last_remote_sha256="remote",
        last_local_sha256="local",
        source_relative_path="2026/07/15/task-1.jsonl",
        project_key="repo",
        project_label="Repo",
        synced_at="2026-07-15T00:00:00Z",
    )

    assert REMOTE_TRANSFER_FORMAT_VERSION == 3
    assert LOCAL_BASELINE_STATE_VERSION == 2
    assert TRANSFER_TASKS_DIRNAME == "tasks"
    assert state.to_dict()["sync_version"] == 2
    assert LocalSyncState.from_dict(state.to_dict()) == state
```

Add this store assertion to `tests/test_sync_store.py` after pushing one task with the existing fixture helpers:

```python
def test_new_remote_entries_use_v3_tasks_directory(tmp_path: Path) -> None:
    root = tmp_path / "remote"
    store = RemoteStore(root)
    source = tmp_path / "source.jsonl"
    source.write_bytes(_session_jsonl("task-1"))
    base = store.load_inventory()
    expected = SyncFileSnapshot(
        path=root / "tasks" / "task-1.jsonl",
        exists=False,
    )

    with store.transaction():
        written = store.write_task(source, "task-1.jsonl", expected)
        entry = replace(
            _remote_entry("task-1"),
            file="tasks/task-1.jsonl",
            sha256=written.sha256,
            size_bytes=written.size_bytes,
        )
        committed = store.commit_index(
            base,
            {"task-1": entry},
            {"task-1": written},
            expected_entries={"task-1": None},
            expected_files={"task-1": expected},
        )

    assert committed.format_version == 3
    assert committed.threads["task-1"].file == "tasks/task-1.jsonl"
    assert (tmp_path / "remote" / "tasks" / "task-1.jsonl").read_bytes() == source.read_bytes()
    assert not (tmp_path / "remote" / "conversations").exists()
```

Use the existing local helpers in that test file, renaming them only when their current names expose the old remote directory. Do not create a second store fixture family.

- [ ] **Step 2: Run the tests and verify the old shared constant fails**

Run:

```bash
uv run pytest tests/test_sync_state.py tests/test_sync_store.py -q
```

Expected: FAIL because the new constants and `write_task` do not exist and current remote entries still point to `conversations/`.

- [ ] **Step 3: Implement independent constants and current-layout task naming**

Replace every local-baseline read/write use of `SYNC_FORMAT_VERSION` with `LOCAL_BASELINE_STATE_VERSION`. Replace every current remote index/layout use with `REMOTE_TRANSFER_FORMAT_VERSION` and `TRANSFER_TASKS_DIRNAME`. Keep the two legacy constants available only for migration code added in Task 2.

Parameterize reconciliation so Task 2 can validate v2 without weakening the current reader:

```python
def reconcile_remote_discovery(
    root: Path,
    persisted_index: RemoteIndex,
    index_snapshot: SyncFileSnapshot,
    discovered_files: dict[str, Path],
    path_guard: PathGuard,
    *,
    directory_name: str,
    format_version: int,
) -> RemoteInventory: ...
```

The current `RemoteStore` passes `directory_name="tasks"` and `format_version=3`. Migration passes the legacy values. Rename current diagnostics from "remote conversation" to "remote task"; historical changelog text is untouched.

- [ ] **Step 4: Update planner and runner path assertions**

Change `_remote_snapshot`, `_remote_entry`, `_sync_dir`, store target guards, commit validation, and direct-child validation to `tasks/`. Ensure `_remote_entry` writes:

```python
file=f"{TRANSFER_TASKS_DIRNAME}/{filename}"
```

Do not change local Codex session paths or `source_relative_path`.

- [ ] **Step 5: Run focused format, planner, runner, and state tests**

Run:

```bash
uv run pytest tests/test_sync_state.py tests/test_sync_store.py tests/test_sync_planner.py tests/test_sync_runner.py -q
```

Expected: PASS. Existing tests should now use current v3 constants unless they explicitly construct a legacy migration fixture.

- [ ] **Step 6: Commit the version split**

```bash
git add src/codex_usage/sync/constants.py src/codex_usage/sync/models.py src/codex_usage/sync/paths.py src/codex_usage/sync/store.py src/codex_usage/sync/planner.py src/codex_usage/sync/runner.py src/codex_usage/sync/remote_reconciliation.py src/codex_usage/sync/errors.py tests/test_sync_state.py tests/test_sync_store.py tests/test_sync_planner.py tests/test_sync_runner.py
git commit -m "refactor: separate transfer and baseline formats"
```

---

### Task 2: Add Lock-Protected Resumable V2-To-V3 Migration

**Files:**
- Create: `src/codex_usage/sync/format_migration.py`
- Create: `tests/test_sync_format_migration.py`
- Modify: `src/codex_usage/sync/store.py`
- Modify: `src/codex_usage/sync/errors.py`
- Modify: `src/codex_usage/sync/remote_reconciliation.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class MigrationResult:
    migrated: bool
    cleaned_legacy: bool


def migrate_remote_layout_v2_to_v3(root: Path) -> MigrationResult: ...
```

`RemoteStore.load_inventory()` is the single entry point that ensures layout v3. It must run migration while its existing file lock is held:

```python
def load_inventory(self) -> RemoteInventory:
    if self._lock.is_locked:
        return self._load_inventory_locked()
    with self.transaction():
        return self._load_inventory_locked()


def _load_inventory_locked(self) -> RemoteInventory:
    self._require_transaction()
    migrate_remote_layout_v2_to_v3(self.root)
    return self._load_current_inventory()
```

- [ ] **Step 1: Write a complete valid-v2 migration fixture and failing happy-path test**

Create this fixture in `tests/test_sync_format_migration.py`:

```python
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from codex_usage.sync.format_migration import migrate_remote_layout_v2_to_v3


def _write_v2_folder(root: Path, thread_id: str = "task-1") -> bytes:
    payload = (
        json.dumps(
            {
                "timestamp": "2026-07-15T00:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": thread_id,
                    "timestamp": "2026-07-15T00:00:00Z",
                    "cwd": "/source/project",
                },
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    source = root / "conversations" / f"{thread_id}.jsonl"
    source.parent.mkdir(parents=True)
    source.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    (root / "sync-index.json").write_text(
        json.dumps(
            {
                "format_version": 2,
                "updated_at": "2026-07-15T00:00:00Z",
                "threads": {
                    thread_id: {
                        "file": f"conversations/{thread_id}.jsonl",
                        "source_relative_path": f"2026/07/15/{thread_id}.jsonl",
                        "index_entry": {"id": thread_id, "thread_name": "Task one"},
                        "project_key": "/source/project",
                        "project_label": "project",
                        "project_aliases": [],
                        "sha256": digest,
                        "size_bytes": len(payload),
                        "session_updated_at": "2026-07-15T00:00:00Z",
                        "exported_at": "2026-07-15T00:00:00Z",
                        "source_machine_id": "source",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return payload


def test_migrates_valid_v2_folder_to_v3_tasks_layout(tmp_path: Path) -> None:
    payload = _write_v2_folder(tmp_path)

    result = migrate_remote_layout_v2_to_v3(tmp_path)
    index = json.loads((tmp_path / "sync-index.json").read_text(encoding="utf-8"))

    assert result.migrated is True
    assert index["format_version"] == 3
    assert index["threads"]["task-1"]["file"] == "tasks/task-1.jsonl"
    assert (tmp_path / "tasks" / "task-1.jsonl").read_bytes() == payload
    assert not (tmp_path / "conversations").exists()
```

- [ ] **Step 2: Write failing interruption and conflict tests**

Add these exact scenarios:

```python
def test_failed_index_commit_leaves_v2_authoritative_and_rerun_resumes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    payload = _write_v2_folder(tmp_path)
    from codex_usage.sync import format_migration

    real_write = format_migration.atomic_write_json
    calls = 0

    def fail_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("simulated index failure")
        return real_write(*args, **kwargs)

    monkeypatch.setattr(format_migration, "atomic_write_json", fail_once)
    with pytest.raises(OSError, match="simulated index failure"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert json.loads((tmp_path / "sync-index.json").read_text())["format_version"] == 2
    assert (tmp_path / "conversations" / "task-1.jsonl").read_bytes() == payload
    assert (tmp_path / "tasks" / "task-1.jsonl").read_bytes() == payload

    result = migrate_remote_layout_v2_to_v3(tmp_path)
    assert result.migrated is True
    assert json.loads((tmp_path / "sync-index.json").read_text())["format_version"] == 3


def test_conflicting_staged_task_blocks_without_overwrite(tmp_path: Path) -> None:
    source = _write_v2_folder(tmp_path)
    staged = tmp_path / "tasks" / "task-1.jsonl"
    staged.parent.mkdir()
    staged.write_bytes(b"different\n")

    with pytest.raises(TransferFormatMigrationError, match="tasks/task-1.jsonl"):
        migrate_remote_layout_v2_to_v3(tmp_path)

    assert staged.read_bytes() == b"different\n"
    assert (tmp_path / "conversations" / "task-1.jsonl").read_bytes() == source
    assert json.loads((tmp_path / "sync-index.json").read_text())["format_version"] == 2
```

Also add concrete tests for:

- an exception after v3 index commit but before legacy cleanup, followed by successful cleanup on the next call;
- matching `tasks/` plus `conversations/` reuse;
- an unrepresented or byte-different legacy file after v3 commit preserving both directories and raising;
- symlinked/junction-like directory entries, path traversal in the v2 index, duplicate file claims, missing files, wrong task identity, bad hash/size, and malformed JSON;
- an unindexed but readable v2 JSONL being reconstructed, migrated, and indexed;
- an unreadable unindexed v2 JSONL blocking migration without mutation;
- version 1 still raising `LegacySyncLayoutError`;
- version 4 raising an unsupported-format error without mutation.

- [ ] **Step 3: Run the new migration suite and verify the module is missing**

```bash
uv run pytest tests/test_sync_format_migration.py -q
```

Expected: FAIL during collection because `format_migration.py` does not exist.

- [ ] **Step 4: Implement validation, staging, commit-last, and resumable cleanup**

Implement this exact order in `migrate_remote_layout_v2_to_v3`:

1. Reject the version-1 `threads/` layout and unsafe path kinds.
2. Read `sync-index.json` with a snapshot and determine its integer format version.
3. For v2, parse with `expected_format_version=2`, enumerate `conversations/*.jsonl`, reconcile unindexed files through the parameterized reconciliation helper, and materialize every effective entry.
4. If any reconciliation/materialization issue exists, raise `TransferFormatMigrationError` before creating or changing `tasks/`.
5. For each effective entry, use the portable filename under `tasks/`. Reuse an existing target only when its snapshot and readable task identity match the verified source; otherwise fail without overwrite.
6. Build v3 entries with `dataclasses.replace(entry, file=f"tasks/{filename}")` and preserve every other field.
7. Atomically replace the index with the original v2 index snapshot as the expected target.
8. Re-read the v3 index and every v3 task before deleting any legacy file.
9. Delete legacy files only when each is represented by an identical v3 task, then remove the empty legacy directory.
10. For an already-v3 index with a leftover `conversations/`, run only the guarded cleanup path.

Do not suppress I/O errors before index commit. A matching staged file is a normal resume state, not an error.

- [ ] **Step 5: Integrate migration with all inventory/status/execution reads**

Make `RemoteStore.load_inventory()` acquire/reuse the transaction lock as shown above. Keep execution's outer transaction so planning, preflight, copies, and index commit remain one locked operation. Read-only selection inventory and status may release the lock after receiving their immutable snapshots.

- [ ] **Step 6: Run migration and existing storage suites**

```bash
uv run pytest tests/test_sync_format_migration.py tests/test_sync_store.py tests/test_sync_selection_inventory.py tests/test_sync_runner.py -q
```

Expected: PASS, including idempotent reruns.

- [ ] **Step 7: Commit migration**

```bash
git add src/codex_usage/sync/format_migration.py src/codex_usage/sync/store.py src/codex_usage/sync/errors.py src/codex_usage/sync/remote_reconciliation.py tests/test_sync_format_migration.py tests/test_sync_store.py tests/test_sync_selection_inventory.py tests/test_sync_runner.py
git commit -m "feat: migrate transfer folders to storage v3"
```

---

### Task 3: Make Destination Resolution Surface-Neutral

**Files:**
- Modify: `src/codex_usage/project_identity.py`
- Modify: `src/codex_usage/sync/project_roots.py`
- Modify: `src/codex_usage/sync/inventory.py`
- Modify: `src/codex_usage/sync/planner.py`
- Modify: `src/codex_usage/sync/selection_inventory.py`
- Modify: `src/codex_usage/sync/models.py`
- Modify: `src/codex_usage/sync/__init__.py`
- Modify: `tests/test_sync_project_roots.py`
- Modify: `tests/test_sync_planner.py`
- Modify: `tests/test_sync_selection_inventory.py`

**Interfaces:**

```python
ProjectIdentityKind = Literal["git", "path"]


@dataclass(frozen=True)
class ProjectBinding:
    project_key: str
    path: Path
    confirmed_unverified: bool = False


@dataclass(frozen=True)
class ProjectResolutionRequest:
    candidate_roots: tuple[Path, ...] = ()
    bindings: tuple[ProjectBinding, ...] = ()


@dataclass(frozen=True)
class ProjectDestination:
    identity_kind: ProjectIdentityKind
    candidate_roots: tuple[Path, ...]


def destination_for_project(
    local: LocalInventory,
    remote_entry: RemoteThreadEntry,
    request: ProjectResolutionRequest,
) -> ProjectDestination: ...


def resolve_local_project_root(
    local: LocalInventory,
    local_thread: ThreadInfo | None,
    remote_entry: RemoteThreadEntry,
    request: ProjectResolutionRequest,
) -> tuple[Path | None, SyncIssue | None]: ...
```

Planner contract:

```python
def build_sync_plan(
    local: LocalInventory,
    remote: RemoteInventory,
    selected_thread_ids: tuple[str, ...],
    sync_dir: Path,
    *,
    project_resolution: ProjectResolutionRequest | None,
) -> SyncPlan: ...
```

`project_resolution=None` is used only for the pre-selection inventory state view. Runtime Import and Review pass a concrete request, even when it has no candidate roots or bindings.

- [ ] **Step 1: Write failing extension-only Git resolution tests**

Extend `tests/test_sync_project_roots.py` with helpers that create a repository and complete remote entry, then add:

```python
def test_workspace_candidate_resolves_without_desktop_global_state(tmp_path: Path) -> None:
    checkout = _git_checkout(tmp_path / "checkout", "https://github.com/example/project.git")
    local = LocalInventory(
        session_dirs=(tmp_path / "codex" / "sessions",),
        threads={},
        index_entries={},
        discovered_count=0,
        project_roots={},
    )
    request = ProjectResolutionRequest(candidate_roots=(checkout,))

    root, issue = resolve_local_project_root(
        local,
        None,
        _remote_entry("https://github.com/example/project"),
        request,
    )

    assert root == checkout.absolute()
    assert issue is None
    assert not (tmp_path / "codex" / ".codex-global-state.json").exists()


def test_wrong_git_origin_is_rejected(tmp_path: Path) -> None:
    checkout = _git_checkout(tmp_path / "wrong", "https://github.com/example/other.git")
    request = ProjectResolutionRequest(
        bindings=(
            ProjectBinding("https://github.com/example/project", checkout),
        )
    )

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        _remote_entry("https://github.com/example/project"),
        request,
    )

    assert root is None
    assert issue is not None
    assert issue.code == "project_binding_identity_mismatch"
    assert "https://github.com/example/project" in issue.message
    assert "https://github.com/example/other" in issue.message
```

Add tests for two matching Git roots returning `ambiguous_local_project`, a missing directory, a file instead of a directory, duplicate bindings, and path spelling preservation through symlinks.

- [ ] **Step 2: Write failing non-Git confirmation and existing-counterpart tests**

```python
def test_non_git_cross_machine_binding_requires_confirmation(tmp_path: Path) -> None:
    checkout = tmp_path / "project"
    checkout.mkdir()
    remote = _remote_entry("c:/users/source/project", aliases=())

    root, issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        remote,
        ProjectResolutionRequest(
            bindings=(ProjectBinding(remote.project_key, checkout),)
        ),
    )

    assert root is None
    assert issue is not None
    assert issue.code == "unverified_project_binding_confirmation_required"

    confirmed_root, confirmed_issue = resolve_local_project_root(
        _empty_local(tmp_path),
        None,
        remote,
        ProjectResolutionRequest(
            bindings=(ProjectBinding(remote.project_key, checkout, True),)
        ),
    )
    assert confirmed_root == checkout.absolute()
    assert confirmed_issue is None


def test_existing_local_counterpart_keeps_its_native_cwd(tmp_path: Path) -> None:
    existing_root = _git_checkout(tmp_path / "existing", "https://github.com/example/project.git")
    other_root = _git_checkout(tmp_path / "other", "https://github.com/example/project.git")
    local_thread = _local_thread("task-1", existing_root, "https://github.com/example/project")
    local = _local_inventory(local_thread)

    root, issue = resolve_local_project_root(
        local,
        local_thread,
        _remote_entry("https://github.com/example/project"),
        ProjectResolutionRequest(
            bindings=(ProjectBinding("https://github.com/example/project", other_root),)
        ),
    )

    assert root == existing_root.resolve(strict=False)
    assert issue is None
```

- [ ] **Step 3: Run project-root tests and verify the old signature fails**

```bash
uv run pytest tests/test_sync_project_roots.py -q
```

Expected: FAIL because `ProjectBinding`, `ProjectResolutionRequest`, and the new resolver argument do not exist.

- [ ] **Step 4: Implement candidate collection and authoritative binding validation**

Candidate order is semantic, not a tie-breaker: collect all matching roots from existing local task `cwd` values, passed candidate roots, and optional desktop saved roots; deduplicate by resolved filesystem target while preserving source spelling. Automatic resolution succeeds only when exactly one matching target exists.

Add a public identity helper in `project_identity.py`:

```python
def is_git_project_key(value: str) -> bool:
    return _looks_like_repo_value(value.strip())
```

For Git projects, normalize each candidate through `normalize_project_key(str(path))`. Explicit wrong-origin bindings are errors, not fallback path aliases. For non-Git projects, allow an exact native normalized path automatically; otherwise require `confirmed_unverified=True` on the explicit binding.

Never modify `.codex-global-state.json`; continue reading its saved roots only as an optional candidate source.

- [ ] **Step 5: Add state and destination fields to inventory version 2**

Update immutable inventory payloads to this exact shape:

```python
@dataclass(frozen=True)
class SyncTaskInventoryItem:
    thread_id: str
    title: str
    updated_at: str
    estimated_sync_bytes: int
    availability: TaskAvailability
    state: str
    action: str


@dataclass(frozen=True)
class SyncProjectInventoryItem:
    project_key: str
    project_label: str
    identity_kind: ProjectIdentityKind
    candidate_roots: tuple[str, ...]
    tasks: tuple[SyncTaskInventoryItem, ...]
```

Set `INVENTORY_VERSION = 2`. Build one selection-only plan for the union of task ids with `project_resolution=None`, then copy each plan item's technical `state` and `action` into the inventory task. Compute project destination candidates independently so a missing destination does not hide a remote task from selection.

Change the loader signature:

```python
def load_sync_selection_inventory(
    data: CachedSessionData,
    sync_dir: Path,
    *,
    candidate_roots: tuple[Path, ...] = (),
) -> SyncSelectionInventory: ...
```

- [ ] **Step 6: Add inventory payload tests**

Add this assertion to `tests/test_sync_selection_inventory.py` using its existing complete local/remote fixture builders:

```python
def test_inventory_v2_exposes_state_and_destination_candidates(tmp_path: Path) -> None:
    checkout = _git_checkout(tmp_path / "checkout", "https://github.com/example/repo.git")
    local, remote = _local_and_remote_inventory(tmp_path)

    result = build_sync_selection_inventory(
        local,
        remote,
        sync_dir=tmp_path / "transfer",
        candidate_roots=(checkout,),
    )
    payload = result.to_dict()

    assert payload["inventory_version"] == 2
    project = payload["projects"][0]
    assert project["identity_kind"] == "git"
    assert project["candidate_roots"] == [str(checkout.absolute())]
    assert set(project["tasks"][0]) == {
        "thread_id",
        "title",
        "updated_at",
        "estimated_sync_bytes",
        "availability",
        "state",
        "action",
    }
```

Also prove remote-only tasks remain selectable when no candidate exists and their project reports `candidate_roots == []`.

- [ ] **Step 7: Run focused resolution, planner, and inventory suites**

```bash
uv run pytest tests/test_sync_project_roots.py tests/test_sync_planner.py tests/test_sync_selection_inventory.py -q
```

Expected: PASS. Existing local counterparts retain their cwd; remote-only tasks obtain only validated destinations.

- [ ] **Step 8: Commit destination resolution**

```bash
git add src/codex_usage/project_identity.py src/codex_usage/sync/project_roots.py src/codex_usage/sync/inventory.py src/codex_usage/sync/planner.py src/codex_usage/sync/selection_inventory.py src/codex_usage/sync/models.py src/codex_usage/sync/__init__.py tests/test_sync_project_roots.py tests/test_sync_planner.py tests/test_sync_selection_inventory.py
git commit -m "feat: resolve imports from local workspace roots"
```

---

### Task 4: Extend The Private CLI And Enforce Directional Preflight

**Files:**
- Create: `src/codex_usage/sync/directional_preflight.py`
- Create: `tests/test_sync_directional_preflight.py`
- Modify: `src/codex_usage/sync_cli.py`
- Modify: `src/codex_usage/cli.py`
- Modify: `src/codex_usage/sync/runner.py`
- Modify: `src/codex_usage/sync/models.py`
- Modify: `src/codex_usage/sync/__init__.py`
- Modify: `tests/test_sync_cli.py`
- Modify: `tests/test_sync_runner.py`
- Modify: `extensions/vscode/src/syncProtocol.ts`
- Modify: `extensions/vscode/src/syncInventory.ts`
- Modify: `extensions/vscode/test/syncProtocol.test.js`
- Modify: `extensions/vscode/test/syncInventory.test.js`

**Interfaces:**

```python
Direction = Literal["pull", "push"]


def directional_blockers(
    plan: SyncPlan,
    direction: Direction,
) -> tuple[SyncIssue, ...]: ...
```

CLI contract:

```text
sync inventory --candidate-project-root PATH
sync pull --candidate-project-root PATH --project-binding PROJECT_KEY PATH
          --confirm-unverified-project PROJECT_KEY
sync status --candidate-project-root PATH
```

All three flags are repeatable. `--project-binding` uses `nargs=2`; never encode a key/path pair with `:` or `=` because Windows paths and repository URLs contain both.

TypeScript contract:

```typescript
export type ProjectBinding = {
  projectKey: string;
  path: string;
  confirmedUnverified: boolean;
};

export type SyncCommandOptions = {
  syncDir: string;
  threadIds: string[];
  autoTransitions: boolean;
  candidateProjectRoots: string[];
  projectBindings: ProjectBinding[];
};
```

- [ ] **Step 1: Write failing directional preflight unit tests**

Create `tests/test_sync_directional_preflight.py`:

```python
from pathlib import Path

from codex_usage.sync.directional_preflight import directional_blockers
from codex_usage.sync.models import SyncFileSnapshot, SyncPlan, SyncPlanItem


def _item(thread_id: str, action: str) -> SyncPlanItem:
    missing = SyncFileSnapshot(path=Path(f"/{thread_id}.jsonl"), exists=False)
    return SyncPlanItem(
        thread_id=thread_id,
        state=action,
        action=action,
        reason=action,
        local=missing,
        remote=missing,
        base_sha256="",
        updated_at="",
        source_relative_path=f"2026/07/15/{thread_id}.jsonl",
        project_key="repo",
        project_label="Repo",
        memory_database_rows=0,
        expected_remote_entry=None,
    )


def _plan(*actions: str) -> SyncPlan:
    return SyncPlan(
        items=tuple(_item(f"task-{index}", action) for index, action in enumerate(actions, 1)),
        issues=(),
        discovered_count=len(actions),
        remote_count=len(actions),
        selected_count=len(actions),
    )


def test_pull_blocks_every_selected_task_when_one_requires_push() -> None:
    issues = directional_blockers(_plan("pull", "none", "push"), "pull")

    assert [(issue.code, issue.thread_id) for issue in issues] == [
        ("pull_requires_push", "task-3")
    ]


def test_push_blocks_every_selected_task_when_one_requires_pull() -> None:
    issues = directional_blockers(_plan("push", "pull"), "push")

    assert [(issue.code, issue.thread_id) for issue in issues] == [
        ("push_requires_pull", "task-2")
    ]


def test_up_to_date_and_same_direction_actions_do_not_block() -> None:
    assert directional_blockers(_plan("pull", "none"), "pull") == ()
    assert directional_blockers(_plan("push", "none"), "push") == ()
```

- [ ] **Step 2: Write failing runner all-or-nothing tests**

In `tests/test_sync_runner.py`, use the existing multi-task integration fixture to produce one planned pull and one planned push in the same selected set. Assert both directions block before either executor is called:

```python
def test_pull_opposite_direction_blocker_copies_nothing(
    mixed_direction_fixture,
    monkeypatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(runner_module, "execute_pulls", lambda *args: copied.append("pull"))

    result = pull_sync(**mixed_direction_fixture.pull_kwargs)

    assert result.outcome == "issue"
    assert result.pulled == ()
    assert copied == []
    assert {issue.code for issue in result.issues} == {"pull_requires_push"}


def test_push_opposite_direction_blocker_copies_nothing(
    mixed_direction_fixture,
    monkeypatch,
) -> None:
    copied: list[str] = []
    monkeypatch.setattr(runner_module, "execute_pushes", lambda *args: copied.append("push"))

    result = push_sync(**mixed_direction_fixture.push_kwargs)

    assert result.outcome == "issue"
    assert result.pushed == ()
    assert copied == []
    assert {issue.code for issue in result.issues} == {"push_requires_pull"}
```

Define `mixed_direction_fixture` in that file with real local/remote files and baselines, not a mocked plan. Preserve the existing snapshot assertions proving no local task, remote task, index, or baseline changed.

- [ ] **Step 3: Run directional tests and verify the missing module failure**

```bash
uv run pytest tests/test_sync_directional_preflight.py tests/test_sync_runner.py -q
```

Expected: FAIL during collection because `directional_preflight.py` does not exist.

- [ ] **Step 4: Implement blockers without rewriting plan actions**

`directional_blockers` returns one structured issue per opposite action. It does not change planner state, because Review must still report the technical action. Add this constructor to `SyncRunResult`:

```python
@classmethod
def blocked_with_issues(
    cls,
    plan: SyncPlan,
    issues: tuple[SyncIssue, ...],
    timings: SyncTimings,
) -> SyncRunResult:
    return cls._from_plan("issue", plan, (), (), (*plan.issues, *issues), timings)
```

Inside `_run_direction`, after structural/conflict planning and before `validate_local_selected`, calculate blockers. If any exist, return `blocked_with_issues`. Keep existing full selected-source snapshot validation before calling `execute_pulls` or `execute_pushes`.

- [ ] **Step 5: Add CLI parsing tests for roots, bindings, and confirmation**

Add to `tests/test_sync_cli.py`:

```python
def test_pull_cli_passes_transient_project_resolution_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(sync_cli, "_sync_session_dirs", lambda *, create: [tmp_path / "sessions"])
    monkeypatch.setattr(sync_cli, "pull_sync", lambda **kwargs: calls.append(kwargs) or _completed_result())

    exit_code = cli_module.main(
        [
            "sync", "pull", "--sync-dir", str(tmp_path / "transfer"),
            "--thread-id", "task-1",
            "--candidate-project-root", str(tmp_path / "workspace"),
            "--project-binding", "https://github.com/example/repo", str(tmp_path / "workspace"),
            "--project-binding", "/source/non-git", str(tmp_path / "workspace"),
            "--confirm-unverified-project", "/source/non-git",
            "--json",
        ]
    )

    assert exit_code == 0
    request = calls[0]["project_resolution"]
    assert request.candidate_roots == (tmp_path / "workspace",)
    assert request.bindings == (
        ProjectBinding("https://github.com/example/repo", tmp_path / "workspace", False),
        ProjectBinding("/source/non-git", tmp_path / "workspace", True),
    )
```

Do not silently merge two different paths for the same project key. Add a parser test that conflicting duplicates raise `ValueError` before session discovery.

- [ ] **Step 6: Implement CLI option parsing and runner plumbing**

Add common roots to inventory/pull/push/status parsers, and bindings/confirmation to execution parsers. Build one `ProjectResolutionRequest` in `sync_cli.py`; never write it to settings or disk.

Change these signatures:

```python
def sync_status(
    *,
    data: CachedSessionData,
    sync_dir: Path,
    thread_ids: Iterable[str],
    project_resolution: ProjectResolutionRequest,
) -> SyncPlan: ...


def pull_sync(
    *,
    data: CachedSessionData,
    sync_dir: Path,
    thread_ids: Iterable[str],
    project_resolution: ProjectResolutionRequest,
    discovery_ms: int = 0,
    on_progress: Callable[[SyncProgressEvent], None] | None = None,
) -> SyncRunResult: ...
```

Export passes an empty `ProjectResolutionRequest`; it never rebinds an existing local task. Selection inventory passes only candidate roots.

- [ ] **Step 7: Write failing TypeScript protocol tests**

Update `extensions/vscode/test/syncProtocol.test.js`:

```javascript
test("import args preserve Windows paths and repository keys as separate argv values", () => {
  assert.deepEqual(
    buildSyncPullArgs({
      syncDir: "C:\\Transfer",
      threadIds: ["task-1"],
      autoTransitions: true,
      candidateProjectRoots: ["C:\\Code\\repo"],
      projectBindings: [
        {
          projectKey: "https://github.com/example/repo",
          path: "C:\\Code\\repo",
          confirmedUnverified: false,
        },
        {
          projectKey: "c:/source/plain",
          path: "D:\\Code\\plain",
          confirmedUnverified: true,
        },
      ],
    }),
    [
      "sync", "pull", "--json", "--sync-dir", "C:\\Transfer",
      "--candidate-project-root", "C:\\Code\\repo",
      "--project-binding", "https://github.com/example/repo", "C:\\Code\\repo",
      "--project-binding", "c:/source/plain", "D:\\Code\\plain",
      "--confirm-unverified-project", "c:/source/plain",
      "--thread-id", "task-1",
    ],
  );
});
```

Update inventory parser fixtures to `inventory_version: 2` and require `identity_kind`, `candidate_roots`, `state`, and `action`. Add malformed-field tests for each new field and retain exact-record rejection.

- [ ] **Step 8: Implement TypeScript protocol v2**

`buildSyncInventoryArgs` accepts `candidateProjectRoots`. `buildSyncPullArgs` appends bindings and confirmation. `buildSyncPushArgs` and `buildSyncStatusArgs` append candidate roots but never append bindings unless their caller explicitly supplies them; the extension will supply bindings only to Import.

Keep strict JSON parsing and change its contract error text from "v2 payload contract" to "task transfer payload contract" so remote format version and process payload version are not conflated.

- [ ] **Step 9: Run Python and TypeScript protocol suites**

```bash
uv run pytest tests/test_sync_directional_preflight.py tests/test_sync_cli.py tests/test_sync_runner.py -q
cd extensions/vscode && npm run build && node --test test/syncProtocol.test.js test/syncInventory.test.js
```

Expected: PASS.

- [ ] **Step 10: Commit private protocol and preflight**

```bash
git add src/codex_usage/sync/directional_preflight.py src/codex_usage/sync_cli.py src/codex_usage/cli.py src/codex_usage/sync/runner.py src/codex_usage/sync/models.py src/codex_usage/sync/__init__.py tests/test_sync_directional_preflight.py tests/test_sync_cli.py tests/test_sync_runner.py extensions/vscode/src/syncProtocol.ts extensions/vscode/src/syncInventory.ts extensions/vscode/test/syncProtocol.test.js extensions/vscode/test/syncInventory.test.js
git commit -m "feat: enforce directional task transfer preflight"
```

---

### Task 5: Replace Setup State With Folder-Only Transfer State And Pure Presentation

**Files:**
- Create: `extensions/vscode/src/taskTransferState.ts`
- Create: `extensions/vscode/src/transferPresentation.ts`
- Create: `extensions/vscode/test/taskTransferState.test.js`
- Create: `extensions/vscode/test/transferPresentation.test.js`
- Modify: `extensions/vscode/src/core.ts`
- Modify: `extensions/vscode/test/core.test.js`
- Delete: `extensions/vscode/src/syncSetupTransaction.ts`
- Delete: `extensions/vscode/test/syncSetupTransaction.test.js`

**State interface:**

```typescript
export const TRANSFER_FOLDER_STATE_KEY = "syncDir";
export const OBSOLETE_TRANSFER_STATE_KEYS = ["syncThreadIds", "syncSelectionVersion"] as const;

export interface TaskTransferStateStore {
  readFolder(): string;
  readLegacyFolder(): string;
  writeFolder(value: string | undefined): Promise<void>;
  removeGlobalState(key: string): Promise<void>;
  obsoleteConfigurationScopes(): readonly string[];
  removeEnabledConfiguration(scope: string): Promise<void>;
}

export async function migrateTaskTransferState(
  store: TaskTransferStateStore,
  logError: (message: string) => void,
): Promise<void> { ... }
```

**Presentation interface:**

```typescript
export type TransferOperation = "import" | "export" | "review";
export type TransferMenuAction =
  | "importTasks"
  | "exportTasks"
  | "reviewStatus"
  | "chooseFolder"
  | "changeFolder"
  | "openFolder"
  | "forgetFolder";

export type TransferTransientStatus =
  | "checking"
  | "importing"
  | "exporting"
  | "conflict"
  | "issue";

export function taskTransferControlLabel(): string { ... }
export function taskTransferMenuItems(folder: string): TransferMenuQuickPickItem[] { ... }
export function taskAvailabilityLabel(value: SyncTaskAvailability): string { ... }
export function taskStateLabel(action: string, state: string): string { ... }
export function transientStatusLabel(value: TransferTransientStatus): string { ... }
export function formatTransferResult(
  operation: "import" | "export",
  result: SyncRunResult,
): TransferResultMessage { ... }
```

- [ ] **Step 1: Write failing folder-only migration tests**

Create `extensions/vscode/test/taskTransferState.test.js` with an in-memory store:

```javascript
test("migration preserves the folder and removes obsolete state and enabled scopes", async () => {
  const removedState = [];
  const removedScopes = [];
  const writes = [];
  const errors = [];
  const store = {
    readFolder: () => "/transfer",
    readLegacyFolder: () => "/legacy",
    writeFolder: async (value) => writes.push(value),
    removeGlobalState: async (key) => removedState.push(key),
    obsoleteConfigurationScopes: () => ["global", "workspace", "folder:/repo"],
    removeEnabledConfiguration: async (scope) => removedScopes.push(scope),
  };

  await migrateTaskTransferState(store, (message) => errors.push(message));

  assert.deepEqual(writes, []);
  assert.deepEqual(removedState, ["syncThreadIds", "syncSelectionVersion"]);
  assert.deepEqual(removedScopes, ["global", "workspace", "folder:/repo"]);
  assert.deepEqual(errors, []);
});


test("migration adopts a legacy folder only when the stable folder is empty", async () => {
  const writes = [];
  const store = fakeStore({ folder: "", legacyFolder: "/legacy", writes });

  await migrateTaskTransferState(store, () => undefined);

  assert.deepEqual(writes, ["/legacy"]);
});


test("cleanup failures are logged independently and do not reject activation", async () => {
  const errors = [];
  const store = fakeStore({
    failStateKey: "syncThreadIds",
    failScope: "workspace",
  });

  await assert.doesNotReject(
    migrateTaskTransferState(store, (message) => errors.push(message)),
  );
  assert.equal(errors.length, 2);
  assert.match(errors[0], /syncThreadIds/);
  assert.match(errors[1], /workspace/);
});
```

The `fakeStore` helper must implement every `TaskTransferStateStore` method and record calls; do not mock the function under test.

- [ ] **Step 2: Write failing presentation tests for the complete wording contract**

Create `extensions/vscode/test/transferPresentation.test.js`:

```javascript
test("task transfer menu has no setup selection pause or resume concepts", () => {
  const empty = taskTransferMenuItems("");
  const configured = taskTransferMenuItems("/transfer");

  assert.equal(taskTransferControlLabel(), "Task Transfer ▾");
  assert.deepEqual(empty.map((item) => item.action), [
    "importTasks", "exportTasks", "reviewStatus", "chooseFolder",
  ]);
  assert.deepEqual(configured.map((item) => item.action), [
    "importTasks", "exportTasks", "reviewStatus", "changeFolder", "openFolder", "forgetFolder",
  ]);
  const copy = JSON.stringify([...empty, ...configured]);
  assert.doesNotMatch(copy, /setup|required|pause|resume|selected/i);
});


test("availability and planner states use task transfer language", () => {
  assert.equal(taskAvailabilityLabel("local"), "On this computer");
  assert.equal(taskAvailabilityLabel("remote"), "In transfer folder");
  assert.equal(taskAvailabilityLabel("both"), "On both");
  assert.equal(taskStateLabel("pull", "remote_only"), "Ready to import");
  assert.equal(taskStateLabel("push", "local_only"), "Ready to export");
  assert.equal(taskStateLabel("none", "synced"), "Up to date");
  assert.equal(taskStateLabel("conflict", "conflict"), "Conflict");
  assert.equal(taskStateLabel("issue", "missing"), "Missing");
});


test("result copy distinguishes success no-op opposite direction conflict and issue", () => {
  assert.equal(
    formatTransferResult("import", result({ pulled: 1 })).message,
    "Imported 1 task. Reload VS Code or restart the Codex app to see it.",
  );
  assert.equal(
    formatTransferResult("import", result({ selected: 2, unchanged: 2 })).message,
    "No changes were needed. All 2 selected tasks are up to date.",
  );
  assert.equal(
    formatTransferResult("export", result({ issues: [issue("push_requires_pull")] })).message,
    "Export was blocked because 1 selected task is newer in the transfer folder. Import it first.",
  );
  assert.match(
    formatTransferResult("import", result({ outcome: "conflict", conflicts: 1 })).message,
    /no tasks were copied/i,
  );
});
```

Implement complete `result` and `issue` fixture helpers in the test with every strict `SyncRunResult` field.

- [ ] **Step 3: Run new tests and verify missing modules**

```bash
cd extensions/vscode && npm test
```

Expected: FAIL because `taskTransferState` and `transferPresentation` do not exist.

- [ ] **Step 4: Implement idempotent folder-only state migration**

Preserve the stable folder if present; otherwise adopt the trimmed legacy `codexUsage.sync.dir` value. Delete both obsolete global-state keys. Ask the VS Code adapter in Task 7 to enumerate and clear explicit `sync.enabled` values at global, workspace, and every workspace-folder scope. Catch and log each deletion failure independently.

Remove the setup transaction module and all imports, types, mutation queues, setup version checks, and selected-task readers from `core.ts`. Replace `SyncSettings` with:

```typescript
export type TaskTransferSettings = {
  folder: string;
};
```

Keep `TRANSFER_FOLDER_STATE_KEY` mapped to the existing `syncDir` string.

- [ ] **Step 5: Implement pure presentation and remove transfer menu code from core**

`taskTransferControlLabel` always returns `Task Transfer ▾`. Menu items use the approved names and no selected-task count. `formatTransferResult` groups issue codes, pluralizes exactly, includes refresh guidance only when at least one task was imported, and routes technical issue text to the output channel through the controller rather than embedding stack details in notifications.

Update `core.ts` webview state to carry `taskTransfer: TaskTransferSettings` and call `taskTransferControlLabel`. Remove `syncStatusKindLabel`, `syncControlLabel`, `syncMenuQuickPickItems`, `hasValidSyncSelection`, and setup-step helpers.

- [ ] **Step 6: Add core guardrails and run extension tests**

Update `extensions/vscode/test/core.test.js` to assert the dashboard control is always `Task Transfer ▾` with no folder, and to reject `Setup required`, `Sync: Off`, and task counts in current rendered controls.

Run:

```bash
cd extensions/vscode && npm test
```

Expected: PASS, and no test imports `syncSetupTransaction`.

- [ ] **Step 7: Commit folder-only state and presentation**

```bash
git add extensions/vscode/src/taskTransferState.ts extensions/vscode/src/transferPresentation.ts extensions/vscode/src/core.ts extensions/vscode/test/taskTransferState.test.js extensions/vscode/test/transferPresentation.test.js extensions/vscode/test/core.test.js
git rm extensions/vscode/src/syncSetupTransaction.ts extensions/vscode/test/syncSetupTransaction.test.js
git commit -m "refactor: model sync ux as task transfer"
```

---

### Task 6: Make The Combined Picker Fresh And Operation-Specific

**Files:**
- Modify: `extensions/vscode/src/syncTaskPicker.ts`
- Modify: `extensions/vscode/test/syncTaskPicker.test.js`
- Modify: `extensions/vscode/src/syncInventory.ts`

**Interfaces:**

```typescript
export function filterInventoryForOperation(
  inventory: SyncInventory,
  operation: TransferOperation,
): SyncInventory;

export function buildTaskPickerItems(
  inventory: SyncInventory,
  operation: TransferOperation,
): TaskPickerItem[];
```

Remove `unavailable` rows and every `storedThreadIds` argument. `selectedPickerItemIds` receives only the current in-memory selection.

- [ ] **Step 1: Replace persisted-selection tests with operation filtering tests**

Rewrite `extensions/vscode/test/syncTaskPicker.test.js` around inventory version 2. Keep its three-task fixture but include technical state/action fields and project destination fields.

```javascript
test("import lists transfer-folder tasks and starts unselected", () => {
  const items = buildTaskPickerItems(inventory(), "import");

  assert.deepEqual(
    items.filter((item) => item.kind === "task").map((item) => item.threadId),
    ["thread-2", "thread-3"],
  );
  assert.deepEqual(selectedPickerItemIds(items, []), []);
});


test("export lists active local tasks and review lists the union", () => {
  assert.deepEqual(taskIds(buildTaskPickerItems(inventory(), "export")), [
    "thread-1", "thread-2",
  ]);
  assert.deepEqual(taskIds(buildTaskPickerItems(inventory(), "review")), [
    "thread-1", "thread-2", "thread-3",
  ]);
});


test("project toggle selects only visible operation tasks", () => {
  const items = buildTaskPickerItems(inventory(), "import");
  const project = items.find((item) => item.id === "project:repo-a");

  assert.deepEqual(project.childThreadIds, ["thread-2"]);
  assert.deepEqual(reduceTaskSelection([], project, true), ["thread-2"]);
});


test("task rows show state availability Task ID and transfer size", () => {
  const task = buildTaskPickerItems(inventory(), "review")
    .find((item) => item.id === "task:thread-3");

  assert.equal(task.description, "Ready to import | In transfer folder");
  assert.match(task.detail, /Task ID: thread-3/);
  assert.match(task.detail, /estimated transfer size/);
  assert.doesNotMatch(task.detail, /Thread ID|sync size/);
});
```

Delete tests for unavailable persisted ids. Retain stable ordering, project partial-selection, deduplication, and case-sensitive technical id tests.

- [ ] **Step 2: Run the picker tests and verify old signatures fail**

```bash
cd extensions/vscode && npm run build && node --test test/syncTaskPicker.test.js
```

Expected: FAIL because `buildTaskPickerItems` still accepts stored ids and does not filter by operation.

- [ ] **Step 3: Implement operation filtering and fresh selection**

Filtering rules are exact:

```typescript
function availableForOperation(
  availability: SyncTaskAvailability,
  operation: TransferOperation,
): boolean {
  if (operation === "import") {
    return availability === "remote" || availability === "both";
  }
  if (operation === "export") {
    return availability === "local" || availability === "both";
  }
  return true;
}
```

Drop projects with zero visible tasks. Project child ids come from the filtered snapshot. The picker never stores or restores selection; its VS Code adapter in Task 7 initializes `selectedThreadIds = []` every time.

- [ ] **Step 4: Run picker and inventory parser tests**

```bash
cd extensions/vscode && npm run build && node --test test/syncTaskPicker.test.js test/syncInventory.test.js
```

Expected: PASS.

- [ ] **Step 5: Commit fresh operation selection**

```bash
git add extensions/vscode/src/syncTaskPicker.ts extensions/vscode/src/syncInventory.ts extensions/vscode/test/syncTaskPicker.test.js
git commit -m "feat: select task transfers per operation"
```

---

### Task 7: Add Task Transfer Controller, VS Code Adapter, And Usage-Only Status

**Files:**
- Create: `extensions/vscode/src/taskTransfer.ts`
- Create: `extensions/vscode/src/taskTransferVscode.ts`
- Create: `extensions/vscode/test/taskTransfer.test.js`
- Create: `extensions/vscode/test/taskTransferVscode.test.js`
- Create: `extensions/vscode/src/dashboardWebview.ts`
- Create: `extensions/vscode/test/dashboardWebview.test.js`
- Modify: `extensions/vscode/src/extension.ts`
- Modify: `extensions/vscode/src/core.ts`
- Modify: `extensions/vscode/src/syncProcess.ts`
- Modify: `extensions/vscode/test/core.test.js`
- Modify: `extensions/vscode/test/syncProcess.test.js`
- Modify: `extensions/vscode/package.json`

**Pure controller interface:**

```typescript
export type TransferExecutionRequest = {
  syncDir: string;
  threadIds: string[];
  autoTransitions: boolean;
  candidateProjectRoots: string[];
  projectBindings: ProjectBinding[];
};

export interface TaskTransferPort {
  readFolder(): string;
  writeFolder(folder: string | undefined): Promise<void>;
  chooseMenu(items: TransferMenuQuickPickItem[]): Promise<TransferMenuAction | undefined>;
  chooseTransferFolder(): Promise<string | undefined>;
  openFolder(folder: string): Promise<void>;
  workspaceRoots(): string[];
  loadInventory(request: SyncInventoryCommandOptions): Promise<SyncInventory>;
  chooseTasks(
    operation: TransferOperation,
    rows: TaskPickerItem[],
    initialThreadIds: string[],
  ): Promise<string[] | undefined>;
  chooseProjectRoot(
    project: SyncInventoryProject,
    candidates: string[],
  ): Promise<string | undefined>;
  confirmUnverifiedProject(
    project: SyncInventoryProject,
    chosenPath: string,
  ): Promise<boolean>;
  execute(
    operation: "import" | "export",
    request: TransferExecutionRequest,
  ): Promise<SyncRunResult>;
  review(request: TransferExecutionRequest): Promise<SyncStatusSummary>;
  notify(kind: "info" | "warning" | "error", message: string): void;
  log(message: string): void;
  setTransientStatus(status: TransferTransientStatus | undefined): void;
}


export class TaskTransferController {
  constructor(
    private readonly port: TaskTransferPort,
    private readonly autoTransitions: () => boolean,
  ) {}

  showMenu(): Promise<void>;
  importTasks(): Promise<void>;
  exportTasks(): Promise<void>;
  reviewStatus(): Promise<void>;
  chooseFolder(): Promise<void>;
  changeFolder(): Promise<void>;
  openFolder(): Promise<void>;
  forgetFolder(): Promise<void>;
}
```

The controller module does not import `vscode`. `taskTransferVscode.ts` implements the port with VS Code APIs and the existing bundled-process helpers.

- [ ] **Step 1: Write controller tests for lazy folder setup and empty sources**

Create a reusable fake port in `extensions/vscode/test/taskTransfer.test.js` that records every call and supplies queued results. Add:

```javascript
test("import lazily chooses and remembers a transfer folder", async () => {
  const port = fakePort({
    folder: "",
    chosenTransferFolder: "/transfer",
    inventory: remoteInventory(),
    selectedThreadIds: ["remote-task"],
    executionResult: completedImport("remote-task"),
  });
  const controller = new TaskTransferController(port, () => true);

  await controller.importTasks();

  assert.deepEqual(port.folderWrites, ["/transfer"]);
  assert.equal(port.inventoryRequests[0].syncDir, "/transfer");
  assert.deepEqual(port.notifications, [
    ["info", "Imported 1 task. Reload VS Code or restart the Codex app to see it."],
  ]);
});


test("cancelling lazy folder choice is silent", async () => {
  const port = fakePort({ folder: "", chosenTransferFolder: undefined });

  await new TaskTransferController(port, () => true).exportTasks();

  assert.deepEqual(port.notifications, []);
  assert.deepEqual(port.inventoryRequests, []);
  assert.deepEqual(port.executions, []);
});


test("empty import and export sources get state-specific messages", async () => {
  const importPort = fakePort({ folder: "/transfer", inventory: emptyInventory() });
  await new TaskTransferController(importPort, () => true).importTasks();
  assert.deepEqual(importPort.notifications, [
    ["info", "No tasks are available to import from this transfer folder."],
  ]);

  const exportPort = fakePort({ folder: "/transfer", inventory: emptyInventory() });
  await new TaskTransferController(exportPort, () => true).exportTasks();
  assert.deepEqual(exportPort.notifications, [
    ["info", "No active Codex tasks are available to export from this computer."],
  ]);
});
```

- [ ] **Step 2: Write controller tests for fresh selection and per-project bindings**

```javascript
test("each operation opens an empty fresh selection and never writes task ids", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: mixedInventory(),
    selectedThreadIdsQueue: [["remote-task"], undefined],
    executionResult: completedImport("remote-task"),
  });
  const controller = new TaskTransferController(port, () => true);

  await controller.importTasks();
  await controller.importTasks();

  assert.deepEqual(port.selectionInitialValues, [[], []]);
  assert.deepEqual(port.folderWrites, []);
  assert.equal("threadIdWrites" in port, false);
});


test("change open and forget affect only the remembered folder", async () => {
  const port = fakePort({
    folder: "/old-transfer",
    chosenTransferFolder: "/new-transfer",
  });
  const controller = new TaskTransferController(port, () => true);

  await controller.changeFolder();
  await controller.openFolder();
  await controller.forgetFolder();

  assert.deepEqual(port.folderWrites, ["/new-transfer", undefined]);
  assert.deepEqual(port.openedFolders, ["/new-transfer"]);
  assert.deepEqual(port.deletedPaths, []);
});


test("ambiguous destination choice becomes one binding for all selected project tasks", async () => {
  const project = remoteProject({
    candidateRoots: ["/repo-a", "/repo-b"],
    tasks: [remoteTask("task-1"), remoteTask("task-2")],
  });
  const port = fakePort({
    folder: "/transfer",
    inventory: inventoryWith(project),
    selectedThreadIds: ["task-1", "task-2"],
    chosenProjectRoot: "/repo-b",
    executionResult: completedImport("task-1", "task-2"),
  });

  await new TaskTransferController(port, () => true).importTasks();

  assert.equal(port.projectRootPrompts.length, 1);
  assert.deepEqual(port.executions[0].request.projectBindings, [
    {
      projectKey: project.projectKey,
      path: "/repo-b",
      confirmedUnverified: false,
    },
  ]);
});


test("non-git mapping requires confirmation and cancellation aborts the whole import", async () => {
  const port = fakePort({
    folder: "/transfer",
    inventory: inventoryWith(nonGitRemoteProject()),
    selectedThreadIds: ["task-1", "task-2"],
    chosenProjectRoot: "/local/project",
    confirmUnverified: false,
  });

  await new TaskTransferController(port, () => true).importTasks();

  assert.deepEqual(port.executions, []);
  assert.deepEqual(port.notifications, []);
});
```

Also test unique candidate auto-resolution, missing candidate folder fallback, wrong-origin engine issue presentation, mapping not retained on the next command, local `both` tasks not prompting, Review not prompting for a destination, and cancellation of task/project pickers remaining silent.

- [ ] **Step 3: Run controller tests and verify the missing module failure**

```bash
cd extensions/vscode && npm run build && node --test test/taskTransfer.test.js
```

Expected: FAIL because `taskTransfer.ts` does not exist.

- [ ] **Step 4: Implement the controller state machine**

For each operation:

1. Read the folder; if empty, ask once, persist the chosen folder, or return silently.
2. Set transient status to `checking`.
3. Load one inventory with current VS Code workspace roots.
4. Filter/build picker rows for the operation; show the approved empty-source message when no task rows remain.
5. Call `chooseTasks` with a fresh empty selection. Cancellation returns silently.
6. For Import only, group selected remote-only tasks by project and resolve at most one current-operation binding per project.
7. Execute exactly one CLI process with selected technical ids.
8. Log every technical issue, show one formatted notification, then clear transient status in `finally`.

Map controller operations to technical commands only inside the port: Import -> pull, Export -> push, Review -> status.

Review uses the same picker and calls `port.review`; its notification starts `Task Transfer status:` and uses user-facing local/folder state labels rather than "sync status."

- [ ] **Step 5: Write VS Code adapter source and behavior tests**

Create `extensions/vscode/test/taskTransferVscode.test.js`. Keep these pure helpers in `taskTransfer.ts` so Node tests can import them without loading the unavailable runtime `vscode` module; `taskTransferVscode.ts` imports and uses them:

```typescript
export function workspaceRootPaths(
  folders: readonly { uri: { fsPath: string } }[] | undefined,
): string[] { ... }

export function configurationScopeIds(
  folders: readonly { uri: { fsPath: string } }[] | undefined,
): string[] { ... }
```

Tests:

```javascript
test("workspace roots are trimmed deduplicated and preserve first spelling", () => {
  assert.deepEqual(
    workspaceRootPaths([
      { uri: { fsPath: "/Repo" } },
      { uri: { fsPath: "/Repo" } },
      { uri: { fsPath: " /Other " } },
    ]),
    ["/Repo", "/Other"],
  );
});


test("adapter source never writes private Codex project registries", () => {
  const source = fs.readFileSync(path.join(__dirname, "../src/taskTransferVscode.ts"), "utf8");
  assert.doesNotMatch(source, /\.codex-global-state\.json|sqlite/i);
  assert.match(source, /workspace\.workspaceFolders/);
  assert.match(source, /ConfigurationTarget\.Global/);
  assert.match(source, /ConfigurationTarget\.Workspace/);
  assert.match(source, /ConfigurationTarget\.WorkspaceFolder/);
});
```

- [ ] **Step 6: Implement the VS Code port**

Move the combined Quick Pick implementation from `extension.ts` into `taskTransferVscode.ts`. Initialize `selectedThreadIds` and selected items as empty every invocation. Titles are `Select tasks to import`, `Select tasks to export`, and `Select tasks to review`.

The adapter:

- reads/writes only `TRANSFER_FOLDER_STATE_KEY`;
- calls `showOpenDialog` with `Use Transfer Folder` or `Choose Local Project Folder`;
- passes `vscode.workspace.workspaceFolders` through `workspaceRootPaths`;
- uses a candidate Quick Pick when Python reports multiple matching roots;
- confirms a non-Git binding with source identity and destination path;
- invokes `buildSyncInventoryArgs`, `buildSyncPullArgs`, `buildSyncPushArgs`, and `buildSyncStatusArgs`;
- uses `runSyncProcess` for Import/Export progress and strict results;
- opens the transfer folder with `vscode.env.openExternal`;
- clears obsolete configuration at all scopes through `migrateTaskTransferState`;
- logs migration cleanup failures without failing activation.

If the remembered path is missing/offline, show `The transfer folder is not available: <path>. Choose another transfer folder and try again.` and perform no write.

- [ ] **Step 7: Register stable command ids with new semantics**

In `extension.ts`, construct one controller and delegate the existing ids. `codexUsage.selectSyncTasks` opens the Task Transfer menu; it must not persist a selection. Remove every old setup, pause/resume, clear, change-tasks, runtime-idle, and setup-required function.

Update `extensions/vscode/package.json` displayed command titles according to the table at the top of this plan and delete the `codexUsage.sync.enabled` configuration property. Keep all existing command ids and activation events.

- [ ] **Step 8: Make persistent status usage-only**

The status bar base text remains:

```typescript
const usageText = projectCount > 0
  ? `Codex Usage: ${settings.range} (${projectCount})`
  : `Codex Usage: ${settings.range}`;
statusItem.text = transientStatus
  ? `${usageText} | ${transientStatusLabel(transientStatus)}`
  : usageText;
```

The persistent tooltip describes range, project filter, and theme only. Controller failures may temporarily set `conflict` or `issue`, but clear the transient state after the notification. Remove last-sync timestamps, enabled/off/idle state, and transfer configuration warnings.

Update `syncProcess.ts` progress phase display only as a technical parser; map `pulling` to transient `Importing tasks` and `pushing` to `Exporting tasks` in the adapter.

- [ ] **Step 9: Extract webview rendering and enforce file-size boundaries**

Move `renderLoadingHtml`, `renderErrorHtml`, `injectWebviewControls`, `injectWebviewCsp`, CSS helpers, and their private escaping/render helpers from `core.ts` to `dashboardWebview.ts`. Re-export only where existing imports require it. Move the corresponding pure tests from `core.test.js` to `dashboardWebview.test.js` without changing expected report behavior except the Task Transfer label.

Run:

```bash
wc -l extensions/vscode/src/core.ts extensions/vscode/src/extension.ts extensions/vscode/src/taskTransfer.ts extensions/vscode/src/taskTransferVscode.ts extensions/vscode/src/transferPresentation.ts
```

Expected: every listed file is at or below 500 lines. If a module approaches the limit during implementation, move process invocation helpers into `taskTransferProcess.ts`; do not leave an oversized exception.

- [ ] **Step 10: Add package/source wording guardrails**

Update `extensions/vscode/test/core.test.js` and `syncProcess.test.js` so current source and contributed commands reject:

```javascript
for (const forbidden of [
  "Setup required",
  "Pause Sync",
  "Resume Sync",
  "Pull Tasks",
  "Push Tasks",
  "Change Tasks",
  "Clear Sync Setup",
]) {
  assert.doesNotMatch(currentProductSource, new RegExp(forbidden, "i"));
}
assert.equal(packageJson.contributes.configuration.properties["codexUsage.sync.enabled"], undefined);
assert.doesNotMatch(currentProductSource, /onDidChangeWindowState|onDidChangeActiveTextEditor|createFileSystemWatcher|setInterval/);
```

Scope `currentProductSource` to `extensions/vscode/src` and `extensions/vscode/package.json`; do not scan historical changelogs or approved design records.

- [ ] **Step 11: Run the full extension suite**

```bash
cd extensions/vscode && npm test
```

Expected: PASS. Persistent status remains usage-only with no folder configured, and every operation is manual.

- [ ] **Step 12: Commit extension orchestration**

```bash
git add extensions/vscode/src/taskTransfer.ts extensions/vscode/src/taskTransferVscode.ts extensions/vscode/src/dashboardWebview.ts extensions/vscode/src/extension.ts extensions/vscode/src/core.ts extensions/vscode/src/syncProcess.ts extensions/vscode/test/taskTransfer.test.js extensions/vscode/test/taskTransferVscode.test.js extensions/vscode/test/dashboardWebview.test.js extensions/vscode/test/core.test.js extensions/vscode/test/syncProcess.test.js extensions/vscode/package.json
git commit -m "feat: add deliberate task transfer workflow"
```

---

### Task 8: Record The Durable Contract And Rewrite Current Documentation

**Files:**
- Create: `docs/adr/0014-manual-task-transfer.md`
- Create: `tests/test_task_transfer_docs.py`
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `CHANGELOG.md`
- Modify: `extensions/vscode/CHANGELOG.md`
- Modify: `docs/release.md`
- Modify: `extensions/vscode/package.json`

- [ ] **Step 1: Write failing current-documentation and changelog tests**

Create `tests/test_task_transfer_docs.py`:

```python
from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURRENT_DOCS = (ROOT / "README.md", ROOT / "extensions/vscode/README.md")
CHANGELOGS = (ROOT / "CHANGELOG.md", ROOT / "extensions/vscode/CHANGELOG.md")


def test_current_docs_lead_with_deliberate_task_transfer() -> None:
    for path in CURRENT_DOCS:
        text = path.read_text(encoding="utf-8")
        assert "Task Transfer" in text
        assert "Export Tasks" in text
        assert "Import Tasks" in text
        assert "Review Transfer Status" in text
        assert "built-in handoff" in text.casefold()
        assert "desktop app is not required" in text.casefold()
        assert "reload vs code or restart the codex app" in text.casefold()
        assert "token" in text.casefold() and "without task transfer" in text.casefold()


def test_current_docs_do_not_claim_ongoing_sync_or_persisted_selection() -> None:
    forbidden = (
        "Setup required",
        "Pause Sync",
        "Resume Sync",
        "Change Tasks",
        "Clear Sync Setup",
        "Pull Tasks",
        "Push Tasks",
        "selected task ids",
    )
    for path in CURRENT_DOCS:
        text = path.read_text(encoding="utf-8")
        for phrase in forbidden:
            assert phrase.casefold() not in text.casefold(), (path, phrase)


def test_every_changelog_has_unreleased_and_dated_release_headings() -> None:
    heading = re.compile(r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})(?: - .+)?$", re.MULTILINE)
    for path in CHANGELOGS:
        text = path.read_text(encoding="utf-8")
        assert text.startswith("# Changelog\n\n## Unreleased\n")
        release_lines = [line for line in text.splitlines() if line.startswith("## 0.")]
        assert release_lines
        assert all(heading.fullmatch(line) for line in release_lines)


def test_matching_changelog_versions_have_identical_dates() -> None:
    def dates(path: Path) -> dict[str, str]:
        return dict(re.findall(r"^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})", path.read_text(), re.MULTILINE))

    root_dates = dates(CHANGELOGS[0])
    extension_dates = dates(CHANGELOGS[1])
    assert {version: root_dates[version] for version in extension_dates} == extension_dates
```

- [ ] **Step 2: Run docs tests and verify undated headings fail**

```bash
uv run pytest tests/test_task_transfer_docs.py -q
```

Expected: FAIL because current READMEs use Sync language and changelog headings are undated.

- [ ] **Step 3: Add ADR 0014**

`docs/adr/0014-manual-task-transfer.md` records:

- context: manual transfer was presented as ongoing sync and desktop saved roots were treated as required;
- decision: explicit Import/Export/Review, folder-only persistence, fresh selection, all-or-nothing preflight, surface-neutral roots, no private state writes, format v3 `tasks/`, baseline v2 independence;
- alternatives rejected: wording-only patch, persisted mapping, desktop-app prerequisite, automatic background transfer, private SQLite/global-state mutation;
- consequences: projects must exist locally, extension-only imports work, migration is automatic, technical sync vocabulary remains private;
- guardrails: manual triggers, identity validation, existing-cwd preservation, conflict safety, no Linux package in this release;
- supersession: presentation, persistent selection, and desktop-root discovery portions of ADR 0013 are superseded; its manual-only triggers and data-safety rules remain.

- [ ] **Step 4: Rewrite both current READMEs and Marketplace metadata**

Lead Task Transfer sections with this sequence:

1. Export selected active tasks on the source computer.
2. Wait for the filesystem provider to converge.
3. Clone or copy the corresponding project checkout on the destination.
4. Open the checkout in VS Code when using the IDE extension alone.
5. Import selected tasks; accept an automatic match or choose a validated folder.
6. Reload VS Code or restart the Codex app.

State explicitly:

- token reporting works without Task Transfer;
- every operation uses a fresh selection;
- imported tasks remain in the transfer folder;
- large tasks can be moved when built-in Codex handoff fails;
- the Codex desktop app is not required;
- Git origin validates cross-machine checkout mapping;
- non-Git mapping asks for confirmation;
- technical CLI commands remain under a clearly labeled `Internal CLI` section;
- current packages are Windows x64 and macOS Apple Silicon only.

Update `extensions/vscode/package.json` description and keywords to include optional cross-computer Codex task transfer without implying background synchronization.

- [ ] **Step 5: Backfill evidence-derived changelog dates**

Insert `## Unreleased` at the top of both changelogs. Use this exact root date map, derived with `git log --all --reverse -S"## <version>" -- CHANGELOG.md`; versions present in the extension changelog use the same date:

```text
0.1.35 2026-07-14
0.1.34 2026-07-14
0.1.33 2026-07-14
0.1.32 2026-07-09
0.1.31 2026-07-03
0.1.30 2026-06-24
0.1.29 2026-06-15
0.1.28 2026-06-12
0.1.27 2026-06-11
0.1.26 2026-06-11
0.1.25 2026-06-11
0.1.24 2026-05-30
0.1.23 2026-05-30
0.1.22 2026-05-30
0.1.21 2026-05-30
0.1.20 2026-05-30
0.1.19 2026-05-27
0.1.18 2026-05-25
0.1.17 2026-05-25
0.1.16 2026-05-25
0.1.15 2026-05-25
0.1.14 2026-05-25
0.1.13 2026-05-25
0.1.12 2026-05-25
0.1.11 2026-05-24
0.1.10 2026-05-24
0.1.9 2026-05-24
0.1.8 2026-05-24
0.1.6 2026-05-24
0.1.5 2026-05-21
0.1.4 2026-05-21
0.1.3 2026-05-19
0.1.0 2026-05-19
```

Preserve historical bullet wording. Add the new work under `Unreleased` in both changelogs; release preparation moves it in Task 9.

- [ ] **Step 6: Update release documentation and manual acceptance checklist**

Replace Sync menu commands in `docs/release.md` with Import/Export/Review. Add the extension-only manual gate:

```text
- Quit the Codex desktop app.
- Open an existing matching checkout in VS Code.
- Import a remote-only task using the packaged extension.
- Reload VS Code.
- Confirm the official Codex extension lists and opens the task under that workspace.
```

Document that Linux packaging is a follow-up, not a hidden supported target.

- [ ] **Step 7: Run documentation tests and wording audit**

```bash
uv run pytest tests/test_task_transfer_docs.py -q
rg -n 'Setup required|Pause Sync|Resume Sync|Pull Tasks|Push Tasks|Change Tasks|Clear Sync Setup|conversation|thread' README.md extensions/vscode/README.md extensions/vscode/package.json docs/release.md
```

Expected: pytest PASS. The `rg` command may return only explicitly labeled internal technical references such as `thread_id`; inspect every result and remove current user-facing conversation/thread terminology.

- [ ] **Step 8: Commit ADR and docs**

```bash
git add docs/adr/0014-manual-task-transfer.md tests/test_task_transfer_docs.py README.md extensions/vscode/README.md CHANGELOG.md extensions/vscode/CHANGELOG.md docs/release.md extensions/vscode/package.json
git commit -m "docs: reposition sync as task transfer"
```

---

### Task 9: Update Packaged Smoke, Repository Guardrails, And Release Metadata

**Files:**
- Modify: `scripts/smoke-test-packaged-sync.py`
- Modify: `tests/test_github_actions_workflow.py`
- Modify: `tests/test_task_transfer_docs.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`
- Modify: `CHANGELOG.md`
- Modify: `extensions/vscode/CHANGELOG.md`

- [ ] **Step 1: Write failing package-smoke guardrail tests**

Update `tests/test_github_actions_workflow.py` to assert the packaged script uses v3 and proves extension-only destination resolution:

```python
def test_packaged_transfer_smoke_uses_v3_without_desktop_project_state() -> None:
    source = PACKAGED_SYNC_SMOKE.read_text(encoding="utf-8")

    assert 'SYNC_FORMAT_VERSION = 3' in source
    assert 'TASKS_DIRNAME = "tasks"' in source
    assert '"--candidate-project-root"' in source
    assert ".codex-global-state.json" not in source
    assert 'sync_dir / "conversations"' not in source


def test_release_workflow_keeps_only_supported_platform_targets() -> None:
    workflow = PACKAGE_WORKFLOW.read_text(encoding="utf-8")

    assert "win32-x64" in workflow
    assert "darwin-arm64" in workflow
    assert "linux-x64" not in workflow
```

Change the version coherence test name and expected values to `0.1.36`.

- [ ] **Step 2: Run guardrails and verify old smoke/version failures**

```bash
uv run pytest tests/test_github_actions_workflow.py -q
```

Expected: FAIL because the smoke script still uses v2 `conversations/`, writes desktop global state, and release metadata is 0.1.35.

- [ ] **Step 3: Convert packaged smoke to extension-only v3 Import**

In `scripts/smoke-test-packaged-sync.py`:

- set inventory version 2 and remote format version 3;
- validate exactly one `tasks/<portable>.jsonl` and no `conversations/`;
- remove creation of target `.codex-global-state.json`;
- pass `--candidate-project-root <project_root>` to target inventory, pull, and status invocations;
- assert destination inventory reports one Git candidate root;
- assert Import rewrites/preserves `cwd` as the exact passed workspace path;
- retain byte/hash/index/baseline checks and packaged executable isolation;
- keep source Export and destination Import as one process each.

Change `_run_sync` to:

```python
def _run_sync(
    executable: Path,
    codex_home: Path,
    sync_dir: Path,
    direction: str,
    *,
    candidate_project_root: Path | None = None,
) -> dict[str, object]:
    args = [
        "sync", direction,
        "--sync-dir", str(sync_dir),
        "--thread-id", THREAD_ID,
        "--json",
    ]
    if candidate_project_root is not None:
        args.extend(["--candidate-project-root", str(candidate_project_root)])
    return _run_json(executable, codex_home, args)
```

- [ ] **Step 4: Prepare version 0.1.36 metadata**

Run from the repository root:

```bash
uv version 0.1.36
cd extensions/vscode && npm version 0.1.36 --no-git-tag-version
```

If the installed uv lacks `uv version`, edit `pyproject.toml` with `apply_patch` and run `uv lock`; do not hand-edit `uv.lock`.

Keep `## Unreleased` at the top of both changelogs. Move this release's bullets beneath:

```text
## 0.1.36 - 2026-07-15 - Task Transfer UX And Storage V3
```

The bullets cover product repositioning, fresh per-operation selection, usage-only status, extension-only project resolution, v3 folder migration, all-or-nothing directional preflight, and wording/docs cleanup.

- [ ] **Step 5: Run metadata, docs, and packaged-script unit tests**

```bash
uv run pytest tests/test_github_actions_workflow.py tests/test_task_transfer_docs.py -q
```

Expected: PASS with all four version sources at 0.1.36, two platform targets only, v3 smoke fixtures, and dated changelogs.

- [ ] **Step 6: Commit release preparation**

```bash
git add scripts/smoke-test-packaged-sync.py tests/test_github_actions_workflow.py tests/test_task_transfer_docs.py pyproject.toml uv.lock extensions/vscode/package.json extensions/vscode/package-lock.json CHANGELOG.md extensions/vscode/CHANGELOG.md
git commit -m "chore: prepare 0.1.36 task transfer release"
```

---

### Task 10: Full Verification, Review, Merge, Push, And Publish

**Files:**
- Verify all changed files.
- Do not modify generated files under `build/`, `extensions/vscode/bin/`, or `output/releases/` unless the packaging scripts own them; those paths remain ignored.

- [ ] **Step 1: Run the complete Python suite**

```bash
uv run pytest -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run changed-scope lint**

```bash
uvx ruff check src tests scripts
```

Expected: PASS with no lint errors.

- [ ] **Step 3: Run the complete extension suite**

```bash
cd extensions/vscode
npm ci
npm test
```

Expected: TypeScript build and every Node test PASS.

- [ ] **Step 4: Build and smoke-test the macOS Apple Silicon VSIX**

On this Apple Silicon Mac:

```bash
cd extensions/vscode
npm run package:vsix:mac
```

Expected:

- PyInstaller builds `extensions/vscode/bin/darwin-arm64/codex-usage`;
- packaged inventory/Export/Import smoke passes with no desktop global-state file;
- `output/releases/codex-usage-dashboard-darwin-arm64.vsix` exists.

Inspect the archive:

```bash
unzip -l ../../output/releases/codex-usage-dashboard-darwin-arm64.vsix | rg 'extension/(out|bin/darwin-arm64|package.json|readme.md|CHANGELOG.md)'
```

Expected: runtime JS, current docs, metadata, and one Darwin arm64 executable are present; source tests and secrets are absent.

- [ ] **Step 5: Perform the extension-only manual Import gate**

Install the built VSIX into VS Code:

```bash
code --install-extension output/releases/codex-usage-dashboard-darwin-arm64.vsix --force
```

Then verify with the Codex desktop app closed:

1. Open an existing Git checkout in VS Code.
2. Use **Codex Usage: Import Tasks** against a disposable v3 transfer fixture containing one remote-only task for that repository.
3. Confirm no desktop project registry is created or modified.
4. Reload VS Code.
5. Confirm the official Codex extension lists and opens the imported task under the checkout.

Record the fixture path and result in the execution notes, but do not commit the fixture or task contents. Do not publish if this gate fails.

- [ ] **Step 6: Run final source and repository audits**

```bash
git diff --check
git status --short
rg -n 'SYNC_FORMAT_VERSION|SYNC_CONVERSATIONS_DIRNAME|conversations/' src/codex_usage extensions/vscode/src scripts/smoke-test-packaged-sync.py README.md extensions/vscode/README.md docs/release.md
rg -n 'Setup required|Pause Sync|Resume Sync|Pull Tasks|Push Tasks|Change Tasks|Clear Sync Setup|codexUsage\.sync\.enabled' extensions/vscode/src extensions/vscode/package.json README.md extensions/vscode/README.md docs/release.md
wc -l src/codex_usage/sync/*.py extensions/vscode/src/*.ts
```

Expected:

- `git diff --check` is silent;
- status lists only intentional tracked changes, or is clean after task commits;
- old remote constants/paths do not remain in current code except explicit legacy migration constants/tests;
- forbidden current product wording is absent;
- no newly modified source file exceeds 500 lines;
- `.env`, transfer fixtures, packaged binaries, and VSIX files are not staged.

- [ ] **Step 7: Request independent code review and address findings**

Use `superpowers:requesting-code-review` against the complete branch diff. Review priorities are:

- migration interruption safety and no-delete-before-v3-commit;
- path traversal/symlink/identity validation;
- no partial copy on preflight blockers;
- no private Codex state writes;
- existing local cwd preservation;
- fresh non-persisted selection;
- folder-only migration across all VS Code configuration scopes;
- strict CLI/inventory payload parsing;
- result wording and usage-only status;
- package target and version coherence.

Apply accepted findings with focused tests and commits, then rerun Steps 1-6.

- [ ] **Step 8: Verify branch history and clean worktree**

```bash
git log --oneline --decorate main..HEAD
git status --short --branch
```

Expected: focused commits for format split, migration, project resolution, preflight/protocol, state/presentation, picker, extension orchestration, docs/ADR, and release preparation; worktree clean.

- [ ] **Step 9: Merge into main and push**

```bash
git checkout main
git pull --ff-only origin main
git merge --no-ff codex/optional-manual-task-sync-ux -m "merge: release task transfer ux and storage v3"
git push origin main
```

Expected: merge and push succeed without rewriting history. Do not delete the feature branch until the workflow succeeds.

- [ ] **Step 10: Dispatch the native two-platform publish workflow**

```bash
gh workflow run "Package and Publish VSIX" \
  --repo Wenjun-Mao/codex_usage \
  --ref main \
  -f publish=true
```

Capture the new run id without selecting an older run:

```bash
run_id=$(gh run list \
  --repo Wenjun-Mao/codex_usage \
  --workflow "Package and Publish VSIX" \
  --event workflow_dispatch \
  --branch main \
  --limit 1 \
  --json databaseId \
  --jq '.[0].databaseId')
gh run watch "$run_id" --repo Wenjun-Mao/codex_usage --exit-status
```

Expected: Windows x64 and macOS Apple Silicon jobs independently pass Python tests, extension tests, packaged extension-only transfer smoke, and VSIX creation; the publish job then publishes both 0.1.36 packages. Linux is not built.

- [ ] **Step 11: Verify publication and report evidence**

```bash
gh run view "$run_id" --repo Wenjun-Mao/codex_usage --json conclusion,url,jobs
git status --short --branch
```

Expected: workflow conclusion `success`, both build jobs and publish job successful, local `main` clean and aligned with `origin/main`. Report the merge commit, workflow URL, local test counts, package smoke result, and Marketplace publish result.
