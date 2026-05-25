# Sync Setup UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace daunting raw sync settings text boxes with a VS Code-native setup flow: users choose a sync folder with a folder picker, choose threads with a QuickPick, and manage sync from dashboard/commands instead of editing `sync.dir` and `sync.threadIds` manually.

**Architecture:** Keep the Python sync CLI unchanged. Move user-facing sync selection state into the VS Code extension's `globalState`, keeping only true behavioral toggles in Settings. TypeScript remains responsible for VS Code UI, command orchestration, persisted extension state, sync status messages, and dashboard command links.

**Tech Stack:** VS Code Extension API, TypeScript, Node standard APIs, existing bundled Python executable, existing HTML/SVG dashboard, Mocha-style extension tests.

---

## Desired UX

- Users should not need to type a sync folder path in Settings.
- Users should not need to paste thread ids into an array setting.
- The main entry point should be a command and dashboard button:
  - `Codex Usage: Configure Sync`
  - dashboard action strip label like `Sync: Off`, `Sync: Select Folder`, or `Sync: 3 threads`
- Sync folder selection should use `vscode.window.showOpenDialog`.
- Thread selection should reuse the existing thread QuickPick and selected dashboard project filters.
- Existing beta users should not lose their current `sync.dir` or `sync.threadIds`; migrate or fall back from old settings into `globalState`.
- Keep sync off until the user explicitly enables it or completes the configure flow.

---

## Phase 1: Inspect Current Surfaces

- [ ] Review current extension sync settings and commands.
  - Files:
    - `extensions/vscode/package.json`
    - `extensions/vscode/src/extension.ts`
    - `extensions/vscode/src/core.ts`
    - `extensions/vscode/test/core.test.js`
  - Confirm current setting keys:
    - `codexUsage.sync.enabled`
    - `codexUsage.sync.dir`
    - `codexUsage.sync.threadIds`
    - `codexUsage.sync.autoPull`
    - `codexUsage.sync.autoPush`
  - Confirm current commands:
    - `codexUsage.selectSyncThreads`
    - `codexUsage.syncNow`
    - `codexUsage.syncStatus`
    - `codexUsage.openSyncFolder`

- [ ] Check whether current docs mention raw sync settings.
  - Files:
    - `README.md`
    - `extensions/vscode/README.md`
    - `PRIVACY.md`
    - `CHANGELOG.md`

---

## Phase 2: Add Global State Sync Helpers

- [ ] Add sync global state keys near existing project-key state helpers.
  - File: `extensions/vscode/src/core.ts`
  - Add constants:
    ```ts
    export const SYNC_DIR_STATE_KEY = "syncDir";
    export const SYNC_THREAD_IDS_STATE_KEY = "syncThreadIds";
    ```

- [ ] Add pure helper functions for sync state normalization.
  - File: `extensions/vscode/src/core.ts`
  - Add:
    ```ts
    export function readSyncDirState(state?: vscode.Memento): string {
      const value = state?.get<string>(SYNC_DIR_STATE_KEY, "");
      return typeof value === "string" ? value.trim() : "";
    }

    export function readSyncThreadIdsState(state?: vscode.Memento): string[] {
      const value = state?.get<string[]>(SYNC_THREAD_IDS_STATE_KEY, []);
      return Array.isArray(value)
        ? value.map((item) => String(item).trim()).filter(Boolean)
        : [];
    }
    ```
  - Keep helper names and signatures testable without launching UI.

- [ ] Update `readSettings(context)` so `settings.sync.dir` and `settings.sync.threadIds` come from `globalState`.
  - File: `extensions/vscode/src/extension.ts`
  - Keep `enabled`, `autoPull`, and `autoPush` from VS Code settings.
  - Read dir/thread ids from `readSyncDirState(context?.globalState)` and `readSyncThreadIdsState(context?.globalState)`.

- [ ] Add migration helper for existing beta users.
  - File: `extensions/vscode/src/extension.ts`
  - Function:
    ```ts
    async function migrateDeprecatedSyncSettings(context: vscode.ExtensionContext): Promise<void>
    ```
  - Behavior:
    - Read existing config values `sync.dir` and `sync.threadIds`.
    - If `globalState.syncDir` is empty and old `sync.dir` is non-empty, store it in `globalState`.
    - If `globalState.syncThreadIds` is empty and old `sync.threadIds` has entries, store normalized ids in `globalState`.
    - Do not remove or edit the user's old settings automatically.
  - Call it during `activate()` before initial `readSettings(context)`.

---

## Phase 3: Remove Raw Sync Dir/Thread Settings From Settings UI

- [ ] Remove contributed settings from package metadata.
  - File: `extensions/vscode/package.json`
  - Remove:
    - `codexUsage.sync.dir`
    - `codexUsage.sync.threadIds`
  - Keep:
    - `codexUsage.sync.enabled`
    - `codexUsage.sync.autoPull`
    - `codexUsage.sync.autoPush`

- [ ] Confirm code does not rely on `config.get("sync.dir")` or `config.get("sync.threadIds")` except inside the migration helper.
  - Command:
    ```powershell
    rg "sync\.dir|sync\.threadIds" extensions/vscode/src extensions/vscode/test extensions/vscode/package.json
    ```
  - Expected after implementation:
    - Only migration/fallback code and tests should mention deprecated keys.

---

## Phase 4: Add Configure Sync Command

- [ ] Add command contribution.
  - File: `extensions/vscode/package.json`
  - Add command:
    ```json
    {
      "command": "codexUsage.configureSync",
      "title": "Codex Usage: Configure Sync"
    }
    ```
  - Add activation event:
    ```json
    "onCommand:codexUsage.configureSync"
    ```

- [ ] Add a folder picker helper.
  - File: `extensions/vscode/src/extension.ts`
  - Function:
    ```ts
    async function selectSyncFolder(context: vscode.ExtensionContext): Promise<string | undefined>
    ```
  - Use:
    ```ts
    vscode.window.showOpenDialog({
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      openLabel: "Use Sync Folder",
      title: "Select Codex Sync Folder"
    })
    ```
  - Persist the chosen folder path to `context.globalState.update(SYNC_DIR_STATE_KEY, selectedPath)`.
  - Return `undefined` on cancel.

- [ ] Refactor thread selection to persist to global state.
  - File: `extensions/vscode/src/extension.ts`
  - Update `selectSyncThreadSettings(context)`:
    - Continue loading threads with the bundled CLI.
    - Continue filtering by selected dashboard projects.
    - Continue showing a multi-select QuickPick.
    - Persist selected thread ids to `SYNC_THREAD_IDS_STATE_KEY`.
    - Return `true` when selection changed, `false` on cancel.
  - Remove writes to `codexUsage.sync.threadIds`.

- [ ] Implement `configureSync(context)`.
  - File: `extensions/vscode/src/extension.ts`
  - Flow:
    - Show folder picker if no sync dir is configured, or ask whether to keep/change existing folder.
    - Enable `codexUsage.sync.enabled` in global settings when the user completes folder selection.
    - Open the thread picker.
    - Refresh settings, status bar, watcher, and dashboard.
  - Keep cancellation graceful:
    - Cancelled folder picker should leave settings unchanged.
    - Cancelled thread picker should keep the folder and existing thread selection.

- [ ] Register the command.
  - File: `extensions/vscode/src/extension.ts`
  - Add:
    ```ts
    context.subscriptions.push(
      vscode.commands.registerCommand("codexUsage.configureSync", async () => {
        await configureSync(context);
      })
    );
    ```

---

## Phase 5: Improve Existing Sync Commands

- [ ] Update `openSyncFolder`.
  - File: `extensions/vscode/src/extension.ts`
  - Change signature to accept context:
    ```ts
    async function openSyncFolder(context: vscode.ExtensionContext): Promise<void>
    ```
  - If no sync dir is configured:
    - Open the folder picker.
    - If a folder is chosen, create it and open it.
    - If cancelled, show no noisy error.

- [ ] Update `syncNow` and `syncStatus` unconfigured behavior.
  - File: `extensions/vscode/src/extension.ts`
  - If sync is not configured, show an information message with action:
    ```ts
    const choice = await vscode.window.showInformationMessage(
      "Codex sync is not configured.",
      "Configure Sync"
    );
    ```
  - If chosen, run `configureSync(context)`.

- [ ] Make status bar tooltip friendlier.
  - File: `extensions/vscode/src/extension.ts`
  - Include:
    - Range
    - Project filter count
    - Theme
    - Sync enabled/disabled
    - Sync folder present/missing
    - Selected sync thread count

---

## Phase 6: Add Dashboard Sync Control

- [ ] Extend webview control state.
  - File: `extensions/vscode/src/core.ts`
  - Add to `WebviewControlState`:
    ```ts
    sync: {
      enabled: boolean;
      dir: string;
      threadIds: string[];
    };
    ```

- [ ] Add a sync control label helper.
  - File: `extensions/vscode/src/core.ts`
  - Suggested labels:
    - `Sync: Off` when disabled.
    - `Sync: Select Folder` when enabled but no dir.
    - `Sync: Select Threads` when dir exists but no threads.
    - `Sync: 1 thread` / `Sync: N threads` when configured.

- [ ] Add command URI to allowlist.
  - File: `extensions/vscode/src/core.ts`
  - Add `codexUsage.configureSync` to `WEBVIEW_COMMANDS`.

- [ ] Render sync control in action strip.
  - File: `extensions/vscode/src/core.ts`
  - Place it near `Projects` and `Theme`, before `Refresh`.
  - Keep `enableScripts: false`.
  - Ensure generated link uses only allowlisted command URI:
    ```html
    <a class="codex-control" href="command:codexUsage.configureSync">Sync: Off</a>
    ```

- [ ] Update calls to `injectWebviewControls`.
  - File: `extensions/vscode/src/extension.ts`
  - Pass current sync state and package version label.

---

## Phase 7: Tests

- [ ] Add pure unit tests for global sync state helpers.
  - File: `extensions/vscode/test/core.test.js`
  - Cover:
    - Empty state returns empty values.
    - String dir is trimmed.
    - Thread ids are trimmed and empty entries removed.

- [ ] Add tests for report argument builders.
  - File: `extensions/vscode/test/core.test.js`
  - Confirm no command emits removed settings-derived args.
  - Existing sync arg tests should still pass with `settings.sync.dir` and `settings.sync.threadIds` populated from normalized settings.

- [ ] Add tests for webview controls.
  - File: `extensions/vscode/test/core.test.js`
  - Confirm action strip includes:
    - `command:codexUsage.configureSync`
    - `Sync: Off`
    - `Sync: 2 threads`
  - Confirm command allowlist includes `codexUsage.configureSync`.
  - Confirm no scripts or remote assets are introduced.

- [ ] Add package metadata test or assertion.
  - File: `extensions/vscode/test/core.test.js`
  - Read `extensions/vscode/package.json`.
  - Assert it no longer contributes:
    - `codexUsage.sync.dir`
    - `codexUsage.sync.threadIds`
  - Assert it still contributes:
    - `codexUsage.sync.enabled`
    - `codexUsage.sync.autoPull`
    - `codexUsage.sync.autoPush`

- [ ] Run TypeScript tests.
  - Command:
    ```powershell
    Push-Location extensions\vscode; npm test; Pop-Location
    ```
  - Expected:
    - All extension unit tests pass.

---

## Phase 8: Docs And Version

- [ ] Bump version for the next beta.
  - Files:
    - `extensions/vscode/package.json`
    - `extensions/vscode/package-lock.json`
    - `pyproject.toml`
    - `uv.lock`
  - Target version: `0.1.11`

- [ ] Update root README.
  - File: `README.md`
  - Add/adjust experimental sync instructions:
    - Use `Codex Usage: Configure Sync`.
    - Choose a sync folder with the folder picker.
    - Select threads from the thread picker.
    - Sync remains bring-your-own-folder and does not use cloud APIs directly.
  - Remove any instruction telling users to edit `sync.dir` or `sync.threadIds` manually.

- [ ] Update extension README.
  - File: `extensions/vscode/README.md`
  - Document commands:
    - `Codex Usage: Configure Sync`
    - `Codex Usage: Select Sync Threads`
    - `Codex Usage: Sync Now`
    - `Codex Usage: Sync Status`
    - `Codex Usage: Open Sync Folder`
  - Settings section should list only:
    - `codexUsage.range`
    - `codexUsage.theme`
    - `codexUsage.sync.enabled`
    - `codexUsage.sync.autoPull`
    - `codexUsage.sync.autoPush`

- [ ] Update privacy doc.
  - File: `PRIVACY.md`
  - Clarify:
    - Sync folder path and selected thread ids are stored locally in VS Code extension state.
    - The extension does not upload data.
    - External sync happens only through the user's chosen folder provider.

- [ ] Update changelog.
  - File: `CHANGELOG.md`
  - Add `0.1.11` entry:
    - Adds VS Code-native sync setup flow.
    - Removes raw sync folder/thread id settings from Settings UI.
    - Keeps sync behavior experimental and user-controlled.

---

## Phase 9: Verification And Packaging

- [ ] Run Python tests to guard against accidental CLI regressions.
  - Command:
    ```powershell
    uv run pytest
    ```
  - Expected:
    - All tests pass.

- [ ] Run extension tests and build.
  - Commands:
    ```powershell
    Push-Location extensions\vscode
    npm test
    npm run build
    Pop-Location
    ```
  - Expected:
    - Tests pass.
    - TypeScript build succeeds.

- [ ] Build bundled Windows executable and VSIX.
  - Command:
    ```powershell
    Push-Location extensions\vscode
    npm run package:vsix:win
    Pop-Location
    ```
  - Expected:
    - `output/codex-usage-dashboard-win32-x64.vsix` is rebuilt.
    - Package contains `bin/win32-x64/codex-usage.exe`.

- [ ] Inspect package metadata after packaging.
  - Command:
    ```powershell
    Push-Location extensions\vscode
    npx vsce ls --tree
    Pop-Location
    ```
  - Expected:
    - No TypeScript source/tests/dev configs.
    - `media/icon.png`, `out/*.js`, `bin/win32-x64/codex-usage.exe`, README, LICENSE are present.

---

## Manual Smoke Checklist

- [ ] Install rebuilt VSIX manually only when ready:
  ```powershell
  code --install-extension output\codex-usage-dashboard-win32-x64.vsix --force
  ```

- [ ] In normal VS Code, confirm Settings UI no longer shows:
  - `Codex Usage > Sync: Dir`
  - `Codex Usage > Sync: Thread Ids`

- [ ] Run `Codex Usage: Configure Sync`.
  - Confirm folder picker opens.
  - Choose a OneDrive/Dropbox/Syncthing/test folder.
  - Confirm thread picker opens.
  - Select one or more threads.

- [ ] Open dashboard.
  - Confirm action strip shows useful sync state:
    - `Sync: Off`, `Sync: Select Threads`, or `Sync: N threads`
  - Click sync action strip button.
  - Confirm configure flow opens without scripts enabled in the webview.

- [ ] Run sync commands:
  - `Codex Usage: Sync Status`
  - `Codex Usage: Sync Now`
  - `Codex Usage: Open Sync Folder`
  - Confirm notifications are readable and output channel logs are useful.

- [ ] Test unconfigured path.
  - Clear sync state or use a clean VS Code profile.
  - Run `Sync Now`.
  - Confirm it offers `Configure Sync` instead of failing with an obscure missing setting message.

---

## Rollback Plan

- [ ] If the configure flow is buggy, keep the Python sync CLI unchanged and revert only the VS Code state/UI changes.
- [ ] If migration causes unexpected behavior, remove migration fallback and require users to reconfigure sync through the new command.
- [ ] If globalState persistence is problematic, temporarily restore hidden advanced settings rather than visible raw settings.

---

## Non-Goals

- [ ] Do not add cloud provider integrations.
- [ ] Do not sync all Codex state.
- [ ] Do not change Python sync CLI commands.
- [ ] Do not add new runtime dependencies.
- [ ] Do not add JavaScript inside the dashboard webview.
