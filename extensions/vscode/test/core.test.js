const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const packageJson = require("../package.json");

const {
  buildReportArgs,
  buildCodexUsageEnv,
  buildSummaryArgs,
  buildSyncExportArgs,
  buildSyncImportArgs,
  buildSyncStatusArgs,
  buildThreadsArgs,
  cacheDbPath,
  buildTransitionSuggestArgs,
  bundledExecutablePath,
  candidateSessionDirs,
  extensionVersionLabel,
  injectWebviewControls,
  injectWebviewCsp,
  SYNC_AUTO_WARNING_COOLDOWN_MS,
  SYNC_FILE_CHANGE_DEBOUNCE_MS,
  SYNC_FOCUS_COOLDOWN_MS,
  normalizeSyncConversationMode,
  normalizeSyncSettings,
  normalizeTheme,
  normalizeRange,
  parseProjectChoices,
  parseSyncProjectChoices,
  readProjectKeysState,
  readSyncConversationModeState,
  readSyncDirState,
  readSyncProjectKeysState,
  readSyncThreadIdsState,
  parseSyncStatusSummary,
  parseThreadChoices,
  parseTransitionChoices,
  renderErrorHtml,
  renderLoadingHtml,
  selectSessionDirsForWatcher,
  shouldRefreshAfterSyncSetupStep,
  syncBackoffMs,
  syncConversationQuickPickItems,
  syncFailureRequiresNotification,
  syncProjectQuickPickItems,
  syncStatusKindLabel,
  WEBVIEW_COMMANDS,
} = require("../out/core");

test("buildReportArgs includes optional CLI arguments for the bundled executable", () => {
  const args = buildReportArgs({
    range: "all",
    outputPath: "C:/tmp/report.html",
    projectKeys: ["repo-a", "repo-b"],
    theme: "night",
  });

  assert.deepEqual(args, [
    "report",
    "--range",
    "all",
    "--output",
    "C:/tmp/report.html",
    "--theme",
    "night",
    "--project-key",
    "repo-a",
    "--project-key",
    "repo-b",
  ]);
  assert.doesNotMatch(args.join(" "), /uv|codex-usage/);
});

test("buildSummaryArgs includes project JSON arguments and project filters", () => {
  const args = buildSummaryArgs({
    range: "30d",
    groupBy: "project",
    projectKeys: ["alpha", " beta "],
  });

  assert.deepEqual(args, [
    "summary",
    "--range",
    "30d",
    "--by",
    "project",
    "--json",
    "--project-key",
    "alpha",
    "--project-key",
    "beta",
  ]);
  assert.doesNotMatch(args.join(" "), /uv|codex-usage/);
});

test("sync CLI argument builders use bundled executable subcommands only", () => {
  assert.deepEqual(buildThreadsArgs({ projectKeys: ["repo-a"] }), [
    "threads",
    "--json",
    "--project-key",
    "repo-a",
  ]);
  assert.deepEqual(buildSyncExportArgs({ syncDir: "D:/sync", threadIds: ["t1", "t2"] }), [
    "sync",
    "export",
    "--sync-dir",
    "D:/sync",
    "--thread-id",
    "t1",
    "--thread-id",
    "t2",
  ]);
  assert.deepEqual(buildSyncImportArgs({ syncDir: "D:/sync", threadIds: ["t1"], conflictPolicy: "remote" }), [
    "sync",
    "import",
    "--sync-dir",
    "D:/sync",
    "--thread-id",
    "t1",
    "--conflict-policy",
    "remote",
  ]);
  assert.deepEqual(buildSyncStatusArgs({ syncDir: "D:/sync", threadIds: ["t1"] }), [
    "sync",
    "status",
    "--json",
    "--sync-dir",
    "D:/sync",
    "--thread-id",
    "t1",
  ]);
});

test("transition suggestion args use bundled executable subcommands only", () => {
  assert.deepEqual(buildTransitionSuggestArgs(), ["transitions", "suggest", "--json"]);
});

test("usage arg builders disable automatic project transitions when configured", () => {
  assert.deepEqual(
    buildReportArgs({
      range: "7d",
      outputPath: "C:/tmp/report.html",
      projectTransitions: { autoDetect: false },
    }),
    [
      "report",
      "--range",
      "7d",
      "--output",
      "C:/tmp/report.html",
      "--theme",
      "auto",
      "--no-auto-transitions",
    ],
  );
  assert.deepEqual(buildSummaryArgs({ range: "all", projectTransitions: { autoDetect: false } }), [
    "summary",
    "--range",
    "all",
    "--by",
    "project",
    "--json",
    "--no-auto-transitions",
  ]);
  assert.deepEqual(buildThreadsArgs({ projectTransitions: { autoDetect: false }, projectKeys: ["repo-a"] }), [
    "threads",
    "--json",
    "--no-auto-transitions",
    "--project-key",
    "repo-a",
  ]);
  assert.doesNotMatch(buildSummaryArgs({ range: "all", projectTransitions: { autoDetect: true } }).join(" "), /--no-auto-transitions/);
});

test("normalizeRange falls back to 30d for unknown settings", () => {
  assert.equal(normalizeRange("month"), "month");
  assert.equal(normalizeRange("nonsense"), "30d");
  assert.equal(normalizeRange(undefined), "30d");
});

test("normalizeTheme falls back to auto for unknown settings", () => {
  assert.equal(normalizeTheme("day"), "day");
  assert.equal(normalizeTheme("night"), "night");
  assert.equal(normalizeTheme("auto"), "auto");
  assert.equal(normalizeTheme("midnight"), "auto");
  assert.equal(normalizeTheme(undefined), "auto");
});

test("normalizeSyncSettings trims folder and thread ids with safe defaults", () => {
  assert.deepEqual(
    normalizeSyncSettings({
      enabled: true,
      dir: " D:/sync ",
      projectKeys: [" repo-a ", "repo-b"],
      conversationMode: "allInProjects",
      threadIds: [" t1 ", "", "t1", "t2"],
      autoPull: false,
      autoPush: true,
    }),
    {
      enabled: true,
      dir: "D:/sync",
      projectKeys: ["repo-a", "repo-b"],
      conversationMode: "allInProjects",
      threadIds: ["t1", "t2"],
      autoPull: false,
      autoPush: true,
    },
  );
  assert.deepEqual(normalizeSyncSettings({}), {
    enabled: false,
    dir: "",
    projectKeys: [],
    conversationMode: "selectedConversations",
    threadIds: [],
    autoPull: true,
    autoPush: true,
  });
});

test("project keys are normalized from extension global state", () => {
  const state = {
    get(key, fallback) {
      return key === "projectKeys" ? [" repo-a ", "", "repo-a", "repo-b"] : fallback;
    },
  };

  assert.deepEqual(readProjectKeysState(state), ["repo-a", "repo-b"]);
});

test("sync folder and thread ids are normalized from extension global state", () => {
  const state = {
    get(key, fallback) {
      if (key === "syncDir") {
        return " D:/CodexSync ";
      }
      if (key === "syncThreadIds") {
        return [" t1 ", "", "t1", "t2"];
      }
      return fallback;
    },
  };

  assert.equal(readSyncDirState(state), "D:/CodexSync");
  assert.deepEqual(readSyncThreadIdsState(state), ["t1", "t2"]);
});

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

test("empty sync global state uses safe defaults", () => {
  const state = {
    get(_key, fallback) {
      return fallback;
    },
  };

  assert.equal(readSyncDirState(state), "");
  assert.deepEqual(readSyncThreadIdsState(state), []);
});

test("session directory candidates are discovered without a user setting", () => {
  const dirs = candidateSessionDirs({
    codexHome: "C:/Users/example/.codex",
    userProfile: "C:/Users/example",
    homeDir: "C:/Users/example",
  });

  assert.deepEqual(dirs, [
    path.join("C:/Users/example/.codex", "sessions"),
  ]);
});

test("watcher session directory selection follows discovery precedence", () => {
  const candidates = ["C:/codex/sessions", "C:/Users/example/.codex/sessions"];

  assert.deepEqual(selectSessionDirsForWatcher(candidates, true, () => false), ["C:/codex/sessions"]);
  assert.deepEqual(selectSessionDirsForWatcher(candidates, false, (dir) => dir.includes("Users")), [
    "C:/Users/example/.codex/sessions",
  ]);
  assert.deepEqual(selectSessionDirsForWatcher(candidates, false, () => false), ["C:/codex/sessions"]);
});

test("buildCodexUsageEnv passes internal cache directory without removing process env", () => {
  const env = buildCodexUsageEnv("C:/global-storage", { PATH: "C:/bin", CODEX_HOME: "C:/codex" });

  assert.equal(env.PATH, "C:/bin");
  assert.equal(env.CODEX_HOME, "C:/codex");
  assert.equal(env.CODEX_USAGE_CACHE_DIR, path.join("C:/global-storage", "cache"));
});

test("cacheDbPath points at the Python cache database under extension storage", () => {
  assert.equal(cacheDbPath("C:/global-storage"), path.join("C:/global-storage", "cache", "usage-cache.sqlite3"));
});

test("sync setup step refresh policy defaults to refresh and can be suppressed", () => {
  assert.equal(shouldRefreshAfterSyncSetupStep(undefined), true);
  assert.equal(shouldRefreshAfterSyncSetupStep({}), true);
  assert.equal(shouldRefreshAfterSyncSetupStep({ refreshDashboard: false }), false);
});

test("bundledExecutablePath resolves Windows x64 executable and rejects unsupported platforms", () => {
  assert.equal(
    bundledExecutablePath("C:/extension", "win32", "x64"),
    path.join("C:/extension", "bin", "win32-x64", "codex-usage.exe"),
  );
  assert.throws(() => bundledExecutablePath("C:/extension", "linux", "x64"), /Unsupported platform/);
});

test("injectWebviewCsp adds a strict CSP without external allowances", () => {
  const html = "<!doctype html><html><head><title>Report</title></head><body>ok</body></html>";
  const out = injectWebviewCsp(html, "vscode-resource:");

  assert.match(out, /Content-Security-Policy/);
  assert.match(out, /default-src 'none'/);
  assert.match(out, /style-src 'unsafe-inline'/);
  assert.doesNotMatch(out, /https:/);
  assert.doesNotMatch(out, /script-src/);
});

test("parseProjectChoices reads project rows for QuickPick", () => {
  const choices = parseProjectChoices(
    JSON.stringify({
      rows: [
        {
          key: "repo-a",
          label: "repo-a",
          usage: { total_tokens: 1234 },
          cost: { total_usd: 0.25 },
        },
        {
          key: "repo-b",
          label: "Repo B",
          usage: { total_tokens: 50 },
          cost: { total_usd: 0.01 },
        },
      ],
    }),
    ["repo-b"],
  );

  assert.equal(choices.length, 2);
  assert.equal(choices[0].description, "1,234 tokens | $0.2500");
  assert.equal(choices[1].label, "Repo B");
  assert.equal(choices[1].picked, true);
});

test("parseThreadChoices reads selected thread rows for QuickPick", () => {
  const choices = parseThreadChoices(
    JSON.stringify({
      threads: [
        {
          thread_id: "t1",
          title: "Build sync",
          project_label: "codex_usage",
          updated_at: "2026-05-23T18:00:00Z",
          total_tokens: 12345,
        },
      ],
    }),
    ["t1"],
  );

  assert.equal(choices.length, 1);
  assert.equal(choices[0].threadId, "t1");
  assert.equal(choices[0].label, "Build sync");
  assert.match(choices[0].description, /codex_usage/);
  assert.match(choices[0].description, /0 B/);
  assert.equal(choices[0].picked, true);
});

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

test("parseTransitionChoices reads detected project transitions for QuickPick", () => {
  const choices = parseTransitionChoices(
    JSON.stringify({
      project_transitions: [
        {
          source_key: "https://github.com/example/signoz-stack",
          source_label: "signoz-stack",
          target_key: "https://github.com/example/ops-board",
          target_label: "ops-board",
          effective_from: "2026-05-23T21:06:45+00:00",
          confidence: 100,
          evidence: ["verified local repo path"],
          thread_ids: ["thread-1"],
        },
      ],
    }),
  );

  assert.equal(choices.length, 1);
  assert.equal(choices[0].label, "signoz-stack -> ops-board");
  assert.match(choices[0].description, /100/);
  assert.match(choices[0].detail, /2026-05-23T21:06:45\+00:00/);
  assert.match(choices[0].detail, /verified local repo path/);
  assert.match(choices[0].detail, /https:\/\/github\.com\/example\/ops-board/);
  assert.equal(choices[0].picked, true);
  assert.equal(choices[0].transition.target_key, "https://github.com/example/ops-board");
  assert.deepEqual(choices[0].transition.thread_ids, ["thread-1"]);
});

test("parseTransitionChoices rejects invalid JSON payloads", () => {
  assert.throws(() => parseTransitionChoices("{"), /Could not parse Codex transition JSON/);
  assert.throws(() => parseTransitionChoices("{}"), /project_transitions array/);
});

test("parseSyncStatusSummary counts states and memory warnings", () => {
  const summary = parseSyncStatusSummary(
    JSON.stringify({
      threads: [
        { thread_id: "t1", state: "synced", memory_database_rows: 0 },
        { thread_id: "t2", state: "conflict", memory_database_rows: 2 },
      ],
    }),
  );

  assert.equal(summary.total, 2);
  assert.equal(summary.synced, 1);
  assert.equal(summary.conflicts, 1);
  assert.equal(summary.memoryWarnings, 1);
  assert.equal(summary.localChanges, 0);
  assert.equal(summary.remoteChanges, 0);
  assert.equal(summary.fastForwards, 0);
  assert.match(summary.message, /2 conversations/);
  assert.match(summary.message, /1 synced/);
  assert.match(summary.message, /1 conflict/);
});

test("parseSyncStatusSummary describes planned pull push and fast-forward states", () => {
  const summary = parseSyncStatusSummary(
    JSON.stringify({
      threads: [
        { thread_id: "a", state: "local_ahead" },
        { thread_id: "b", state: "remote_ahead" },
        { thread_id: "c", state: "fast_forward_push" },
        { thread_id: "d", state: "fast_forward_pull" },
        { thread_id: "e", state: "synced" },
      ],
    }),
  );

  assert.equal(summary.total, 5);
  assert.equal(summary.synced, 1);
  assert.match(summary.message, /1 local change/);
  assert.match(summary.message, /1 remote change/);
  assert.match(summary.message, /2 fast-forward/);
});

test("injectWebviewControls adds command links without scripts or external URLs", () => {
  const html = "<!doctype html><html><head><title>Report</title></head><body><main><h1>Report</h1></main></body></html>";
  const out = injectWebviewControls(html, {
    range: "7d",
    projectKeys: ["repo-a", "repo-b"],
    theme: "night",
    sync: {
      enabled: true,
      dir: "D:/CodexSync",
      projectKeys: ["repo-a"],
      conversationMode: "selectedConversations",
      threadIds: ["t1", "t2"],
    },
    versionLabel: "v0.1.9",
  });

  assert.match(out, /codex-usage-actions/);
  assert.match(out, /codex-usage-version/);
  assert.match(out, /command:codexUsage.selectRange/);
  assert.match(out, /command:codexUsage.selectTheme/);
  assert.match(out, /command:codexUsage.configureSync/);
  assert.match(out, /command:codexUsage.syncNow/);
  assert.match(out, /command:codexUsage.syncStatus/);
  assert.match(out, /command:codexUsage.reviewProjectTransitions/);
  assert.match(out, /Projects: 2 selected/);
  assert.match(out, /Theme: Night/);
  assert.match(out, /Sync: 2 conversations/);
  assert.match(out, />Sync Now<\/a>/);
  assert.match(out, />Sync Status<\/a>/);
  assert.match(out, />v0\.1\.9<\/span>/);
  assert.doesNotMatch(out, /<script/i);
  assert.doesNotMatch(out, /https:/);
});

test("injectWebviewControls labels unconfigured sync states", () => {
  const html = "<!doctype html><html><head><title>Report</title></head><body><main><h1>Report</h1></main></body></html>";

  assert.match(
    injectWebviewControls(html, {
      range: "7d",
      projectKeys: [],
      theme: "auto",
      sync: { enabled: false, dir: "", projectKeys: [], conversationMode: "selectedConversations", threadIds: [] },
    }),
    /Sync: Off/,
  );
  assert.match(
    injectWebviewControls(html, {
      range: "7d",
      projectKeys: [],
      theme: "auto",
      sync: { enabled: true, dir: "", projectKeys: [], conversationMode: "selectedConversations", threadIds: [] },
    }),
    /Sync: Select Folder/,
  );
  assert.match(
    injectWebviewControls(html, {
      range: "7d",
      projectKeys: [],
      theme: "auto",
      sync: { enabled: true, dir: "D:\/CodexSync", projectKeys: [], conversationMode: "selectedConversations", threadIds: [] },
    }),
    /Sync: Select Projects/,
  );
  assert.match(
    injectWebviewControls(html, {
      range: "7d",
      projectKeys: [],
      theme: "auto",
      sync: { enabled: true, dir: "D:\/CodexSync", projectKeys: ["repo-a", "repo-b"], conversationMode: "allInProjects", threadIds: [] },
    }),
    /Sync: All conversations in 2 projects/,
  );
});

test("extensionVersionLabel reads package metadata", () => {
  assert.equal(extensionVersionLabel({ version: "0.1.9" }), "v0.1.9");
  assert.equal(extensionVersionLabel({ version: " " }), "");
  assert.equal(extensionVersionLabel({}), "");
});

test("webview command allowlist includes dashboard commands", () => {
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
});

test("package metadata no longer contributes removed manual settings", () => {
  const properties = packageJson.contributes.configuration.properties;

  assert.equal(properties["codexUsage.sessionsDir"], undefined);
  assert.equal(properties["codexUsage.subscriptionUsd"], undefined);
  assert.equal(properties["codexUsage.projectKeys"], undefined);
  assert.equal(properties["codexUsage.projectAliases"], undefined);
  assert.equal(properties["codexUsage.sync.dir"], undefined);
  assert.equal(properties["codexUsage.sync.threadIds"], undefined);
  assert.equal(properties["codexUsage.sync.projectKeys"], undefined);
  assert.equal(properties["codexUsage.sync.conversationMode"], undefined);
  assert.ok(properties["codexUsage.sync.enabled"]);
  assert.ok(properties["codexUsage.sync.autoPull"]);
  assert.ok(properties["codexUsage.sync.autoPush"]);
});

test("package metadata describes manual-only sync mode clearly", () => {
  const properties = packageJson.contributes.configuration.properties;

  assert.match(properties["codexUsage.sync.enabled"].description, /manual Sync Now/i);
  assert.match(properties["codexUsage.sync.enabled"].description, /optional automatic/i);
  assert.match(properties["codexUsage.sync.autoPull"].description, /optional/i);
  assert.match(properties["codexUsage.sync.autoPush"].description, /optional/i);
  assert.doesNotMatch(properties["codexUsage.sync.enabled"].description, /selected-thread/i);
});

test("package metadata uses project and conversation wording for sync commands", () => {
  const commands = new Map(packageJson.contributes.commands.map((item) => [item.command, item.title]));

  assert.equal(commands.get("codexUsage.selectSyncProjects"), "Codex Usage: Select Sync Projects");
  assert.equal(commands.get("codexUsage.selectSyncThreads"), "Codex Usage: Select Sync Conversations");
});

test("loading and error HTML are script-free and themeable", () => {
  const loading = renderLoadingHtml("Initializing Codex usage cache. This can take a few seconds the first time.");
  const error = renderErrorHtml("boom");

  assert.match(loading, /data-codex-theme="auto"/);
  assert.match(loading, /Initializing Codex usage cache/);
  assert.match(error, /data-codex-theme="auto"/);
  assert.match(loading, /body\.vscode-dark/);
  assert.match(error, /body\.vscode-dark/);
  assert.doesNotMatch(loading, /<script/i);
  assert.doesNotMatch(error, /<script/i);
});
