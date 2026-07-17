const assert = require("node:assert/strict");
const test = require("node:test");

const {
  injectWebviewControls,
  injectWebviewCsp,
  renderErrorHtml,
  renderLoadingHtml,
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
