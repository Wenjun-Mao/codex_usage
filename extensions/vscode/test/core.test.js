const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");
const packageJson = require("../package.json");

const {
  buildReportArgs,
  buildSummaryArgs,
  buildSyncExportArgs,
  buildSyncImportArgs,
  buildSyncStatusArgs,
  buildThreadsArgs,
  buildTransitionSuggestArgs,
  bundledExecutablePath,
  candidateSessionDirs,
  extensionVersionLabel,
  injectWebviewControls,
  injectWebviewCsp,
  normalizeSyncSettings,
  normalizeTheme,
  normalizeRange,
  parseProjectChoices,
  readProjectKeysState,
  parseSyncStatusSummary,
  parseThreadChoices,
  parseTransitionChoices,
  renderErrorHtml,
  renderLoadingHtml,
  selectSessionDirsForWatcher,
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
      threadIds: [" t1 ", "", "t1", "t2"],
      autoPull: false,
      autoPush: true,
    }),
    {
      enabled: true,
      dir: "D:/sync",
      threadIds: ["t1", "t2"],
      autoPull: false,
      autoPush: true,
    },
  );
  assert.deepEqual(normalizeSyncSettings({}), {
    enabled: false,
    dir: "",
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
  assert.equal(choices[0].picked, true);
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
  assert.match(summary.message, /1 synced/);
  assert.match(summary.message, /1 conflict/);
});

test("injectWebviewControls adds command links without scripts or external URLs", () => {
  const html = "<!doctype html><html><head><title>Report</title></head><body><main><h1>Report</h1></main></body></html>";
  const out = injectWebviewControls(html, {
    range: "7d",
    projectKeys: ["repo-a", "repo-b"],
    theme: "night",
    versionLabel: "v0.1.9",
  });

  assert.match(out, /codex-usage-actions/);
  assert.match(out, /codex-usage-version/);
  assert.match(out, /command:codexUsage.selectRange/);
  assert.match(out, /command:codexUsage.selectTheme/);
  assert.match(out, /command:codexUsage.reviewProjectTransitions/);
  assert.match(out, /Projects: 2 selected/);
  assert.match(out, /Theme: Night/);
  assert.match(out, />v0\.1\.9<\/span>/);
  assert.doesNotMatch(out, /<script/i);
  assert.doesNotMatch(out, /https:/);
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
});

test("loading and error HTML are script-free and themeable", () => {
  const loading = renderLoadingHtml();
  const error = renderErrorHtml("boom");

  assert.match(loading, /data-codex-theme="auto"/);
  assert.match(error, /data-codex-theme="auto"/);
  assert.match(loading, /body\.vscode-dark/);
  assert.match(error, /body\.vscode-dark/);
  assert.doesNotMatch(loading, /<script/i);
  assert.doesNotMatch(error, /<script/i);
});
