# Sync Menu Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make sync control discoverable from the dashboard by adding explicit pause/resume, change, and clear actions to the existing Sync menu.

**Architecture:** Keep the dashboard webview script-free and continue using one command URI, `codexUsage.openSyncMenu`, as the sync entry point. Move menu item construction into a small pure TypeScript helper so labels and enabled/disabled states are unit-testable, while `extension.ts` owns VS Code effects: updating settings/globalState, refreshing the panel, configuring watchers, and showing confirmations.

**Tech Stack:** VS Code extension API, TypeScript, Node test runner, existing Python CLI unchanged.

---

## File Structure

- Modify `extensions/vscode/src/core.ts`
  - Add pure sync-menu action types and `syncMenuQuickPickItems(settings)`.
  - Export a clearer sync dashboard label that appends a visual dropdown hint, such as `Sync: 1 conversation ▾`.
  - Keep all functions framework-free so `node --test` can cover them.
- Modify `extensions/vscode/src/extension.ts`
  - Replace hard-coded `showSyncMenu()` items with `syncMenuQuickPickItems()`.
  - Add sync actions: pause/resume, change folder, change projects, change conversations, clear setup.
  - Add helper functions for pausing, resuming, changing folder only, clearing sync globalState, refreshing dashboard, and reconfiguring watchers.
- Modify `extensions/vscode/test/core.test.js`
  - Add unit tests for sync menu item composition and dashboard label wording.
- Modify `extensions/vscode/package.json`
  - Bump beta version.
  - Optionally add command palette entries for pause/resume/clear only if implementation chooses separate registered commands. The preferred implementation keeps these as Sync Menu actions and does not add new command IDs.
- Modify `extensions/vscode/package-lock.json`
  - Match the version bump.
- Modify `pyproject.toml` and `uv.lock`
  - Match the package version bump so the bundled CLI and extension keep version parity.
- Modify `CHANGELOG.md`
  - Add a beta release note for sync menu controls.
- Modify `extensions/vscode/README.md`
  - Document the new Sync Menu actions and the manual way to pause/resume without opening Settings.
- Modify root `README.md`
  - Add one sentence in the sync section noting that sync can be paused, resumed, reconfigured, or cleared from the dashboard Sync menu.

## Behavioral Decisions

- `Pause Sync` sets `codexUsage.sync.enabled = false`, disposes watchers, clears pending debounce, sets scheduler status to `off`, and refreshes the dashboard. It does not delete folder/project/conversation selections.
- `Resume Sync` sets `codexUsage.sync.enabled = true`, reconfigures watchers, sets status to idle/setup based on configuration, and refreshes the dashboard. It does not run a sync automatically.
- `Change Folder` uses the existing folder picker and updates only `SYNC_DIR_STATE_KEY`.
- `Change Projects` runs the existing project picker. It should preserve the current conversation mode when possible.
- `Change Conversations` runs the existing conversation picker.
- `Clear Sync Setup` requires confirmation, then disables sync and clears `SYNC_DIR_STATE_KEY`, `SYNC_PROJECT_KEYS_STATE_KEY`, `SYNC_CONVERSATION_MODE_STATE_KEY`, and `SYNC_THREAD_IDS_STATE_KEY`. It does not delete anything from the user’s sync folder.
- `Sync Now` remains available but disabled-looking by description when sync is paused. If clicked while paused, it should offer Resume Sync instead of running.
- Dashboard label becomes `Sync: Off ▾`, `Sync: 1 conversation ▾`, etc., so it reads as a menu control rather than a static badge.

---

### Task 1: Add Pure Sync Menu Model

**Files:**
- Modify: `extensions/vscode/src/core.ts`
- Test: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Write failing tests for menu actions**

Add these imports near the existing destructuring import in `extensions/vscode/test/core.test.js`:

```js
  syncMenuQuickPickItems,
  syncControlLabel,
```

Add this test near the existing sync setting tests:

```js
test("sync menu exposes pause resume change and clear actions", () => {
  const enabledItems = syncMenuQuickPickItems({
    enabled: true,
    dir: "D:/CodexSync",
    projectKeys: ["repo-a"],
    conversationMode: "selectedConversations",
    threadIds: ["t1"],
    autoPull: true,
    autoPush: true,
  });

  assert.deepEqual(
    enabledItems.map((item) => item.action),
    [
      "syncNow",
      "syncStatus",
      "pauseSync",
      "changeFolder",
      "changeProjects",
      "changeConversations",
      "clearSync",
      "openSyncFolder",
    ],
  );
  assert.match(enabledItems[2].label, /Pause Sync/);
  assert.match(enabledItems[4].description, /1 selected/);
  assert.match(enabledItems[5].description, /1 selected/);
  assert.match(enabledItems[6].detail, /does not delete/);

  const pausedItems = syncMenuQuickPickItems({
    enabled: false,
    dir: "D:/CodexSync",
    projectKeys: ["repo-a"],
    conversationMode: "selectedConversations",
    threadIds: ["t1"],
    autoPull: true,
    autoPush: true,
  });

  assert.equal(pausedItems[0].action, "resumeSync");
  assert.match(pausedItems[0].label, /Resume Sync/);
  assert.match(pausedItems[0].description, /Paused/);
});
```

Add this test near `injectWebviewControls` tests:

```js
test("sync control labels read as menu controls", () => {
  assert.equal(
    syncControlLabel({ enabled: false, dir: "", projectKeys: [], conversationMode: "selectedConversations", threadIds: [] }),
    "Sync: Off ▾",
  );
  assert.equal(
    syncControlLabel({
      enabled: true,
      dir: "D:/CodexSync",
      projectKeys: ["repo-a"],
      conversationMode: "selectedConversations",
      threadIds: ["t1"],
    }),
    "Sync: 1 conversation ▾",
  );
  assert.equal(
    syncControlLabel({
      enabled: true,
      dir: "D:/CodexSync",
      projectKeys: ["repo-a", "repo-b"],
      conversationMode: "allInProjects",
      threadIds: [],
    }),
    "Sync: All conversations in 2 projects ▾",
  );
});
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected: TypeScript build fails because `syncMenuQuickPickItems` and/or `syncControlLabel` are not exported.

- [ ] **Step 3: Add types and exported helpers in `core.ts`**

In `extensions/vscode/src/core.ts`, add this type near the other sync types:

```ts
export type SyncMenuAction =
  | "syncNow"
  | "syncStatus"
  | "pauseSync"
  | "resumeSync"
  | "changeFolder"
  | "changeProjects"
  | "changeConversations"
  | "clearSync"
  | "openSyncFolder";

export type SyncMenuQuickPickItem = {
  label: string;
  description: string;
  detail: string;
  action: SyncMenuAction;
};
```

Replace the current private `syncControlLabel()` with this exported implementation:

```ts
export function syncControlLabel(sync: WebviewControlState["sync"]): string {
  const normalized = normalizeSyncSettings(sync ?? {});
  if (!normalized.enabled) {
    return "Sync: Off ▾";
  }
  if (!normalized.dir) {
    return "Sync: Select Folder ▾";
  }
  if (normalized.projectKeys.length === 0 && normalized.threadIds.length === 0) {
    return "Sync: Select Projects ▾";
  }
  if (normalized.conversationMode === "allInProjects") {
    const count = normalized.projectKeys.length;
    if (count === 1) {
      return "Sync: All conversations in 1 project ▾";
    }
    return `Sync: All conversations in ${count} projects ▾`;
  }
  if (normalized.threadIds.length === 0) {
    return "Sync: Select Conversations ▾";
  }
  if (normalized.threadIds.length === 1) {
    return "Sync: 1 conversation ▾";
  }
  return `Sync: ${normalized.threadIds.length} conversations ▾`;
}
```

Add this helper near `syncControlLabel()`:

```ts
export function syncMenuQuickPickItems(sync: SyncSettings): SyncMenuQuickPickItem[] {
  const settings = normalizeSyncSettings(sync);
  const projectCount = settings.projectKeys.length;
  const conversationCount =
    settings.conversationMode === "allInProjects" ? 0 : settings.threadIds.length;
  const conversationDescription =
    settings.conversationMode === "allInProjects"
      ? projectCount === 1
        ? "All conversations in 1 project"
        : `All conversations in ${projectCount} projects`
      : conversationCount === 1
        ? "1 selected"
        : `${conversationCount} selected`;

  const primary: SyncMenuQuickPickItem = settings.enabled
    ? {
        label: "$(sync) Sync Now",
        description: "Pull then push selected conversations",
        detail: "Run one manual sync using the current folder, project, and conversation selections.",
        action: "syncNow",
      }
    : {
        label: "$(play) Resume Sync",
        description: settings.dir ? "Paused" : "Setup needed",
        detail: "Turn sync back on without changing the selected folder, projects, or conversations.",
        action: "resumeSync",
      };

  const pauseOrResume: SyncMenuQuickPickItem = settings.enabled
    ? {
        label: "$(debug-pause) Pause Sync",
        description: "Stop automatic and manual sync",
        detail: "Keeps the selected folder, projects, and conversations so sync can be resumed later.",
        action: "pauseSync",
      }
    : {
        label: "$(play) Resume Sync",
        description: settings.dir ? "Paused" : "Setup needed",
        detail: "Turn sync back on without changing the selected folder, projects, or conversations.",
        action: "resumeSync",
      };

  return [
    primary,
    {
      label: "$(info) Sync Status",
      description: "Inspect selected conversations",
      detail: "Show local/remote state, conflicts, missing files, and memory warnings.",
      action: "syncStatus",
    },
    pauseOrResume,
    {
      label: "$(folder-opened) Change Folder",
      description: settings.dir || "No folder selected",
      detail: "Choose a different bring-your-own sync folder.",
      action: "changeFolder",
    },
    {
      label: "$(repo) Change Projects",
      description: projectCount === 1 ? "1 selected" : `${projectCount} selected`,
      detail: "Choose which Codex projects are eligible for sync.",
      action: "changeProjects",
    },
    {
      label: "$(comment-discussion) Change Conversations",
      description: conversationDescription,
      detail: "Choose all conversations in selected projects or specific conversations.",
      action: "changeConversations",
    },
    {
      label: "$(trash) Clear Sync Setup",
      description: "Disable sync and forget selections",
      detail: "Does not delete local Codex files or anything inside the sync folder.",
      action: "clearSync",
    },
    {
      label: "$(folder) Open Sync Folder",
      description: settings.dir || "No folder selected",
      detail: "Open the configured bring-your-own sync folder.",
      action: "openSyncFolder",
    },
  ];
}
```

- [ ] **Step 4: Run tests and verify they pass**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected: TypeScript builds and all existing Node tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add extensions/vscode/src/core.ts extensions/vscode/test/core.test.js
git commit -m "feat: model sync menu actions"
```

---

### Task 2: Wire Sync Menu Actions To VS Code Effects

**Files:**
- Modify: `extensions/vscode/src/extension.ts`
- Test: `extensions/vscode/test/core.test.js` indirectly covers menu labels; manual smoke covers VS Code side effects.

- [ ] **Step 1: Import the new helper and action type**

In `extensions/vscode/src/extension.ts`, extend the existing import from `./core`:

```ts
  SyncMenuAction,
  syncMenuQuickPickItems,
```

- [ ] **Step 2: Replace hard-coded `showSyncMenu()` items**

Replace the existing `showSyncMenu()` function body with:

```ts
async function showSyncMenu(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  const selected = await vscode.window.showQuickPick(syncMenuQuickPickItems(settings.sync), {
    placeHolder: "Choose a Codex sync action",
  });
  if (!selected) {
    return;
  }
  await handleSyncMenuAction(context, selected.action);
}
```

- [ ] **Step 3: Add `handleSyncMenuAction()`**

Add this function below `showSyncMenu()`:

```ts
async function handleSyncMenuAction(context: vscode.ExtensionContext, action: SyncMenuAction): Promise<void> {
  if (action === "syncNow") {
    const settings = readSettings(context);
    if (!settings.sync.enabled) {
      await resumeSync(context);
      return;
    }
    await requestSync(context, "manual");
    return;
  }
  if (action === "syncStatus") {
    await showSyncStatus(context);
    return;
  }
  if (action === "pauseSync") {
    await pauseSync(context);
    return;
  }
  if (action === "resumeSync") {
    await resumeSync(context);
    return;
  }
  if (action === "changeFolder") {
    await changeSyncFolder(context);
    return;
  }
  if (action === "changeProjects") {
    await selectSyncProjectSettings(context);
    return;
  }
  if (action === "changeConversations") {
    await selectSyncThreadSettings(context);
    return;
  }
  if (action === "clearSync") {
    await clearSyncSetup(context);
    return;
  }
  await openSyncFolder(context);
}
```

- [ ] **Step 4: Add `refreshSyncUi()`**

Add this helper near other sync helpers:

```ts
async function refreshSyncUi(context: vscode.ExtensionContext): Promise<void> {
  updateStatusItem(readSettings(context));
  configureSyncWatcher(context);
  resetSyncSchedulerWhenDisabled(context);
  if (panel) {
    await refreshDashboard(context, panel);
  }
}
```

- [ ] **Step 5: Add pause/resume helpers**

Add these functions below `handleSyncMenuAction()`:

```ts
async function pauseSync(context: vscode.ExtensionContext): Promise<void> {
  await vscode.workspace.getConfiguration("codexUsage").update("sync.enabled", false, vscode.ConfigurationTarget.Global);
  output.appendLine("[sync] Sync paused from dashboard menu.");
  await refreshSyncUi(context);
}

async function resumeSync(context: vscode.ExtensionContext): Promise<void> {
  await vscode.workspace.getConfiguration("codexUsage").update("sync.enabled", true, vscode.ConfigurationTarget.Global);
  output.appendLine("[sync] Sync resumed from dashboard menu.");
  await refreshSyncUi(context);
}
```

- [ ] **Step 6: Add change folder helper**

Add this function below `resumeSync()`:

```ts
async function changeSyncFolder(context: vscode.ExtensionContext): Promise<void> {
  const selectedDir = await selectSyncFolder(context);
  if (!selectedDir) {
    return;
  }
  output.appendLine(`[sync] Sync folder changed: ${selectedDir}`);
  await refreshSyncUi(context);
}
```

- [ ] **Step 7: Add clear setup helper**

Add this function below `changeSyncFolder()`:

```ts
async function clearSyncSetup(context: vscode.ExtensionContext): Promise<void> {
  const choice = await vscode.window.showWarningMessage(
    "Clear Codex sync setup? This disables sync and forgets the selected folder, projects, and conversations. It does not delete any files.",
    { modal: true },
    "Clear Sync Setup",
  );
  if (choice !== "Clear Sync Setup") {
    return;
  }

  await vscode.workspace.getConfiguration("codexUsage").update("sync.enabled", false, vscode.ConfigurationTarget.Global);
  await context.globalState.update(SYNC_DIR_STATE_KEY, undefined);
  await context.globalState.update(SYNC_PROJECT_KEYS_STATE_KEY, undefined);
  await context.globalState.update(SYNC_CONVERSATION_MODE_STATE_KEY, undefined);
  await context.globalState.update(SYNC_THREAD_IDS_STATE_KEY, undefined);
  output.appendLine("[sync] Sync setup cleared from dashboard menu.");
  await refreshSyncUi(context);
}
```

- [ ] **Step 8: Run TypeScript tests**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected: all Node tests pass.

- [ ] **Step 9: Commit Task 2**

```powershell
git add extensions/vscode/src/extension.ts
git commit -m "feat: wire sync menu controls"
```

---

### Task 3: Update Docs, Version, And Changelog

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`
- Modify: `CHANGELOG.md`
- Modify: `extensions/vscode/README.md`
- Modify: `README.md`

- [ ] **Step 1: Bump versions to `0.1.25`**

In `pyproject.toml`:

```toml
version = "0.1.25"
```

In `uv.lock`, update the `codex-usage` package entry:

```toml
version = "0.1.25"
```

In `extensions/vscode/package.json`:

```json
"version": "0.1.25"
```

In `extensions/vscode/package-lock.json`, update both top-level version fields:

```json
"version": "0.1.25"
```

- [ ] **Step 2: Update `CHANGELOG.md`**

Add this entry above `0.1.24`:

```markdown
## 0.1.25 - Sync Menu Controls

- Added explicit Sync menu actions for pause/resume, changing folder, changing projects, changing conversations, clearing sync setup, opening the sync folder, status, and manual sync.
- Updated the dashboard Sync control label to read like a menu control.
```

- [ ] **Step 3: Update `extensions/vscode/README.md`**

In the `Experimental Sync` section, add:

```markdown
Click the dashboard `Sync: ... ▾` control or run `Codex Usage: Sync Menu` to manage sync. The menu supports manual sync, status, pause/resume, changing the sync folder, changing projects, changing conversations, clearing the setup, and opening the sync folder. Clearing setup only forgets extension selections; it does not delete Codex logs or sync-folder files.
```

- [ ] **Step 4: Update root `README.md`**

In the VS Code sync section, add:

```markdown
Sync is managed from the dashboard `Sync: ... ▾` menu, where you can pause/resume, change the folder, change projects or conversations, clear setup, run manual sync, and inspect status.
```

- [ ] **Step 5: Run docs-adjacent tests**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected: all Node tests pass after version metadata changes.

- [ ] **Step 6: Commit Task 3**

```powershell
git add pyproject.toml uv.lock extensions/vscode/package.json extensions/vscode/package-lock.json CHANGELOG.md extensions/vscode/README.md README.md
git commit -m "docs: document sync menu controls"
```

---

### Task 4: Full Verification And VSIX Rebuild

**Files:**
- Generated: `extensions/vscode/bin/win32-x64/codex-usage.exe`
- Generated: `output/codex-usage-dashboard-win32-x64.vsix`

- [ ] **Step 1: Run Python tests**

```powershell
uv run pytest
```

Expected: `119 passed` or the current full suite count with zero failures.

- [ ] **Step 2: Run TypeScript tests**

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected: all Node tests pass.

- [ ] **Step 3: Rebuild Windows VSIX**

```powershell
Push-Location extensions\vscode
npm run package:vsix:win
Pop-Location
```

Expected: `DONE Packaged: ../../output/codex-usage-dashboard-win32-x64.vsix`.

- [ ] **Step 4: Verify VSIX version**

```powershell
tar -xOf output\codex-usage-dashboard-win32-x64.vsix extension/package.json | Select-String '"version"'
```

Expected:

```text
"version": "0.1.25",
```

- [ ] **Step 5: Manual Extension Host smoke**

Install or launch the rebuilt extension, then verify:

```text
1. Dashboard shows Sync label with a dropdown hint, for example Sync: 1 conversation ▾.
2. Clicking the Sync control opens the Sync Menu.
3. Pause Sync turns the dashboard label to Sync: Off ▾ and stops watcher-driven sync.
4. Resume Sync turns sync back on without losing folder/project/conversation selections.
5. Change Folder opens a folder picker and returns to the dashboard after selection.
6. Change Projects opens the project picker.
7. Change Conversations opens the conversation picker.
8. Clear Sync Setup shows a modal warning and, after confirmation, clears folder/projects/conversations and disables sync.
9. Sync Status and Open Sync Folder still work.
```

- [ ] **Step 6: Commit generated release artifacts only if this repo convention allows them**

The current repo does not commit generated binaries by default. If `git status` shows only ignored generated files for the exe/VSIX, do not force-add them.

```powershell
git status --short
```

Expected: source/docs/version changes are already committed; generated binaries remain untracked or ignored.

---

## Self-Review

- Spec coverage: The plan covers pause/resume, clearing setup, changing sync folder/projects/conversations, keeping Sync Now/Status/Open Folder, dashboard menu wording, docs, versioning, tests, and VSIX rebuild.
- Placeholder scan: No task uses TBD/TODO/fill-in wording. Every code-changing task includes concrete snippets.
- Type consistency: The action names in `SyncMenuAction`, `syncMenuQuickPickItems()`, and `handleSyncMenuAction()` match exactly.
- Scope check: This is one UX slice. It does not alter Python sync semantics, conflict handling, cloud storage behavior, or the BYO folder model.
