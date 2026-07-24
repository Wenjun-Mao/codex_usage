# Deterministic Codex Import Registration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every certified Task Transfer Import discoverable by Codex through its supported `app-server` read-repair path while constraining each Import and Export operation to exactly one Codex project.

**Architecture:** The Python transfer engine remains authoritative for project validation, preflight, atomic file operations, and completion certification. The VS Code extension adds a project-aware picker, defensive project-scope validation, official Codex executable discovery, and a bounded JSON-RPC client that registers imported task ids with one short-lived `codex app-server --stdio` process. Registration is a post-transfer boundary: it never rolls back certified files, never writes Codex SQLite directly, and is reflected explicitly in final user-facing results.

**Tech Stack:** Python 3.12, argparse, pytest, TypeScript 5.7, VS Code Extension API 1.90, Node.js child processes and streams, Node test runner, PyInstaller packaging, GitHub Actions.

## Global Constraints

- Supported release targets remain Windows x64 and macOS Apple Silicon; do not add Windows ARM64 or Intel macOS behavior.
- Use **project** in user-facing copy; retain `thread_id` only in technical CLI, JSON, and storage contracts.
- Each Import and Export handles exactly one project and any nonempty task subset from that project; Review Transfer Status remains cross-project and read-only.
- All eligible tasks in a chosen project start selected; switching projects clears the old task selection and selects all eligible tasks in the new project.
- The transfer folder remains multi-project across separate operations, and an operation must never delete tasks belonging to another project.
- Register all selected task ids after a fully completed Import, including unchanged tasks; after a partial certified Import, register only `result.pulled`.
- Never register after Export, Review, conflict, a pre-copy block, or unknown file completion.
- Never mutate Codex SQLite, reset Codex backfill state, invoke a model, send a prompt, start a turn, or run a filesystem-wide task scan.
- Spawn executables directly with fixed argument arrays and `shell: false`; retain bounded stdout/stderr and apply startup, request, and batch timeouts.
- Continue to the next executable candidate only after startup or initialization failure; never retry through another candidate after task requests create an ambiguous registration boundary.
- Registration failure leaves imported files intact and produces a partial-completion result with retry guidance.
- Keep every TypeScript and Python source file under 500 lines; extract focused modules instead of growing `taskTransfer.ts`, `syncProtocol.ts`, or `sync/runner.py`.
- Do not add runtime dependencies; use the Node and Python standard libraries already shipped by the project.
- Follow test-driven development: add each failing test first, observe the expected failure, implement the smallest durable contract, then rerun the focused suite.
- Before dispatching each subagent, state the selected model and reasoning-effort level in the parent task, as requested by the user.
- The approved design and durable decisions are in `docs/superpowers/specs/2026-07-23-post-import-codex-registration-design.md`, `docs/adr/0016-register-imported-tasks-through-codex.md`, and `docs/adr/0017-one-project-per-transfer-operation.md`.

## File Responsibility Map

| File | Responsibility |
| --- | --- |
| `src/codex_usage/sync/project_scope.py` | Pure Python one-project validation before destination resolution or writes. |
| `extensions/vscode/src/taskTransferProjectScope.ts` | Resolve and validate the selected extension project and its task ids. |
| `extensions/vscode/src/syncTaskPicker.ts` | Pure project-aware picker state and canonical selection reduction. |
| `extensions/vscode/src/codexExecutableDiscovery.ts` | Ordered, platform-specific official Codex executable candidates. |
| `extensions/vscode/src/codexAppServer.ts` | Bounded JSON-RPC lifecycle for targeted `thread/read` registration. |
| `extensions/vscode/src/codexRegistrationVscode.ts` | VS Code, filesystem, AppX, and process adapters for discovery and registration. |
| `extensions/vscode/src/taskTransferRegistration.ts` | Pure certification-to-registration id rules and registration summaries. |
| Existing controller/protocol/presentation files | Orchestration, CLI argv, progress, logging, and final user-facing outcome. |

---

### Task 1: Enforce One Project in the Python Transfer Core

**Files:**
- Create: `src/codex_usage/sync/project_scope.py`
- Create: `tests/test_sync_project_scope.py`
- Modify: `src/codex_usage/sync/runner.py`
- Modify: `src/codex_usage/sync_cli.py`
- Modify: `src/codex_usage/cli.py`
- Modify: `tests/test_sync_cli.py`
- Modify: `tests/test_cli.py`
- Modify: `tests/test_sync_inventory.py`
- Modify: `tests/test_sync_project_resolution_security.py`
- Modify: `tests/test_sync_runner.py`
- Modify: `tests/test_sync_runner_bookkeeping.py`
- Modify: `tests/test_sync_runner_reconciliation.py`
- Modify: `tests/test_sync_runner_validation.py`

**Interfaces:**
- Produces: `transfer_project_scope_issues(local: LocalInventory, remote: RemoteInventory, thread_ids: Iterable[str], expected_project_key: str) -> tuple[SyncIssue, ...]`, where the tuple contains zero or one issue.
- Changes: `pull_sync` gains the required keyword-only parameter `project_key: str` and continues to return `SyncRunResult`.
- Changes: `push_sync` gains the required keyword-only parameter `project_key: str` and continues to return `SyncRunResult`.
- CLI contract: `sync pull` and `sync push` require exactly one `--project-key`; `sync status` continues to reject that flag.

- [ ] **Step 1: Write pure project-scope tests**

Add `tests/test_sync_project_scope.py` with fixtures using `LocalInventory`, `RemoteInventory`, `ThreadInfo`, and `RemoteThreadEntry`. Cover:

```python
def test_one_matching_project_has_no_scope_issue() -> None:
    issues = transfer_project_scope_issues(
        local=local_inventory(task("task-1", project_key="repo-a")),
        remote=empty_remote_inventory(),
        thread_ids=("task-1",),
        expected_project_key="repo-a",
    )
    assert issues == ()


def test_cross_project_selection_is_rejected() -> None:
    issues = transfer_project_scope_issues(
        local=local_inventory(
            task("task-1", project_key="repo-a"),
            task("task-2", project_key="repo-b"),
        ),
        remote=empty_remote_inventory(),
        thread_ids=("task-1", "task-2"),
        expected_project_key="repo-a",
    )
    assert [issue.code for issue in issues] == ["cross_project_selection"]
    assert "one project at a time" in issues[0].message


def test_declared_project_must_match_selected_project() -> None:
    issues = transfer_project_scope_issues(
        local=local_inventory(task("task-1", project_key="repo-a")),
        remote=empty_remote_inventory(),
        thread_ids=("task-1",),
        expected_project_key="repo-b",
    )
    assert [issue.code for issue in issues] == ["project_scope_mismatch"]


def test_matching_local_and_remote_aliases_use_remote_picker_key() -> None:
    issues = transfer_project_scope_issues(
        local=local_inventory(
            task(
                "task-1",
                project_key="/old/path",
                project_aliases=("https://github.com/example/repo",),
            )
        ),
        remote=remote_inventory(
            remote_task(
                "task-1",
                project_key="https://github.com/example/repo",
                project_aliases=("/old/path",),
            )
        ),
        thread_ids=("task-1",),
        expected_project_key="https://github.com/example/repo",
    )
    assert issues == ()
```

- [ ] **Step 2: Run the new tests and verify the missing-module failure**

Run:

```bash
uv run pytest -q tests/test_sync_project_scope.py
```

Expected: collection fails because `codex_usage.sync.project_scope` does not exist.

- [ ] **Step 3: Implement the pure early scope validator**

Create `src/codex_usage/sync/project_scope.py` with this contract and behavior:

```python
from __future__ import annotations

from collections.abc import Iterable

from codex_usage.sync.inventory import normalize_selected_thread_ids
from codex_usage.sync.models import (
    LocalInventory,
    RemoteInventory,
    RemoteThreadEntry,
    SyncIssue,
)
from codex_usage.threads import ThreadInfo


def transfer_project_scope_issues(
    local: LocalInventory,
    remote: RemoteInventory,
    thread_ids: Iterable[str],
    expected_project_key: str,
) -> tuple[SyncIssue, ...]:
    expected = expected_project_key.strip()
    selected = normalize_selected_thread_ids(thread_ids)
    project_keys = {
        project_key
        for thread_id in selected
        if (
            project_key := _selected_project_key(
                local.threads.get(thread_id),
                remote.index.threads.get(thread_id),
            )
        )
    }
    if len(project_keys) > 1:
        return (
            SyncIssue(
                "cross_project_selection",
                "Import and Export handle one project at a time. Choose tasks from one project.",
            ),
        )
    actual = next(iter(project_keys), "")
    if not expected or not actual or expected != actual:
        return (
            SyncIssue(
                "project_scope_mismatch",
                "The selected tasks do not match the project chosen for this transfer.",
            ),
        )
    return ()


def _selected_project_key(
    local_task: ThreadInfo | None,
    remote_task: RemoteThreadEntry | None,
) -> str:
    if local_task is None:
        return remote_task.project_key if remote_task is not None else ""
    if remote_task is None:
        return local_task.project_key
    local_identities = {local_task.project_key, *local_task.project_aliases}
    remote_identities = {remote_task.project_key, *remote_task.project_aliases}
    if local_identities.intersection(remote_identities):
        return remote_task.project_key
    return local_task.project_key
```

This mirrors the inventory grouping rule, so the explicit project key from the picker is checked against the same identity the user saw.

- [ ] **Step 4: Run the pure tests and verify they pass**

Run:

```bash
uv run pytest -q tests/test_sync_project_scope.py
```

Expected: all project-scope tests pass.

- [ ] **Step 5: Add failing runner tests for pre-resolution blocking**

Extend `tests/test_sync_project_resolution_security.py` with a two-project selected batch. Inject a project-resolution candidate that would be observable if resolution ran, then assert:

```python
assert result.outcome == "issue"
assert [issue.code for issue in result.issues] == ["cross_project_selection"]
assert not sync_dir.exists()
assert destination_prompt_or_resolution_calls == []
```

Add a second test passing `project_key="repo-b"` for a single `repo-a` task and assert `project_scope_mismatch` before any local or remote write.

Add a successful single-project Export test whose remote index already contains an unrelated `repo-b` task. Assert the selected `repo-a` entry changes while the unrelated index entry and JSONL bytes remain exactly unchanged.

- [ ] **Step 6: Thread the expected project key through the runner**

Change `pull_sync`, `push_sync`, and `_run_direction` to require `project_key`. In `_run_direction`, load and materialize selected remote entries, call `transfer_project_scope_issues`, and build a diagnostic plan with `project_resolution=None` when scope is invalid. Return `SyncRunResult.blocked_with_issues(plan, scope_issues, timings=timer.finish())` before destination resolution, snapshot validation, conflict backups, or directional file writes.

Keep `sync_status` on the existing cross-project `_prepare_sync_plan` path. Extract the directional preparation into a small helper if needed so `runner.py` remains under 500 lines:

```python
def _prepare_direction_plan(
    local: LocalInventory,
    store: RemoteStore,
    sync_dir: Path,
    thread_ids: Iterable[str],
    project_resolution: ProjectResolutionRequest,
    project_key: str,
) -> tuple[RemoteInventory, SyncPlan, tuple[SyncIssue, ...]]:
    remote = store.load_inventory()
    selected = normalize_selected_thread_ids(thread_ids)
    remote = store.materialize_selected(remote, selected)
    scope_issues = transfer_project_scope_issues(
        local,
        remote,
        selected,
        project_key,
    )
    plan = build_sync_plan(
        local,
        remote,
        selected,
        sync_dir,
        project_resolution=None if scope_issues else project_resolution,
    )
    return promote_matching_local_metadata(remote, local, plan), plan, scope_issues
```

- [ ] **Step 7: Add the required transfer CLI flag**

Split parser helpers so common selection options remain available to status while transfer-only options require a project:

```python
def add_sync_execution_options(parser: argparse.ArgumentParser) -> None:
    add_sync_common_options(parser)
    parser.add_argument("--thread-id", action="append", help="Technical thread id for a selected Codex task. Repeat as needed.")
    parser.add_argument("--project-binding", action="append", nargs=2, metavar=("PROJECT_KEY", "PATH"))
    parser.add_argument("--confirm-unverified-project", action="append")


def add_sync_transfer_options(parser: argparse.ArgumentParser) -> None:
    add_sync_execution_options(parser)
    parser.add_argument(
        "--project-key",
        required=True,
        help="Exact project key for this one-project transfer operation.",
    )
```

Use `add_sync_transfer_options` for pull and push, retain `add_sync_execution_options` for status, and pass `args.project_key` into `pull_sync` and `push_sync`.

- [ ] **Step 8: Update CLI tests**

Change the old parameterized rejection test so:

- pull and push fail when `--project-key` is omitted;
- pull and push accept one `--project-key`;
- status still rejects `--project-key`;
- handler tests assert `project_key` is passed to the directional runner;
- every end-to-end pull/push invocation supplies the exact fixture project key.
- every direct `pull_sync`/`push_sync` test in the runner, inventory, bookkeeping, reconciliation, validation, and project-resolution suites supplies the project key represented by its selected fixture.

Run:

```bash
uv run pytest -q tests/test_sync_project_scope.py tests/test_sync_cli.py tests/test_cli.py tests/test_sync_inventory.py tests/test_sync_project_resolution_security.py tests/test_sync_runner.py tests/test_sync_runner_bookkeeping.py tests/test_sync_runner_reconciliation.py tests/test_sync_runner_validation.py
```

Expected: all focused Python tests pass.

- [ ] **Step 9: Commit the Python contract**

```bash
git add src/codex_usage/sync/project_scope.py src/codex_usage/sync/runner.py src/codex_usage/sync_cli.py src/codex_usage/cli.py tests/test_sync_project_scope.py tests/test_sync_cli.py tests/test_cli.py tests/test_sync_inventory.py tests/test_sync_project_resolution_security.py tests/test_sync_runner.py tests/test_sync_runner_bookkeeping.py tests/test_sync_runner_reconciliation.py tests/test_sync_runner_validation.py
git commit -m "feat: enforce one-project task transfers"
```

---

### Task 2: Build the Project-Aware Combined Picker

**Files:**
- Modify: `extensions/vscode/src/syncTaskPicker.ts`
- Modify: `extensions/vscode/src/taskTransferVscodePicker.ts`
- Modify: `extensions/vscode/src/taskTransferOperation.ts`
- Modify: `extensions/vscode/src/taskTransfer.ts`
- Modify: `extensions/vscode/test/syncTaskPicker.test.js`
- Create: `extensions/vscode/test/taskTransferVscodePicker.test.js`
- Modify: `extensions/vscode/test/taskTransfer.test.js`
- Modify: `extensions/vscode/test/taskTransferFixtures.js`

**Interfaces:**
- Produces: `TaskPickerSelection = { projectKey?: string; threadIds: string[] }`
- Produces: `TaskPickerSelectionState = { activeProjectKey?: string; selectedThreadIds: string[] }`
- Produces: `activateTaskPickerProject(rows, projectKey) -> TaskPickerSelectionState`
- Produces: `visibleTaskPickerItems(rows, state, operation) -> TaskPickerItem[]`
- Changes: `chooseTasks(operation, rows) -> Promise<TaskPickerSelection | undefined>`; every picker invocation constructs fresh state and accepts no persisted initial selection.

- [ ] **Step 1: Replace selection tests with the approved one-project behavior**

In `syncTaskPicker.test.js`, retain operation filtering tests and replace “starts unselected” transfer assertions with:

```javascript
test("activating an import project selects all eligible tasks in that project", () => {
  const rows = buildTaskPickerItems(inventory(), "import");
  const state = activateTaskPickerProject(rows, "repo-a");

  assert.deepEqual(state, {
    activeProjectKey: "repo-a",
    selectedThreadIds: ["thread-2"],
  });
  assert.deepEqual(
    visibleTaskPickerItems(rows, state, "import").map((item) => item.id),
    ["project:repo-a", "task:thread-2", "project:repo-b"],
  );
});


test("switching projects discards the old subset and selects the new project", () => {
  const rows = buildTaskPickerItems(inventory(), "review");
  const first = reduceTransferTaskSelection(
    activateTaskPickerProject(rows, "repo-a"),
    rows.find((row) => row.id === "task:thread-1"),
    false,
  );
  const second = activateTaskPickerProject(rows, "repo-b");

  assert.deepEqual(first.selectedThreadIds, ["thread-2"]);
  assert.deepEqual(second, {
    activeProjectKey: "repo-b",
    selectedThreadIds: ["thread-3"],
  });
});


test("review retains fresh cross-project selection", () => {
  const rows = buildTaskPickerItems(inventory(), "review");
  const state = initialTaskPickerSelection("review");
  assert.equal(state.activeProjectKey, undefined);
  assert.deepEqual(state.selectedThreadIds, []);
  assert.deepEqual(visibleTaskPickerItems(rows, state, "review"), rows);
});
```

- [ ] **Step 2: Run picker tests and verify they fail on missing contracts**

Run:

```bash
cd extensions/vscode
npm run build
node --test test/syncTaskPicker.test.js
```

Expected: build or tests fail because the project-aware picker state functions do not exist.

- [ ] **Step 3: Implement the pure picker state**

Add these exported contracts to `syncTaskPicker.ts` while retaining `buildTaskPickerItems`:

```typescript
export type TaskPickerSelection = {
  projectKey?: string;
  threadIds: string[];
};

export type TaskPickerSelectionState = {
  activeProjectKey?: string;
  selectedThreadIds: string[];
};

export function initialTaskPickerSelection(
  operation: TransferOperation,
): TaskPickerSelectionState {
  return operation === "review"
    ? { selectedThreadIds: [] }
    : { activeProjectKey: undefined, selectedThreadIds: [] };
}

export function activateTaskPickerProject(
  rows: TaskPickerItem[],
  projectKey: string,
): TaskPickerSelectionState {
  const project = rows.find(
    (row) => row.kind === "project" && row.projectKey === projectKey,
  );
  return {
    activeProjectKey: projectKey,
    selectedThreadIds: project ? Array.from(project.childThreadIds) : [],
  };
}

export function visibleTaskPickerItems(
  rows: TaskPickerItem[],
  state: TaskPickerSelectionState,
  operation: TransferOperation,
): TaskPickerItem[] {
  if (operation === "review") {
    return rows;
  }
  return rows.filter(
    (row) => row.kind === "project" || row.projectKey === state.activeProjectKey,
  );
}
```

Add a transfer reducer that activates project rows, permits task deselection only inside the active project, and never carries task ids between projects. Preserve the existing cross-project reducer for Review.

The active project row must remain visibly marked with description `Selected project` even after the user deselects one of its tasks. Task checkbox state and active-project state are separate: a partially selected project is still the operation's one chosen project.

- [ ] **Step 4: Add a fake QuickPick integration test**

Create `taskTransferVscodePicker.test.js` with an EventEmitter-backed fake implementing `items`, `selectedItems`, `onDidChangeSelection`, `onDidAccept`, `onDidHide`, `show`, and `dispose`. Test these observable UI contracts:

- Import title is `Import Tasks: Choose One Project`.
- Import placeholder is `One project per import. All tasks start selected.`
- Initially only project rows are visible.
- Choosing a project keeps the picker open, reveals only that project’s tasks, and selects every task.
- The active project row displays `Selected project`, including after a child task is deselected.
- Deselecting one task changes only that project’s subset.
- Choosing another project clears the previous subset and selects all new tasks.
- Accept resolves `{ projectKey: "repo-b", threadIds: ["thread-3"] }`.
- Review title and detail explicitly say it can review tasks across projects.

- [ ] **Step 5: Wire the VS Code picker to canonical state**

Update `showTaskTransferPicker` to drive `quickPick.items` and `quickPick.selectedItems` from the pure state after every event. Use exact transfer copy:

```typescript
const TRANSFER_PICKER_COPY = {
  import: {
    title: "Import Tasks: Choose One Project",
    placeholder: "One project per import. All tasks start selected.",
  },
  export: {
    title: "Export Tasks: Choose One Project",
    placeholder: "One project per export. All tasks start selected.",
  },
  review: {
    title: "Review Tasks Across Projects",
    placeholder: "Select any tasks to compare without copying files.",
  },
} as const;
```

On accept, transfer operations require an active project and a nonempty task subset. Review requires only a nonempty task subset.

- [ ] **Step 6: Thread `TaskPickerSelection` through the selection port**

Change `TaskTransferSelectionPort.chooseTasks`, `chooseFreshTaskTransferSelection`, `TaskTransferPort.chooseTasks`, the fake port, and controller call sites to use `TaskPickerSelection`. Remove the `initialThreadIds` parameter entirely because task selections are never persisted. At this task boundary, the controller may read `selection.threadIds`; Task 3 adds independent project validation.

- [ ] **Step 7: Run picker and controller tests**

Run:

```bash
cd extensions/vscode
npm run build
node --test test/syncTaskPicker.test.js test/taskTransferVscodePicker.test.js test/taskTransfer.test.js
```

Expected: all focused picker/controller tests pass.

- [ ] **Step 8: Commit the combined picker**

```bash
git add extensions/vscode/src/syncTaskPicker.ts extensions/vscode/src/taskTransferVscodePicker.ts extensions/vscode/src/taskTransferOperation.ts extensions/vscode/src/taskTransfer.ts extensions/vscode/test/syncTaskPicker.test.js extensions/vscode/test/taskTransferVscodePicker.test.js extensions/vscode/test/taskTransfer.test.js extensions/vscode/test/taskTransferFixtures.js
git commit -m "feat: choose one project per task transfer"
```

---

### Task 3: Carry and Defend the Project Contract Through the Extension

**Files:**
- Create: `extensions/vscode/src/taskTransferProjectScope.ts`
- Create: `extensions/vscode/test/taskTransferProjectScope.test.js`
- Modify: `extensions/vscode/src/syncProtocol.ts`
- Modify: `extensions/vscode/src/taskTransfer.ts`
- Modify: `extensions/vscode/src/taskTransferVscode.ts`
- Modify: `extensions/vscode/test/syncProtocol.test.js`
- Modify: `extensions/vscode/test/taskTransfer.test.js`
- Modify: `extensions/vscode/test/taskTransferVscode.test.js`
- Modify: `extensions/vscode/test/taskTransferFixtures.js`

**Interfaces:**
- Produces: `SelectedTransferProject = { project: SyncInventoryProject; projectKey: string; projectLabel: string; threadIds: string[] }`
- Produces: `requireSelectedTransferProject(inventory, operation, selection) -> SelectedTransferProject`
- Changes: transfer execution requests include required `projectKey` and `projectLabel`.
- Changes: pull/push argv include `--project-key`; status argv does not.

- [ ] **Step 1: Add failing defensive scope tests**

Create `taskTransferProjectScope.test.js` covering one valid subset, a task id outside the declared project, two-project ids, a missing project, and an empty subset. The primary assertions are:

```javascript
assert.deepEqual(
  requireSelectedTransferProject(source, "import", {
    projectKey: "repo-a",
    threadIds: ["thread-2"],
  }),
  {
    project: source.projects[0],
    projectKey: "repo-a",
    projectLabel: "Repo A",
    threadIds: ["thread-2"],
  },
);

assert.throws(
  () => requireSelectedTransferProject(source, "import", {
    projectKey: "repo-a",
    threadIds: ["thread-2", "thread-3"],
  }),
  /one project at a time/i,
);
```

- [ ] **Step 2: Implement focused extension project validation**

Create `taskTransferProjectScope.ts`. Filter inventory by operation before validating, require the picker’s project key to exist, require every selected id to belong to that project, deduplicate ids while preserving order, and throw `TransferProjectScopeError` with user-safe one-project wording.

Move the existing single-project destination-binding routine from `taskTransfer.ts` into this module:

```typescript
export async function resolveImportProjectBindings(
  selected: SelectedTransferProject,
  port: Pick<
    TaskTransferPort,
    "chooseProjectRoot" | "confirmUnverifiedProject"
  >,
): Promise<ProjectBinding[] | undefined>
```

It prompts at most once because `selected.project` is exactly one project. This extraction keeps `taskTransfer.ts` below 500 lines.

- [ ] **Step 3: Add failing protocol tests for the explicit key**

Update `syncProtocol.test.js` so pull/push options include `projectKey: "repo-a"` and assert:

```javascript
assert.deepEqual(buildSyncPullArgs(options), [
  "sync", "pull", "--json",
  "--sync-dir", "/sync",
  "--project-key", "repo-a",
  "--thread-id", "thread-1",
]);
assert.doesNotMatch(buildSyncStatusArgs(statusOptions).join(" "), /--project-key/);
```

Also assert blank transfer project keys throw before process launch.

- [ ] **Step 4: Split status and transfer command option types**

In `syncProtocol.ts`, define:

```typescript
export type SyncCommandOptions = {
  syncDir: string;
  threadIds: string[];
  autoTransitions: boolean;
  candidateProjectRoots: string[];
  projectBindings: ProjectBinding[];
};

export type SyncTransferCommandOptions = SyncCommandOptions & {
  projectKey: string;
};
```

Make `buildSyncPullArgs` and `buildSyncPushArgs` accept `SyncTransferCommandOptions`, validate and append one `--project-key`, and leave `buildSyncStatusArgs` on `SyncCommandOptions`.

- [ ] **Step 5: Validate scope before project resolution in the controller**

After the picker resolves, call `requireSelectedTransferProject` before `resolveImportProjectBindings` or `port.execute`. Add `projectKey` and `projectLabel` to `TransferExecutionRequest`; keep Review on a separate `TransferReviewRequest` without a one-project key.

Use project-specific progress:

```typescript
const direction = operation === "import" ? "into" : "from";
const verb = operation === "import" ? "Importing" : "Exporting";
const title = `${verb} ${request.threadIds.length} ${taskWord(request.threadIds.length)} ${direction} ${request.projectLabel}`;
```

The destination dialog title becomes `Choose Destination Folder for ${project.projectLabel}` with placeholder `Choose the matching local project folder`.

- [ ] **Step 6: Test controller and adapter enforcement**

Add controller tests proving:

- cross-project selection is rejected before destination prompts and execution;
- the execution request contains the exact picker project key and label;
- one import destination prompt is made at most once;
- Review accepts selected ids across multiple projects and omits `--project-key`;
- progress titles name the project and task count.

Run:

```bash
cd extensions/vscode
npm run build
node --test test/taskTransferProjectScope.test.js test/syncProtocol.test.js test/taskTransfer.test.js test/taskTransferVscode.test.js
```

Expected: all focused extension project-contract tests pass.

- [ ] **Step 7: Commit the extension project contract**

```bash
git add extensions/vscode/src/taskTransferProjectScope.ts extensions/vscode/src/syncProtocol.ts extensions/vscode/src/taskTransfer.ts extensions/vscode/src/taskTransferVscode.ts extensions/vscode/test/taskTransferProjectScope.test.js extensions/vscode/test/syncProtocol.test.js extensions/vscode/test/taskTransfer.test.js extensions/vscode/test/taskTransferVscode.test.js extensions/vscode/test/taskTransferFixtures.js
git commit -m "feat: carry project scope through task transfer"
```

---

### Task 4: Discover Official Codex Executables Cross-Platform

**Files:**
- Create: `extensions/vscode/src/codexExecutableDiscovery.ts`
- Create: `extensions/vscode/test/codexExecutableDiscovery.test.js`

**Interfaces:**
- Produces: `CodexExecutableSource = "cli-override" | "official-vscode-extension" | "desktop-app" | "path"`
- Produces: `CodexExecutableCandidate = { executablePath: string; source: CodexExecutableSource }`
- Produces: `discoverCodexExecutableCandidates(context, probe) -> Promise<CodexExecutableCandidate[]>`

- [ ] **Step 1: Write platform-matrix discovery tests**

Use injected `pathExists`, `listDirectoryNames`, and `windowsAppxInstallLocation` functions. Cover:

- explicit `chatgpt.cliExecutable` first;
- official extension `bin/windows-x86_64/codex.exe`;
- official extension `bin/macos-aarch64/codex`;
- macOS `/Applications/ChatGPT.app/Contents/Resources/codex` and user-local app path;
- Windows `%LOCALAPPDATA%\OpenAI\Codex\bin\codex.exe`;
- Windows Store LocalCache path;
- immediate version/hash children beneath each per-user `bin`;
- AppX `<InstallLocation>\app\resources\codex.exe` after writable desktop copies;
- inaccessible AppX path skipped;
- `codex` or `codex.exe` last;
- native-path deduplication, case-insensitive on Windows;
- clear rejection of unsupported architecture/platform pairs.

- [ ] **Step 2: Run tests and verify the missing-module failure**

Run:

```bash
cd extensions/vscode
npm run build
node --test test/codexExecutableDiscovery.test.js
```

Expected: build fails because `codexExecutableDiscovery.ts` does not exist.

- [ ] **Step 3: Implement injectable discovery**

Use these exact public types:

```typescript
export type CodexExecutableDiscoveryContext = {
  platform: NodeJS.Platform;
  arch: string;
  env: NodeJS.ProcessEnv;
  homeDir: string;
  cliOverride?: string;
  officialExtensionPath?: string;
};

export type CodexExecutableDiscoveryProbe = {
  pathExists(candidate: string): Promise<boolean>;
  listDirectoryNames(directory: string): Promise<string[]>;
  windowsAppxInstallLocation(): Promise<string | undefined>;
};

export async function discoverCodexExecutableCandidates(
  context: CodexExecutableDiscoveryContext,
  probe: CodexExecutableDiscoveryProbe,
): Promise<CodexExecutableCandidate[]>
```

Use `path.win32` for Windows construction even when tests execute on macOS and `path.posix` for fixed app-bundle paths. Explicit override and PATH command candidates are attempted by the app-server client; fixed extension/desktop candidates are included only when `pathExists` succeeds. Sort immediate version/hash child names for deterministic order. Catch inaccessible directory and AppX probes and continue.

The macOS desktop candidates are exactly:

```text
/Applications/ChatGPT.app/Contents/Resources/codex
$HOME/Applications/ChatGPT.app/Contents/Resources/codex
```

The Windows candidate roots are exactly:

```text
%LOCALAPPDATA%\OpenAI\Codex\bin
%LOCALAPPDATA%\Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\OpenAI\Codex\bin
```

Check `codex.exe` directly under each root, then `codex.exe` under each immediate sorted child. Check `<AppX InstallLocation>\app\resources\codex.exe` after those user-writable candidates.

- [ ] **Step 4: Run discovery tests**

Run:

```bash
cd extensions/vscode
npm run build
node --test test/codexExecutableDiscovery.test.js
```

Expected: all discovery tests pass.

- [ ] **Step 5: Commit executable discovery**

```bash
git add extensions/vscode/src/codexExecutableDiscovery.ts extensions/vscode/test/codexExecutableDiscovery.test.js
git commit -m "feat: discover official Codex runtimes"
```

---

### Task 5: Implement the Bounded Codex App-Server Client

**Files:**
- Create: `extensions/vscode/src/codexAppServer.ts`
- Create: `extensions/vscode/test/codexAppServer.test.js`

**Interfaces:**
- Produces: `CodexRegistrationFailure = { threadId: string; message: string }`
- Produces: `CodexTaskRegistrationResult = { attemptedThreadIds: string[]; registeredThreadIds: string[]; failures: CodexRegistrationFailure[]; executable?: CodexExecutableCandidate }`
- Produces: `registerCodexTasks(options) -> Promise<CodexTaskRegistrationResult>`

- [ ] **Step 1: Build a fake child-process harness**

In `codexAppServer.test.js`, use Node `PassThrough` streams and an EventEmitter-backed fake process. Capture direct spawn calls, stdin JSON lines, `kill`, and exit. The spawn assertion must be:

```javascript
assert.deepEqual(spawnCalls[0], {
  executablePath: "/official/codex",
  args: ["app-server", "--stdio"],
  options: { shell: false, stdio: ["pipe", "pipe", "pipe"] },
});
```

- [ ] **Step 2: Write protocol success tests**

Test one process registering two unique ids. Feed chunked and out-of-order responses and assert stdin contains:

```json
{"id":1,"method":"initialize","params":{"clientInfo":{"name":"codex-usage","version":"0.1.37"},"capabilities":{}}}
{"method":"initialized","params":{}}
{"id":2,"method":"thread/read","params":{"threadId":"task-a","includeTurns":false}}
{"id":3,"method":"thread/read","params":{"threadId":"task-b","includeTurns":false}}
```

Assert duplicate/blank ids are removed before requests and matching `result.thread.id` values populate `registeredThreadIds`.

- [ ] **Step 3: Write failure-boundary tests**

Cover:

- fallback after spawn failure;
- fallback after initialization error or timeout;
- no fallback after any `thread/read` request is sent;
- per-task JSON-RPC error;
- mismatched returned thread id;
- malformed stdout;
- chunked JSON lines;
- stderr warnings retained separately and capped;
- early exit;
- request timeout and whole-batch timeout;
- child termination and listener cleanup;
- no method containing `turn`, `prompt`, `model`, `message/send`, or `thread/list`.

- [ ] **Step 4: Run tests and verify the missing-module failure**

Run:

```bash
cd extensions/vscode
npm run build
node --test test/codexAppServer.test.js
```

Expected: build fails because `codexAppServer.ts` does not exist.

- [ ] **Step 5: Implement JSON-line framing and request correlation**

Use these public options:

```typescript
export type CodexAppServerOptions = {
  candidates: CodexExecutableCandidate[];
  threadIds: readonly string[];
  extensionVersion: string;
  spawnProcess?: CodexAppServerSpawner;
  startupTimeoutMs?: number;
  requestTimeoutMs?: number;
  batchTimeoutMs?: number;
  retainedDiagnosticBytes?: number;
};
```

Implementation requirements:

1. Accept only unique task ids that are nonempty and exactly equal to their own trim; report invalid ids as failures without sending requests.
2. Try candidates in order.
3. Spawn directly with `["app-server", "--stdio"]`, `shell: false`, and piped stdio.
4. Buffer stdout by newline and parse only complete JSON objects.
5. Send `initialize`; accept only its matching result before sending `initialized`.
6. Send all targeted `thread/read` requests with unique numeric ids.
7. Correlate out-of-order responses by id.
8. Mark success only when `result.thread.id` equals the requested task id.
9. Convert explicit task errors to task failures without retrying them.
10. Ignore well-formed server notifications that do not claim a pending response id.
11. On malformed protocol, early exit, or timeout after task dispatch, fail unresolved ids and do not try another executable.
12. End stdin, terminate the child, clear timers, and remove listeners once the batch settles.
13. Cap retained stdout/stderr diagnostics by bytes and never include rollout contents in the result.

- [ ] **Step 6: Run app-server tests**

Run:

```bash
cd extensions/vscode
npm run build
node --test test/codexAppServer.test.js
```

Expected: all app-server tests pass with no leaked timer or child-process handles.

- [ ] **Step 7: Commit the protocol client**

```bash
git add extensions/vscode/src/codexAppServer.ts extensions/vscode/test/codexAppServer.test.js
git commit -m "feat: register tasks through Codex app server"
```

---

### Task 6: Add the VS Code Registration Adapter

**Files:**
- Create: `extensions/vscode/src/codexRegistrationVscode.ts`
- Create: `extensions/vscode/test/codexRegistrationVscode.test.js`
- Modify: `extensions/vscode/src/extension.ts`
- Modify: `extensions/vscode/src/taskTransferVscode.ts`
- Modify: `extensions/vscode/test/taskTransferVscode.test.js`

**Interfaces:**
- Produces: `createCodexTaskRegistrar(options) -> (threadIds: readonly string[]) => Promise<CodexTaskRegistrationResult>`
- Adds: `TaskTransferVscodeDependencies.registerImportedTasks(threadIds)`.

- [ ] **Step 1: Add failing adapter tests with a fake VS Code API**

Test that the adapter:

- reads `vscode.workspace.getConfiguration("chatgpt").get("cliExecutable")`;
- reads `vscode.extensions.getExtension("openai.chatgpt")?.extensionPath`;
- never calls `activate()` on the official extension;
- supplies `process.platform`, `process.arch`, environment, and home directory to discovery;
- checks filesystem candidates without widening permissions;
- queries AppX only on Windows;
- invokes the app-server client with the extension version;
- returns structured failure when no candidate initializes.

- [ ] **Step 2: Run adapter tests and verify the missing-module failure**

Run:

```bash
cd extensions/vscode
npm run build
node --test test/codexRegistrationVscode.test.js
```

Expected: build fails because `codexRegistrationVscode.ts` does not exist.

- [ ] **Step 3: Implement VS Code and operating-system probes**

Create the adapter with dependency injection for tests. Use `fs.stat` and `fs.readdir({ withFileTypes: true })`; treat inaccessible paths as absent. Query AppX with a direct `powershell.exe` argument array and no shell:

```typescript
[
  "-NoProfile",
  "-NonInteractive",
  "-Command",
  "(Get-AppxPackage -Name OpenAI.Codex | Select-Object -First 1 -ExpandProperty InstallLocation)",
]
```

Trim stdout and return `undefined` on command absence, access denial, nonzero exit, or empty output. Do not log or expose user directory contents beyond candidate paths.

- [ ] **Step 4: Wire the registrar at extension activation**

In `extension.ts`, construct one registrar with:

```typescript
const registerImportedTasks = createCodexTaskRegistrar({
  extensionVersion: context.extension.packageJSON.version,
});
```

Pass it into `createTaskTransferVscodePort`. Keep all discovery and process logic out of `extension.ts` so the file remains below 500 lines.

- [ ] **Step 5: Test the port wiring**

Update `taskTransferVscode.test.js` to assert `port.registerImportedTasks(["task-a"])` delegates once and returns the exact structured result. Run:

```bash
cd extensions/vscode
npm run build
node --test test/codexRegistrationVscode.test.js test/taskTransferVscode.test.js
```

Expected: all adapter and port tests pass.

- [ ] **Step 6: Commit the VS Code adapter**

```bash
git add extensions/vscode/src/codexRegistrationVscode.ts extensions/vscode/src/extension.ts extensions/vscode/src/taskTransferVscode.ts extensions/vscode/test/codexRegistrationVscode.test.js extensions/vscode/test/taskTransferVscode.test.js
git commit -m "feat: connect imports to installed Codex runtimes"
```

---

### Task 7: Orchestrate Registration and Report the Combined Outcome

**Files:**
- Create: `extensions/vscode/src/taskTransferRegistration.ts`
- Create: `extensions/vscode/test/taskTransferRegistration.test.js`
- Modify: `extensions/vscode/src/taskTransfer.ts`
- Modify: `extensions/vscode/src/transferPresentation.ts`
- Modify: `extensions/vscode/test/taskTransfer.test.js`
- Modify: `extensions/vscode/test/transferPresentation.test.js`
- Modify: `extensions/vscode/test/taskTransferFixtures.js`

**Interfaces:**
- Produces: `certifiedImportThreadIds(result, selectedThreadIds) -> string[]`
- Produces: `TaskRegistrationSummary = { attempted: number; registered: number; failed: number }`
- Adds: `TaskTransferPort.registerImportedTasks(threadIds)`.
- Changes: `formatTransferResult(operation, result, context)` receives project and optional registration context.

- [ ] **Step 1: Write certification-rule tests**

Create `taskTransferRegistration.test.js` with exact cases:

```javascript
assert.deepEqual(
  certifiedImportThreadIds(completedImport, ["task-a", "task-b"]),
  ["task-a", "task-b"],
);
assert.deepEqual(
  certifiedImportThreadIds(partialImportWithPulledA, ["task-a", "task-b"]),
  ["task-a"],
);
assert.deepEqual(certifiedImportThreadIds(conflictResult, ["task-a"]), []);
assert.deepEqual(certifiedImportThreadIds(blockedIssueResult, ["task-a"]), []);
```

The completed result case must include `counts.unchanged > 0` to prove rerunning an unchanged Import heals tasks copied by older versions.

- [ ] **Step 2: Implement the pure certification boundary**

Create:

```typescript
export function certifiedImportThreadIds(
  result: SyncRunResult,
  selectedThreadIds: readonly string[],
): string[] {
  if (result.outcome === "completed") {
    return uniqueThreadIds(selectedThreadIds);
  }
  if (result.pulled.length > 0) {
    return uniqueThreadIds(result.pulled);
  }
  return [];
}
```

Keep normalization local to this module and preserve input order.

- [ ] **Step 3: Add failing controller orchestration tests**

Extend `taskTransferFixtures.js` with `registrationResultQueue`, `registrationCalls`, and `registerImportedTasks`. Add tests proving:

- completed Import registers every selected id, including unchanged ids;
- partial Import registers only `result.pulled`;
- Export, Review, conflict, and pre-copy issue do not register;
- registration is awaited before the final notification;
- the transient sequence contains `checking`, `importing` when emitted, `registering`, then clear;
- registration failures do not invoke a second transfer or alter the transfer result;
- each failed task id is logged without rollout content or private paths.

- [ ] **Step 4: Orchestrate post-import registration**

After `port.execute("import", request)` returns, compute certified ids. If nonempty:

```typescript
this.port.setTransientStatus("registering");
const registration = await this.port.registerImportedTasks(certifiedThreadIds);
for (const failure of registration.failures) {
  this.port.log(
    `[task registration] ${failure.threadId}: ${failure.message}`,
  );
}
```

Await registration before result formatting. Do not throw registration failures into the transfer catch path; pass them as a distinct result boundary.

- [ ] **Step 5: Add exact combined-result presentation tests**

Update `transferPresentation.test.js` for these messages:

```text
Imported 2 tasks into Letta-Open-ADE. Open or restart Codex to display them.
No file changes were needed for 2 tasks in Letta-Open-ADE. Registered them with Codex. Open or restart Codex to display them.
Imported files for 2 tasks into Letta-Open-ADE, but Codex registered only 1. The files are safe. Retry Import after resolving Codex availability.
Exported 2 tasks from Letta-Open-ADE to the transfer folder.
```

Also cover singular grammar, zero registered, partial certified imports, and blocked/conflict project-specific copy. Keep the full-success notification exactly aligned with the approved open/restart wording; document VS Code reload as the equivalent refresh in both READMEs.

- [ ] **Step 6: Update transient and final presentation**

Add `"registering"` to `TransferTransientStatus` with label `Registering imported tasks`. Change `formatTransferResult` to:

```typescript
export type TransferResultContext = {
  projectLabel: string;
  registration?: CodexTaskRegistrationResult;
};

export function formatTransferResult(
  operation: "import" | "export",
  result: SyncRunResult,
  context: TransferResultContext,
): TransferResultMessage
```

Rules:

- full transfer plus full registration is `info`;
- no-op transfer plus full registration explicitly says no file changes were needed;
- any registration failure is `warning`, says files are safe, gives registered/failed counts, and tells the user to retry Import;
- at least one registered task adds open/restart guidance;
- Export never mentions registration and names the project plus transfer folder;
- transfer blocks and conflicts retain their existing safety meaning while naming the project.

- [ ] **Step 7: Run orchestration and presentation tests**

Run:

```bash
cd extensions/vscode
npm run build
node --test test/taskTransferRegistration.test.js test/taskTransfer.test.js test/transferPresentation.test.js
```

Expected: all registration-boundary and wording tests pass.

- [ ] **Step 8: Commit registration orchestration**

```bash
git add extensions/vscode/src/taskTransferRegistration.ts extensions/vscode/src/taskTransfer.ts extensions/vscode/src/transferPresentation.ts extensions/vscode/test/taskTransferRegistration.test.js extensions/vscode/test/taskTransfer.test.js extensions/vscode/test/transferPresentation.test.js extensions/vscode/test/taskTransferFixtures.js
git commit -m "feat: report post-import Codex registration"
```

---

### Task 8: Extend Native Packaging Smoke Gates

**Files:**
- Create: `scripts/fake-codex-app-server`
- Create: `scripts/smoke-test-codex-registration.js`
- Modify: `scripts/smoke-test-packaged-sync.py`
- Modify: `extensions/vscode/package.json`
- Modify: `.github/workflows/package-vsix.yml`
- Modify: `extensions/vscode/test/core.test.js`

**Interfaces:**
- Adds npm script: `test:registration-smoke`
- Keeps the existing packaged Python round trip and adds one-project CLI enforcement.
- Adds a platform-neutral fake app-server smoke run executed on both native release runners.

- [ ] **Step 1: Make the packaged Python smoke pass its project key**

Change `_run_sync` in `smoke-test-packaged-sync.py` to include:

```python
"--project-key",
PROJECT_KEY,
```

Add a smoke assertion that a second selected task under `UNRELATED_PROJECT_KEY` returns `cross_project_selection` and leaves both local and remote task files unchanged.

- [ ] **Step 2: Add a real-process fake app-server fixture**

Create executable JavaScript fixture `scripts/fake-codex-app-server` that:

- reads newline-delimited JSON from stdin;
- returns an initialize result for method `initialize`;
- returns `{ "thread": { "id": params.threadId } }` for `thread/read`;
- exits nonzero for any turn, prompt, model, or list method;
- writes a harmless warning to stderr to exercise stream separation.

Create `smoke-test-codex-registration.js` that imports compiled `out/codexAppServer.js`, copies the fixture into a temporary working directory as the Node script named `app-server`, changes `process.cwd()` to that directory for the registration call, restores the original working directory in `finally`, and uses `process.execPath` as the candidate executable. Because the production client always invokes `<candidate> app-server --stdio`, Node executes the fixture through the same fixed argv contract on Windows and macOS.

Assert two ids register through one process and no failures occur.

- [ ] **Step 3: Add the npm and CI smoke commands**

Add:

```json
"test:registration-smoke": "npm run build && node ../../scripts/smoke-test-codex-registration.js"
```

In both `package-windows` and `package-macos` jobs, run `npm run test:registration-smoke` after dependency installation and before VSIX packaging. Extend `core.test.js` to assert both release jobs contain the gate and the script uses no shell invocation.

- [ ] **Step 4: Run local smoke gates**

Run:

```bash
cd extensions/vscode
npm run test:registration-smoke
npm run package:vsix:mac
```

Expected:

- registration smoke reports two registered task ids;
- packaged Task Transfer smoke reports `inventory=local,remote pushed=1 pulled=1 status=up-to-date format_version=3`;
- `output/releases/codex-usage-dashboard-darwin-arm64.vsix` exists.

- [ ] **Step 5: Commit packaging coverage**

```bash
git add scripts/fake-codex-app-server scripts/smoke-test-codex-registration.js scripts/smoke-test-packaged-sync.py extensions/vscode/package.json .github/workflows/package-vsix.yml extensions/vscode/test/core.test.js
git commit -m "test: gate packaged Codex task registration"
```

---

### Task 9: Update Documentation and Run Full Verification

**Files:**
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `CHANGELOG.md`
- Modify: `extensions/vscode/CHANGELOG.md`
- Verify only: `docs/adr/README.md`
- Verify only: `docs/adr/0016-register-imported-tasks-through-codex.md`
- Verify only: `docs/adr/0017-one-project-per-transfer-operation.md`

**Interfaces:**
- Public documentation describes one-project transfers and post-import registration without implying model use or direct private-state writes.
- `Unreleased` changelog entries capture the behavior without a version bump.

- [ ] **Step 1: Update the root and Marketplace READMEs**

Replace fresh-empty-selection wording with:

```text
Each Import or Export handles one Codex project. Choose a project, then all eligible
tasks in it start selected; deselect any tasks you do not want to transfer. The
transfer folder can retain tasks from many projects across separate operations.
Review Transfer Status remains cross-project and does not copy files.
```

Document:

- the destination project checkout must already exist;
- Import asks Codex’s installed official runtime to register certified tasks after copying;
- registration sends targeted reads only and does not invoke a model;
- Codex Usage never writes Codex SQLite or private project registries directly;
- imported files remain safe when registration fails and rerunning Import retries registration;
- open or restart Codex, or reload VS Code, after successful registration to refresh a cached task list;
- Windows x64 and macOS Apple Silicon discovery sources and current package limits.

Add troubleshooting heading `Imported files exist but tasks are not visible` with steps to verify an official Codex runtime is installed, check the Codex Usage output, retry Import, and refresh the client.

- [ ] **Step 2: Add dated Unreleased bullets to both changelogs**

Under `Unreleased`, add bullets covering:

- one-project Import/Export picker with all eligible tasks initially selected;
- defensive one-project CLI/core enforcement;
- deterministic post-import registration through official Codex `app-server`;
- safe partial-completion and retry behavior;
- refresh guidance and no-model/no-direct-SQLite guarantees.

Do not change `0.1.37` in `pyproject.toml` or `extensions/vscode/package.json`; release versioning remains a separate release step.

- [ ] **Step 3: Run the full Python suite**

Run:

```bash
uv run pytest -q
```

Expected: the complete Python suite passes.

- [ ] **Step 4: Run the full extension suite**

Run:

```bash
cd extensions/vscode
npm test
```

Expected: TypeScript builds and every `test/*.test.js` test passes, including the source-file size guard.

- [ ] **Step 5: Run native smoke and repository hygiene checks**

Run:

```bash
cd extensions/vscode
npm run test:registration-smoke
npm run package:vsix:mac
cd ../..
git diff --check
git status --short
```

Expected:

- both local smoke gates pass;
- the macOS Apple Silicon VSIX is produced;
- `git diff --check` prints nothing;
- only intentional source, test, workflow, and documentation files are modified; generated `output/` content remains ignored.

- [ ] **Step 6: Review durable-contract consistency**

Confirm:

- ADR 0016 states Codex owns state repair and direct SQLite writes remain forbidden;
- ADR 0017 states one project per Import/Export and cross-project Review;
- no README still says every transfer starts with an empty task selection;
- no source or docs claim the extension never asks Codex to update its own state;
- no user-facing copy uses conversation or thread where task is intended;
- every plan step names concrete files, commands, behavior, and expected results without deferred implementation placeholders.

- [ ] **Step 7: Commit documentation and final verified state**

```bash
git add README.md extensions/vscode/README.md CHANGELOG.md extensions/vscode/CHANGELOG.md
git commit -m "docs: explain deterministic one-project task transfer"
```

- [ ] **Step 8: Request final code review before integration**

Use `superpowers:requesting-code-review` against the complete branch. Require the reviewer to check:

- project scope is enforced before destination resolution and writes;
- registration id certification matches full and partial Import semantics;
- candidate fallback never crosses an ambiguous task-request boundary;
- no direct Codex SQLite mutation exists;
- Windows and macOS candidate ordering matches the approved design;
- result copy cannot claim full success after any registration failure;
- full test and native smoke outputs are attached to the review.

Address every accepted finding with a focused failing test, implementation fix, rerun, and commit before merging or releasing.
