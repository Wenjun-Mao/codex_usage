const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const packageJson = require("../package.json");

const core = require("../out/core");
const {
  buildReportArgs,
  buildCodexUsageEnv,
  buildSummaryArgs,
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
  hasValidSyncSelection,
  normalizeSyncSettings,
  normalizeTheme,
  normalizeRange,
  parseProjectChoices,
  readProjectKeysState,
  readSyncDirState,
  readSyncSelectionVersionState,
  readSyncThreadIdsState,
  parseTransitionChoices,
  renderErrorHtml,
  renderLoadingHtml,
  selectSessionDirsForWatcher,
  shouldRefreshAfterSyncSetupStep,
  syncBackoffMs,
  syncControlLabel,
  syncFailureRequiresNotification,
  syncMenuQuickPickItems,
  syncStatusKindLabel,
  SYNC_SELECTION_VERSION,
  SYNC_SELECTION_VERSION_STATE_KEY,
  WEBVIEW_COMMANDS,
} = core;

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

test("thread picker argument builder uses the bundled executable subcommand only", () => {
  assert.deepEqual(buildThreadsArgs({ projectKeys: ["repo-a"] }), [
    "threads",
    "--json",
    "--project-key",
    "repo-a",
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

test("normalizeSyncSettings accepts exact thread ids only for selection schema version 2", () => {
  assert.deepEqual(
    normalizeSyncSettings({
      enabled: true,
      dir: " D:/Sync ",
      selectionVersion: 2,
      threadIds: [" t1 ", "", "t1", "t2"],
      autoPull: false,
      autoPush: true,
    }),
    {
      enabled: true,
      dir: "D:/Sync",
      selectionVersion: 2,
      threadIds: ["t1", "t2"],
      autoPull: false,
      autoPush: true,
    },
  );
  assert.deepEqual(normalizeSyncSettings({}), {
    enabled: false,
    dir: "",
    selectionVersion: 0,
    threadIds: [],
    autoPull: true,
    autoPush: true,
  });
  assert.deepEqual(normalizeSyncSettings({ threadIds: ["legacy"] }).threadIds, []);
  assert.deepEqual(normalizeSyncSettings({ selectionVersion: 1, threadIds: ["legacy"] }).threadIds, []);
});

test("project keys are normalized from extension global state", () => {
  const state = {
    get(key, fallback) {
      return key === "projectKeys" ? [" repo-a ", "", "repo-a", "repo-b"] : fallback;
    },
  };

  assert.deepEqual(readProjectKeysState(state), ["repo-a", "repo-b"]);
});

test("sync folder, selection version, and thread ids are normalized from extension global state", () => {
  const state = {
    get(key, fallback) {
      if (key === "syncDir") {
        return " D:/CodexSync ";
      }
      if (key === "syncThreadIds") {
        return [" t1 ", "", "t1", "t2"];
      }
      if (key === "syncSelectionVersion") {
        return 2;
      }
      return fallback;
    },
  };

  assert.equal(readSyncDirState(state), "D:/CodexSync");
  assert.equal(readSyncSelectionVersionState(state), 2);
  assert.deepEqual(readSyncThreadIdsState(state), ["t1", "t2"]);
  assert.equal(SYNC_SELECTION_VERSION, 2);
  assert.equal(SYNC_SELECTION_VERSION_STATE_KEY, "syncSelectionVersion");
});

test("sync selection version rejects legacy and unknown global state", () => {
  const state = {
    get(key, fallback) {
      return key === "syncSelectionVersion" ? 1 : fallback;
    },
  };

  assert.equal(readSyncSelectionVersionState(state), 0);
  assert.equal(readSyncSelectionVersionState(undefined), 0);
});

test("sync selection validity requires a folder, schema version 2, and at least one exact task", () => {
  assert.equal(
    hasValidSyncSelection(
      normalizeSyncSettings({
        enabled: true,
        dir: "D:/Sync",
        selectionVersion: 2,
        threadIds: ["t1"],
      }),
    ),
    true,
  );
  assert.equal(
    hasValidSyncSelection(
      normalizeSyncSettings({
        enabled: true,
        dir: "D:/Sync",
        selectionVersion: 1,
        threadIds: ["legacy"],
      }),
    ),
    false,
  );
  assert.equal(
    hasValidSyncSelection(
      normalizeSyncSettings({ enabled: true, dir: "D:/Sync", selectionVersion: 2, threadIds: [] }),
    ),
    false,
  );
});

test("sync menu exposes pause resume change and clear actions", () => {
  const enabledItems = syncMenuQuickPickItems({
    enabled: true,
    dir: "D:/CodexSync",
    selectionVersion: 2,
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
      "changeTasks",
      "clearSync",
      "openSyncFolder",
    ],
  );
  assert.match(enabledItems[2].label, /Pause Sync/);
  assert.match(enabledItems[4].description, /1 selected/);
  assert.equal(enabledItems[4].label, "$(checklist) Change Tasks");
  assert.match(enabledItems[5].detail, /does not delete/i);

  const pausedItems = syncMenuQuickPickItems({
    enabled: false,
    dir: "D:/CodexSync",
    selectionVersion: 2,
    threadIds: ["t1"],
    autoPull: true,
    autoPush: true,
  });

  assert.equal(pausedItems[0].action, "resumeSync");
  assert.match(pausedItems[0].label, /Resume Sync/);
  assert.match(pausedItems[0].description, /Paused/);
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
  assert.equal(syncFailureRequiresNotification("No Codex tasks are selected for sync."), true);
  assert.equal(syncFailureRequiresNotification("PermissionError: [WinError 5] Access is denied"), false);
  assert.equal(syncFailureRequiresNotification("codex-usage exited with code 1"), false);
});

test("syncStatusKindLabel maps scheduler states to concise status bar labels", () => {
  assert.equal(syncStatusKindLabel("off"), "Off");
  assert.equal(syncStatusKindLabel("idle"), "Idle");
  assert.equal(syncStatusKindLabel("waiting"), "Waiting");
  assert.equal(syncStatusKindLabel("scanning"), "Scanning");
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
  assert.equal(readSyncSelectionVersionState(state), 0);
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
    path.join("C:/Users/example/.codex", "archived_sessions"),
  ]);
});

test("watcher session directory selection follows discovery precedence", () => {
  const candidates = [
    "C:/codex/sessions",
    "C:/codex/archived_sessions",
    "C:/Users/example/.codex/sessions",
    "C:/Users/example/.codex/archived_sessions",
  ];

  assert.deepEqual(selectSessionDirsForWatcher(candidates, true, () => false), [
    "C:/codex/sessions",
    "C:/codex/archived_sessions",
  ]);
  assert.deepEqual(selectSessionDirsForWatcher(candidates, false, (dir) => dir.includes("Users")), [
    "C:/Users/example/.codex/sessions",
    "C:/Users/example/.codex/archived_sessions",
  ]);
  assert.deepEqual(selectSessionDirsForWatcher(candidates, false, () => false), [
    "C:/codex/sessions",
    "C:/codex/archived_sessions",
  ]);
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

test("bundledExecutablePath resolves supported bundled executables and rejects unsupported platforms", () => {
  assert.equal(
    bundledExecutablePath("C:/extension", "win32", "x64"),
    path.join("C:/extension", "bin", "win32-x64", "codex-usage.exe"),
  );
  assert.equal(
    bundledExecutablePath("/Users/alice/.vscode/extensions/codex-usage", "darwin", "arm64"),
    path.join("/Users/alice/.vscode/extensions/codex-usage", "bin", "darwin-arm64", "codex-usage"),
  );
  assert.throws(
    () => bundledExecutablePath("/extension", "darwin", "x64"),
    /Unsupported platform.*Windows x64 and macOS Apple Silicon/s,
  );
  assert.throws(() => bundledExecutablePath("/extension", "linux", "x64"), /Unsupported platform/);
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

test("injectWebviewControls adds command links without scripts or external URLs", () => {
  const html = "<!doctype html><html><head><title>Report</title></head><body><main><h1>Report</h1></main></body></html>";
  const out = injectWebviewControls(html, {
    range: "7d",
    projectKeys: ["repo-a", "repo-b"],
    theme: "night",
    sync: {
      enabled: true,
      dir: "D:/CodexSync",
      selectionVersion: 2,
      threadIds: ["t1", "t2"],
    },
    versionLabel: "v0.1.9",
  });

  assert.match(out, /codex-usage-actions/);
  assert.match(out, /codex-usage-version/);
  assert.match(out, /command:codexUsage.selectRange/);
  assert.match(out, /command:codexUsage.selectTheme/);
  assert.match(out, /command:codexUsage.openSyncMenu/);
  assert.doesNotMatch(out, /command:codexUsage.syncNow/);
  assert.doesNotMatch(out, /command:codexUsage.syncStatus/);
  assert.doesNotMatch(out, /command:codexUsage.reviewProjectTransitions/);
  assert.match(out, /Projects: 2 selected/);
  assert.match(out, /Theme: Night/);
  assert.match(out, /Sync: 2 tasks/);
  assert.doesNotMatch(out, />Sync Now<\/a>/);
  assert.doesNotMatch(out, />Sync Status<\/a>/);
  assert.doesNotMatch(out, />Transitions<\/a>/);
  assert.match(out, />v0\.1\.9<\/span>/);
  assert.doesNotMatch(out, /<script/i);
  assert.doesNotMatch(out, /https:/);
});

test("sync control labels read as menu controls", () => {
  assert.equal(
    syncControlLabel({ enabled: false, dir: "", selectionVersion: 0, threadIds: [] }),
    "Sync: Setup required ▾",
  );
  assert.equal(
    syncControlLabel({
      enabled: true,
      dir: "D:/CodexSync",
      selectionVersion: 2,
      threadIds: ["t1"],
    }),
    "Sync: 1 task ▾",
  );
  assert.equal(
    syncControlLabel({
      enabled: false,
      dir: "D:/CodexSync",
      selectionVersion: 2,
      threadIds: ["t1", "t2"],
    }),
    "Sync: Off ▾",
  );
  assert.equal(
    syncControlLabel({ enabled: true, dir: "D:/CodexSync", selectionVersion: 1, threadIds: ["legacy"] }),
    "Sync: Setup required ▾",
  );
});

test("injectWebviewControls labels unconfigured sync states", () => {
  const html = "<!doctype html><html><head><title>Report</title></head><body><main><h1>Report</h1></main></body></html>";

  assert.match(
    injectWebviewControls(html, {
      range: "7d",
      projectKeys: [],
      theme: "auto",
      sync: { enabled: false, dir: "", selectionVersion: 0, threadIds: [] },
    }),
    /Sync: Setup required/,
  );
  assert.match(
    injectWebviewControls(html, {
      range: "7d",
      projectKeys: [],
      theme: "auto",
      sync: { enabled: true, dir: "", selectionVersion: 2, threadIds: ["t1"] },
    }),
    /Sync: Setup required/,
  );
  assert.match(
    injectWebviewControls(html, {
      range: "7d",
      projectKeys: [],
      theme: "auto",
      sync: { enabled: true, dir: "D:\/CodexSync", selectionVersion: 1, threadIds: ["legacy"] },
    }),
    /Sync: Setup required/,
  );
  assert.match(
    injectWebviewControls(html, {
      range: "7d",
      projectKeys: [],
      theme: "auto",
      sync: { enabled: true, dir: "D:\/CodexSync", selectionVersion: 2, threadIds: ["t1", "t2"] },
    }),
    /Sync: 2 tasks/,
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
    "codexUsage.openSyncMenu",
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
  for (const key of ["codexUsage.sync.enabled", "codexUsage.sync.autoPull", "codexUsage.sync.autoPush"]) {
    assert.match(properties[key].description, /task/i);
    assert.doesNotMatch(properties[key].description, /conversation|project/i);
  }
});

test("package metadata contributes one exact task selection command", () => {
  const commands = new Map(packageJson.contributes.commands.map((item) => [item.command, item.title]));

  assert.equal(commands.get("codexUsage.openSyncMenu"), "Codex Usage: Sync Menu");
  assert.equal(commands.get("codexUsage.selectSyncTasks"), "Codex Usage: Select Sync Tasks");
  assert.equal(commands.has("codexUsage.selectSyncProjects"), false);
  assert.equal(commands.has("codexUsage.selectSyncThreads"), false);
  assert.equal(packageJson.activationEvents.includes("onCommand:codexUsage.selectSyncTasks"), true);
  assert.equal(packageJson.activationEvents.includes("onCommand:codexUsage.selectSyncProjects"), false);
  assert.equal(packageJson.activationEvents.includes("onCommand:codexUsage.selectSyncThreads"), false);
});

test("core no longer exports legacy sync project or conversation selection contracts", () => {
  for (const name of [
    "SYNC_CONVERSATION_MODE_VALUES",
    "SYNC_PROJECT_KEYS_STATE_KEY",
    "SYNC_CONVERSATION_MODE_STATE_KEY",
    "normalizeSyncConversationMode",
    "readSyncProjectKeysState",
    "readSyncConversationModeState",
    "parseSyncProjectChoices",
    "parseThreadChoices",
    "syncProjectQuickPickItems",
    "syncConversationQuickPickItems",
  ]) {
    assert.equal(core[name], undefined, `${name} should not be exported`);
  }
});

test("windows VSIX package script creates the release output directory", () => {
  assert.match(
    packageJson.scripts["package:vsix:win"],
    /New-Item -ItemType Directory -Force \.\.\\\.\.\\output\\releases/,
  );
  assert.match(packageJson.scripts["package:vsix:win"], /--out \.\.\/\.\.\/output\/releases\/codex-usage-dashboard-win32-x64\.vsix/);
});

test("macos Apple Silicon VSIX package script creates the release output directory", () => {
  assert.match(packageJson.scripts["build:python:mac"], /build-macos-arm64-exe\.sh/);
  assert.match(packageJson.scripts["package:vsix:mac"], /mkdir -p \.\.\/\.\.\/output\/releases/);
  assert.match(packageJson.scripts["package:vsix:mac"], /npm run build:python:mac/);
  assert.match(packageJson.scripts["package:vsix:mac"], /--target darwin-arm64/);
  assert.match(
    packageJson.scripts["package:vsix:mac"],
    /--out \.\.\/\.\.\/output\/releases\/codex-usage-dashboard-darwin-arm64\.vsix/,
  );
});

test("package metadata is ready for Marketplace preview publishing", () => {
  assert.equal(packageJson.publisher, "wenjun-mao");
  assert.equal(packageJson.private, undefined);
  assert.equal(packageJson.preview, true);
  assert.equal(packageJson.repository.url, "https://github.com/Wenjun-Mao/codex_usage.git");
  assert.match(packageJson.description, /local/i);
  assert.match(packageJson.description, /Codex/i);
  assert.doesNotMatch(packageJson.publisher, /local/i);
  assert.doesNotMatch(packageJson.scripts["package:vsix:win"], /allow-missing-repository/);
});

test("extension package includes Marketplace support documents", () => {
  const extensionRoot = path.resolve(__dirname, "..");
  const changelog = fs.readFileSync(path.join(extensionRoot, "CHANGELOG.md"), "utf8");
  const support = fs.readFileSync(path.join(extensionRoot, "SUPPORT.md"), "utf8");
  const readme = fs.readFileSync(path.join(extensionRoot, "README.md"), "utf8");

  assert.match(changelog, /0\.1\.29/);
  assert.match(support, /GitHub Issues/i);
  assert.match(readme, /Windows x64/i);
  assert.match(readme, /Preview/i);
  assert.match(readme, /fast mode/i);
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
