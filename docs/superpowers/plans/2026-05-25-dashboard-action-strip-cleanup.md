# Dashboard Action Strip Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce dashboard top-bar crowding by collapsing sync actions into one Sync menu and removing rare transition review from the primary action strip.

**Architecture:** Keep the dashboard webview script-free and command-URI driven. The Python report remains unchanged; the TypeScript wrapper owns the compact action strip, the new Sync menu QuickPick, command registration, and tests.

**Tech Stack:** VS Code extension API, TypeScript, Node test runner, existing Python CLI unchanged.

---

## File Structure

- Modify `extensions/vscode/src/core.ts`
  - Add `codexUsage.openSyncMenu` to the webview command allowlist.
  - Change `renderWebviewControls()` so the strip renders one sync link instead of three sync-related links.
  - Remove the `Transitions` link from the strip while keeping its command available elsewhere.
- Modify `extensions/vscode/src/extension.ts`
  - Register `codexUsage.openSyncMenu`.
  - Add `showSyncMenu(context)` as a small QuickPick router for sync actions.
  - Keep existing sync commands unchanged: `configureSync`, `syncNow`, `syncStatus`, `openSyncFolder`.
- Modify `extensions/vscode/package.json`
  - Add command metadata for `Codex Usage: Sync Menu`.
  - Add activation event `onCommand:codexUsage.openSyncMenu`.
  - Bump extension beta version from `0.1.17` to `0.1.18`.
- Modify `extensions/vscode/package-lock.json`
  - Keep package lock version aligned with `package.json`.
- Modify `pyproject.toml` and `uv.lock`
  - Bump Python package version to `0.1.18` to keep the bundled executable/version story aligned.
- Modify `extensions/vscode/test/core.test.js`
  - Update strip assertions.
  - Add tests for the new allowlist entry and command metadata.
- Modify `CHANGELOG.md`
  - Add a concise `0.1.18` entry describing the action strip cleanup.

---

### Task 1: Update Webview Control Tests First

**Files:**
- Modify: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Change the main webview controls test expectation**

In `extensions/vscode/test/core.test.js`, update `injectWebviewControls adds command links without scripts or external URLs` so it expects one Sync menu link and no separate sync/transition links:

```js
  assert.match(out, /command:codexUsage.openSyncMenu/);
  assert.doesNotMatch(out, /command:codexUsage.syncNow/);
  assert.doesNotMatch(out, /command:codexUsage.syncStatus/);
  assert.doesNotMatch(out, /command:codexUsage.reviewProjectTransitions/);
  assert.match(out, /Sync: 2 conversations/);
  assert.doesNotMatch(out, />Sync Now<\/a>/);
  assert.doesNotMatch(out, />Sync Status<\/a>/);
  assert.doesNotMatch(out, />Transitions<\/a>/);
```

Keep the existing assertions for `selectRange`, `selectProjects`, `selectTheme`, `refreshDashboard`, `openSettings`, version label, no scripts, and no external URLs.

- [ ] **Step 2: Update the webview command allowlist test**

In `webview command allowlist includes dashboard commands`, change the expected list to:

```js
  assert.deepEqual([...WEBVIEW_COMMANDS], [
    "codexUsage.selectRange",
    "codexUsage.selectProjects",
    "codexUsage.selectTheme",
    "codexUsage.openSyncMenu",
    "codexUsage.refreshDashboard",
    "codexUsage.openSettings",
  ]);
```

- [ ] **Step 3: Add package metadata assertions for the Sync menu command**

Extend `package metadata uses project and conversation wording for sync commands` with:

```js
  assert.equal(commands.get("codexUsage.openSyncMenu"), "Codex Usage: Sync Menu");
```

- [ ] **Step 4: Run the focused Node tests and confirm they fail**

Run:

```powershell
Push-Location extensions/vscode
npm test
Pop-Location
```

Expected: FAIL because `core.ts` still renders old command links and `package.json` does not yet contribute `codexUsage.openSyncMenu`.

- [ ] **Step 5: Commit the failing tests**

```powershell
git add extensions/vscode/test/core.test.js
git commit -m "test: specify compact dashboard action strip"
```

---

### Task 2: Compact The Webview Action Strip

**Files:**
- Modify: `extensions/vscode/src/core.ts`

- [ ] **Step 1: Update the webview command allowlist**

In `WEBVIEW_COMMANDS`, replace the sync and transition entries with the new menu command:

```ts
export const WEBVIEW_COMMANDS = [
  "codexUsage.selectRange",
  "codexUsage.selectProjects",
  "codexUsage.selectTheme",
  "codexUsage.openSyncMenu",
  "codexUsage.refreshDashboard",
  "codexUsage.openSettings",
] as const;
```

- [ ] **Step 2: Update `renderWebviewControls()`**

Replace the sync/transition block in `renderWebviewControls()` with a single sync menu link:

```ts
    `<a href="command:codexUsage.openSyncMenu">${escapeHtml(syncControlLabel(state.sync))}</a>` +
    '<a href="command:codexUsage.refreshDashboard">Refresh</a>' +
    '<a href="command:codexUsage.openSettings">Settings</a>' +
```

The resulting strip order must be:

```text
Range | Projects | Theme | Sync | Refresh | Settings | Version
```

- [ ] **Step 3: Run the focused tests**

Run:

```powershell
Push-Location extensions/vscode
npm test
Pop-Location
```

Expected: still FAIL because `codexUsage.openSyncMenu` is not registered or contributed yet, but webview control tests should now pass.

- [ ] **Step 4: Commit the webview strip implementation**

```powershell
git add extensions/vscode/src/core.ts
git commit -m "feat: compact dashboard action strip"
```

---

### Task 3: Add The VS Code Sync Menu Command

**Files:**
- Modify: `extensions/vscode/src/extension.ts`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`

- [ ] **Step 1: Register `codexUsage.openSyncMenu`**

In `activate(context)`, add the command registration near the existing sync commands:

```ts
  const openSyncMenuCommand = vscode.commands.registerCommand("codexUsage.openSyncMenu", async () => {
    await showSyncMenu(context);
  });
```

Add `openSyncMenuCommand` to `context.subscriptions.push(...)` with the other command disposables.

- [ ] **Step 2: Implement `showSyncMenu(context)`**

Add this helper near the existing sync UI helpers:

```ts
async function showSyncMenu(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  const items: Array<vscode.QuickPickItem & { action: "syncNow" | "syncStatus" | "configureSync" | "openSyncFolder" }> = [
    {
      label: "$(sync) Sync Now",
      description: settings.sync.enabled ? "Pull then push selected conversations" : "Sync is currently disabled",
      detail: "Run one manual sync using the current folder, project, and conversation selections.",
      action: "syncNow",
    },
    {
      label: "$(info) Sync Status",
      description: "Inspect selected conversations",
      detail: "Show local/remote state, conflicts, missing files, and memory warnings.",
      action: "syncStatus",
    },
    {
      label: "$(settings-gear) Configure Sync",
      description: "Folder, projects, and conversations",
      detail: "Choose the sync folder and select which projects or conversations participate in sync.",
      action: "configureSync",
    },
    {
      label: "$(folder-opened) Open Sync Folder",
      description: settings.sync.dir || "No folder selected",
      detail: "Open the configured bring-your-own sync folder.",
      action: "openSyncFolder",
    },
  ];

  const selected = await vscode.window.showQuickPick(items, {
    placeHolder: "Choose a Codex sync action",
  });
  if (!selected) {
    return;
  }

  if (selected.action === "syncNow") {
    await requestSync(context, "manual");
    return;
  }
  if (selected.action === "syncStatus") {
    await showSyncStatus(context);
    return;
  }
  if (selected.action === "configureSync") {
    await configureSync(context);
    return;
  }
  await openSyncFolder(context);
}
```

- [ ] **Step 3: Add activation and command metadata**

In `extensions/vscode/package.json`, add this activation event:

```json
"onCommand:codexUsage.openSyncMenu"
```

Add this command contribution near the sync command entries:

```json
{
  "command": "codexUsage.openSyncMenu",
  "title": "Codex Usage: Sync Menu"
}
```

- [ ] **Step 4: Bump VS Code package version**

In `extensions/vscode/package.json`, set:

```json
"version": "0.1.18"
```

In `extensions/vscode/package-lock.json`, update the package version fields for `codex-usage-dashboard` to `0.1.18`.

- [ ] **Step 5: Run the extension tests**

Run:

```powershell
Push-Location extensions/vscode
npm test
Pop-Location
```

Expected: PASS.

- [ ] **Step 6: Commit the Sync menu implementation**

```powershell
git add extensions/vscode/src/extension.ts extensions/vscode/package.json extensions/vscode/package-lock.json
git commit -m "feat: add dashboard sync menu"
```

---

### Task 4: Align Versions And Changelog

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Bump the Python package version**

In `pyproject.toml`, set:

```toml
version = "0.1.18"
```

In `uv.lock`, update the `codex-usage` package version from `0.1.17` to `0.1.18`.

- [ ] **Step 2: Add a changelog entry**

At the top of `CHANGELOG.md`, add:

```markdown
## 0.1.18 - Dashboard Action Strip Cleanup

- Collapsed dashboard sync actions into one Sync menu to reduce top-bar crowding.
- Removed project transition review from the dashboard action strip; it remains available through the Command Palette.
- Kept Sync Now, Sync Status, Configure Sync, and Open Sync Folder available from the Sync menu.
```

- [ ] **Step 3: Run Python tests**

Run:

```powershell
uv run pytest
```

Expected: PASS.

- [ ] **Step 4: Commit version and docs updates**

```powershell
git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "docs: note dashboard action strip cleanup"
```

---

### Task 5: Package And Smoke Test

**Files:**
- Generated: `extensions/vscode/bin/win32-x64/codex-usage.exe`
- Generated: `output/codex-usage-dashboard-win32-x64.vsix`

- [ ] **Step 1: Run full Python verification**

```powershell
uv run pytest
```

Expected: all tests pass with `0 failed`.

- [ ] **Step 2: Run full TypeScript verification**

```powershell
Push-Location extensions/vscode
npm test
Pop-Location
```

Expected: all Node tests pass with `0 fail`.

- [ ] **Step 3: Build the Windows VSIX**

```powershell
Push-Location extensions/vscode
npm run package:vsix:win
Pop-Location
```

Expected output includes:

```text
Packaged: ../../output/codex-usage-dashboard-win32-x64.vsix
```

- [ ] **Step 4: Smoke test the bundled executable**

```powershell
extensions\vscode\bin\win32-x64\codex-usage.exe summary --range 30d --by project --json > output\action-strip-summary-smoke.json
extensions\vscode\bin\win32-x64\codex-usage.exe report --range 30d --output output\action-strip-report-smoke.html
```

Expected:

```text
Wrote output\action-strip-report-smoke.html
```

- [ ] **Step 5: Inspect the VSIX contents**

```powershell
Push-Location extensions/vscode
npx vsce ls --tree
Pop-Location
```

Expected: the listing includes:

```text
extension/package.json
extension/bin/win32-x64/codex-usage.exe
extension/out/core.js
extension/out/extension.js
extension/media/icon.png
```

- [ ] **Step 6: Commit generated-lock/build metadata only if tracked files changed**

Generated binaries and `output/` are ignored. If `git status --short` shows only ignored outputs, do not commit them.

Run:

```powershell
git status --short
```

Expected tracked changes: none.

---

### Task 6: Manual VS Code Smoke After Install

**Files:**
- Uses: `output/codex-usage-dashboard-win32-x64.vsix`

- [ ] **Step 1: Install the rebuilt VSIX manually**

```powershell
code --install-extension output\codex-usage-dashboard-win32-x64.vsix --force
```

Expected: VS Code installs `Codex Usage Dashboard` version `0.1.18`.

- [ ] **Step 2: Open the dashboard**

Run command:

```text
Codex Usage: Open Dashboard
```

Expected action strip:

```text
Range: <range> | Projects: <selection> | Theme: <theme> | Sync: <state> | Refresh | Settings | v0.1.18
```

The strip must not show:

```text
Sync Now
Sync Status
Transitions
```

- [ ] **Step 3: Verify the Sync menu**

Click the single `Sync: ...` action.

Expected QuickPick items:

```text
Sync Now
Sync Status
Configure Sync
Open Sync Folder
```

- [ ] **Step 4: Verify transition review is still available**

Open Command Palette and run:

```text
Codex Usage: Review Project Transitions
```

Expected: the existing transition review flow still opens.

---

## Self-Review

- Spec coverage: The plan collapses the three sync controls, removes the transition control from the dashboard strip, preserves all existing sync actions through a menu, keeps transition review available, updates tests, bumps version, and rebuilds the VSIX.
- Placeholder scan: No placeholder markers or vague implementation steps remain.
- Type consistency: The new command is consistently named `codexUsage.openSyncMenu`; the helper is consistently named `showSyncMenu(context)`.
