import type { ReportRange, ReportTheme, ReportView, StorageSnapshot } from "./types";

export const WEBVIEW_COMMANDS = [
  "codexUsage.captureNow",
  "codexUsage.selectRange",
  "codexUsage.selectProjects",
  "codexUsage.selectTheme",
  "codexUsage.showUsageView",
  "codexUsage.showStorageView",
  "codexUsage.openTaskTransfer",
  "codexUsage.openNativeApp",
  "codexUsage.analyzeTaskStorage",
  "codexUsage.refreshDashboard",
] as const;

interface ControlState {
  range: ReportRange;
  theme: ReportTheme;
  projectCount: number;
  loadedSeconds: number;
  cacheHit: boolean;
  version: string;
  view: ReportView;
}

export function decorateUsageReport(html: string, state: ControlState, cspSource: string): string {
  const additions = `${companionCsp(cspSource)}${companionStyle()}`;
  const controls = companionControls(state);
  return html
    .replace(/<head([^>]*)>/i, `<head$1>${additions}`)
    .replace(/<main([^>]*)>/i, `<main$1>${controls}`);
}

export function renderStorageReport(snapshot: StorageSnapshot, state: ControlState, cspSource: string): string {
  const totals = snapshot.totals;
  const rows = snapshot.task_trees.map((tree) => {
    const flags = [
      tree.has_history_amplification ? "History amplification" : "",
      tree.has_media_amplification ? "Inline media" : "",
      tree.has_active_root_history_risk ? "Active root risk" : "",
      tree.has_missing_root ? "Root missing" : "",
    ].filter(Boolean).join(", ") || "None";
    const analyze = tree.analysis_status === "complete" ? "" : `<a class="icon-action" title="Analyze task storage" href="${commandUri("codexUsage.analyzeTaskStorage", [tree.root_task_id])}">Analyze</a>`;
    return `<tr><td><strong>${escapeHtml(tree.title || tree.root_task_id)}</strong><small>${escapeHtml(tree.root_task_id)}</small></td><td>${escapeHtml(tree.project_label || "Unassigned")}</td><td>${formatBytes(tree.total_bytes)}</td><td>${formatBytes(tree.root_bytes)}</td><td>${formatBytes(tree.descendant_bytes)}<small>${tree.descendant_count.toLocaleString()} descendants</small></td><td>${escapeHtml(flags)}</td><td>${analyze}</td></tr>`;
  }).join("");
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${companionCsp(cspSource)}${baseStyle()}${companionStyle()}<title>Codex Task Storage</title></head><body><main class="report-shell">${companionControls(state)}<header class="report-header"><p class="eyebrow">Local corpus</p><h1>Task Storage</h1><p>Read-only inventory and amplification diagnostics. Analysis runs only when requested.</p></header>${snapshot.diagnostics.map((diagnostic) => `<div class="notice warning">${escapeHtml(diagnostic)}</div>`).join("")}<section class="metric-strip"><div><span>Total corpus</span><strong>${formatBytes(totals.total_bytes)}</strong></div><div><span>Root tasks</span><strong>${formatBytes(totals.root_bytes)}</strong></div><div><span>Descendants</span><strong>${formatBytes(totals.descendant_bytes)}</strong></div><div><span>Task trees</span><strong>${totals.task_tree_count.toLocaleString()}</strong></div><div><span>Files</span><strong>${totals.physical_file_count.toLocaleString()}</strong></div></section><section><h2>Largest Task Trees</h2><div class="table-scroll"><table><thead><tr><th>Task</th><th>Project</th><th>Total</th><th>Root</th><th>Descendants</th><th>Flags</th><th></th></tr></thead><tbody>${rows}</tbody></table></div></section></main></body></html>`;
}

export function renderLoading(message: string, cspSource: string): string {
  return `<!doctype html><html><head>${companionCsp(cspSource)}${baseStyle()}</head><body><main class="loading"><span></span>${escapeHtml(message)}</main></body></html>`;
}

export function renderError(message: string, cspSource: string): string {
  return `<!doctype html><html><head>${companionCsp(cspSource)}${baseStyle()}</head><body><main><h1>Codex Usage</h1><div class="notice error">${escapeHtml(message)}</div></main></body></html>`;
}

function companionControls(state: ControlState): string {
  const projectLabel = state.projectCount === 0 ? "All Projects" : state.projectCount === 1 ? "1 Project" : `${state.projectCount} Projects`;
  return `<nav class="companion-actions" aria-label="Codex Usage controls"><a class="primary" href="command:codexUsage.captureNow">Capture Now</a><a href="command:codexUsage.selectRange">Range: ${escapeHtml(state.range)}</a><a href="command:codexUsage.selectProjects">${projectLabel}</a><a href="command:codexUsage.selectTheme">Theme: ${escapeHtml(state.theme)}</a><a href="command:codexUsage.openTaskTransfer">Task Transfer</a><a href="command:codexUsage.refreshDashboard">Refresh</a><a href="command:codexUsage.openNativeApp">Open App</a><span class="view-switch"><a href="command:codexUsage.showUsageView"${state.view === "usage" ? ' aria-current="page"' : ""}>Usage</a><a href="command:codexUsage.showStorageView"${state.view === "storage" ? ' aria-current="page"' : ""}>Storage</a></span><span class="metadata">Loaded in ${state.loadedSeconds.toFixed(2)}s · ${state.cacheHit ? "render cache" : "ledger"} · v${escapeHtml(state.version)}</span></nav>`;
}

function companionCsp(cspSource: string): string {
  const policy = `default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src ${cspSource}`;
  return `<meta http-equiv="Content-Security-Policy" content="${escapeHtml(policy)}">`;
}

function companionStyle(): string {
  return `<style>.companion-actions{display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin:0 0 20px;padding:8px;border:1px solid var(--border,#343a42);background:var(--surface,#171b20)}.companion-actions a{display:inline-flex;align-items:center;min-height:29px;padding:4px 9px;border:1px solid var(--border,#343a42);border-radius:5px;color:var(--accent,#50b8db);text-decoration:none;font-size:12px}.companion-actions a:hover,.companion-actions a[aria-current=page]{background:var(--surface-soft,#232932)}.companion-actions a.primary{border-color:var(--accent,#50b8db);background:var(--accent,#238aaa);color:#fff}.view-switch{display:inline-flex}.view-switch a{border-radius:0}.view-switch a:first-child{border-radius:5px 0 0 5px}.view-switch a:last-child{border-radius:0 5px 5px 0}.metadata{margin-left:auto;color:var(--muted,#9da8b2);font-size:11px;white-space:nowrap}</style>`;
}

function baseStyle(): string {
  return `<style>:root{color-scheme:light dark;--bg:#f5f7f9;--surface:#fff;--surface-soft:#edf1f4;--text:#172027;--muted:#64717b;--border:#d5dce1;--accent:#087ea4;--danger:#bb3748}body{margin:0;padding:24px;background:var(--bg);color:var(--text);font:14px system-ui,-apple-system,Segoe UI,sans-serif}h1{font-size:26px}h2{font-size:18px}.eyebrow{margin:0;color:var(--accent);font-size:11px;text-transform:uppercase}.report-header p{color:var(--muted)}.metric-strip{display:grid;grid-template-columns:repeat(5,minmax(110px,1fr));margin:22px 0;border-block:1px solid var(--border)}.metric-strip div{display:grid;gap:4px;padding:13px;border-right:1px solid var(--border)}.metric-strip span,small{display:block;color:var(--muted);font-size:10px}.table-scroll{overflow:auto;border:1px solid var(--border)}table{width:100%;border-collapse:collapse}th,td{padding:9px 10px;border-bottom:1px solid var(--border);text-align:right}th:first-child,td:first-child{text-align:left}th{background:var(--surface-soft);color:var(--muted);font-size:11px}.notice{padding:11px;border-left:4px solid var(--accent);background:var(--surface-soft)}.notice.error{border-left-color:var(--danger)}.loading{display:flex;justify-content:center;align-items:center;gap:10px;min-height:50vh;color:var(--muted)}.loading span{width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--accent);border-radius:50%;animation:spin .8s linear infinite}@keyframes spin{to{transform:rotate(360deg)}}@media(prefers-color-scheme:dark){:root{--bg:#101316;--surface:#15191d;--surface-soft:#1e242a;--text:#edf2f5;--muted:#9ba7b1;--border:#303840;--accent:#43b4da}}@media(max-width:760px){.metric-strip{grid-template-columns:repeat(2,1fr)}}</style>`;
}

function commandUri(command: string, args: unknown[]): string {
  return `command:${command}?${encodeURIComponent(JSON.stringify(args))}`;
}

function escapeHtml(value: string): string {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}
