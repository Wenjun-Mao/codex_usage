# Exact Task Sync Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace dynamic project/conversation sync selection with one project-grouped picker that persists exact Codex task thread ids from a combined local-and-remote inventory.

**Architecture:** Python remains authoritative for local session discovery, remote-store validation, canonical project identity, and inventory merging. The VS Code extension invokes one read-only inventory command during configuration, parses its strict JSON in a focused module, and drives a pure task-picker state model; routine status and sync continue as one process with explicit thread ids only.

**Tech Stack:** Python 3.13, pytest, TypeScript 5.7, VS Code 1.90 Quick Pick APIs, Node's built-in test runner, uv, PyInstaller, and vsce.

## Global Constraints

- User-facing sync copy says **task**; technical Python, TypeScript, JSON, CLI, and storage contracts retain `thread_id`, `threadIds`, and `--thread-id`.
- Persist exact task thread ids only. Project rows are current-snapshot shortcuts and never include future tasks automatically.
- Selection schema version is exactly `2`; missing or obsolete versions mean **Setup required** and must never start automatic sync.
- Do not migrate legacy project, conversation-mode, or thread selectors. Preserve the configured folder, enabled state, and automatic-sync preferences.
- Keep the version-2 remote layout, byte-preserved JSONLs, three-way planner, conflict behavior, and no-delete-on-deselect guarantees unchanged.
- Inventory is read-only. It may use effective in-memory reconciliation but must not write local base state or the remote index.
- Sync continues to consider active local `sessions` only; archived local tasks remain out of scope.
- Add no runtime dependencies. Reuse existing path guards and tenacity-backed I/O operations.
- Keep new Python and TypeScript responsibilities in focused files; do not add protocol or picker state to the already large `models.py`, `core.ts`, or `extension.ts`.

---

### Task 1: Build The Combined Python Task Inventory

**Files:**
- Create: `src/codex_usage/sync/selection_inventory.py`
- Create: `tests/test_sync_selection_inventory.py`
- Modify: `src/codex_usage/sync/__init__.py`

**Interfaces:**
- Consumes: `LocalInventory`, `RemoteInventory`, `ThreadInfo`, `RemoteThreadEntry`, `RemoteStore.load_inventory()`, and `build_local_inventory()`.
- Produces: `SyncTaskInventoryItem`, `SyncProjectInventoryItem`, `SyncSelectionInventory`, `build_sync_selection_inventory(local, remote)`, and `load_sync_selection_inventory(data, sync_dir)`.

- [ ] **Step 1: Write failing merge and ordering tests**

Add fixtures that construct a local task, a remote-only task, and one shared thread id. Reuse the complete `ThreadInfo`, `RemoteThreadEntry`, `RemoteIndex`, `SyncFileSnapshot`, and `RemoteInventory` builders from `tests/test_sync_inventory.py`, but make `RemoteInventory.files` explicit so only existing remote JSONLs are selectable:

```python
def _remote_inventory(
    *entries: RemoteThreadEntry,
    issues: tuple[SyncIssue, ...] = (),
    missing_thread_ids: tuple[str, ...] = (),
) -> RemoteInventory:
    index = RemoteIndex(
        format_version=2,
        updated_at="",
        threads={entry.thread_id: entry for entry in entries},
    )
    files = {
        entry.thread_id: SyncFileSnapshot(
            path=Path("sync") / entry.file,
            exists=entry.thread_id not in missing_thread_ids,
            sha256=entry.sha256,
            size_bytes=entry.size_bytes,
        )
        for entry in entries
    }
    return RemoteInventory(index, index, SyncFileSnapshot(None, False), files, (), issues)

def _local_inventory(*tasks: ThreadInfo) -> LocalInventory:
    return LocalInventory((Path("sessions"),), {task.thread_id: task for task in tasks}, {}, len(tasks))

def _local_task(
    thread_id: str,
    title: str,
    project_key: str,
    project_label: str,
    updated_at: str,
) -> ThreadInfo:
    return ThreadInfo(
        thread_id=thread_id,
        title=title,
        updated_at=updated_at,
        session_path=Path("sessions") / f"{thread_id}.jsonl",
        project_key=project_key,
        project_label=project_label,
        project_aliases=(),
        total_tokens=0,
        session_bytes=100,
        estimated_sync_bytes=4196,
    )

def _remote_task(
    thread_id: str,
    title: str,
    project_key: str,
    project_label: str,
    updated_at: str,
) -> RemoteThreadEntry:
    return RemoteThreadEntry(
        thread_id=thread_id,
        file=f"conversations/{thread_id}.jsonl",
        source_relative_path=f"2026/07/14/{thread_id}.jsonl",
        index_entry={"id": thread_id, "thread_name": title, "updated_at": updated_at},
        project_key=project_key,
        project_label=project_label,
        project_aliases=(),
        sha256=f"sha-{thread_id}",
        size_bytes=100,
        session_updated_at=updated_at,
        exported_at=updated_at,
        source_machine_id="machine-a",
    )
```

Assert local display metadata wins for the shared task, availability values are exact, canonical project groups are deterministic, and remote issues survive in the payload.

```python
def test_build_inventory_merges_by_thread_id_and_groups_projects() -> None:
    local = LocalInventory(
        session_dirs=(Path("/codex/sessions"),),
        threads={
            "shared": _local_task("shared", "Local title", "repo-a", "Repo A", "2026-07-14T12:00:00Z"),
            "local": _local_task("local", "Local only", "repo-a", "Repo A", "2026-07-14T11:00:00Z"),
        },
        index_entries={},
        discovered_count=2,
    )
    remote = _remote_inventory(
        _remote_task("shared", "Remote title", "repo-b", "Repo B", "2026-07-14T13:00:00Z"),
        _remote_task("remote", "Remote only", "repo-b", "Repo B", "2026-07-14T10:00:00Z"),
    )

    result = build_sync_selection_inventory(local, remote)

    assert result.inventory_version == 1
    assert [project.project_key for project in result.projects] == ["repo-a", "repo-b"]
    assert [(task.thread_id, task.title, task.availability) for task in result.projects[0].tasks] == [
        ("shared", "Local title", "both"),
        ("local", "Local only", "local"),
    ]
    assert [(task.thread_id, task.availability) for task in result.projects[1].tasks] == [
        ("remote", "remote"),
    ]
```

Also add these concrete guardrails:

```python
def test_inventory_omits_missing_remote_files_and_keeps_issue() -> None:
    issue = SyncIssue("unidentified_remote_file", "Could not identify mystery.jsonl")
    remote = _remote_inventory(
        _remote_task("missing", "Missing", "repo", "Repo", "2026-07-14T10:00:00Z"),
        issues=(issue,),
        missing_thread_ids=("missing",),
    )

    result = build_sync_selection_inventory(_local_inventory(), remote)

    assert result.projects == ()
    assert result.issues == (issue,)

def _snapshot_tree(root: Path) -> tuple[tuple[str, str, bytes], ...]:
    entries: list[tuple[str, str, bytes]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((relative, "symlink", os.readlink(path).encode()))
        elif path.is_dir():
            entries.append((relative, "directory", b""))
        else:
            entries.append((relative, "file", path.read_bytes()))
    return tuple(entries)

def test_load_inventory_is_read_only(tmp_path: Path) -> None:
    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    data = CachedSessionData(
        session_dirs=[tmp_path / "sessions"],
        files=[],
        records=[],
        file_summaries={},
        project_transitions=[],
        stats=CacheStats(),
        file_errors={},
    )
    before = _snapshot_tree(tmp_path)

    load_sync_selection_inventory(data, sync_dir)

    assert _snapshot_tree(tmp_path) == before
```

Import `os`, `CacheStats`, and `CachedSessionData` for the helpers above. Add parameterized integration tests proving malformed `sync-index.json`, a legacy `threads/` directory, a symlinked `conversations/` directory, and an unreadable remote folder raise the existing structural exception without changing `_snapshot_tree(tmp_path)`. Add `test_empty_remote_folder_returns_local_tasks` so that normal first setup is explicit.

- [ ] **Step 2: Run the new tests and verify the missing module failure**

Run: `uv run pytest tests/test_sync_selection_inventory.py -q`

Expected: FAIL during collection with `ModuleNotFoundError: No module named 'codex_usage.sync.selection_inventory'`.

- [ ] **Step 3: Implement immutable inventory models and the merge**

Use focused dataclasses with strict `to_dict()` output and deterministic sort keys. Import `Literal` from `typing`:

```python
INVENTORY_VERSION = 1
TaskAvailability = Literal["local", "remote", "both"]

@dataclass(frozen=True)
class SyncTaskInventoryItem:
    thread_id: str
    title: str
    updated_at: str
    estimated_sync_bytes: int
    availability: TaskAvailability

    def to_dict(self) -> dict[str, object]:
        return {
            "thread_id": self.thread_id,
            "title": self.title,
            "updated_at": self.updated_at,
            "estimated_sync_bytes": self.estimated_sync_bytes,
            "availability": self.availability,
        }

@dataclass(frozen=True)
class SyncProjectInventoryItem:
    project_key: str
    project_label: str
    tasks: tuple[SyncTaskInventoryItem, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "project_key": self.project_key,
            "project_label": self.project_label,
            "tasks": [task.to_dict() for task in self.tasks],
        }

@dataclass(frozen=True)
class SyncSelectionInventory:
    inventory_version: int
    projects: tuple[SyncProjectInventoryItem, ...]
    issues: tuple[SyncIssue, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "inventory_version": self.inventory_version,
            "projects": [project.to_dict() for project in self.projects],
            "issues": [issue.to_dict() for issue in self.issues],
        }
```

Implement the merge with one internal candidate type. This complete algorithm limits remote candidates to validated existing snapshots, preserves remote issues, prefers local metadata, and gives both task and project labels deterministic precedence:

```python
@dataclass(frozen=True)
class _TaskCandidate:
    project_key: str
    project_label: str
    from_local: bool
    task: SyncTaskInventoryItem

def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""

def build_sync_selection_inventory(
    local: LocalInventory,
    remote: RemoteInventory,
) -> SyncSelectionInventory:
    remote_entries: dict[str, tuple[RemoteThreadEntry, SyncFileSnapshot]] = {}
    for thread_id, entry in remote.index.threads.items():
        snapshot = remote.files.get(thread_id)
        if snapshot is not None and snapshot.exists:
            remote_entries[thread_id] = (entry, snapshot)

    grouped: dict[str, list[_TaskCandidate]] = {}
    for thread_id in sorted(local.threads.keys() | remote_entries.keys()):
        local_task = local.threads.get(thread_id)
        remote_pair = remote_entries.get(thread_id)
        if local_task is not None:
            availability: TaskAvailability = "both" if remote_pair is not None else "local"
            project_key = local_task.project_key
            project_label = local_task.project_label
            candidate = _TaskCandidate(
                project_key=project_key,
                project_label=project_label,
                from_local=True,
                task=SyncTaskInventoryItem(
                    thread_id=thread_id,
                    title=local_task.title,
                    updated_at=local_task.updated_at,
                    estimated_sync_bytes=local_task.estimated_sync_bytes,
                    availability=availability,
                ),
            )
        else:
            assert remote_pair is not None
            entry, snapshot = remote_pair
            project_key = entry.project_key
            project_label = entry.project_label
            candidate = _TaskCandidate(
                project_key=project_key,
                project_label=project_label,
                from_local=False,
                task=SyncTaskInventoryItem(
                    thread_id=thread_id,
                    title=(
                        _text(entry.index_entry.get("thread_name"))
                        or _text(entry.index_entry.get("title"))
                        or project_label
                        or thread_id
                    ),
                    updated_at=(
                        _text(entry.index_entry.get("updated_at"))
                        or entry.session_updated_at
                    ),
                    estimated_sync_bytes=snapshot.size_bytes,
                    availability="remote",
                ),
            )
        grouped.setdefault(project_key, []).append(candidate)

    projects: list[SyncProjectInventoryItem] = []
    for project_key, candidates in grouped.items():
        candidates.sort(key=lambda candidate: candidate.task.thread_id)
        candidates.sort(key=lambda candidate: timestamp_key(candidate.task.updated_at), reverse=True)
        local_labels = [candidate for candidate in candidates if candidate.from_local]
        label_candidates = local_labels or candidates
        project_label = label_candidates[0].project_label
        projects.append(
            SyncProjectInventoryItem(
                project_key=project_key,
                project_label=project_label,
                tasks=tuple(candidate.task for candidate in candidates),
            )
        )
    projects.sort(key=lambda project: (project.project_label.casefold(), project.project_key))
    return SyncSelectionInventory(INVENTORY_VERSION, tuple(projects), remote.issues)
```

Do not call `RemoteStore.materialize_selected`, `transaction`, state writers, or index writers from this module.

```python
def load_sync_selection_inventory(
    data: CachedSessionData,
    sync_dir: Path,
) -> SyncSelectionInventory:
    local = build_local_inventory(data)
    remote = RemoteStore(sync_dir).load_inventory()
    return build_sync_selection_inventory(local, remote)
```

Export the models and loader from `codex_usage.sync`.

- [ ] **Step 4: Run inventory tests and the existing inventory/store suites**

Run: `uv run pytest tests/test_sync_selection_inventory.py tests/test_sync_inventory.py tests/test_sync_store.py -q`

Expected: PASS with no failures.

- [ ] **Step 5: Commit the inventory domain slice**

```bash
git add src/codex_usage/sync/selection_inventory.py src/codex_usage/sync/__init__.py tests/test_sync_selection_inventory.py
git commit -m "feat: add combined task sync inventory"
```

---

### Task 2: Expose Read-Only Inventory Through The CLI

**Files:**
- Modify: `src/codex_usage/sync_cli.py`
- Modify: `src/codex_usage/cli.py`
- Modify: `tests/test_sync_cli.py`

**Interfaces:**
- Consumes: `load_sync_selection_inventory(data, sync_dir)` from Task 1 and the existing session data loader.
- Produces: `codex-usage sync inventory --sync-dir <path> --json` and `handle_sync_inventory(args, load_session_data)`.

- [ ] **Step 1: Add failing parser and one-load CLI tests**

Update the sync help expectation to `{inventory,run,status}` and add:

```python
def test_sync_inventory_loads_local_data_once_and_prints_json(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    data = object()
    calls: list[tuple[object, ...]] = []
    expected = SimpleNamespace(to_dict=lambda: {"inventory_version": 1, "projects": [], "issues": []})

    def load(paths: list[Path], *, auto_transitions: bool) -> object:
        calls.append((tuple(paths), auto_transitions))
        return data

    monkeypatch.setattr(sync_cli, "_sync_session_dirs", lambda *, create: [tmp_path / "sessions"])
    monkeypatch.setattr(sync_cli, "load_sync_selection_inventory", lambda value, path: expected)

    exit_code = sync_cli.handle_sync_inventory(_args(tmp_path), load)

    assert exit_code == 0
    assert calls == [((tmp_path / "sessions",), True)]
    assert json.loads(capsys.readouterr().out) == expected.to_dict()
```

Add an integration test invoking `main(["sync", "inventory", ...])` against one local task and an empty remote folder.

- [ ] **Step 2: Run the CLI tests and verify the missing subcommand failure**

Run: `uv run pytest tests/test_sync_cli.py -q`

Expected: FAIL because `inventory` is not a registered sync subcommand and `handle_sync_inventory` does not exist.

- [ ] **Step 3: Register inventory with options separate from execution selectors**

Split option registration so inventory has no selector and run/status share explicit thread options:

```python
def add_sync_common_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--sync-dir", type=Path, required=True, help="Bring-your-own local sync folder.")
    parser.add_argument("--no-auto-transitions", action="store_true", help="Disable automatic project transition inference.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")

def add_sync_execution_options(parser: argparse.ArgumentParser) -> None:
    add_sync_common_options(parser)
    parser.add_argument("--thread-id", action="append", help="Technical thread id for a selected Codex task. Repeat as needed.")

def handle_sync_inventory(args: argparse.Namespace, load_session_data: SessionDataLoader) -> int:
    data, _ = _load_sync_data(args, create_sessions=False, load_session_data=load_session_data)
    payload = load_sync_selection_inventory(data, args.sync_dir).to_dict()
    if args.json:
        print_json(payload)
    else:
        _print_sync_inventory(payload)
    return 0

def _print_sync_inventory(payload: dict[str, object]) -> None:
    projects = payload["projects"]
    issues = payload["issues"]
    assert isinstance(projects, list) and isinstance(issues, list)
    task_count = sum(
        len(project.get("tasks", []))
        for project in projects
        if isinstance(project, dict) and isinstance(project.get("tasks"), list)
    )
    print(
        f"Sync inventory: {len(projects)} projects, "
        f"{task_count} tasks, {len(issues)} issues."
    )
```

Register `inventory` before `run` and wire `handle_sync_inventory` through `cli.py`. Update the `sync`, `run`, and `status` parser help to say selected Codex tasks; keep the option help explicit that `--thread-id` is the technical id for a selected task. The human summary prints one line with project, task, and issue counts.

- [ ] **Step 4: Run CLI and inventory tests**

Run: `uv run pytest tests/test_sync_cli.py tests/test_sync_selection_inventory.py -q`

Expected: PASS with no failures.

- [ ] **Step 5: Commit the CLI inventory surface**

```bash
git add src/codex_usage/sync_cli.py src/codex_usage/cli.py tests/test_sync_cli.py
git commit -m "feat: expose task sync inventory command"
```

---

### Task 3: Make Sync Selectors Exact Thread IDs Only

**Files:**
- Modify: `src/codex_usage/sync/inventory.py`
- Modify: `src/codex_usage/sync/runner.py`
- Modify: `src/codex_usage/sync_cli.py`
- Modify: `tests/test_sync_inventory.py`
- Modify: `tests/test_sync_cli.py`
- Modify: `tests/test_sync_runner.py`
- Modify: `tests/test_sync_runner_bookkeeping.py`

**Interfaces:**
- Consumes: repeatable explicit thread ids from the CLI and direct Python callers.
- Produces: `normalize_selected_thread_ids(thread_ids) -> tuple[str, ...]`, plus `run_sync` and `sync_status` signatures with no `project_keys` parameter.

- [ ] **Step 1: Rewrite selector tests to require exact ids**

Replace project-expansion tests with normalization and future-exclusion coverage:

```python
def test_normalize_selected_thread_ids_is_exact_case_sensitive_and_deduplicated() -> None:
    assert normalize_selected_thread_ids([" Task/A ", "Task/A", "task/a", ""]) == (
        "Task/A",
        "task/a",
    )

def test_new_task_in_same_project_remains_excluded_after_initial_selection(tmp_path: Path) -> None:
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
```

Keep `test_run_sync_pulls_before_pushes_in_one_transaction` as the remote-only pull acceptance test: remove both `project_keys=[]` arguments, leave its explicit `thread_ids=["remote-thread", "local-thread"]`, and preserve its byte-equality assertion for the pulled remote-only task. This keeps the acceptance test on the public runner path rather than constructing a remote index by hand.

Update CLI tests so `--project-key` is rejected under `sync run` and an empty selector reports `Select at least one task with --thread-id for sync.`

- [ ] **Step 2: Run focused tests and verify old project behavior fails the new assertions**

Run: `uv run pytest tests/test_sync_inventory.py tests/test_sync_cli.py tests/test_sync_runner.py -q`

Expected: FAIL while runner signatures and CLI options still accept `project_keys`.

- [ ] **Step 3: Remove project expansion from the execution contract**

Replace `resolve_selected_thread_ids` with:

```python
def normalize_selected_thread_ids(thread_ids: Iterable[str]) -> tuple[str, ...]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in thread_ids:
        thread_id = value.strip()
        if not thread_id or thread_id in seen:
            continue
        seen.add(thread_id)
        selected.append(thread_id)
    return tuple(selected)
```

Remove `project_keys` from `run_sync`, `sync_status`, and `_prepare_sync_plan`. Build the plan from `normalize_selected_thread_ids(thread_ids)`. In `sync_cli.py`, normalize only `args.thread_id`, reject an empty result, and pass only `thread_ids` to the runner.

Mechanically remove `project_keys=[]` from all runner tests and update direct mock assertions. Do not change top-level report or `threads --project-key` behavior.

- [ ] **Step 4: Run every Python sync test**

Run: `uv run pytest tests/test_sync.py tests/test_sync_cli.py tests/test_sync_inventory.py tests/test_sync_io.py tests/test_sync_planner.py tests/test_sync_runner.py tests/test_sync_runner_bookkeeping.py tests/test_sync_state.py tests/test_sync_store.py -q`

Expected: PASS with no failures.

- [ ] **Step 5: Commit the exact-selector contract**

```bash
git add src/codex_usage/sync/inventory.py src/codex_usage/sync/runner.py src/codex_usage/sync_cli.py tests/test_sync_inventory.py tests/test_sync_cli.py tests/test_sync_runner.py tests/test_sync_runner_bookkeeping.py
git commit -m "refactor: sync exact task thread ids only"
```

---

### Task 4: Add A Strict TypeScript Inventory Protocol

**Files:**
- Create: `extensions/vscode/src/syncInventory.ts`
- Create: `extensions/vscode/test/syncInventory.test.js`

**Interfaces:**
- Consumes: stdout from `codex-usage sync inventory --json`.
- Produces: `SyncInventory`, `SyncInventoryProject`, `SyncInventoryTask`, `buildSyncInventoryArgs(options)`, and `parseSyncInventory(json)`.

- [ ] **Step 1: Write failing argument and strict-parser tests**

```javascript
test("inventory args use one read-only command", () => {
  assert.deepEqual(buildSyncInventoryArgs({ syncDir: " D:/Sync ", autoTransitions: false }), [
    "sync", "inventory", "--json", "--sync-dir", "D:/Sync", "--no-auto-transitions",
  ]);
});

test("inventory parser preserves project tasks and availability", () => {
  const parsed = parseSyncInventory(JSON.stringify({
    inventory_version: 1,
    projects: [{
      project_key: "repo-a",
      project_label: "Repo A",
      tasks: [{
        thread_id: "thread-1",
        title: "Persona - execution",
        updated_at: "2026-07-14T12:00:00Z",
        estimated_sync_bytes: 2048,
        availability: "remote",
      }],
    }],
    issues: [],
  }));
  assert.equal(parsed.projects[0].tasks[0].availability, "remote");
});
```

Add table tests rejecting extra keys, missing fields, duplicate project keys, duplicate thread ids, invalid availability, unsafe integers, negative byte counts, and malformed issue objects. Each case must assert the parser throws an error containing the failing field path.

- [ ] **Step 2: Run the extension inventory test and verify module absence**

Run: `cd extensions/vscode && npm test -- --test-name-pattern="inventory"`

Expected: FAIL because `../out/syncInventory` does not exist.

- [ ] **Step 3: Implement exact-key decoding and argument construction**

Define these public types:

```typescript
export type SyncTaskAvailability = "local" | "remote" | "both";
export type SyncInventoryTask = {
  threadId: string;
  title: string;
  updatedAt: string;
  estimatedSyncBytes: number;
  availability: SyncTaskAvailability;
};
export type SyncInventoryProject = { projectKey: string; projectLabel: string; tasks: SyncInventoryTask[] };
export type SyncInventoryIssue = { code: string; message: string; threadId: string };
export type SyncInventory = { inventoryVersion: 1; projects: SyncInventoryProject[]; issues: SyncInventoryIssue[] };
export type SyncInventoryCommandOptions = { syncDir: string; autoTransitions: boolean };

export function buildSyncInventoryArgs(options: SyncInventoryCommandOptions): string[];
export function parseSyncInventory(json: string): SyncInventory;
```

`parseSyncInventory` must parse JSON, require exact top-level/project/task/issue keys, require `inventory_version === 1`, validate safe nonnegative byte counts, reject duplicate project keys and duplicate thread ids globally, and map snake-case fields to the types above. Keep private `exactRecord`, `stringField`, `nonnegativeInteger`, and `parseArray` decoders in this focused module; each throws `Invalid sync inventory: <field path> <reason>`. `buildSyncInventoryArgs` trims the folder, emits `--json` before options, and emits `--no-auto-transitions` only when false.

- [ ] **Step 4: Run TypeScript build and inventory tests**

Run: `cd extensions/vscode && npm run build && node --test test/syncInventory.test.js`

Expected: PASS with no failures.

- [ ] **Step 5: Commit the inventory protocol**

```bash
git add extensions/vscode/src/syncInventory.ts extensions/vscode/test/syncInventory.test.js
git commit -m "feat: parse task sync inventory"
```

---

### Task 5: Build Pure Project-Grouped Task Picker State

**Files:**
- Create: `extensions/vscode/src/syncTaskPicker.ts`
- Create: `extensions/vscode/test/syncTaskPicker.test.js`

**Interfaces:**
- Consumes: `SyncInventory` from Task 4 and stored technical thread ids.
- Produces: `TaskPickerItem`, `buildTaskPickerItems`, `reduceTaskSelection`, and `selectedPickerItemIds` without importing `vscode`.

- [ ] **Step 1: Write failing hierarchy, partial-selection, and unavailable tests**

```javascript
test("project rows toggle current child tasks without selecting future ids", () => {
  const items = buildTaskPickerItems(inventory(), []);
  const project = items.find((item) => item.kind === "project" && item.projectKey === "repo-a");
  const selected = reduceTaskSelection([], project, true);
  assert.deepEqual(selected, ["thread-1", "thread-2"]);
  assert.deepEqual(selectedPickerItemIds(items, selected), ["project:repo-a", "task:thread-1", "task:thread-2"]);
});

test("a filtered project toggle still uses every snapshot child", () => {
  const items = buildTaskPickerItems(inventory(), []);
  const project = items.find((item) => item.id === "project:repo-a");
  const visibleRows = items.filter((item) => item.label.includes("Persona"));

  assert.equal(visibleRows.some((item) => item.threadId === "thread-2"), false);
  assert.deepEqual(reduceTaskSelection([], project, true), ["thread-1", "thread-2"]);
});

test("partial task selection leaves the project row unselected", () => {
  const items = buildTaskPickerItems(inventory(), ["thread-1"]);
  assert.deepEqual(selectedPickerItemIds(items, ["thread-1"]), ["task:thread-1"]);
});

test("missing stored ids remain selected under unavailable tasks", () => {
  const items = buildTaskPickerItems(inventory(), ["missing-thread"]);
  const separator = items.find((item) => item.kind === "separator");
  const missing = items.find((item) => item.kind === "unavailable");
  assert.equal(separator.label, "Unavailable selected tasks");
  assert.equal(missing.threadId, "missing-thread");
  assert.deepEqual(selectedPickerItemIds(items, ["missing-thread"]), ["unavailable:missing-thread"]);
});
```

Also test project deselection, deterministic item order, availability labels (`This device`, `Sync folder`, `Both`), and an empty initial selection.

- [ ] **Step 2: Run picker tests and verify module absence**

Run: `cd extensions/vscode && npm run build && node --test test/syncTaskPicker.test.js`

Expected: FAIL because `syncTaskPicker.ts` has not been created.

- [ ] **Step 3: Implement the pure picker reducer**

Use a discriminated item contract:

```typescript
export type TaskPickerItem = {
  id: string;
  kind: "project" | "task" | "unavailable" | "separator";
  label: string;
  description: string;
  detail: string;
  projectKey?: string;
  threadId?: string;
  childThreadIds: string[];
};
```

Use these exact signatures:

```typescript
export function buildTaskPickerItems(inventory: SyncInventory, storedThreadIds: unknown): TaskPickerItem[];
export function reduceTaskSelection(
  selectedThreadIds: unknown,
  changedItem: TaskPickerItem,
  selected: boolean,
): string[];
export function selectedPickerItemIds(items: TaskPickerItem[], selectedThreadIds: unknown): string[];
```

`buildTaskPickerItems` emits each project parent followed by its task children. When stored ids are absent from the inventory, append one `separator` row labeled `Unavailable selected tasks`, followed by unavailable rows sorted by thread id. Project details contain the exact current task count; task descriptions map availability to `This device`, `Sync folder`, or `Both`; task details include the technical thread id and formatted estimated size. `reduceTaskSelection` ignores separators, adds or removes all `childThreadIds` for project actions, and changes one `threadId` for task/unavailable actions. `selectedPickerItemIds` ignores separators and includes a project id only when every child id is selected. Normalize selected ids with stable case-sensitive deduplication.

- [ ] **Step 4: Run picker and inventory protocol tests**

Run: `cd extensions/vscode && npm run build && node --test test/syncInventory.test.js test/syncTaskPicker.test.js`

Expected: PASS with no failures.

- [ ] **Step 5: Commit picker state**

```bash
git add extensions/vscode/src/syncTaskPicker.ts extensions/vscode/test/syncTaskPicker.test.js
git commit -m "feat: model project grouped task selection"
```

---

### Task 6: Replace Legacy Extension Selection State And Copy

**Files:**
- Modify: `extensions/vscode/src/core.ts`
- Modify: `extensions/vscode/src/syncProtocol.ts`
- Modify: `extensions/vscode/test/core.test.js`
- Modify: `extensions/vscode/test/syncProtocol.test.js`
- Modify: `extensions/vscode/package.json`

**Interfaces:**
- Consumes: exact selected thread ids and selection schema version `2`.
- Produces: simplified `SyncSettings`, `SYNC_SELECTION_VERSION_STATE_KEY`, `readSyncSelectionVersionState`, `hasValidSyncSelection`, task-only sync arguments, task menu actions, and setup-required labels.

- [ ] **Step 1: Rewrite core and argument tests for the breaking contract**

Assert normalization gates ids on version `2`:

```javascript
assert.deepEqual(normalizeSyncSettings({
  enabled: true,
  dir: " D:/Sync ",
  selectionVersion: 2,
  threadIds: [" t1 ", "t1", "t2"],
}), {
  enabled: true,
  dir: "D:/Sync",
  selectionVersion: 2,
  threadIds: ["t1", "t2"],
  autoPull: true,
  autoPush: true,
});
assert.deepEqual(normalizeSyncSettings({ threadIds: ["legacy"] }).threadIds, []);
```

Update menu expectations to one `changeTasks` action, control labels to `Sync: 1 task` and `Sync: N tasks`, invalid version to `Sync: Setup required`, package commands to `codexUsage.selectSyncTasks`, and all sync setting descriptions to task wording.

Update sync protocol tests so options contain only `syncDir`, `threadIds`, and `autoTransitions`, and output never contains `--project-key`.

Add direct validity assertions:

```javascript
assert.equal(hasValidSyncSelection(normalizeSyncSettings({
  enabled: true,
  dir: "D:/Sync",
  selectionVersion: 2,
  threadIds: ["t1"],
})), true);
assert.equal(hasValidSyncSelection(normalizeSyncSettings({
  enabled: true,
  dir: "D:/Sync",
  selectionVersion: 1,
  threadIds: ["legacy"],
})), false);
```

- [ ] **Step 2: Run core and protocol tests and verify legacy fields fail**

Run: `cd extensions/vscode && npm run build && node --test test/core.test.js test/syncProtocol.test.js`

Expected: FAIL while `projectKeys`, `conversationMode`, and old command actions remain.

- [ ] **Step 3: Simplify settings, labels, commands, and sync arguments**

Use this active contract:

```typescript
export const SYNC_SELECTION_VERSION = 2;
export const SYNC_SELECTION_VERSION_STATE_KEY = "syncSelectionVersion";

export type SyncSettings = {
  enabled: boolean;
  dir: string;
  selectionVersion: number;
  threadIds: string[];
  autoPull: boolean;
  autoPush: boolean;
};

export function normalizeSyncSettings(value: unknown): SyncSettings {
  const input = isRecord(value) ? value : {};
  const selectionVersion = input.selectionVersion === SYNC_SELECTION_VERSION ? SYNC_SELECTION_VERSION : 0;
  return {
    enabled: input.enabled === true,
    dir: typeof input.dir === "string" ? input.dir.trim() : "",
    selectionVersion,
    threadIds: selectionVersion === SYNC_SELECTION_VERSION ? normalizeThreadIds(input.threadIds) : [],
    autoPull: input.autoPull !== false,
    autoPush: input.autoPush !== false,
  };
}

export function readSyncSelectionVersionState(state?: GlobalStateReader): number {
  return state?.get(SYNC_SELECTION_VERSION_STATE_KEY, 0) === SYNC_SELECTION_VERSION
    ? SYNC_SELECTION_VERSION
    : 0;
}

export function hasValidSyncSelection(settings: SyncSettings): boolean {
  const normalized = normalizeSyncSettings(settings);
  return Boolean(
    normalized.dir &&
    normalized.selectionVersion === SYNC_SELECTION_VERSION &&
    normalized.threadIds.length > 0
  );
}
```

Change `WebviewControlState.sync` to `Pick<SyncSettings, "enabled" | "dir" | "selectionVersion" | "threadIds">`. Replace the sync menu union with:

```typescript
export type SyncMenuAction =
  | "syncNow"
  | "syncStatus"
  | "pauseSync"
  | "resumeSync"
  | "changeFolder"
  | "changeTasks"
  | "clearSync"
  | "openSyncFolder";
```

Make `syncControlLabel` use this exact precedence: missing folder, invalid selection version, or zero ids -> `Sync: Setup required`; valid but disabled -> `Sync: Off`; one id -> `Sync: 1 task`; otherwise `Sync: N tasks`. Make `syncMenuQuickPickItems` expose one `$(checklist) Change Tasks` row with `N selected`; replace all selectable-item copy with task/tasks. Update `syncFailureRequiresNotification` to match `no Codex tasks are selected` rather than conversations.

Remove sync project and conversation-mode types, keys, readers, project/conversation Quick Pick helpers, and menu actions. Keep `PROJECT_KEYS_STATE_KEY`, dashboard `projectKeys`, report project filtering, and the independent dashboard project picker unchanged. Rename the package command contribution and activation event to `codexUsage.selectSyncTasks`. Build routine sync args from `threadIds` only:

```typescript
export type SyncCommandOptions = {
  syncDir: string;
  threadIds: string[];
  autoTransitions: boolean;
};

function buildSyncArgs(command: "run" | "status", options: SyncCommandOptions): string[] {
  const args = ["sync", command, "--json"];
  const syncDir = options.syncDir.trim();
  if (syncDir) args.push("--sync-dir", syncDir);
  if (options.autoTransitions === false) args.push("--no-auto-transitions");
  appendSelectors(args, "--thread-id", options.threadIds);
  return args;
}
```

- [ ] **Step 4: Run all extension unit tests**

Run: `cd extensions/vscode && npm test`

Expected: PASS with no failures.

- [ ] **Step 5: Commit the breaking state and copy update**

```bash
git add extensions/vscode/src/core.ts extensions/vscode/src/syncProtocol.ts extensions/vscode/test/core.test.js extensions/vscode/test/syncProtocol.test.js extensions/vscode/package.json
git commit -m "refactor: select exact Codex tasks for sync"
```

---

### Task 7: Wire One Hierarchical Quick Pick Into The Extension

**Files:**
- Modify: `extensions/vscode/src/extension.ts`
- Modify: `extensions/vscode/test/syncProcess.test.js`

**Interfaces:**
- Consumes: `buildSyncInventoryArgs`, `parseSyncInventory`, and the picker functions from Tasks 4-5.
- Produces: one `selectSyncTaskSettings` flow, transactional setup writes, `Change Tasks`, and routine sync/status with exact ids.

- [ ] **Step 1: Add failing source-contract tests**

Replace legacy orchestration assertions with checks that:

```javascript
assert.doesNotMatch(extensionSource, /selectSyncProjectSettings|selectSyncThreadSettings|conversationMode/);
assert.match(extensionSource, /buildSyncInventoryArgs/);
assert.match(extensionSource, /parseSyncInventory/);
assert.match(extensionSource, /createQuickPick/);
assert.match(extensionSource, /SYNC_SELECTION_VERSION_STATE_KEY/);
assert.match(extensionSource, /selectionVersion:\s*readSyncSelectionVersionState/);
assert.doesNotMatch(extensionSource, /projectKeys:\s*settings\.sync/);
```

Assert `runSyncNow` and status return before `runCodexUsage` when `hasValidSyncSelection(settings.sync)` is false. Assert the inventory subprocess and all `globalState.update(...)` calls are ordered after folder choice, and that folder/id/version writes occur only after the `if (!selectedThreadIds) return false` guard. Assert the source contains exactly one registration for `codexUsage.selectSyncTasks` and none for the removed sync picker commands.

Keep the existing assertion that routine `runSyncNow` launches exactly one `sync run` process and does not invoke inventory first.

- [ ] **Step 2: Run orchestration tests and verify old functions fail the contract**

Run: `cd extensions/vscode && npm run build && node --test test/syncProcess.test.js`

Expected: FAIL because the two legacy picker functions and dynamic mode still exist.

- [ ] **Step 3: Implement one inventory-backed Quick Pick**

Replace the state-writing `selectSyncFolder(context)` with a read-only `pickSyncFolder(): Promise<string | undefined>`. Add the exact orchestration boundary:

```typescript
async function selectSyncTaskSettings(
  context: vscode.ExtensionContext,
  syncDir: string,
  options: { enableAfterAccept?: boolean; refreshDashboard?: boolean } = {},
): Promise<boolean>;
```

Inside it, read current settings, resolve the bundled executable, construct `env = buildCodexUsageEnv(context.globalStorageUri.fsPath)`, and do not write global/config state before the task picker accepts. The task flow is:

```typescript
const result = await runCodexUsage(
  executablePath,
  buildSyncInventoryArgs({ syncDir, autoTransitions: settings.projectTransitions.autoDetect }),
  env,
);
const inventory = parseSyncInventory(result.stdout);
const rows = buildTaskPickerItems(inventory, settings.sync.threadIds);
const selectedThreadIds = await showSyncTaskPicker(rows, settings.sync.threadIds);
if (!selectedThreadIds) {
  return false;
}
await context.globalState.update(SYNC_DIR_STATE_KEY, syncDir);
await context.globalState.update(SYNC_THREAD_IDS_STATE_KEY, selectedThreadIds);
await context.globalState.update(SYNC_SELECTION_VERSION_STATE_KEY, SYNC_SELECTION_VERSION);
if (options.enableAfterAccept) {
  await vscode.workspace.getConfiguration("codexUsage").update(
    "sync.enabled",
    true,
    vscode.ConfigurationTarget.Global,
  );
}
```

Use this adapter boundary so the pure picker module never imports `vscode`:

```typescript
type TaskQuickPickItem = vscode.QuickPickItem & { task?: TaskPickerItem };

function showSyncTaskPicker(
  rows: TaskPickerItem[],
  initialThreadIds: string[],
): Promise<string[] | undefined>;
```

Implement `showSyncTaskPicker` with `vscode.window.createQuickPick<TaskQuickPickItem>()`, `canSelectMany = true`, and one adapter item per row. Map pure separator rows to `{ label, kind: vscode.QuickPickItemKind.Separator }`; map selectable rows to `{ label, description, detail, task: row }` without spreading the pure row's string `kind` into VS Code's numeric `kind` field. Maintain `selectedThreadIds` and the previous selected row-id set separately. For every user event, ignore adapter rows without `task`, compute removed row ids and apply `reduceTaskSelection(..., false)` first, then added row ids with `true`. Replace `selectedItems` from `selectedPickerItemIds(rows, selectedThreadIds)` under a reentrancy guard and update the previous row-id set to that canonical selection. Project toggles therefore use the full `childThreadIds` snapshot even while VS Code hides rows under text filtering.

Use one settled `finish(value)` closure that disposes the picker listeners and picker exactly once. On accept with zero ids, keep the picker open and set its title to `Select at least one Codex task`; otherwise resolve a fresh id array. On hide/cancel, resolve `undefined`. The only settings writes remain after a non-`undefined` result in `selectSyncTaskSettings`, so cancel and inventory exceptions are transactional.

Log every inventory issue with ``output.appendLine(`[sync inventory:${issue.code}] ${issue.message}${issue.threadId ? ` (${issue.threadId})` : ""}`)`` and show one warning, `Some remote task files could not be identified and were omitted from selection. See Codex Usage output for details.`, when `inventory.issues.length > 0`.

Wire callers exactly as follows:

- `configureSync`: keep or pick a candidate folder, then call `selectSyncTaskSettings(context, candidate, { enableAfterAccept: true })`.
- `codexUsage.selectSyncTasks` and the `changeTasks` menu action: use the configured folder, or route to `configureSync` when it is absent.
- `changeSyncFolder`: pick a candidate and call `selectSyncTaskSettings(context, candidate)`; cancellation preserves the old folder and ids.
- `openSyncFolder`: when no folder is configured, run `configureSync`, reread settings, and open only the committed folder.

Register only `codexUsage.selectSyncTasks`. Clear setup in this order: write selection version `0`, then remove folder and ids. Remove legacy project/thread/conversation-mode migration while preserving the existing deprecated folder migration only.

Build `readSettings(...).sync` with `selectionVersion: readSyncSelectionVersionState(context?.globalState)` and no sync project/mode reads. Before status, manual sync, resume, or automatic sync can spawn a process, require `hasValidSyncSelection`; otherwise show `Sync setup is required. Select a folder and at least one Codex task.` and route interactive commands to setup. Update run, status, status tooltip, progress title, warnings, clear confirmation, and menu handling to task wording and exact `threadIds` only.

- [ ] **Step 4: Run all extension tests**

Run: `cd extensions/vscode && npm test`

Expected: PASS with no failures, including inventory, picker, core, protocol, process, and package metadata tests.

- [ ] **Step 5: Commit extension orchestration**

```bash
git add extensions/vscode/src/extension.ts extensions/vscode/test/syncProcess.test.js
git commit -m "feat: configure sync with one task picker"
```

---

### Task 8: Document, Package, And Verify The Breaking Release

**Files:**
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `CHANGELOG.md`
- Modify: `extensions/vscode/CHANGELOG.md`
- Modify: `scripts/smoke-test-packaged-sync.py`
- Modify: `tests/test_github_actions_workflow.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`

**Interfaces:**
- Consumes: the completed exact-task inventory and selection flow.
- Produces: version `0.1.34`, packaged inventory smoke coverage, current docs, and full verification evidence.

- [ ] **Step 1: Add failing packaged-smoke and documentation assertions**

Extend `tests/test_github_actions_workflow.py` to require the packaged smoke script to invoke `sync inventory` as well as `sync run`. Extend package metadata tests to require version `0.1.34` and task wording.

In the smoke script, replace `_run_sync` with this general JSON runner, then keep `_run_sync` as a thin selector wrapper:

```python
def _run_json(
    executable: Path,
    codex_home: Path,
    args: list[str],
) -> dict[str, object]:
    environment = os.environ.copy()
    environment["CODEX_HOME"] = str(codex_home)
    completed = subprocess.run(
        [str(executable), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=environment,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Packaged command exited with code {completed.returncode}.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            "Packaged command stdout was not one JSON object.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        ) from error
    if not isinstance(result, dict):
        raise RuntimeError(f"Packaged command returned non-object JSON: {result!r}")
    return result

def _run_sync(executable: Path, codex_home: Path, sync_dir: Path) -> dict[str, object]:
    return _run_json(
        executable,
        codex_home,
        ["sync", "run", "--sync-dir", str(sync_dir), "--thread-id", THREAD_ID, "--json"],
    )
```

Assert local-only before push and remote-only on the empty target after push:

```python
local_inventory = _run_json(executable, source_home, ["sync", "inventory", "--sync-dir", str(sync_dir), "--json"])
assert local_inventory["projects"][0]["tasks"][0]["availability"] == "local"

remote_inventory = _run_json(executable, target_home, ["sync", "inventory", "--sync-dir", str(sync_dir), "--json"])
assert remote_inventory["projects"][0]["tasks"][0]["availability"] == "remote"
```

- [ ] **Step 2: Run smoke-structure tests and verify they fail**

Run: `uv run pytest tests/test_github_actions_workflow.py -q`

Expected: FAIL because the smoke script does not invoke `sync inventory`.

- [ ] **Step 3: Run extension metadata tests and verify they fail**

Run: `cd extensions/vscode && npm test`

Expected: FAIL because extension metadata and tests still reflect `0.1.33` and legacy conversation wording.

- [ ] **Step 4: Update docs, changelogs, smoke test, and versions**

Document:

- one project-grouped Select Tasks picker;
- project rows as current-task shortcuts only;
- remote-only task discovery;
- future tasks remaining excluded;
- the intentional one-time **Setup required** state after upgrade;
- no required remote cleanup or republish;
- user-facing task versus technical thread-id terminology.

Add `0.1.34 - Exact Task Sync Selection` to both changelogs. Update Python and extension versions to `0.1.34`, then refresh lockfiles:

```bash
uv lock
npm --prefix extensions/vscode install --package-lock-only
```

Update the packaged smoke output to report `inventory=local,remote pushed=1 pulled=1 format_version=2`.

- [ ] **Step 5: Run complete local verification**

Run each command separately and require a zero exit code:

```bash
uv run pytest -q
uv lock --check
uvx ruff check src/codex_usage/sync src/codex_usage/sync_cli.py tests/test_sync_selection_inventory.py tests/test_sync_cli.py tests/test_sync_inventory.py tests/test_sync_runner.py tests/test_sync_runner_bookkeeping.py scripts/smoke-test-packaged-sync.py
npm --prefix extensions/vscode test
npm --prefix extensions/vscode run package:vsix:mac
git diff --check
git status --short
```

Expected: all Python and extension tests pass; the changed Python scope passes Ruff; the macOS arm64 package and packaged inventory/sync smoke pass; `git diff --check` is silent; `git status --short` lists only intended release files before commit.

Windows x64 packaging cannot be proven on the Mac. After push, require the GitHub Actions Windows build and packaged smoke job to pass before publication.

- [ ] **Step 6: Commit release documentation and verification assets**

```bash
git add README.md extensions/vscode/README.md CHANGELOG.md extensions/vscode/CHANGELOG.md scripts/smoke-test-packaged-sync.py tests/test_github_actions_workflow.py pyproject.toml uv.lock extensions/vscode/package.json extensions/vscode/package-lock.json
git commit -m "chore: prepare 0.1.34 task sync release"
```

---

## Final Review Gate

Before merging:

1. Run `uv run pytest -q` and `cd extensions/vscode && npm test` again from the final commit.
2. Run `git diff main...HEAD --check` and inspect `git diff --stat main...HEAD` for unplanned files.
3. Confirm no active sync path accepts `--project-key`, `conversationMode`, or sync-specific project keys.
4. Confirm user-facing extension sync copy contains no selectable-item use of conversation or thread; technical diagnostics may still use `thread_id`.
5. Confirm a newly created task under an already represented project is absent until its thread id is selected.
6. Confirm malformed/legacy/unsafe/unreadable inventory tests prove no local state, remote index, or remote JSONL writes.
7. Confirm setup cancellation, inventory failure, and missing/obsolete selection versions cause no settings writes or routine sync subprocess.
8. Request code review with `superpowers:requesting-code-review` and resolve all blocking findings before merge.
