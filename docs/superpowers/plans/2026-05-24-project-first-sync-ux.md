# Project-First Sync UX Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make sync feel project-first and conversation-friendly, including rough per-project sync storage estimates, while keeping Codex thread/session ids as the internal sync unit.

**Architecture:** Keep the Python CLI command names and sync manifest format unchanged because session JSONL files are still the resumable unit. Extend the `threads --json` payload with local file-size metadata so the extension can estimate sync storage without extra dependencies or cloud-provider APIs. Update the VS Code extension so users first choose sync projects, see an estimated sync size for each project, then choose whether to sync all conversations in those projects or only selected conversations.

**Tech Stack:** VS Code Extension API, TypeScript, Node standard APIs, existing bundled Python executable, existing Python CLI `threads` and `sync` commands, Mocha-style Node tests.

---

## Mental Model

- **Project** means a repo/workspace identity shown in Project Breakdown, such as `codex_usage` or `ops-board`.
- **Conversation** means one Codex thread/session within a project.
- **Thread id** remains the internal CLI/storage identifier.
- The UI should say **conversation** unless it is showing diagnostics, JSON, CLI docs, or implementation details.
- Sync should start from projects because users think in projects.
- Sync operations still pass `--thread-id` to the bundled CLI after the extension resolves the selected conversations.
- Disk estimates are rough local estimates based on session JSONL file sizes plus a small per-conversation manifest/index/metadata allowance. They do not predict cloud-provider filesystem overhead, version-history retention, or duplicate storage behavior.

---

## File Structure

- Modify `src/codex_usage/sync.py`
  - Add per-conversation `session_bytes` and `estimated_sync_bytes` to `ThreadInfo`.
  - Use standard-library file sizes only; no new dependencies.

- Modify `tests/test_sync.py`
  - Verify thread listings include size metadata.

- Modify `extensions/vscode/src/core.ts`
  - Add sync project and conversation mode state helpers.
  - Add project-first sync control labels.
  - Keep thread-oriented CLI builders unchanged.
  - Add pure helpers for grouping conversations into project sync choices with estimated disk usage.

- Modify `extensions/vscode/src/extension.ts`
  - Update configure flow to choose folder, projects, then conversations.
  - Resolve dynamic conversation ids before sync when mode is `allInProjects`.
  - Keep old command id `codexUsage.selectSyncThreads` for compatibility, but present it as conversations in the UI.
  - Add optional command id `codexUsage.selectSyncProjects` for direct project selection.

- Modify `extensions/vscode/test/core.test.js`
  - Add failing tests first for new global state helpers, labels, QuickPick item helpers, and package metadata.

- Modify `extensions/vscode/package.json`
  - Add command contribution `codexUsage.selectSyncProjects`.
  - Rename command title for `codexUsage.selectSyncThreads` to `Codex Usage: Select Sync Conversations`.
  - Bump version to `0.1.12`.

- Modify docs:
  - `README.md`
  - `extensions/vscode/README.md`
  - `PRIVACY.md`
  - `CHANGELOG.md`

- Modify version locks:
  - `pyproject.toml`
  - `uv.lock`
  - `extensions/vscode/package-lock.json`

---

## Task 0: Add Size Metadata To Thread Listings

**Files:**
- Modify: `src/codex_usage/sync.py`
- Modify: `tests/test_sync.py`

- [ ] **Step 1: Write failing test for thread size metadata**

In `tests/test_sync.py`, update `test_list_threads_filters_by_project_key_and_returns_titles` by adding these assertions after the existing `session_path` assertion:

```python
    expected_session_bytes = session_path.stat().st_size
    assert threads[0].session_bytes == expected_session_bytes
    assert threads[0].estimated_sync_bytes == expected_session_bytes + 4096
    assert threads[0].to_dict()["session_bytes"] == expected_session_bytes
    assert threads[0].to_dict()["estimated_sync_bytes"] == expected_session_bytes + 4096
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```powershell
uv run pytest tests\test_sync.py::test_list_threads_filters_by_project_key_and_returns_titles -q
```

Expected:

- Fails because `ThreadInfo` has no `session_bytes` or `estimated_sync_bytes` fields.

- [ ] **Step 3: Add file-size fields to `ThreadInfo`**

In `src/codex_usage/sync.py`, add near `SYNC_VERSION`:

```python
SYNC_METADATA_OVERHEAD_BYTES = 4096
```

Update `ThreadInfo`:

```python
@dataclass(frozen=True)
class ThreadInfo:
    thread_id: str
    title: str
    updated_at: str
    session_path: Path
    project_key: str
    project_label: str
    project_aliases: tuple[str, ...]
    total_tokens: int
    session_bytes: int
    estimated_sync_bytes: int
    memory_mode: str = ""
    has_base_instructions: bool = False
```

Update `to_dict` to include:

```python
            "session_bytes": self.session_bytes,
            "estimated_sync_bytes": self.estimated_sync_bytes,
```

- [ ] **Step 4: Populate size fields in `list_threads`**

In `list_threads`, before constructing `ThreadInfo`, add:

```python
            session_bytes = _file_size(path)
```

Pass:

```python
                session_bytes=session_bytes,
                estimated_sync_bytes=session_bytes + SYNC_METADATA_OVERHEAD_BYTES,
```

- [ ] **Step 5: Add safe file-size helper**

Add near other private helpers in `src/codex_usage/sync.py`:

```python
def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0
```

- [ ] **Step 6: Run sync tests**

Run:

```powershell
uv run pytest tests\test_sync.py -q
```

Expected:

- All sync tests pass.

---

## Task 1: Add Failing Core Tests For Project-First Sync State

**Files:**
- Modify: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Add imports for new helpers**

Add these names to the existing destructuring import from `../out/core`:

```js
  normalizeSyncConversationMode,
  readSyncProjectKeysState,
  readSyncConversationModeState,
  parseSyncProjectChoices,
  syncProjectQuickPickItems,
  syncConversationQuickPickItems,
```

- [ ] **Step 2: Add failing tests for sync project and conversation mode state**

Append this test near the existing sync global state tests:

```js
test("sync project keys and conversation mode are normalized from extension global state", () => {
  const state = {
    get(key, fallback) {
      if (key === "syncProjectKeys") {
        return [" repo-a ", "", "repo-a", "repo-b"];
      }
      if (key === "syncConversationMode") {
        return "allInProjects";
      }
      return fallback;
    },
  };

  assert.deepEqual(readSyncProjectKeysState(state), ["repo-a", "repo-b"]);
  assert.equal(readSyncConversationModeState(state), "allInProjects");
  assert.equal(normalizeSyncConversationMode("selectedConversations"), "selectedConversations");
  assert.equal(normalizeSyncConversationMode("allInProjects"), "allInProjects");
  assert.equal(normalizeSyncConversationMode("other"), "selectedConversations");
});
```

- [ ] **Step 3: Add failing tests for project sync estimates and QuickPick item helpers**

Append these tests near the existing project/thread parsing tests:

```js
test("parseSyncProjectChoices groups conversations and estimates disk usage by project", () => {
  const choices = parseSyncProjectChoices(
    JSON.stringify({
      threads: [
        {
          thread_id: "thread-1",
          title: "One",
          project_key: "repo-a",
          project_label: "repo-a",
          total_tokens: 1000,
          estimated_sync_bytes: 1536,
        },
        {
          thread_id: "thread-2",
          title: "Two",
          project_key: "repo-a",
          project_label: "repo-a",
          total_tokens: 2000,
          estimated_sync_bytes: 2048,
        },
      ],
    }),
    ["repo-a"],
  );

  assert.equal(choices.length, 1);
  assert.equal(choices[0].key, "repo-a");
  assert.equal(choices[0].conversationCount, 2);
  assert.equal(choices[0].estimatedSyncBytes, 3584);
  assert.match(choices[0].description, /2 conversations/);
  assert.match(choices[0].description, /3\.5 KB/);
  assert.equal(choices[0].picked, true);
});

test("syncProjectQuickPickItems adds explicit project choices without exposing raw settings", () => {
  const items = syncProjectQuickPickItems(
    [
      {
        key: "repo-a",
        label: "repo-a",
        description: "1 conversation | 1.5 KB estimated sync size",
        detail: "https://github.com/example/repo-a",
        totalTokens: 1000,
        conversationCount: 1,
        estimatedSyncBytes: 1536,
        picked: false,
      },
    ],
    ["repo-a"],
  );

  assert.equal(items.length, 1);
  assert.equal(items[0].label, "repo-a");
  assert.equal(items[0].projectKey, "repo-a");
  assert.equal(items[0].picked, true);
});

test("syncConversationQuickPickItems adds an all-conversations default item", () => {
  const items = syncConversationQuickPickItems(
    [
      {
        threadId: "thread-1",
        label: "Review dashboard",
        description: "codex_usage | 1,000 tokens | 1.5 KB",
        detail: "thread-1 | 2026-05-24T10:00:00Z",
        totalTokens: 1000,
        estimatedSyncBytes: 1536,
        picked: false,
      },
    ],
    "allInProjects",
  );

  assert.equal(items[0].label, "All conversations in selected projects");
  assert.equal(items[0].allConversations, true);
  assert.equal(items[0].picked, true);
  assert.equal(items[1].label, "Review dashboard");
  assert.match(items[1].description, /1\.5 KB/);
  assert.equal(items[1].threadId, "thread-1");
});
```

- [ ] **Step 4: Update failing dashboard label assertions**

Change existing sync label expectations from thread wording to conversation/project wording:

```js
assert.match(out, /Sync: 2 conversations/);
```

In the unconfigured label test, expect:

```js
/Sync: Off/
/Sync: Select Projects/
/Sync: All conversations in 2 projects/
```

- [ ] **Step 5: Update failing package metadata expectations**

In `package metadata no longer contributes removed manual settings`, add:

```js
assert.equal(properties["codexUsage.sync.projectKeys"], undefined);
assert.equal(properties["codexUsage.sync.conversationMode"], undefined);
```

- [ ] **Step 6: Run tests and verify they fail for missing helpers**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected:

- Build succeeds.
- Node tests fail with messages like `readSyncProjectKeysState is not a function` and `syncConversationQuickPickItems is not a function`.

---

## Task 2: Implement Core State And Label Helpers

**Files:**
- Modify: `extensions/vscode/src/core.ts`
- Test: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Add sync project and mode constants**

Add near `SYNC_THREAD_IDS_STATE_KEY`:

```ts
export const SYNC_PROJECT_KEYS_STATE_KEY = "syncProjectKeys";
export const SYNC_CONVERSATION_MODE_STATE_KEY = "syncConversationMode";
```

- [ ] **Step 2: Add conversation mode type**

Add near `SyncSettings`:

```ts
export const SYNC_CONVERSATION_MODE_VALUES = ["selectedConversations", "allInProjects"] as const;
export type SyncConversationMode = (typeof SYNC_CONVERSATION_MODE_VALUES)[number];
```

- [ ] **Step 3: Extend `SyncSettings`**

Change `SyncSettings` to include:

```ts
export type SyncSettings = {
  enabled: boolean;
  dir: string;
  projectKeys: string[];
  conversationMode: SyncConversationMode;
  threadIds: string[];
  autoPull: boolean;
  autoPush: boolean;
};
```

- [ ] **Step 4: Add mode and state readers**

Add after `readSyncThreadIdsState`:

```ts
export function normalizeSyncConversationMode(value: unknown): SyncConversationMode {
  return typeof value === "string" && SYNC_CONVERSATION_MODE_VALUES.includes(value as SyncConversationMode)
    ? (value as SyncConversationMode)
    : "selectedConversations";
}

export function readSyncProjectKeysState(state?: GlobalStateReader): string[] {
  return normalizeProjectKeys(state?.get(SYNC_PROJECT_KEYS_STATE_KEY, []));
}

export function readSyncConversationModeState(state?: GlobalStateReader): SyncConversationMode {
  return normalizeSyncConversationMode(state?.get(SYNC_CONVERSATION_MODE_STATE_KEY, "selectedConversations"));
}
```

- [ ] **Step 5: Update `normalizeSyncSettings`**

Change the returned object to include:

```ts
projectKeys: normalizeProjectKeys(input.projectKeys),
conversationMode: normalizeSyncConversationMode(input.conversationMode),
```

Place these fields between `dir` and `threadIds`.

- [ ] **Step 6: Add size-aware choice and QuickPick item helper types**

Add near `ProjectChoice` / `ThreadChoice`:

```ts
export type SyncProjectChoice = {
  key: string;
  label: string;
  description: string;
  detail: string;
  totalTokens: number;
  conversationCount: number;
  estimatedSyncBytes: number;
  picked: boolean;
};

export type SyncProjectQuickPickItem = {
  label: string;
  description?: string;
  detail?: string;
  picked?: boolean;
  projectKey: string;
};

export type SyncConversationQuickPickItem = {
  label: string;
  description?: string;
  detail?: string;
  picked?: boolean;
  threadId?: string;
  allConversations?: boolean;
};
```

Also add `estimatedSyncBytes` to `ThreadChoice`:

```ts
export type ThreadChoice = {
  threadId: string;
  label: string;
  description: string;
  detail: string;
  totalTokens: number;
  estimatedSyncBytes: number;
  picked: boolean;
};
```

- [ ] **Step 7: Add project-size parser and QuickPick item helper functions**

Add after `parseThreadChoices`:

```ts
export function parseSyncProjectChoices(threadsJson: string, selectedProjectKeys: string[] = []): SyncProjectChoice[] {
  let payload: unknown;
  try {
    payload = JSON.parse(threadsJson);
  } catch (error) {
    throw new Error(`Could not parse Codex thread JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
  if (!isRecord(payload) || !Array.isArray(payload.threads)) {
    throw new Error("Codex thread JSON did not contain a threads array.");
  }

  const selected = new Set(normalizeProjectKeys(selectedProjectKeys));
  const byProject = new Map<string, SyncProjectChoice>();
  for (const row of payload.threads) {
    if (!isRecord(row) || typeof row.project_key !== "string") {
      continue;
    }
    const key = row.project_key.trim();
    if (!key) {
      continue;
    }
    const label = stringValue(row.project_label) || key;
    const totalTokens = numberValue(row.total_tokens);
    const estimatedBytes = numberValue(row.estimated_sync_bytes);
    const existing = byProject.get(key);
    if (existing) {
      existing.totalTokens += totalTokens;
      existing.conversationCount += 1;
      existing.estimatedSyncBytes += estimatedBytes;
      existing.description = syncProjectDescription(existing.conversationCount, existing.estimatedSyncBytes);
      continue;
    }
    byProject.set(key, {
      key,
      label,
      totalTokens,
      conversationCount: 1,
      estimatedSyncBytes: estimatedBytes,
      description: syncProjectDescription(1, estimatedBytes),
      detail: key,
      picked: selected.has(key),
    });
  }
  return [...byProject.values()].sort((a, b) => b.estimatedSyncBytes - a.estimatedSyncBytes);
}

export function syncProjectQuickPickItems(
  choices: SyncProjectChoice[],
  selectedProjectKeys: string[],
): SyncProjectQuickPickItem[] {
  const selected = new Set(normalizeProjectKeys(selectedProjectKeys));
  return choices.map((choice) => ({
    label: choice.label,
    description: choice.description,
    detail: choice.detail,
    picked: selected.has(choice.key),
    projectKey: choice.key,
  }));
}

export function syncConversationQuickPickItems(
  choices: ThreadChoice[],
  mode: SyncConversationMode,
): SyncConversationQuickPickItem[] {
  return [
    {
      label: "All conversations in selected projects",
      description: "Automatically include current and future conversations for these projects",
      picked: mode === "allInProjects",
      allConversations: true,
    },
    ...choices.map((choice) => ({
      label: choice.label,
      description: choice.description,
      detail: choice.detail,
      picked: mode === "selectedConversations" ? choice.picked : false,
      threadId: choice.threadId,
    })),
  ];
}
```

Add helper functions near `formatInt`:

```ts
function syncProjectDescription(conversationCount: number, estimatedBytes: number): string {
  const conversationLabel = `${conversationCount} conversation${conversationCount === 1 ? "" : "s"}`;
  return `${conversationLabel} | ${formatBytes(estimatedBytes)} estimated sync size`;
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  if (unitIndex === 0) {
    return `${Math.round(size)} ${units[unitIndex]}`;
  }
  return `${size.toFixed(1)} ${units[unitIndex]}`;
}
```

Update `parseThreadChoices` so conversation rows also show their own estimated size:

```ts
    const totalTokens = numberValue(row.total_tokens);
    const estimatedSyncBytes = numberValue(row.estimated_sync_bytes);
    choices.push({
      threadId,
      label,
      totalTokens,
      estimatedSyncBytes,
      description: `${project} | ${formatInt(totalTokens)} tokens | ${formatBytes(estimatedSyncBytes)}`,
      detail: updated ? `${threadId} | ${updated}` : threadId,
      picked: selected.has(threadId),
    });
```

- [ ] **Step 8: Update sync control label**

Replace `syncControlLabel` with:

```ts
function syncControlLabel(sync: WebviewControlState["sync"]): string {
  const normalized = normalizeSyncSettings(sync ?? {});
  if (!normalized.enabled) {
    return "Sync: Off";
  }
  if (!normalized.dir) {
    return "Sync: Select Folder";
  }
  if (normalized.projectKeys.length === 0 && normalized.threadIds.length === 0) {
    return "Sync: Select Projects";
  }
  if (normalized.conversationMode === "allInProjects") {
    const count = normalized.projectKeys.length;
    if (count === 1) {
      return "Sync: All conversations in 1 project";
    }
    return `Sync: All conversations in ${count} projects`;
  }
  if (normalized.threadIds.length === 0) {
    return "Sync: Select Conversations";
  }
  if (normalized.threadIds.length === 1) {
    return "Sync: 1 conversation";
  }
  return `Sync: ${normalized.threadIds.length} conversations`;
}
```

- [ ] **Step 9: Extend `WebviewControlState.sync`**

Change the `sync` field type to include the new fields:

```ts
sync?: Pick<SyncSettings, "enabled" | "dir" | "projectKeys" | "conversationMode" | "threadIds">;
```

- [ ] **Step 10: Run tests and verify core helper tests pass**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected:

- The new core tests pass.
- Some extension/package behavior tests may still fail until package metadata and extension flow are updated.

---

## Task 3: Update VS Code Package Commands And Titles

**Files:**
- Modify: `extensions/vscode/package.json`
- Modify: `extensions/vscode/package-lock.json`
- Test: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Add direct sync project command metadata**

In `activationEvents`, add:

```json
"onCommand:codexUsage.selectSyncProjects"
```

In `contributes.commands`, add before sync conversations:

```json
{
  "command": "codexUsage.selectSyncProjects",
  "title": "Codex Usage: Select Sync Projects"
}
```

- [ ] **Step 2: Rename sync thread command title**

Change:

```json
{
  "command": "codexUsage.selectSyncThreads",
  "title": "Codex Usage: Select Sync Threads"
}
```

to:

```json
{
  "command": "codexUsage.selectSyncThreads",
  "title": "Codex Usage: Select Sync Conversations"
}
```

Keep the command id unchanged so older command links and keybindings do not break.

- [ ] **Step 3: Bump package version**

Change `extensions/vscode/package.json`:

```json
"version": "0.1.12"
```

- [ ] **Step 4: Refresh package lock**

Run:

```powershell
Push-Location extensions\vscode
npm install --package-lock-only
Pop-Location
```

Expected:

- `extensions/vscode/package-lock.json` updates package versions to `0.1.12`.
- Existing dependency vulnerability output may still appear from `npm audit`; do not run `npm audit fix` in this feature.

- [ ] **Step 5: Add package metadata test for command titles**

Append to `extensions/vscode/test/core.test.js`:

```js
test("package metadata uses project and conversation wording for sync commands", () => {
  const commands = new Map(packageJson.contributes.commands.map((item) => [item.command, item.title]));

  assert.equal(commands.get("codexUsage.selectSyncProjects"), "Codex Usage: Select Sync Projects");
  assert.equal(commands.get("codexUsage.selectSyncThreads"), "Codex Usage: Select Sync Conversations");
});
```

- [ ] **Step 6: Run tests and verify package metadata tests pass**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected:

- Package metadata tests pass.
- Extension flow may still need updates before all tests pass if type changes create compile errors.

---

## Task 4: Implement Project-First Configure Sync Flow

**Files:**
- Modify: `extensions/vscode/src/extension.ts`
- Modify: `extensions/vscode/src/core.ts`
- Test: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Import new helpers and constants**

In `extensions/vscode/src/extension.ts`, add imports:

```ts
  SYNC_PROJECT_KEYS_STATE_KEY,
  SYNC_CONVERSATION_MODE_STATE_KEY,
  readSyncProjectKeysState,
  readSyncConversationModeState,
  parseSyncProjectChoices,
  syncProjectQuickPickItems,
  syncConversationQuickPickItems,
```

- [ ] **Step 2: Register direct sync project command**

In `activate`, add:

```ts
const selectSyncProjectsCommand = vscode.commands.registerCommand("codexUsage.selectSyncProjects", async () => {
  await selectSyncProjectSettings(context);
});
```

Add `selectSyncProjectsCommand` to `context.subscriptions.push(...)`.

- [ ] **Step 3: Update `readSettings` to read sync project state**

Change the `normalizeSyncSettings` input:

```ts
const sync = normalizeSyncSettings({
  enabled: config.get<boolean>("sync.enabled", false),
  dir: readSyncDirState(context?.globalState),
  projectKeys: readSyncProjectKeysState(context?.globalState),
  conversationMode: readSyncConversationModeState(context?.globalState),
  threadIds: readSyncThreadIdsState(context?.globalState),
  autoPull: config.get<boolean>("sync.autoPull", true),
  autoPush: config.get<boolean>("sync.autoPush", true),
});
```

- [ ] **Step 4: Add migration for old selected thread ids**

Keep existing `sync.threadIds` migration and set mode to selected when legacy ids are found:

```ts
if (existingThreadIds.length === 0 && legacyThreadIds.length > 0) {
  await context.globalState.update(SYNC_THREAD_IDS_STATE_KEY, legacyThreadIds);
  await context.globalState.update(SYNC_CONVERSATION_MODE_STATE_KEY, "selectedConversations");
}
```

- [ ] **Step 5: Add `selectSyncProjectSettings`**

Add this function near `selectProjectSettings`:

```ts
async function selectSyncProjectSettings(context: vscode.ExtensionContext): Promise<boolean> {
  const settings = readSettings(context);
  try {
    const executablePath = await resolveBundledExecutable(context);
    const result = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Window,
        title: "Loading Codex sync projects",
      },
      () =>
        runCodexUsage(
          executablePath,
          buildThreadsArgs({
            projectTransitions: settings.projectTransitions,
          }),
        ),
    );
    const choices = parseSyncProjectChoices(result.stdout, settings.sync.projectKeys.length > 0 ? settings.sync.projectKeys : settings.projectKeys);
    if (choices.length === 0) {
      void vscode.window.showInformationMessage("No Codex projects were found to sync.");
      return false;
    }

    const selected = await vscode.window.showQuickPick(
      syncProjectQuickPickItems(
        choices,
        settings.sync.projectKeys.length > 0 ? settings.sync.projectKeys : settings.projectKeys,
      ),
      {
        canPickMany: true,
        placeHolder: "Select Codex projects to sync. Disk estimates include all conversations in each project.",
      },
    );
    if (!selected) {
      return false;
    }

    const projectKeys = normalizeProjectKeys(selected.map((item) => item.projectKey));
    await context.globalState.update(SYNC_PROJECT_KEYS_STATE_KEY, projectKeys);
    updateStatusItem(readSettings(context));
    if (panel) {
      await refreshDashboard(context, panel);
    }
    return true;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(`Codex Usage failed to load sync projects: ${message}`);
    return false;
  }
}
```

- [ ] **Step 6: Rename user-facing text in `selectSyncThreadSettings`**

Keep function name for internal continuity, but change UI strings:

```ts
title: "Loading Codex conversations",
```

```ts
void vscode.window.showInformationMessage("No Codex conversations were found for the selected sync projects.");
```

```ts
placeHolder: "Select Codex conversations to sync, or choose all conversations in selected projects",
```

```ts
void vscode.window.showErrorMessage(`Codex Usage failed to load sync conversations: ${message}`);
```

- [ ] **Step 7: Load conversations from sync projects**

Inside `selectSyncThreadSettings`, use sync projects first:

```ts
const projectKeys = settings.sync.projectKeys.length > 0 ? settings.sync.projectKeys : settings.projectKeys;
```

Pass `projectKeys` to `buildThreadsArgs`.

- [ ] **Step 8: Use all-conversations sentinel**

Replace `threadQuickPickItems(choices)` with:

```ts
syncConversationQuickPickItems(choices, settings.sync.conversationMode)
```

After selection:

```ts
if (selected.some((item) => item.allConversations)) {
  await context.globalState.update(SYNC_CONVERSATION_MODE_STATE_KEY, "allInProjects");
  await context.globalState.update(SYNC_THREAD_IDS_STATE_KEY, []);
} else {
  const threadIds = selected.map((item) => item.threadId).filter((threadId): threadId is string => Boolean(threadId));
  await context.globalState.update(SYNC_CONVERSATION_MODE_STATE_KEY, "selectedConversations");
  await context.globalState.update(SYNC_THREAD_IDS_STATE_KEY, threadIds);
}
```

- [ ] **Step 9: Update `configureSync` flow**

After sync folder selection and enabling sync, call the project picker before the conversation picker:

```ts
const selectedProjects = await selectSyncProjectSettings(context);
if (!selectedProjects && readSettings(context).sync.projectKeys.length === 0) {
  updateStatusItem(readSettings(context));
  configureSyncWatcher(context);
  if (panel) {
    await refreshDashboard(context, panel);
  }
  return;
}
await selectSyncThreadSettings(context);
```

This keeps cancellation graceful: a folder can be selected without forcing project/conversation choices.

- [ ] **Step 10: Pass sync fields to dashboard controls**

In `renderWebviewHtml`, update `sync`:

```ts
sync: {
  enabled: settings.sync.enabled,
  dir: settings.sync.dir,
  projectKeys: settings.sync.projectKeys,
  conversationMode: settings.sync.conversationMode,
  threadIds: settings.sync.threadIds,
},
```

- [ ] **Step 11: Remove unused local `threadQuickPickItems` if no longer referenced**

Delete:

```ts
type ThreadQuickPickItem = vscode.QuickPickItem & {
  threadId?: string;
};

function threadQuickPickItems(choices: ReturnType<typeof parseThreadChoices>): ThreadQuickPickItem[] {
  return choices.map((choice) => ({
    label: choice.label,
    description: choice.description,
    detail: choice.detail,
    picked: choice.picked,
    threadId: choice.threadId,
  }));
}
```

- [ ] **Step 12: Run TypeScript build**

Run:

```powershell
Push-Location extensions\vscode
npm run build
Pop-Location
```

Expected:

- TypeScript compile succeeds.

---

## Task 5: Resolve Dynamic Conversations During Sync

**Files:**
- Modify: `extensions/vscode/src/extension.ts`
- Modify: `extensions/vscode/src/core.ts`
- Test: `extensions/vscode/test/core.test.js`

- [ ] **Step 1: Add sync target resolution helper**

Add in `extensions/vscode/src/extension.ts` near `syncOptions`:

```ts
async function resolveSyncThreadIds(context: vscode.ExtensionContext, settings: ExtensionSettings): Promise<string[]> {
  if (settings.sync.conversationMode === "selectedConversations") {
    return settings.sync.threadIds;
  }
  if (settings.sync.projectKeys.length === 0) {
    return [];
  }
  const executablePath = await resolveBundledExecutable(context);
  const result = await runCodexUsage(
    executablePath,
    buildThreadsArgs({
      projectKeys: settings.sync.projectKeys,
      projectTransitions: settings.projectTransitions,
    }),
  );
  return parseThreadChoices(result.stdout, []).map((choice) => choice.threadId);
}
```

- [ ] **Step 2: Add async sync options helper**

Replace synchronous `syncOptions` usage with:

```ts
async function resolvedSyncOptions(context: vscode.ExtensionContext, settings: ExtensionSettings) {
  return {
    syncDir: settings.sync.dir,
    threadIds: await resolveSyncThreadIds(context, settings),
  };
}
```

- [ ] **Step 3: Update `syncNow`**

In `syncNow`, after resolving the executable path:

```ts
const options = await resolvedSyncOptions(context, settings);
if (options.threadIds.length === 0) {
  throw new Error("No Codex conversations are selected for sync.");
}
```

Then use:

```ts
buildSyncStatusArgs(options)
buildSyncImportArgs(options)
buildSyncExportArgs(options)
```

- [ ] **Step 4: Update `showSyncStatus`**

Before running status:

```ts
const options = await resolvedSyncOptions(context, settings);
if (options.threadIds.length === 0) {
  await offerConfigureSync(context, "No Codex conversations are selected for sync.");
  return;
}
const result = await runCodexUsage(executablePath, buildSyncStatusArgs(options));
```

- [ ] **Step 5: Update `syncIsConfigured`**

Replace with:

```ts
function syncIsConfigured(settings: ExtensionSettings): boolean {
  if (!settings.sync.enabled || settings.sync.dir.length === 0) {
    return false;
  }
  if (settings.sync.conversationMode === "allInProjects") {
    return settings.sync.projectKeys.length > 0;
  }
  return settings.sync.threadIds.length > 0;
}
```

- [ ] **Step 6: Update status bar text**

Replace thread wording with conversation/project wording:

```ts
const syncText = syncStatusTooltip(settings);
```

Add:

```ts
function syncStatusTooltip(settings: ExtensionSettings): string {
  if (!settings.sync.enabled) {
    return "Sync: disabled.";
  }
  const folder = settings.sync.dir ? "folder selected" : "folder not selected";
  if (settings.sync.conversationMode === "allInProjects") {
    const projectCount = settings.sync.projectKeys.length;
    return `Sync: enabled, ${folder}, all conversations in ${projectCount} project${projectCount === 1 ? "" : "s"}.`;
  }
  const conversationCount = settings.sync.threadIds.length;
  return `Sync: enabled, ${folder}, ${conversationCount} conversation${conversationCount === 1 ? "" : "s"} selected.`;
}
```

- [ ] **Step 7: Update progress/notification copy**

Change:

```ts
title: "Syncing Codex threads",
```

to:

```ts
title: "Syncing Codex conversations",
```

Keep `parseSyncStatusSummary` internals as thread-based JSON parsing, but user-facing notifications should say `conversation` when edited in this task.

- [ ] **Step 8: Preserve disk estimate wording during dynamic resolution**

No additional code is needed for storage estimates during sync execution because `allInProjects` resolves the same `threads --json` payload at sync time. Confirm `parseThreadChoices` accepts `estimated_sync_bytes` but does not require it; older bundled output should behave as `0 B` in tests.

- [ ] **Step 9: Run tests**

Run:

```powershell
Push-Location extensions\vscode
npm test
Pop-Location
```

Expected:

- All extension tests pass.

---

## Task 6: Update Documentation And Version Locks

**Files:**
- Modify: `README.md`
- Modify: `extensions/vscode/README.md`
- Modify: `PRIVACY.md`
- Modify: `CHANGELOG.md`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `extensions/vscode/package-lock.json`

- [ ] **Step 1: Bump Python package version**

Change `pyproject.toml`:

```toml
version = "0.1.12"
```

- [ ] **Step 2: Refresh `uv.lock`**

Run:

```powershell
uv lock
```

Expected:

- `uv.lock` updates `codex-usage` to `0.1.12`.

- [ ] **Step 3: Update root README commands**

In `README.md`, replace:

```markdown
- `Codex Usage: Select Sync Threads`
```

with:

```markdown
- `Codex Usage: Select Sync Projects`
- `Codex Usage: Select Sync Conversations`
```

- [ ] **Step 4: Update root README sync section**

Replace the first two paragraphs under `## Experimental Thread Sync` with:

```markdown
## Experimental Conversation Sync

The Windows VS Code beta can sync selected Codex conversations through a bring-your-own local sync folder such as OneDrive, Dropbox, Syncthing, or a network drive. Sync is off by default. Run `Codex Usage: Configure Sync` to choose a sync folder, select one or more projects, see a rough sync-size estimate for each project, then choose whether to sync all conversations in those projects or only specific conversations.

Projects match the repo/workspace identities shown in Project Breakdown. Conversations are individual Codex sessions inside those projects. Size estimates are based on local session JSONL file sizes plus a small manifest/index/metadata allowance, so they are useful for cloud-storage planning but not exact billing or provider overhead. The extension stores the sync folder, selected sync projects, and selected conversations as local VS Code extension UI state, not as raw settings you need to edit by hand.
```

- [ ] **Step 5: Update extension README commands/settings/sync section**

In `extensions/vscode/README.md`, replace command list item:

```markdown
- `Codex Usage: Select Sync Threads`
```

with:

```markdown
- `Codex Usage: Select Sync Projects`
- `Codex Usage: Select Sync Conversations`
```

Replace:

```markdown
Sync folder and thread selections are managed with `Codex Usage: Configure Sync` and stored as extension UI state, not as user settings.
```

with:

```markdown
Sync folder, sync project, and sync conversation selections are managed with `Codex Usage: Configure Sync` and stored as extension UI state, not as user settings.
```

Add to `## Experimental Sync`:

```markdown
The setup flow is project-first: choose the sync folder, choose projects with rough sync-size estimates, then choose all conversations in those projects or specific conversations. The command id for selecting conversations remains `codexUsage.selectSyncThreads` internally for compatibility, but the command palette shows `Codex Usage: Select Sync Conversations`.
```

- [ ] **Step 6: Update privacy wording**

In `PRIVACY.md`, replace:

```markdown
- Extension UI state for selected dashboard projects, the selected sync folder, and selected sync thread ids.
```

with:

```markdown
- Extension UI state for selected dashboard projects, the selected sync folder, selected sync projects, sync conversation mode, and selected sync conversation ids.
```

- [ ] **Step 7: Update changelog**

Add above `0.1.11`:

```markdown
## 0.1.12 - Project-First Sync UX

- Changed the sync setup flow to select projects before conversations.
- Renamed user-facing sync thread wording to conversations while keeping thread ids as the internal sync unit.
- Added an all-conversations-in-selected-projects mode that resolves current conversations at sync time.
- Added rough per-project sync-size estimates based on local session JSONL files plus metadata overhead.
- Added a direct `Codex Usage: Select Sync Projects` command.
```

- [ ] **Step 8: Run docs wording check**

Run:

```powershell
rg "Select Sync Threads|Sync: .*thread|sync thread|selected threads|Codex threads to sync" README.md extensions\vscode\README.md extensions\vscode\package.json extensions\vscode\src extensions\vscode\test
```

Expected:

- No user-facing command title or dashboard label uses `threads`.
- Internal code names, CLI args, and diagnostic text may still contain `thread` where they refer to Codex storage identifiers.

---

## Task 7: Verification And Packaging

**Files:**
- Verify generated artifact: `output/codex-usage-dashboard-win32-x64.vsix`

- [ ] **Step 1: Run Python tests**

Run:

```powershell
uv run pytest
```

Expected:

- `87 passed` or the current full test count with zero failures.

- [ ] **Step 2: Run extension tests and build**

Run:

```powershell
Push-Location extensions\vscode
npm test
npm run build
Pop-Location
```

Expected:

- Node tests pass with zero failures.
- TypeScript build succeeds.

- [ ] **Step 3: Rebuild portable Windows VSIX**

Run:

```powershell
Push-Location extensions\vscode
npm run package:vsix:win
Pop-Location
```

Expected:

- `output/codex-usage-dashboard-win32-x64.vsix` is rebuilt.
- `vsce` output lists `extension/bin/win32-x64/codex-usage.exe`, `extension/media/icon.png`, `extension/out/core.js`, and `extension/out/extension.js`.

- [ ] **Step 4: Smoke bundled executable**

Run:

```powershell
extensions\vscode\bin\win32-x64\codex-usage.exe threads --project-key https://github.com/wenjun-mao/codex_usage --json
```

Expected:

- JSON output contains a `threads` array.
- Each thread row contains `session_bytes` and `estimated_sync_bytes`.
- The CLI output may still use `thread_id`; this is correct because the CLI remains the internal/advanced interface.

- [ ] **Step 5: Inspect package contents**

Run:

```powershell
Push-Location extensions\vscode
npx vsce ls --tree
Pop-Location
```

Expected:

- VSIX contents include README, LICENSE, package metadata, icon, compiled JS, and bundled executable.
- VSIX contents exclude TypeScript source and tests.

---

## Manual Smoke Checklist

- [ ] Install the rebuilt VSIX only when ready:

```powershell
code --install-extension output\codex-usage-dashboard-win32-x64.vsix --force
```

- [ ] Open the dashboard and confirm the action strip shows one of:
  - `Sync: Off`
  - `Sync: Select Folder`
  - `Sync: Select Projects`
  - `Sync: All conversations in 1 project`
  - `Sync: N conversations`

- [ ] Run `Codex Usage: Configure Sync`.
  - Choose a sync folder with the folder picker.
  - Choose one or more sync projects from Project Breakdown-style labels.
  - Confirm each project row shows an estimated sync size.
  - Choose `All conversations in selected projects`.

- [ ] Run `Codex Usage: Sync Status`.
  - Confirm notifications and output channel copy use conversation wording.
  - Confirm no raw thread id is presented as the primary label in QuickPick rows.

- [ ] Run `Codex Usage: Select Sync Conversations`.
  - Confirm the picker title and placeholder use conversations.
  - Confirm thread ids appear only in the detail line for diagnostics.

- [ ] Create or use a second conversation under a selected project and run sync again.
  - In `allInProjects` mode, confirm the new conversation is included after the extension resolves conversations at sync time.

---

## Rollback Plan

- [ ] If dynamic `allInProjects` sync has surprising behavior, keep project-first selection but store explicit conversation ids only.
- [ ] If command compatibility is confusing, keep `codexUsage.selectSyncThreads` as an alias and add a new command id `codexUsage.selectSyncConversations`.
- [ ] If sync project state causes migration issues, clear only sync global state keys and leave dashboard project selection unchanged.

---

## Non-Goals

- [ ] Do not change the Python CLI command names in this slice.
- [ ] Do not rename sync manifest folders from `threads/`.
- [ ] Do not sync whole projects or all Codex state.
- [ ] Do not add cloud-provider integrations.
- [ ] Do not add new runtime dependencies.
