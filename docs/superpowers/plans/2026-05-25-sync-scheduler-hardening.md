# Sync Scheduler Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make VS Code background sync calm, single-flight, cooldown-aware, backoff-aware, and primarily visible through the status bar instead of repeated popups.

**Architecture:** Keep the Python CLI sync engine unchanged. Add pure scheduler constants/classification helpers in `extensions/vscode/src/core.ts`, then use a small private scheduler state in `extensions/vscode/src/extension.ts` to coordinate timers, single-flight execution, notifications, and status bar state.

**Tech Stack:** VS Code Extension API, TypeScript, Node standard test runner, existing bundled Python CLI, existing VSIX packaging.

---

## File Structure

- Modify `extensions/vscode/src/core.ts`
  - Add sync scheduler constants.
  - Add pure backoff and notification-classification helpers.
  - Add status label helper for status bar text.

- Modify `extensions/vscode/test/core.test.js`
  - Add tests for scheduler constants/helpers.

- Modify `extensions/vscode/src/extension.ts`
  - Add scheduler state.
  - Replace direct `syncNow` auto calls with a scheduler-aware `requestSync`.
  - Prevent overlapping sync runs.
  - Add cooldown/backoff.
  - Clear pending timers when sync is disabled.
  - Move auto sync feedback into the status bar/output channel.

- Modify docs/version files
  - `CHANGELOG.md`
  - `README.md`
  - `extensions/vscode/README.md`
  - `pyproject.toml`
  - `uv.lock`
  - `extensions/vscode/package.json`
  - `extensions/vscode/package-lock.json`

---

## Task 1: Add Pure Scheduler Helper Tests

**Files:**
- Modify: `extensions/vscode/test/core.test.js`
- Later modify: `extensions/vscode/src/core.ts`

- [ ] **Step 1: Add imports for scheduler helpers**

In `extensions/vscode/test/core.test.js`, add these names to the existing destructuring import from `../out/core`:

```js
  SYNC_AUTO_WARNING_COOLDOWN_MS,
  SYNC_FILE_CHANGE_DEBOUNCE_MS,
  SYNC_FOCUS_COOLDOWN_MS,
  syncBackoffMs,
  syncFailureRequiresNotification,
  syncStatusKindLabel,
```

- [ ] **Step 2: Add failing tests for timing constants and backoff**

Append this near the existing sync helper tests:

```js
test("sync scheduler constants use calm background timing", () => {
  assert.equal(SYNC_FILE_CHANGE_DEBOUNCE_MS, 30_000);
  assert.equal(SYNC_FOCUS_COOLDOWN_MS, 5 * 60_000);
  assert.equal(SYNC_AUTO_WARNING_COOLDOWN_MS, 5 * 60_000);
});

test("syncBackoffMs escalates auto retry delays and caps them", () => {
  assert.equal(syncBackoffMs(0), 0);
  assert.equal(syncBackoffMs(1), 60_000);
  assert.equal(syncBackoffMs(2), 5 * 60_000);
  assert.equal(syncBackoffMs(3), 15 * 60_000);
  assert.equal(syncBackoffMs(20), 15 * 60_000);
});
```

- [ ] **Step 3: Add failing tests for notification classification and status labels**

Append:

```js
test("syncFailureRequiresNotification only elevates action-needed auto failures", () => {
  assert.equal(syncFailureRequiresNotification("Codex sync has 1 conflict. Run Codex Usage: Sync Status."), true);
  assert.equal(syncFailureRequiresNotification("Bundled codex-usage executable was not found at C:/x/codex-usage.exe."), true);
  assert.equal(syncFailureRequiresNotification("Codex sync is not configured."), true);
  assert.equal(syncFailureRequiresNotification("No Codex conversations are selected for sync."), true);
  assert.equal(syncFailureRequiresNotification("PermissionError: [WinError 5] Access is denied"), false);
  assert.equal(syncFailureRequiresNotification("codex-usage exited with code 1"), false);
});

test("syncStatusKindLabel maps scheduler states to concise status bar labels", () => {
  assert.equal(syncStatusKindLabel("off"), "Off");
  assert.equal(syncStatusKindLabel("idle"), "Idle");
  assert.equal(syncStatusKindLabel("waiting"), "Waiting");
  assert.equal(syncStatusKindLabel("pulling"), "Pulling");
  assert.equal(syncStatusKindLabel("pushing"), "Pushing");
  assert.equal(syncStatusKindLabel("conflict"), "Conflict");
  assert.equal(syncStatusKindLabel("issue"), "Issue");
});
```

- [ ] **Step 4: Run tests and verify they fail for missing exports**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected:

- Build fails because the imported scheduler helpers are not exported yet, or tests fail because helpers are undefined.

---

## Task 2: Implement Core Scheduler Helpers

**Files:**
- Modify: `extensions/vscode/src/core.ts`
- Test: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Add scheduler constants and type**

In `extensions/vscode/src/core.ts`, near the existing exported constants, add:

```ts
export const SYNC_FILE_CHANGE_DEBOUNCE_MS = 30_000;
export const SYNC_FOCUS_COOLDOWN_MS = 5 * 60_000;
export const SYNC_AUTO_WARNING_COOLDOWN_MS = 5 * 60_000;

export const SYNC_STATUS_KIND_VALUES = ["off", "idle", "waiting", "pulling", "pushing", "conflict", "issue"] as const;
export type SyncStatusKind = (typeof SYNC_STATUS_KIND_VALUES)[number];
```

- [ ] **Step 2: Add `syncBackoffMs`**

In `extensions/vscode/src/core.ts`, near other pure helpers, add:

```ts
export function syncBackoffMs(failureCount: number): number {
  if (!Number.isFinite(failureCount) || failureCount <= 0) {
    return 0;
  }
  if (failureCount === 1) {
    return 60_000;
  }
  if (failureCount === 2) {
    return 5 * 60_000;
  }
  return 15 * 60_000;
}
```

- [ ] **Step 3: Add notification classification**

Add:

```ts
export function syncFailureRequiresNotification(message: string): boolean {
  const text = message.toLowerCase();
  return (
    text.includes("conflict") ||
    text.includes("not configured") ||
    text.includes("bundled codex-usage executable was not found") ||
    text.includes("no codex conversations are selected")
  );
}
```

- [ ] **Step 4: Add status label helper**

Add:

```ts
export function syncStatusKindLabel(kind: SyncStatusKind): string {
  if (kind === "off") {
    return "Off";
  }
  if (kind === "idle") {
    return "Idle";
  }
  if (kind === "waiting") {
    return "Waiting";
  }
  if (kind === "pulling") {
    return "Pulling";
  }
  if (kind === "pushing") {
    return "Pushing";
  }
  if (kind === "conflict") {
    return "Conflict";
  }
  return "Issue";
}
```

- [ ] **Step 5: Run tests and verify helper tests pass**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected:

- All current extension tests pass.

---

## Task 3: Add Scheduler State And Status Bar Model

**Files:**
- Modify: `extensions/vscode/src/extension.ts`

- [ ] **Step 1: Import scheduler helpers**

In `extensions/vscode/src/extension.ts`, add these imports from `./core`:

```ts
  SYNC_AUTO_WARNING_COOLDOWN_MS,
  SYNC_FILE_CHANGE_DEBOUNCE_MS,
  SYNC_FOCUS_COOLDOWN_MS,
  SyncStatusKind,
  syncBackoffMs,
  syncFailureRequiresNotification,
  syncStatusKindLabel,
```

- [ ] **Step 2: Add scheduler types and state**

Near the current module-level variables, add:

```ts
type SyncReason = "manual" | "auto" | "watch";

type SyncSchedulerState = {
  inFlight: boolean;
  pendingReason: SyncReason | undefined;
  status: SyncStatusKind;
  lastAutoSyncAt: number;
  nextAutoSyncAllowedAt: number;
  autoFailureCount: number;
  lastAutoWarningAt: number;
  lastSyncAt: number;
  lastError: string;
};

const syncScheduler: SyncSchedulerState = {
  inFlight: false,
  pendingReason: undefined,
  status: "off",
  lastAutoSyncAt: 0,
  nextAutoSyncAllowedAt: 0,
  autoFailureCount: 0,
  lastAutoWarningAt: 0,
  lastSyncAt: 0,
  lastError: "",
};
```

- [ ] **Step 3: Add small scheduler utility functions**

Near `syncStatusTooltip`, add:

```ts
function setSyncStatus(context: vscode.ExtensionContext, status: SyncStatusKind, lastError = ""): void {
  syncScheduler.status = status;
  if (lastError) {
    syncScheduler.lastError = lastError;
  }
  updateStatusItem(readSettings(context));
}

function autoReason(reason: SyncReason): boolean {
  return reason !== "manual";
}

function mergePendingSyncReason(existing: SyncReason | undefined, next: SyncReason): SyncReason {
  if (existing === "manual" || next === "manual") {
    return "manual";
  }
  if (existing === "watch" || next === "watch") {
    return "watch";
  }
  return "auto";
}
```

- [ ] **Step 4: Update status bar text**

Replace `syncStatusBadge` with this signature and implementation:

```ts
function syncStatusBadge(settings: ExtensionSettings, status: SyncStatusKind): string {
  if (!settings.sync.enabled) {
    return "Sync:Off";
  }
  if (!syncIsConfigured(settings)) {
    return "Sync:Setup";
  }
  return `Sync:${syncStatusKindLabel(status === "off" ? "idle" : status)}`;
}
```

In `updateStatusItem`, change:

```ts
const syncStatus = syncStatusBadge(settings);
```

to:

```ts
const syncStatus = syncStatusBadge(settings, syncScheduler.status);
```

Keep appending the sync badge to `statusItem.text`.

- [ ] **Step 5: Update status tooltip to include scheduler details**

Replace `syncStatusTooltip` with:

```ts
function syncStatusTooltip(settings: ExtensionSettings): string {
  if (!settings.sync.enabled) {
    return "Sync: disabled.";
  }
  const folder = settings.sync.dir ? "folder selected" : "folder not selected";
  const mode =
    settings.sync.conversationMode === "allInProjects"
      ? `all conversations in ${settings.sync.projectKeys.length} project${settings.sync.projectKeys.length === 1 ? "" : "s"}`
      : `${settings.sync.threadIds.length} conversation${settings.sync.threadIds.length === 1 ? "" : "s"} selected`;
  const auto = `auto pull ${settings.sync.autoPull ? "on" : "off"}, auto push ${settings.sync.autoPush ? "on" : "off"}`;
  const state = `state ${syncStatusKindLabel(syncScheduler.status === "off" ? "idle" : syncScheduler.status)}`;
  const lastSync = syncScheduler.lastSyncAt ? `last sync ${new Date(syncScheduler.lastSyncAt).toLocaleString()}` : "no completed sync yet";
  const nextRetry =
    syncScheduler.nextAutoSyncAllowedAt > Date.now()
      ? `next retry after ${new Date(syncScheduler.nextAutoSyncAllowedAt).toLocaleTimeString()}`
      : "";
  const lastError = syncScheduler.lastError ? `last error: ${syncScheduler.lastError}` : "";
  return ["Sync: enabled", folder, mode, auto, state, lastSync, nextRetry, lastError].filter(Boolean).join(". ") + ".";
}
```

- [ ] **Step 6: Run TypeScript build**

Run:

```powershell
Push-Location extensions\vscode
npm run build
Pop-Location
```

Expected:

- TypeScript compilation succeeds.

---

## Task 4: Replace Direct Sync Execution With Single-Flight Scheduler

**Files:**
- Modify: `extensions/vscode/src/extension.ts`

- [ ] **Step 1: Rename the existing sync body**

Rename:

```ts
async function syncNow(context: vscode.ExtensionContext, reason: string): Promise<void> {
```

to:

```ts
async function runSyncNow(context: vscode.ExtensionContext, reason: SyncReason): Promise<void> {
```

Do not change its body yet.

- [ ] **Step 2: Add `requestSync` before `runSyncNow`**

Add:

```ts
async function requestSync(context: vscode.ExtensionContext, reason: SyncReason): Promise<void> {
  const settings = readSettings(context);
  const now = Date.now();

  if (!syncIsConfigured(settings)) {
    if (reason === "manual") {
      await offerConfigureSync(context, "Codex sync is not configured.");
    } else {
      setSyncStatus(context, settings.sync.enabled ? "idle" : "off");
    }
    return;
  }

  if (autoReason(reason)) {
    if (now < syncScheduler.nextAutoSyncAllowedAt) {
      output.appendLine(`[sync] auto sync skipped during backoff until ${new Date(syncScheduler.nextAutoSyncAllowedAt).toLocaleString()}`);
      setSyncStatus(context, "waiting");
      return;
    }
    if (reason === "auto" && now - syncScheduler.lastAutoSyncAt < SYNC_FOCUS_COOLDOWN_MS) {
      output.appendLine("[sync] auto sync skipped during focus cooldown");
      return;
    }
  }

  if (syncScheduler.inFlight) {
    syncScheduler.pendingReason = mergePendingSyncReason(syncScheduler.pendingReason, reason);
    output.appendLine(`[sync] sync already running; queued ${reason} follow-up`);
    if (reason === "manual") {
      void vscode.window.showInformationMessage("Codex sync is already running; another run will start afterward.");
    }
    return;
  }

  await runScheduledSync(context, reason);
}
```

- [ ] **Step 3: Add `runScheduledSync`**

Add:

```ts
async function runScheduledSync(context: vscode.ExtensionContext, reason: SyncReason): Promise<void> {
  syncScheduler.inFlight = true;
  syncScheduler.pendingReason = undefined;
  if (autoReason(reason)) {
    syncScheduler.lastAutoSyncAt = Date.now();
  }
  try {
    await runSyncNow(context, reason);
    syncScheduler.autoFailureCount = 0;
    syncScheduler.nextAutoSyncAllowedAt = 0;
    syncScheduler.lastError = "";
    syncScheduler.lastSyncAt = Date.now();
    setSyncStatus(context, "idle");
  } finally {
    syncScheduler.inFlight = false;
    const pending = syncScheduler.pendingReason;
    syncScheduler.pendingReason = undefined;
    if (pending && syncIsConfigured(readSettings(context))) {
      void requestSync(context, pending);
    }
  }
}
```

- [ ] **Step 4: Update command registration and callers**

Change the manual command:

```ts
await syncNow(context, "manual");
```

to:

```ts
await requestSync(context, "manual");
```

Change all other `syncNow(context, "...")` calls:

```ts
void requestSync(context, "auto");
void requestSync(context, "watch");
```

- [ ] **Step 5: Run TypeScript build**

Run:

```powershell
Push-Location extensions\vscode
npm run build
Pop-Location
```

Expected:

- TypeScript compilation succeeds.

---

## Task 5: Make Sync Phases, Notifications, And Backoff Policy-Aware

**Files:**
- Modify: `extensions/vscode/src/extension.ts`

- [ ] **Step 1: Update `runSyncNow` phase status**

Inside `runSyncNow`, before status/import commands, set pulling:

```ts
setSyncStatus(context, "pulling");
```

Before export, set pushing:

```ts
setSyncStatus(context, "pushing");
```

The command sequence should read:

```ts
setSyncStatus(context, "pulling");
const status = await runCodexUsage(executablePath, buildSyncStatusArgs(options));
const summary = parseSyncStatusSummary(status.stdout);
if (summary.conflicts > 0) {
  setSyncStatus(context, "conflict", `${summary.conflicts} conflict${summary.conflicts === 1 ? "" : "s"}`);
  throw new Error(`Codex sync has ${summary.conflicts} conflict${summary.conflicts === 1 ? "" : "s"}. Run Codex Usage: Sync Status.`);
}
await runCodexUsage(executablePath, buildSyncImportArgs(options));
setSyncStatus(context, "pushing");
await runCodexUsage(executablePath, buildSyncExportArgs(options));
```

- [ ] **Step 2: Replace success notification behavior**

Replace:

```ts
void vscode.window.showInformationMessage(`Codex sync complete (${reason}).`);
```

with:

```ts
if (reason === "manual") {
  void vscode.window.showInformationMessage("Codex sync complete.");
} else {
  output.appendLine(`[sync] auto sync complete (${reason})`);
}
```

- [ ] **Step 3: Replace failure notification behavior**

Replace the catch block in `runSyncNow` with:

```ts
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    setSyncStatus(context, message.toLowerCase().includes("conflict") ? "conflict" : "issue", message);
    if (reason === "manual") {
      void vscode.window.showWarningMessage(`Codex sync failed: ${message}`);
      return;
    }

    syncScheduler.autoFailureCount += 1;
    const delay = syncBackoffMs(syncScheduler.autoFailureCount);
    syncScheduler.nextAutoSyncAllowedAt = Date.now() + delay;
    output.appendLine(`[sync] auto sync backoff ${Math.round(delay / 1000)}s after ${syncScheduler.autoFailureCount} failure(s)`);

    const shouldNotify = syncFailureRequiresNotification(message);
    const canNotify = Date.now() - syncScheduler.lastAutoWarningAt >= SYNC_AUTO_WARNING_COOLDOWN_MS;
    if (shouldNotify && canNotify && readSettings(context).sync.enabled) {
      syncScheduler.lastAutoWarningAt = Date.now();
      void vscode.window.showWarningMessage(`Codex sync needs attention: ${message}`);
    }
  }
```

- [ ] **Step 4: Ensure `runScheduledSync` does not reset failures after failed runs**

The previous step catches errors inside `runSyncNow`, so `runScheduledSync` needs a success signal. Change `runSyncNow` to return `Promise<boolean>`:

```ts
async function runSyncNow(context: vscode.ExtensionContext, reason: SyncReason): Promise<boolean> {
```

Return `true` after success handling. Return `false` at the end of the catch block.

In `runScheduledSync`, change:

```ts
await runSyncNow(context, reason);
syncScheduler.autoFailureCount = 0;
syncScheduler.nextAutoSyncAllowedAt = 0;
syncScheduler.lastError = "";
syncScheduler.lastSyncAt = Date.now();
setSyncStatus(context, "idle");
```

to:

```ts
const ok = await runSyncNow(context, reason);
if (ok) {
  syncScheduler.autoFailureCount = 0;
  syncScheduler.nextAutoSyncAllowedAt = 0;
  syncScheduler.lastError = "";
  syncScheduler.lastSyncAt = Date.now();
  setSyncStatus(context, "idle");
}
```

- [ ] **Step 5: Run TypeScript build**

Run:

```powershell
Push-Location extensions\vscode
npm run build
Pop-Location
```

Expected:

- TypeScript compilation succeeds.

---

## Task 6: Harden Timers, Watchers, And Sync-Off Behavior

**Files:**
- Modify: `extensions/vscode/src/extension.ts`

- [ ] **Step 1: Add `clearSyncDebounce`**

Near `disposeSyncWatchers`, add:

```ts
function clearSyncDebounce(): void {
  if (syncDebounce) {
    clearTimeout(syncDebounce);
    syncDebounce = undefined;
  }
}
```

- [ ] **Step 2: Use `clearSyncDebounce` in deactivate**

Replace:

```ts
if (syncDebounce) {
  clearTimeout(syncDebounce);
}
```

with:

```ts
clearSyncDebounce();
```

- [ ] **Step 3: Reset scheduler when sync is disabled**

Add:

```ts
function resetSyncSchedulerWhenDisabled(context: vscode.ExtensionContext): void {
  const settings = readSettings(context);
  if (settings.sync.enabled) {
    return;
  }
  clearSyncDebounce();
  syncScheduler.pendingReason = undefined;
  syncScheduler.nextAutoSyncAllowedAt = 0;
  syncScheduler.autoFailureCount = 0;
  syncScheduler.lastError = "";
  setSyncStatus(context, "off");
}
```

- [ ] **Step 4: Call reset from configuration changes**

In the configuration watcher, after `configureSyncWatcher(context);`, add:

```ts
resetSyncSchedulerWhenDisabled(context);
```

- [ ] **Step 5: Make watcher setup clear pending timers**

At the start of `configureSyncWatcher`, after `disposeSyncWatchers();`, add:

```ts
clearSyncDebounce();
```

- [ ] **Step 6: Update file-change debounce to 30 seconds and status waiting**

Replace the watcher `schedule` function with:

```ts
  const schedule = () => {
    const latestSettings = readSettings(context);
    if (!latestSettings.sync.enabled || !latestSettings.sync.autoPush) {
      clearSyncDebounce();
      setSyncStatus(context, latestSettings.sync.enabled ? "idle" : "off");
      return;
    }
    clearSyncDebounce();
    setSyncStatus(context, "waiting");
    syncDebounce = setTimeout(() => {
      syncDebounce = undefined;
      void requestSync(context, "watch");
    }, SYNC_FILE_CHANGE_DEBOUNCE_MS);
  };
```

- [ ] **Step 7: Update `syncOnFocus` to use scheduler**

Replace:

```ts
await syncNow(context, "auto");
```

with:

```ts
await requestSync(context, "auto");
```

- [ ] **Step 8: Run TypeScript build**

Run:

```powershell
Push-Location extensions\vscode
npm run build
Pop-Location
```

Expected:

- TypeScript compilation succeeds.

---

## Task 7: Update Docs And Version

**Files:**
- Modify: `CHANGELOG.md`
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`

- [ ] **Step 1: Bump versions to 0.1.14**

Change `pyproject.toml`:

```toml
version = "0.1.14"
```

Change `extensions/vscode/package.json`:

```json
"version": "0.1.14"
```

- [ ] **Step 2: Refresh lock files**

Run:

```powershell
uv lock
Push-Location extensions\vscode
npm install --package-lock-only
Pop-Location
```

Expected:

- `uv.lock` updates `codex-usage` to `0.1.14`.
- `extensions/vscode/package-lock.json` updates to `0.1.14`.
- Existing npm audit output may still mention the current dev dependency vulnerabilities; do not run `npm audit fix` in this slice.

- [ ] **Step 3: Update changelog**

Add above `0.1.13` in `CHANGELOG.md`:

```markdown
## 0.1.14 - Sync Scheduler Hardening

- Added single-flight sync scheduling so background triggers do not start overlapping sync runs.
- Added calmer auto sync timing with focus cooldown, file-change debounce, and failure backoff.
- Moved normal background sync feedback into the VS Code status bar and output channel.
- Kept visible notifications for manual sync and action-needed failures such as conflicts.
- Clearing Sync Off now cancels pending file-change sync timers and prevents new auto sync runs.
```

- [ ] **Step 4: Update root README sync section**

In `README.md`, under `## Experimental Conversation Sync`, add:

```markdown
Background sync is intentionally quiet. The VS Code status bar shows the current sync state, such as `Sync:Off`, `Sync:Idle`, `Sync:Waiting`, `Sync:Pulling`, `Sync:Pushing`, `Sync:Conflict`, or `Sync:Issue`. Automatic sync logs details to the Codex Usage output channel; visible notifications are reserved for manual sync and action-needed failures.
```

- [ ] **Step 5: Update extension README sync section**

In `extensions/vscode/README.md`, under `## Experimental Sync`, add:

```markdown
The status bar is the primary background sync indicator. Automatic sync uses a focus cooldown, a file-change debounce, and failure backoff to avoid noisy repeated runs. Normal automatic success/failure details go to the Codex Usage output channel; popups are reserved for manual sync and action-needed failures such as conflicts.
```

- [ ] **Step 6: Run docs wording check**

Run:

```powershell
rg "2-second|2 second|thread picker|selected-thread sync" README.md extensions\vscode\README.md CHANGELOG.md extensions\vscode\package.json
```

Expected:

- No stale sync timing or old thread-picker user-facing wording remains, except historical changelog entries where old wording is describing an older release.

---

## Task 8: Verification And Packaging

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
- [ ] Confirm status bar includes sync state, for example `Sync:Off` or `Sync:Idle`.
- [ ] Turn Sync Off and confirm pending background sync warnings stop after any already-running operation finishes.
- [ ] Turn Sync On with auto push enabled, edit a selected session JSONL indirectly by using Codex, and confirm status changes to `Sync:Waiting` before one debounced sync.
- [ ] Focus VS Code repeatedly and confirm it does not run auto sync more than once inside the cooldown.
- [ ] Run `Codex Usage: Sync Now` and confirm manual success/failure still shows visible feedback.
- [ ] Force or observe a conflict and confirm it shows `Sync:Conflict` plus a visible warning.

---

## Rollback Plan

- [ ] If scheduler behavior is too quiet, keep single-flight/cooldown but add one visible rate-limited auto warning for any repeated failure after three failed attempts.
- [ ] If status bar text is too long, reduce text to `Codex Usage: 7d` and move sync state fully into tooltip plus dashboard action strip.
- [ ] If file-change debounce feels too slow, lower `SYNC_FILE_CHANGE_DEBOUNCE_MS` from `30_000` to `15_000` while keeping single-flight and backoff.
