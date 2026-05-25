# Manual Sync UX Clarification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make manual sync discoverable and make it clear that Sync Enabled plus Auto Pull/Auto Push disabled means manual-only sync.

**Architecture:** Reuse the existing `codexUsage.syncNow` and `codexUsage.syncStatus` commands. Add webview command-strip links for manual sync and status, allow those command URIs in the existing CSP-safe allowlist, and update settings/docs wording without changing the Python sync engine or scheduler behavior.

**Tech Stack:** VS Code Extension API command URIs, existing TypeScript core helpers/tests, existing documentation and VSIX packaging.

---

## File Structure

- Modify `extensions/vscode/src/core.ts`
  - Add `codexUsage.syncNow` and `codexUsage.syncStatus` to `WEBVIEW_COMMANDS`.
  - Add `Sync Now` and `Sync Status` links to the dashboard action strip.

- Modify `extensions/vscode/test/core.test.js`
  - Update webview allowlist expectations.
  - Update command-strip HTML expectations.
  - Add package metadata assertions for clearer sync setting descriptions.

- Modify `extensions/vscode/package.json`
  - Clarify `codexUsage.sync.enabled`, `codexUsage.sync.autoPull`, and `codexUsage.sync.autoPush` descriptions.
  - Bump extension version to `0.1.15`.

- Modify docs/version files
  - `CHANGELOG.md`
  - `README.md`
  - `extensions/vscode/README.md`
  - `pyproject.toml`
  - `uv.lock`
  - `extensions/vscode/package-lock.json`

---

## Task 1: Add Failing Tests For Dashboard Manual Sync Controls

**Files:**
- Modify: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Update webview command-strip test expectations**

In `test("injectWebviewControls adds command links without scripts or external URLs", ...)`, after the existing `configureSync` assertion:

```js
  assert.match(out, /command:codexUsage.syncNow/);
  assert.match(out, /command:codexUsage.syncStatus/);
  assert.match(out, />Sync Now<\/a>/);
  assert.match(out, />Sync Status<\/a>/);
```

- [ ] **Step 2: Update command allowlist test expectation**

In `test("webview command allowlist includes dashboard commands", ...)`, change the expected command array to include sync commands after `codexUsage.configureSync`:

```js
  assert.deepEqual([...WEBVIEW_COMMANDS], [
    "codexUsage.selectRange",
    "codexUsage.selectProjects",
    "codexUsage.selectTheme",
    "codexUsage.reviewProjectTransitions",
    "codexUsage.configureSync",
    "codexUsage.syncNow",
    "codexUsage.syncStatus",
    "codexUsage.refreshDashboard",
    "codexUsage.openSettings",
  ]);
```

- [ ] **Step 3: Add failing test for clearer setting descriptions**

Append this near the package metadata tests:

```js
test("package metadata describes manual-only sync mode clearly", () => {
  const properties = packageJson.contributes.configuration.properties;

  assert.match(properties["codexUsage.sync.enabled"].description, /manual Sync Now/i);
  assert.match(properties["codexUsage.sync.enabled"].description, /optional automatic/i);
  assert.match(properties["codexUsage.sync.autoPull"].description, /optional/i);
  assert.match(properties["codexUsage.sync.autoPush"].description, /optional/i);
  assert.doesNotMatch(properties["codexUsage.sync.enabled"].description, /selected-thread/i);
});
```

- [ ] **Step 4: Run tests and verify they fail**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected:

- Tests fail because `syncNow` and `syncStatus` command URIs are not yet in the webview allowlist/action strip.
- The package metadata test fails because the setting description still says selected-thread sync.

---

## Task 2: Expose Manual Sync In The Dashboard Action Strip

**Files:**
- Modify: `extensions/vscode/src/core.ts`
- Test: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Add sync commands to the webview allowlist**

In `extensions/vscode/src/core.ts`, change `WEBVIEW_COMMANDS` from:

```ts
export const WEBVIEW_COMMANDS = [
  "codexUsage.selectRange",
  "codexUsage.selectProjects",
  "codexUsage.selectTheme",
  "codexUsage.reviewProjectTransitions",
  "codexUsage.configureSync",
  "codexUsage.refreshDashboard",
  "codexUsage.openSettings",
] as const;
```

to:

```ts
export const WEBVIEW_COMMANDS = [
  "codexUsage.selectRange",
  "codexUsage.selectProjects",
  "codexUsage.selectTheme",
  "codexUsage.reviewProjectTransitions",
  "codexUsage.configureSync",
  "codexUsage.syncNow",
  "codexUsage.syncStatus",
  "codexUsage.refreshDashboard",
  "codexUsage.openSettings",
] as const;
```

- [ ] **Step 2: Add manual sync links to action strip**

In `renderWebviewControls`, after the existing Configure Sync link:

```ts
    `<a href="command:codexUsage.configureSync">${escapeHtml(syncControlLabel(state.sync))}</a>` +
```

add:

```ts
    '<a href="command:codexUsage.syncNow">Sync Now</a>' +
    '<a href="command:codexUsage.syncStatus">Sync Status</a>' +
```

The final sequence should be:

```ts
    `<a href="command:codexUsage.selectRange">Range: ${escapeHtml(state.range)}</a>` +
    `<a href="command:codexUsage.selectProjects">Projects: ${escapeHtml(projectFilterLabel(state.projectKeys))}</a>` +
    `<a href="command:codexUsage.selectTheme">Theme: ${escapeHtml(themeLabel(state.theme))}</a>` +
    `<a href="command:codexUsage.configureSync">${escapeHtml(syncControlLabel(state.sync))}</a>` +
    '<a href="command:codexUsage.syncNow">Sync Now</a>' +
    '<a href="command:codexUsage.syncStatus">Sync Status</a>' +
    '<a href="command:codexUsage.reviewProjectTransitions">Transitions</a>' +
    '<a href="command:codexUsage.refreshDashboard">Refresh</a>' +
    '<a href="command:codexUsage.openSettings">Settings</a>' +
```

- [ ] **Step 3: Run extension tests**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected:

- Webview allowlist/action-strip tests pass.
- Package metadata description test still fails until Task 3.

---

## Task 3: Clarify Sync Settings Descriptions

**Files:**
- Modify: `extensions/vscode/package.json`
- Test: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Update `codexUsage.sync.enabled` description**

In `extensions/vscode/package.json`, change:

```json
"description": "Enable experimental selected-thread Codex sync."
```

to:

```json
"description": "Enable experimental Codex sync for manual Sync Now and optional automatic pull/push."
```

- [ ] **Step 2: Update `codexUsage.sync.autoPull` description**

Change:

```json
"description": "Automatically pull selected thread updates when VS Code activates or gains focus."
```

to:

```json
"description": "Optional automatic pull of selected conversation updates when VS Code activates or gains focus. Turn off for manual-only sync."
```

- [ ] **Step 3: Update `codexUsage.sync.autoPush` description**

Change:

```json
"description": "Automatically push selected thread updates after watched Codex session files change."
```

to:

```json
"description": "Optional automatic push of selected conversation updates after watched Codex session files change. Turn off for manual-only sync."
```

- [ ] **Step 4: Run extension tests**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected:

- All extension tests pass.

---

## Task 4: Update Docs And Version To 0.1.15

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`

- [ ] **Step 1: Bump Python and extension versions**

In `pyproject.toml`, change:

```toml
version = "0.1.14"
```

to:

```toml
version = "0.1.15"
```

In `extensions/vscode/package.json`, change:

```json
"version": "0.1.14"
```

to:

```json
"version": "0.1.15"
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

- `uv.lock` updates `codex-usage` to `0.1.15`.
- `extensions/vscode/package-lock.json` updates to `0.1.15`.
- Existing npm audit output may still mention current dev dependency vulnerabilities; do not run `npm audit fix`.

- [ ] **Step 3: Update changelog**

Add above `0.1.14` in `CHANGELOG.md`:

```markdown
## 0.1.15 - Manual Sync UX

- Added `Sync Now` and `Sync Status` to the dashboard action strip.
- Clarified that Sync Enabled allows manual sync, while Auto Pull and Auto Push are optional automation.
- Updated sync setting descriptions to use conversation wording and explain manual-only mode.
```

- [ ] **Step 4: Update root README sync section**

In `README.md`, under `## Experimental Conversation Sync`, after the paragraph beginning `Background sync is intentionally quiet`, add:

```markdown
Manual-only sync is supported: keep Sync Enabled on, turn Auto Pull and Auto Push off, then use `Codex Usage: Sync Now` from the command palette or the dashboard action strip. Use `Sync Status` to inspect selected conversation state without running a full sync.
```

- [ ] **Step 5: Update extension README sync section**

In `extensions/vscode/README.md`, under `## Experimental Sync`, after the paragraph beginning `The status bar is the primary background sync indicator`, add:

```markdown
For manual-only sync, leave `codexUsage.sync.enabled` on and turn off both `codexUsage.sync.autoPull` and `codexUsage.sync.autoPush`. Run `Codex Usage: Sync Now` from the command palette or the dashboard action strip when you want to sync, and use `Codex Usage: Sync Status` to inspect selected conversations.
```

- [ ] **Step 6: Run docs wording check**

Run:

```powershell
rg "selected-thread|Sync Now|Sync Status|manual-only" README.md extensions\vscode\README.md extensions\vscode\package.json CHANGELOG.md
```

Expected:

- `Sync Now`, `Sync Status`, and `manual-only` appear in current docs.
- `selected-thread` does not appear in current setting descriptions. Historical changelog entries may still mention older selected-thread language.

---

## Task 5: Verification And Packaging

**Files:**
- Verify generated artifact: `output/codex-usage-dashboard-win32-x64.vsix`

- [ ] **Step 1: Run Python tests**

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

- [ ] **Step 3: Rebuild Windows VSIX**

Run:

```powershell
Push-Location extensions\vscode
npm run package:vsix:win
Pop-Location
```

Expected:

- `output/codex-usage-dashboard-win32-x64.vsix` is rebuilt.
- Package output shows `0.1.15`.
- VSIX output includes `extension/bin/win32-x64/codex-usage.exe`, `extension/out/core.js`, and `extension/out/extension.js`.

- [ ] **Step 4: Inspect package contents**

Run:

```powershell
Push-Location extensions\vscode
npx vsce ls --tree
Pop-Location
```

Expected:

- VSIX contains compiled output and bundled executable.
- VSIX excludes TypeScript source and tests.

- [ ] **Step 5: Run git diff sanity check**

Run:

```powershell
git diff --check
```

Expected:

- No whitespace errors. Line-ending warnings are acceptable on Windows if they match existing repo behavior.

---

## Manual Smoke Checklist

- [ ] Install rebuilt VSIX only when ready:

```powershell
code --install-extension output\codex-usage-dashboard-win32-x64.vsix --force
```

- [ ] Reload VS Code or restart the extension host.
- [ ] Open the dashboard and confirm `Sync Now` and `Sync Status` are visible in the action strip.
- [ ] Disable Auto Pull and Auto Push while leaving Sync Enabled on.
- [ ] Confirm status bar still shows sync as enabled/setup/idle rather than off.
- [ ] Click `Sync Status` and confirm it reports selected conversation state without running import/export.
- [ ] Click `Sync Now` and confirm manual sync runs with visible manual feedback.
- [ ] Open Settings and confirm descriptions explain manual Sync Now plus optional automation.

---

## Rollback Plan

- [ ] If the action strip becomes too crowded, keep `Sync Now` visible and remove `Sync Status` from the strip while keeping it in the command palette.
- [ ] If command links in the webview feel too easy to click accidentally, rename `Sync Now` to `Run Sync` but keep the command id unchanged.
- [ ] If users still confuse Sync Enabled with auto sync, consider renaming the setting title in a later slice by adding a separate contributed configuration title structure or moving sync setup fully out of Settings.
