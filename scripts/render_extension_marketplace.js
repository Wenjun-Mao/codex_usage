// Synthetic Marketplace fixture through the extension's production HTML renderer.
const fs = require("node:fs");
const path = require("node:path");
const { decorateUsageReport, renderStorageReport } = require(path.join(
  __dirname, "../extensions/vscode/out/reportHtml.js",
));

const [usageInput, outputDirectory] = process.argv.slice(2);
if (!usageInput || !outputDirectory) {
  throw new Error("usage: node render_extension_marketplace.js USAGE_HTML OUTPUT_DIR");
}
const usage = fs.readFileSync(usageInput, "utf8");
const storage = {
  totals: {
    total_bytes: 2_516_582_400,
    root_bytes: 839_860_224,
    descendant_bytes: 1_676_722_176,
    task_tree_count: 9,
    physical_file_count: 143,
  },
  diagnostics: [],
  task_trees: [
    ["sample-task-01", "Build onboarding flow", "Studio Atlas", 594_000_000, 124_000_000, 470_000_000, 22, true, false],
    ["sample-task-02", "Investigate sync reliability", "Northstar", 430_000_000, 188_000_000, 242_000_000, 14, false, true],
    ["sample-task-03", "Refine account settings", "Studio Atlas", 315_000_000, 151_000_000, 164_000_000, 9, false, false],
    ["sample-task-04", "Prototype search results", "Meridian", 227_000_000, 70_000_000, 157_000_000, 7, true, false],
    ["sample-task-05", "Review release notes", "Northstar", 168_000_000, 98_000_000, 70_000_000, 5, false, false],
  ].map(([root_task_id, title, project_label, total_bytes, root_bytes, descendant_bytes, descendant_count, has_history_amplification, has_media_amplification]) => ({
    root_task_id, title, project_label, total_bytes, root_bytes, descendant_bytes,
    descendant_count, has_history_amplification, has_media_amplification,
    analysis_status: "not_analyzed", has_active_root_history_risk: false,
    has_missing_root: false,
  })),
};

for (const theme of ["day", "night"]) {
  const state = {
    range: "All", theme, projectCount: 0, loadedSeconds: 0.04,
    cacheHit: true, version: "2.9.0", view: "usage",
    lastCaptureAt: "synthetic · 2026-09-02 16:00 UTC",
  };
  fs.writeFileSync(path.join(outputDirectory, `usage-${theme}.html`),
    decorateUsageReport(usage, state, "vscode-resource:"));
  fs.writeFileSync(path.join(outputDirectory, `storage-${theme}.html`),
    renderStorageReport(storage, { ...state, view: "storage" }, "vscode-resource:"));
}
