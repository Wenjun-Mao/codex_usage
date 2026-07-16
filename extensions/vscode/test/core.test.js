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
  extensionVersionLabel,
  normalizeTheme,
  normalizeRange,
  parseProjectChoices,
  readProjectKeysState,
  parseTransitionChoices,
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

test("project keys are normalized from extension global state", () => {
  const state = {
    get(key, fallback) {
      return key === "projectKeys" ? [" repo-a ", "", "repo-a", "repo-b"] : fallback;
    },
  };

  assert.deepEqual(readProjectKeysState(state), ["repo-a", "repo-b"]);
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
  assert.equal(properties["codexUsage.sync.enabled"], undefined);
  assert.equal(properties["codexUsage.sync.autoPull"], undefined);
  assert.equal(properties["codexUsage.sync.autoPush"], undefined);
});

test("package metadata keeps command ids with exact Task Transfer titles", () => {
  const commands = new Map(packageJson.contributes.commands.map((item) => [item.command, item.title]));

  assert.equal(commands.get("codexUsage.openSyncMenu"), "Codex Usage: Task Transfer");
  assert.equal(commands.get("codexUsage.configureSync"), "Codex Usage: Choose Transfer Folder");
  assert.equal(commands.get("codexUsage.selectSyncTasks"), "Codex Usage: Task Transfer");
  assert.equal(commands.get("codexUsage.pullTasks"), "Codex Usage: Import Tasks");
  assert.equal(commands.get("codexUsage.pushTasks"), "Codex Usage: Export Tasks");
  assert.equal(commands.get("codexUsage.syncStatus"), "Codex Usage: Review Transfer Status");
  assert.equal(commands.get("codexUsage.openSyncFolder"), "Codex Usage: Open Transfer Folder");
  assert.equal(commands.has("codexUsage.syncNow"), false);
  assert.equal(commands.has("codexUsage.selectSyncProjects"), false);
  assert.equal(commands.has("codexUsage.selectSyncThreads"), false);
  assert.equal(packageJson.activationEvents.includes("onCommand:codexUsage.selectSyncTasks"), true);
  assert.equal(packageJson.activationEvents.includes("onCommand:codexUsage.pullTasks"), true);
  assert.equal(packageJson.activationEvents.includes("onCommand:codexUsage.pushTasks"), true);
  assert.equal(packageJson.activationEvents.includes("onCommand:codexUsage.syncNow"), false);
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
    "SYNC_STATUS_KIND_VALUES",
    "SyncStatusKind",
    "SYNC_DIR_STATE_KEY",
    "SYNC_THREAD_IDS_STATE_KEY",
    "SYNC_SELECTION_VERSION_STATE_KEY",
    "readSyncDirState",
    "readSyncThreadIdsState",
    "readSyncSelectionVersionState",
    "normalizeSyncSettings",
    "hasValidSyncSelection",
    "syncStatusKindLabel",
    "syncControlLabel",
    "syncMenuQuickPickItems",
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
