const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const { buildReportArgs, inferProjectRoot, injectWebviewCsp, normalizeRange } = require("../out/core");

test("buildReportArgs includes optional CLI arguments without using a shell string", () => {
  const args = buildReportArgs({
    range: "all",
    outputPath: "C:/tmp/report.html",
    sessionsDir: "C:/Users/example/.codex/sessions",
    subscriptionUsd: 20,
  });

  assert.deepEqual(args, [
    "run",
    "codex-usage",
    "report",
    "--range",
    "all",
    "--output",
    "C:/tmp/report.html",
    "--sessions-dir",
    "C:/Users/example/.codex/sessions",
    "--subscription-usd",
    "20",
  ]);
});

test("normalizeRange falls back to 30d for unknown settings", () => {
  assert.equal(normalizeRange("month"), "month");
  assert.equal(normalizeRange("nonsense"), "30d");
  assert.equal(normalizeRange(undefined), "30d");
});

test("inferProjectRoot uses configured root when provided and repo root otherwise", () => {
  assert.equal(inferProjectRoot("/repo/extensions/vscode", "/custom/root"), "/custom/root");
  assert.equal(inferProjectRoot(path.join("/repo", "extensions", "vscode")), path.resolve("/repo"));
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
