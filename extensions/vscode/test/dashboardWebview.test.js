const assert = require("node:assert/strict");
const test = require("node:test");

const {
  injectWebviewControls,
  injectWebviewCsp,
  renderErrorHtml,
  renderLoadingHtml,
  injectStorageBackupActions,
  setWebviewReportView,
} = require("../out/dashboardWebview");

test("dashboard CSP is strict and replaces an existing policy", () => {
  const html = '<html><head><meta http-equiv="Content-Security-Policy" content="old"></head><body></body></html>';
  const out = injectWebviewCsp(html, "vscode-resource:");

  assert.match(out, /default-src 'none'/);
  assert.match(out, /font-src vscode-resource:/);
  assert.doesNotMatch(out, /content="old"/);
  assert.doesNotMatch(out, /https:|script-src/);
});

test("dashboard controls always expose Task Transfer without setup-derived copy", () => {
  const html = "<!doctype html><html><head></head><body><main><h1>Report</h1></main></body></html>";
  const out = injectWebviewControls(html, {
    range: "7d",
    projectKeys: [],
    theme: "auto",
    taskTransfer: { folder: "" },
    reportView: "usage",
    versionLabel: "v0.1.35",
  });

  assert.match(out, /command:codexUsage.openSyncMenu/);
  assert.match(out, /Task Transfer ▾/);
  assert.match(out, /v0\.1\.35/);
  assert.doesNotMatch(out, /Setup required|Sync: Off|Sync: \d+ tasks?/i);
});

test("dashboard controls render loaded time in a shared trailing metadata region", () => {
  const html = "<!doctype html><html><head></head><body><main><h1>Report</h1></main></body></html>";
  const withTiming = injectWebviewControls(html, {
    range: "today",
    projectKeys: [],
    theme: "auto",
    taskTransfer: { folder: "" },
    reportView: "usage",
    loadedSeconds: 4.24,
    versionLabel: "v1.0.0",
  });
  const withoutTiming = injectWebviewControls(html, {
    range: "today",
    projectKeys: [],
    theme: "auto",
    taskTransfer: { folder: "" },
    reportView: "usage",
    versionLabel: "v1.0.0",
  });

  assert.match(withTiming, /Loaded in 4\.2 seconds/);
  assert.match(withTiming, /class="codex-usage-trailing-metadata"/);
  assert.match(withTiming, /codex-usage-load-time[\s\S]*?codex-usage-version/);
  assert.match(withTiming, /\.codex-usage-trailing-metadata\s*\{[\s\S]*?flex-wrap: wrap;/);
  assert.match(withTiming, /\.codex-usage-trailing-metadata\s*\{[\s\S]*?margin-left: auto;/);
  assert.doesNotMatch(withoutTiming, /Loaded in/);
});

test("loading and error documents remain escaped script-free and themeable", () => {
  const loading = renderLoadingHtml("Loading <tasks>");
  const error = renderErrorHtml("boom <script>alert(1)</script>");

  assert.match(loading, /Loading &lt;tasks&gt;/);
  assert.match(error, /boom &lt;script&gt;alert\(1\)&lt;\/script&gt;/);
  assert.match(loading, /body\.vscode-dark/);
  assert.match(error, /body\.vscode-dark/);
  assert.doesNotMatch(loading, /<script/i);
  assert.doesNotMatch(error, /<script/i);
});

test("Task Storage actions reflect analysis and rollover eligibility with full task IDs", () => {
  const report = '<section data-report-section="task-storage-details"><table><thead><tr><th>Task</th><th>Flags</th></tr></thead><tbody><tr data-storage-tree-id="root-incomplete" data-storage-analysis-status="partial" data-storage-can-rollover="false" data-storage-recovery-ready="true"><td>Incomplete</td><td>-</td></tr><tr data-storage-tree-id="root-ready" data-storage-analysis-status="complete" data-storage-can-rollover="true" data-storage-recovery-ready="true"><td>Ready</td><td>-</td></tr></tbody></table></section>';
  const out = injectStorageBackupActions(report);

  assert.match(out, /<th>Actions<\/th>/);
  assert.match(out, /command:codexUsage\.backupTask\?%5B%22root-incomplete%22%5D/);
  assert.match(out, /command:codexUsage\.analyzeTaskStorage\?%5B%22root-incomplete%22%5D/);
  assert.doesNotMatch(out, /prepareTaskRollover\?%5B%22root-incomplete%22%5D/);
  assert.match(out, /command:codexUsage\.prepareTaskRollover\?%5B%22root-ready%22%5D/);
  assert.doesNotMatch(out, /analyzeTaskStorage\?%5B%22root-ready%22%5D/);
  assert.doesNotMatch(out, /<script/i);
});

test("standalone report markup gains backup controls only during extension injection", () => {
  const report = '<html><head></head><body><main><section data-report-section="task-storage-details"><table><thead><tr><th>Task</th><th>Flags</th></tr></thead><tbody><tr data-storage-tree-id="root-1234567890abcdef" data-storage-analysis-status="not_analyzed" data-storage-can-rollover="false" data-storage-recovery-ready="true"><td>Task <code>root-1234567...</code></td><td>-</td></tr></tbody></table></section></main></body></html>';
  const state = {
    range: "7d",
    projectKeys: [],
    theme: "auto",
    taskTransfer: { folder: "" },
    reportView: "usage",
  };
  const extensionShape = injectWebviewControls(report, state);

  assert.doesNotMatch(report, /codexUsage\.backupTask/);
  assert.match(extensionShape, /codexUsage\.backupTask/);
  assert.match(extensionShape, /codexUsage\.analyzeTaskStorage/);
});

test("report view links become allowlisted commands and update without scripts", () => {
  const report = '<html><head></head><body><main class="report-shell"><nav class="report-view-tabs"><a data-report-view-link="usage" href="#report-usage">Usage</a><a data-report-view-link="task-storage" href="#report-task-storage">Task Storage</a></nav><section id="report-usage">Usage body</section><section id="report-task-storage">Storage body</section></main></body></html>';

  const usage = setWebviewReportView(report, "usage");
  const storage = setWebviewReportView(usage, "task-storage");

  assert.match(usage, /data-active-report-view="usage"/);
  assert.match(usage, /command:codexUsage\.showUsageView[^>]*aria-current="page"/);
  assert.match(usage, /command:codexUsage\.showTaskStorageView/);
  assert.match(storage, /data-active-report-view="task-storage"/);
  assert.match(storage, /command:codexUsage\.showTaskStorageView[^>]*aria-current="page"/);
  assert.doesNotMatch(storage, /showUsageView[^>]*aria-current/);
  assert.equal((storage.match(/data-active-report-view=/g) || []).length, 1);
  assert.doesNotMatch(storage, /<script/i);
});

test("storage view hides only the usage-range control", () => {
  const report = '<html><head></head><body><main class="report-shell"><a data-report-view-link="usage" href="#report-usage">Usage</a><a data-report-view-link="task-storage" href="#report-task-storage">Task Storage</a></main></body></html>';
  const out = injectWebviewControls(report, {
    range: "30d",
    projectKeys: ["repo"],
    theme: "night",
    taskTransfer: { folder: "" },
    reportView: "task-storage",
  });

  assert.match(out, /Usage Range: 30d/);
  assert.match(out, /codex-usage-range-action/);
  assert.match(out, /data-active-report-view="task-storage"/);
  assert.match(out, /data-active-report-view="task-storage"[^}]*codex-usage-range-action/s);
  assert.match(out, /Projects: 1 selected/);
});
