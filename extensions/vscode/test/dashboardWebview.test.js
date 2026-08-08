const assert = require("node:assert/strict");
const test = require("node:test");

const {
  injectWebviewControls,
  injectWebviewCsp,
  renderErrorHtml,
  renderLoadingHtml,
  injectStorageBackupActions,
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
    loadedSeconds: 4.24,
    versionLabel: "v1.0.0",
  });
  const withoutTiming = injectWebviewControls(html, {
    range: "today",
    projectKeys: [],
    theme: "auto",
    taskTransfer: { folder: "" },
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

test("Task Storage backup actions use a command allowlist URI with a full task ID", () => {
  const report = '<section data-report-section="task-storage-details"><table><thead><tr><th>Task</th><th>Flags</th></tr></thead><tbody><tr data-storage-tree-id="root-1234567890abcdef"><td>Task <code>root-1234567...</code></td><td>-</td></tr></tbody></table></section>';
  const out = injectStorageBackupActions(report);

  assert.match(out, /<th>Backup<\/th>/);
  assert.match(out, /command:codexUsage\.backupTask\?%5B%22root-1234567890abcdef%22%5D/);
  assert.match(out, />Back Up<\/a>/);
  assert.doesNotMatch(out, /<script/i);
});

test("standalone report markup gains backup controls only during extension injection", () => {
  const report = '<html><head></head><body><main><section data-report-section="task-storage-details"><table><thead><tr><th>Task</th><th>Flags</th></tr></thead><tbody><tr data-storage-tree-id="root-1234567890abcdef"><td>Task <code>root-1234567...</code></td><td>-</td></tr></tbody></table></section></main></body></html>';
  const state = { range: "7d", projectKeys: [], theme: "auto", taskTransfer: { folder: "" } };
  const extensionShape = injectWebviewControls(report, state);

  assert.doesNotMatch(report, /codexUsage\.backupTask/);
  assert.match(extensionShape, /codexUsage\.backupTask/);
});
