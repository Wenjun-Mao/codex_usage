const assert = require("node:assert/strict");
const test = require("node:test");

const {
  decorateUsageReport,
  renderError,
  renderLoading,
  renderStorageReport,
} = require("../out/reportHtml");

const controls = {
  range: "30d",
  theme: "night",
  projectCount: 0,
  loadedSeconds: 0.04,
  cacheHit: true,
  version: "2.1.0",
  view: "usage",
  lastCaptureAt: "2026-09-04T12:30:00Z",
};

test("usage report receives companion controls and restrictive CSP", () => {
  const result = decorateUsageReport("<html><head></head><body><main><h1>Report</h1></main></body></html>", controls, "vscode-resource:");
  assert.match(result, /Content-Security-Policy/);
  assert.match(result, /command:codexUsage\.captureNow/);
  assert.match(result, />Capture Usage</);
  assert.match(result, /aria-label="Reload usage from ledger"/);
  assert.match(result, /Range: 30d/);
  assert.match(result, /data-codex-theme="night"/);
  assert.doesNotMatch(result, />Refresh</);
  assert.match(result, /Loaded in 0\.04s/);
  assert.doesNotMatch(result, /<script/i);
});

test("storage report escapes task metadata and exposes only explicit analysis", () => {
  const result = renderStorageReport({
    totals: { total_bytes: 1024, root_bytes: 512, descendant_bytes: 512, task_tree_count: 1, physical_file_count: 2 },
    diagnostics: ["<diagnostic>"],
    task_trees: [{
      root_task_id: "task-1",
      title: "<unsafe>",
      project_label: "project",
      total_bytes: 1024,
      root_bytes: 512,
      descendant_bytes: 512,
      descendant_count: 1,
      analysis_status: "not_analyzed",
      has_history_amplification: false,
      has_media_amplification: false,
      has_active_root_history_risk: false,
      has_missing_root: false,
    }],
  }, { ...controls, view: "storage" }, "vscode-resource:");
  assert.match(result, /&lt;unsafe&gt;/);
  assert.match(result, /&lt;diagnostic&gt;/);
  assert.match(result, /command:codexUsage\.analyzeTaskStorage/);
  assert.match(result, /aria-label="Reload storage inventory"/);
  assert.match(result, /storage inventory/);
  assert.match(result, /data-codex-theme="night"/);
  assert.doesNotMatch(result, /Range: 30d/);
  assert.doesNotMatch(result, /Back Up|Rollover/);
});

test("loading and error documents honor the explicit report theme", () => {
  assert.match(renderLoading("Loading", "vscode-resource:", "night"), /data-codex-theme="night"/);
  assert.match(renderError("Failed", "vscode-resource:", "day"), /data-codex-theme="day"/);
});
