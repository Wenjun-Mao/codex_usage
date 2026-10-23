const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const { WEBVIEW_COMMANDS, decorateUsageReport, renderStorageReport } = require("../out/reportHtml");
const manifest = require("../package.json");

const retired = ["openTaskTransfer", "importTasks", "exportTasks", "reviewTransferStatus", "chooseTransferFolder"];
const controls = { range: "30d", theme: "night", projectCount: 0, loadedSeconds: 0.01,
  cacheHit: false, version: manifest.version, view: "usage", lastCaptureAt: "" };

test("retired transfer commands are absent from activation, contributions and command permissions", () => {
  const active = [...manifest.activationEvents, ...manifest.contributes.commands.map(item => item.command), ...WEBVIEW_COMMANDS];
  for (const name of retired) assert.ok(active.every(value => !value.endsWith(`codexUsage.${name}`)), name);
  assert.ok(!manifest.keywords.includes("task-transfer"));
  const source = fs.readFileSync(path.join(__dirname, "../src/extension.ts"), "utf8");
  for (const name of retired) assert.ok(!source.includes(`codexUsage.${name}`), name);
  assert.ok(WEBVIEW_COMMANDS.includes("codexUsage.exportAgentActivityCsv"));
  assert.ok(manifest.contributes.commands.some(item => item.command === "codexUsage.handoffLegacyService"));
});

test("both dashboard views omit Task Transfer and retain capture and storage workflows", () => {
  const usage = decorateUsageReport("<html><head></head><body><main></main></body></html>", controls, "vscode-resource:");
  const storage = renderStorageReport({ totals: { total_bytes: 0, root_bytes: 0, descendant_bytes: 0,
    task_tree_count: 0, physical_file_count: 0 }, task_trees: [], diagnostics: [] },
    { ...controls, view: "storage" }, "vscode-resource:");
  for (const html of [usage, storage]) {
    assert.doesNotMatch(html, /Task Transfer|openTaskTransfer|importTasks|exportTasks|reviewTransferStatus|chooseTransferFolder/);
    assert.match(html, /command:codexUsage\.captureNow/);
    assert.match(html, /command:codexUsage\.showStorageView/);
    assert.doesNotMatch(html, /<script/i);
  }
  assert.match(usage, /command:codexUsage\.exportAgentActivityCsv/);
});

test("clean extension output contains no retired transfer implementation", () => {
  for (const name of ["taskTransferClient", "taskTransferContract"]) {
    for (const suffix of [".js", ".js.map"]) {
      assert.equal(fs.existsSync(path.join(__dirname, "../out", name + suffix)), false);
    }
  }
});
