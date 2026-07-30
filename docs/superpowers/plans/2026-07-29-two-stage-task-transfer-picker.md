# Two-Stage Task Transfer Picker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the combined project/task multi-select UI with a two-stage Import and Export picker that chooses exactly one project, starts task selection empty, and supports native Back navigation.

**Architecture:** Keep operation-filtered project and task row construction in the pure `syncTaskPicker.ts` module. Drive one reusable VS Code `QuickPick` through project and task stages in `taskTransferVscodePicker.ts`, while retaining the existing cross-project Review picker and the controller/core one-project validation boundary.

**Tech Stack:** TypeScript 5.7, VS Code extension API 1.90, Node.js test runner, Python 3.12, pytest, npm, uv.

## Global Constraints

- Every Import and Export accepts exactly one project and one or more eligible tasks from that project.
- The project is navigation context, never a selected task and never part of the selected count.
- Project selection and task selection use separate screens in one picker flow.
- Every task screen starts with zero selected tasks.
- Search sees only projects on the project screen and only the chosen project's tasks on the task screen.
- Native Back navigation discards task selection and returns to project choice.
- Review Transfer Status remains cross-project and read-only.
- Use **task** in user-facing copy and retain `threadId` only for technical identifiers.
- Preserve Windows x64 and macOS Apple Silicon support without adding dependencies.
- Do not optimize inventory discovery or loading in this change.
- Follow test-driven development and keep the existing Python-core one-project guard.

---

## File Map

- `extensions/vscode/src/syncTaskPicker.ts`: owns pure picker rows, staged visibility, and transfer task-selection state.
- `extensions/vscode/src/taskTransferVscodePicker.ts`: owns VS Code project/task navigation, Back handling, acceptance, and Review adaptation.
- `extensions/vscode/test/syncTaskPicker.test.js`: proves the pure staged-selection contract.
- `extensions/vscode/test/taskTransferVscodePicker.test.js`: simulates project/task navigation and Windows selection events.
- `extensions/vscode/test/taskTransferVscode.test.js`: guards approved picker copy at the adapter boundary.
- `extensions/vscode/test/syncProcess.test.js`: replaces obsolete combined-picker source assertions with staged-picker guardrails.
- `README.md` and `extensions/vscode/README.md`: explain the two-stage one-project workflow.
- `CHANGELOG.md` and `extensions/vscode/CHANGELOG.md`: record the release behavior.
- `pyproject.toml`, `uv.lock`, `extensions/vscode/package.json`, and `extensions/vscode/package-lock.json`: keep release version `0.1.40` aligned.
- `tests/test_github_actions_workflow.py`: guards release versions and current Task Transfer documentation.

---

### Task 1: Encode The Staged Selection Contract

**Files:**
- Modify: `extensions/vscode/src/syncTaskPicker.ts`
- Test: `extensions/vscode/test/syncTaskPicker.test.js`

**Interfaces:**
- Consumes: `TaskPickerItem[]` from `buildTaskPickerItems(...)`.
- Produces: `activateTaskPickerProject(rows, projectKey) -> TaskPickerSelectionState` with an empty `selectedThreadIds`.
- Produces: `visibleTaskPickerItems(rows, state, operation) -> TaskPickerItem[]`, returning project-only or active-project-task-only rows for Import and Export.
- Produces: `selectedTaskPickerItemIds(rows, state, operation) -> string[]`, never returning a project id for Import or Export.
- Preserves: `reduceTaskSelection(...)` and `selectedPickerItemIds(...)` for the cross-project Review picker.

- [ ] **Step 1: Replace the old all-selected expectations with failing staged-state tests**

Add `selectedTaskPickerItemIds` to the test imports and replace the activation and switching tests with:

```javascript
test("transfer starts with project rows only and activating a project selects no tasks", () => {
  const rows = buildTaskPickerItems(inventory(), "import");
  const initial = initialTaskPickerSelection("import");

  assert.deepEqual(
    visibleTaskPickerItems(rows, initial, "import").map((item) => item.id),
    ["project:repo-a", "project:repo-b"],
  );

  const active = activateTaskPickerProject(rows, "repo-a");
  assert.deepEqual(active, {
    activeProjectKey: "repo-a",
    selectedThreadIds: [],
  });
  assert.deepEqual(
    visibleTaskPickerItems(rows, active, "import").map((item) => item.id),
    ["task:thread-2"],
  );
  assert.deepEqual(selectedTaskPickerItemIds(rows, active, "import"), []);
});

test("switching projects discards task state and never selects the project row", () => {
  const rows = buildTaskPickerItems(inventory(), "review");
  const repoA = activateTaskPickerProject(rows, "repo-a");
  const selectedRepoA = reduceTransferTaskSelection(
    repoA,
    rows.find((row) => row.id === "task:thread-1"),
    true,
  );
  const repoB = activateTaskPickerProject(rows, "repo-b");

  assert.deepEqual(selectedRepoA.selectedThreadIds, ["thread-1"]);
  assert.deepEqual(selectedTaskPickerItemIds(rows, selectedRepoA, "export"), [
    "task:thread-1",
  ]);
  assert.deepEqual(repoB, {
    activeProjectKey: "repo-b",
    selectedThreadIds: [],
  });
});

test("a task outside the active project cannot enter transfer selection", () => {
  const rows = buildTaskPickerItems(inventory(), "review");
  const active = activateTaskPickerProject(rows, "repo-a");
  const foreignTask = rows.find((row) => row.id === "task:thread-3");

  assert.deepEqual(
    reduceTransferTaskSelection(active, foreignTask, true),
    active,
  );
});
```

- [ ] **Step 2: Run the focused tests and verify the old contract fails**

Run:

```bash
cd extensions/vscode
npm run build
node --test test/syncTaskPicker.test.js
```

Expected: FAIL because activation still selects all child tasks and transfer visibility still mixes project and task rows.

- [ ] **Step 3: Implement project-only and task-only staged visibility**

Change the transfer helpers to this behavior:

```typescript
export function activateTaskPickerProject(
  rows: TaskPickerItem[],
  projectKey: string,
): TaskPickerSelectionState {
  const project = rows.find(
    (row) => row.kind === "project" && row.projectKey === projectKey,
  );
  return project
    ? { activeProjectKey: projectKey, selectedThreadIds: [] }
    : { activeProjectKey: undefined, selectedThreadIds: [] };
}

export function visibleTaskPickerItems(
  rows: TaskPickerItem[],
  state: TaskPickerSelectionState,
  operation: TransferOperation,
): TaskPickerItem[] {
  if (operation === "review") {
    return rows;
  }
  if (state.activeProjectKey === undefined) {
    return rows.filter((row) => row.kind === "project");
  }
  return rows.filter(
    (row) => row.kind === "task" && row.projectKey === state.activeProjectKey,
  );
}
```

Keep task toggling restricted to `state.activeProjectKey`. Change project activation inside `reduceTransferTaskSelection(...)` to use the empty selection returned above. Change `selectedTaskPickerItemIds(...)` so its Import and Export path returns selected task row ids only:

```typescript
const selected = new Set(state.selectedThreadIds);
return visibleTaskPickerItems(rows, state, operation).flatMap((row) =>
  row.kind === "task" && row.threadId && selected.has(row.threadId)
    ? [row.id]
    : [],
);
```

Remove `activateTaskPickerProjectForRow(...)` once no caller needs the old all-child behavior.

- [ ] **Step 4: Run the pure picker tests**

Run:

```bash
cd extensions/vscode
npm run build
node --test test/syncTaskPicker.test.js
```

Expected: all `syncTaskPicker` tests PASS.

- [ ] **Step 5: Commit the pure contract**

```bash
git add extensions/vscode/src/syncTaskPicker.ts extensions/vscode/test/syncTaskPicker.test.js
git commit -m "refactor: separate project and task picker state"
```

---

### Task 2: Build The Two-Stage VS Code Picker

**Files:**
- Modify: `extensions/vscode/src/taskTransferVscodePicker.ts`
- Modify: `extensions/vscode/test/taskTransferVscodePicker.test.js`
- Modify: `extensions/vscode/test/taskTransferVscode.test.js`
- Modify: `extensions/vscode/test/syncProcess.test.js`

**Interfaces:**
- Consumes: staged pure helpers from Task 1.
- Produces: unchanged public signature `showTaskTransferPicker(operation, rows) -> Promise<TaskPickerSelection | undefined>`.
- Produces: one reusable Import/Export `QuickPick` with project and task stages.
- Preserves: cross-project Review output `{ threadIds: string[] }`.

- [ ] **Step 1: Expand the fake QuickPick and write failing two-stage interaction tests**

Add native Back support and active-row behavior to `FakeQuickPick`:

```javascript
onDidTriggerButton(listener) {
  this.on("button", listener);
  return { dispose: () => this.off("button", listener) };
}

focus(id) {
  this.activeItems = this.items.filter((item) => item.task?.id === id);
}

triggerBack() {
  this.emit("button", fakeVscode.QuickInputButtons.Back);
}
```

Initialize `activeItems`, `buttons`, and `value` in the constructor. Add:

```javascript
QuickInputButtons: { Back: { id: "back" } },
```

Replace the combined Import test with:

```javascript
test("import uses separate project and task screens with an empty task selection", async () => {
  quickPicks.length = 0;
  const result = showTaskTransferPicker("import", buildTaskPickerItems(inventory(), "import"));
  const quickPick = quickPicks.at(-1);

  assert.equal(quickPick.title, "Import Tasks: Choose a Project");
  assert.equal(quickPick.placeholder, "Choose one project to import tasks into.");
  assert.equal(quickPick.canSelectMany, false);
  assert.deepEqual(quickPick.items.map((item) => item.task?.id), [
    "project:repo-a",
    "project:repo-b",
  ]);

  quickPick.focus("project:repo-a");
  quickPick.accept();

  assert.equal(quickPick.title, "Import Tasks: Select Tasks for Repo A");
  assert.equal(quickPick.placeholder, "Search tasks in Repo A.");
  assert.equal(quickPick.canSelectMany, true);
  assert.deepEqual(quickPick.items.map((item) => item.task?.id), [
    "task:thread-2",
    "task:thread-4",
  ]);
  assert.deepEqual(quickPick.selectedItems, []);

  quickPick.select(["task:thread-4"]);
  quickPick.accept();
  assert.deepEqual(await result, {
    projectKey: "repo-a",
    threadIds: ["thread-4"],
  });
});
```

Add a Back test that selects a task, sets `quickPick.value = "follow-up"`, triggers Back, and verifies:

```javascript
assert.equal(quickPick.title, "Import Tasks: Choose a Project");
assert.equal(quickPick.canSelectMany, false);
assert.equal(quickPick.value, "");
assert.deepEqual(quickPick.selectedItems, []);
assert.deepEqual(quickPick.items.map((item) => item.task?.id), [
  "project:repo-a",
  "project:repo-b",
]);
```

Re-enter `repo-a` and assert task selection is still empty. Add an empty-accept test expecting the title `Select at least one Codex task to import`. Update the delayed-event test to emit a stale empty `selection` event after a real task selection and verify acceptance still returns the real selected task.

- [ ] **Step 2: Run the adapter test and verify it fails**

Run:

```bash
cd extensions/vscode
npm run build
node --test test/taskTransferVscodePicker.test.js
```

Expected: FAIL because the current adapter has one multi-select screen, no Back button, and preselects child tasks.

- [ ] **Step 3: Split scoped transfer navigation from Review selection**

Keep the exported entrypoint and route by operation:

```typescript
type ScopedTransferOperation = Exclude<TransferOperation, "review">;

export function showTaskTransferPicker(
  operation: TransferOperation,
  rows: TaskPickerItem[],
): Promise<TaskPickerSelection | undefined> {
  return operation === "review"
    ? showReviewTaskPicker(rows)
    : showScopedTaskTransferPicker(operation, rows);
}
```

Use exact scoped copy:

```typescript
const SCOPED_TRANSFER_PICKER_COPY = {
  import: {
    projectTitle: "Import Tasks: Choose a Project",
    projectPlaceholder: "Choose one project to import tasks into.",
    taskTitle: (projectLabel: string) => `Import Tasks: Select Tasks for ${projectLabel}`,
    taskPlaceholder: (projectLabel: string) => `Search tasks in ${projectLabel}.`,
    emptyTitle: "Select at least one Codex task to import",
  },
  export: {
    projectTitle: "Export Tasks: Choose a Project",
    projectPlaceholder: "Choose one project to export tasks from.",
    taskTitle: (projectLabel: string) => `Export Tasks: Select Tasks from ${projectLabel}`,
    taskPlaceholder: (projectLabel: string) => `Search tasks in ${projectLabel}.`,
    emptyTitle: "Select at least one Codex task to export",
  },
} as const;
```

Map pure rows without changing their identity:

```typescript
function toQuickPickItem(row: TaskPickerItem): TaskQuickPickItem {
  return {
    label: row.label,
    description: row.description,
    detail: row.detail,
    task: row,
  };
}
```

Implement
`showScopedTaskTransferPicker(operation: ScopedTransferOperation, rows:
TaskPickerItem[]): Promise<TaskPickerSelection | undefined>` with one QuickPick.
Render it from `TaskPickerSelectionState`:

```typescript
const isTaskStep = state.activeProjectKey !== undefined;
const activeProject = rows.find(
  (row) => row.kind === "project" && row.projectKey === state.activeProjectKey,
);
const copy = SCOPED_TRANSFER_PICKER_COPY[operation];

quickPick.canSelectMany = isTaskStep;
quickPick.buttons = isTaskStep ? [vscode.QuickInputButtons.Back] : [];
quickPick.title = activeProject
  ? copy.taskTitle(activeProject.label)
  : copy.projectTitle;
quickPick.placeholder = activeProject
  ? copy.taskPlaceholder(activeProject.label)
  : copy.projectPlaceholder;
quickPick.value = "";
quickPick.items = visibleTaskPickerItems(rows, state, operation).map(toQuickPickItem);
quickPick.activeItems = [];
quickPick.selectedItems = [];
```

On project-stage acceptance, read `quickPick.activeItems[0]?.task`, require a project row, call `activateTaskPickerProject(...)`, and render the task stage. On task-stage acceptance, derive a fresh state by applying `reduceTransferTaskSelection(...)` only to `quickPick.selectedItems` task rows. Reject an empty result without closing. Resolve with:

```typescript
{
  projectKey: state.activeProjectKey,
  threadIds: [...acceptedState.selectedThreadIds],
}
```

Handle Back with `quickPick.onDidTriggerButton(...)`: reset via `initialTaskPickerSelection(operation)` and render the project stage. Do not persist previous task ids.

Do not programmatically mirror task selections after user events in the scoped picker. Read `quickPick.selectedItems` only on acceptance. This removes the event feedback loop that caused the Windows selection oscillation.

Move the existing canonical project-group selection behavior into `showReviewTaskPicker(...)`. Keep its title `Review Tasks Across Projects`, its current project-row shortcuts, and its settle-once disposal guard.

- [ ] **Step 4: Replace obsolete source-contract assertions**

In `taskTransferVscode.test.js`, assert the source contains:

```javascript
for (const title of [
  "Import Tasks: Choose a Project",
  "Export Tasks: Choose a Project",
  "Review Tasks Across Projects",
]) {
  assert.match(source, new RegExp(title));
}
assert.match(source, /QuickInputButtons\.Back/);
assert.match(source, /Select Tasks for/);
assert.match(source, /Select Tasks from/);
assert.doesNotMatch(source, /All tasks start selected|Selected project/);
```

In `syncProcess.test.js`, replace assertions for the combined selection
reconciler with assertions that the adapter contains
`quickPick.canSelectMany = isTaskStep`, `QuickInputButtons.Back`,
`visibleTaskPickerItems(...)`, the operation-specific empty-selection copy, and
the settle-once guard.

- [ ] **Step 5: Run all extension tests**

Run:

```bash
cd extensions/vscode
npm test
```

Expected: TypeScript build, contract typecheck, and every Node test PASS.

- [ ] **Step 6: Commit the VS Code workflow**

```bash
git add extensions/vscode/src/taskTransferVscodePicker.ts extensions/vscode/test/taskTransferVscodePicker.test.js extensions/vscode/test/taskTransferVscode.test.js extensions/vscode/test/syncProcess.test.js
git commit -m "fix: add two-stage task transfer picker"
```

---

### Task 3: Document The Workflow And Prepare Version 0.1.40

**Files:**
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `CHANGELOG.md`
- Modify: `extensions/vscode/CHANGELOG.md`
- Modify: `tests/test_github_actions_workflow.py`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`

**Interfaces:**
- Consumes: the approved two-stage behavior from Tasks 1 and 2.
- Produces: synchronized release version `0.1.40` and user-facing workflow documentation.

- [ ] **Step 1: Update the release and documentation tests first**

Rename the metadata test to `test_release_metadata_versions_are_0_1_40` and change all five expected versions to `0.1.40`.

In `test_task_transfer_documentation_describes_current_release_contract`, replace the all-selected assertions with:

```python
assert "first choose one project" in transfer
assert "no tasks are selected by default" in transfer
assert "search" in transfer and "chosen project" in transfer
assert "back" in transfer and "different project" in transfer
assert "repeat" in transfer and "another project" in transfer
```

- [ ] **Step 2: Run the focused Python tests and verify they fail**

Run:

```bash
uv run pytest tests/test_github_actions_workflow.py -q
```

Expected: FAIL because metadata remains `0.1.39` and both READMEs describe all tasks as initially selected.

- [ ] **Step 3: Rewrite both Task Transfer workflow paragraphs**

Use this contract in `README.md` and `extensions/vscode/README.md`, adapting only surrounding wording:

```text
Each Import or Export handles one Codex project. First choose one project, then
choose one or more eligible tasks from that project. No tasks are selected by
default. Search on the task screen is limited to the chosen project. Use Back to
discard the current task choices and choose a different project. Repeat the
operation to transfer tasks from another project.
```

Keep the existing transfer-folder retention, cross-project Review, transient
selection, destination checkout, registration, and safety text unchanged.

- [ ] **Step 4: Add the 0.1.40 changelog entry**

Add this section below `Unreleased` in both changelogs:

```markdown
## 0.1.40 - 2026-07-29 - Two-Stage Task Transfer Selection

- Split Import and Export into a project-only screen followed by a task-only screen.
- Started every task screen with zero selected tasks and removed projects from the selected count.
- Added Back navigation that clears task choices before returning to project selection.
- Limited task search to the chosen project while preserving cross-project Review Transfer Status.
```

- [ ] **Step 5: Align package versions and lockfiles**

Change `pyproject.toml` to version `0.1.40`, then run:

```bash
uv lock
cd extensions/vscode
npm version 0.1.40 --no-git-tag-version
```

Confirm `uv.lock`, `package.json`, and both package-lock version fields changed to `0.1.40` without unrelated dependency churn.

- [ ] **Step 6: Run focused documentation and release tests**

Run:

```bash
uv run pytest tests/test_github_actions_workflow.py -q
```

Expected: all workflow, metadata, README, and changelog tests PASS.

- [ ] **Step 7: Commit documentation and release metadata**

```bash
git add README.md CHANGELOG.md pyproject.toml uv.lock tests/test_github_actions_workflow.py extensions/vscode/README.md extensions/vscode/CHANGELOG.md extensions/vscode/package.json extensions/vscode/package-lock.json
git commit -m "chore: prepare 0.1.40 task picker release"
```

---

### Task 4: Run Final Cross-Platform Release Verification

**Files:**
- Verify only; no planned source changes.

**Interfaces:**
- Consumes: the completed two-stage picker and synchronized `0.1.40` metadata.
- Produces: evidence that unit, integration, contract, packaging, and repository checks pass.

- [ ] **Step 1: Run the complete Python suite**

Run:

```bash
uv run pytest
```

Expected: all Python tests PASS.

- [ ] **Step 2: Run the complete extension suite**

Run:

```bash
cd extensions/vscode
npm test
```

Expected: build, type contracts, and all extension tests PASS.

- [ ] **Step 3: Build the local macOS Apple Silicon VSIX**

Run:

```bash
cd extensions/vscode
npm run package:vsix:mac
```

Expected: `output/releases/codex-usage-dashboard-darwin-arm64.vsix` is rebuilt successfully with version `0.1.40`.

- [ ] **Step 4: Verify repository integrity**

Run:

```bash
git diff --check
git status --short --branch
```

Expected: no whitespace errors and a clean feature branch ahead only by the intentional commits.

- [ ] **Step 5: Review the final diff against the design**

Verify all of these from tests and diff:

```text
Project screen: projects only, single-select
Task screen: chosen-project tasks only, multi-select, zero selected
Selected count: tasks only
Back: clears task selection and returns to project choice
Accept: requires at least one task
Import/Export: one project per operation
Review: cross-project and unchanged
Inventory loading: unchanged
```

Expected: every line is directly covered by a test or existing project-scope validator.

- [ ] **Step 6: Run the Windows CI release gate before publication**

Push the completed branch or merged `main`, then run the existing `Package VSIX`
GitHub Actions workflow. Its Windows x64 job must run `npm test`, build the native
executable, run packaged Task Transfer smoke checks, and package the Windows
VSIX before any Marketplace publication is accepted.

Expected: Windows x64 and macOS Apple Silicon jobs both PASS; publication remains
an explicit release action.
