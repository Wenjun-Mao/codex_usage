const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const {
  buildReportArgs,
  buildSummaryArgs,
  bundledExecutablePath,
  injectWebviewControls,
  injectWebviewCsp,
  normalizeRange,
  parseProjectChoices,
} = require("../out/core");

test("buildReportArgs includes optional CLI arguments for the bundled executable", () => {
  const args = buildReportArgs({
    range: "all",
    outputPath: "C:/tmp/report.html",
    sessionsDir: "C:/Users/example/.codex/sessions",
    subscriptionUsd: 20,
    projectKeys: ["repo-a", "repo-b"],
  });

  assert.deepEqual(args, [
    "report",
    "--range",
    "all",
    "--output",
    "C:/tmp/report.html",
    "--sessions-dir",
    "C:/Users/example/.codex/sessions",
    "--subscription-usd",
    "20",
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
    sessionsDir: "/tmp/sessions",
    projectKeys: ["alpha", " beta "],
  });

  assert.deepEqual(args, [
    "summary",
    "--range",
    "30d",
    "--by",
    "project",
    "--json",
    "--sessions-dir",
    "/tmp/sessions",
    "--project-key",
    "alpha",
    "--project-key",
    "beta",
  ]);
  assert.doesNotMatch(args.join(" "), /uv|codex-usage/);
});

test("normalizeRange falls back to 30d for unknown settings", () => {
  assert.equal(normalizeRange("month"), "month");
  assert.equal(normalizeRange("nonsense"), "30d");
  assert.equal(normalizeRange(undefined), "30d");
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

test("injectWebviewControls adds command links without scripts or external URLs", () => {
  const html = "<!doctype html><html><head><title>Report</title></head><body><main><h1>Report</h1></main></body></html>";
  const out = injectWebviewControls(html, { range: "7d", projectKeys: ["repo-a", "repo-b"] });

  assert.match(out, /codex-usage-actions/);
  assert.match(out, /command:codexUsage.selectRange/);
  assert.match(out, /Projects: 2 selected/);
  assert.doesNotMatch(out, /<script/i);
  assert.doesNotMatch(out, /https:/);
});
