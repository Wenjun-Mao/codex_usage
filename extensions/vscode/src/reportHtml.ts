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
  lastCaptureAt: string;
}

export function decorateUsageReport(html: string, state: ControlState, cspSource: string): string {
  const additions = `${companionCsp(cspSource)}${companionStyle()}`;
  const chrome = `${companionControls(state)}${reportViewHeader(state)}`;
  return applyThemeAttribute(html, state.theme)
    .replace(/<head([^>]*)>/i, `<head$1>${additions}`)
    .replace(/<main([^>]*)>/i, `<main$1>${chrome}`);
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
  return `<!doctype html><html lang="en" data-codex-theme="${escapeHtml(state.theme)}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">${companionCsp(cspSource)}${baseStyle()}${companionStyle()}<title>Codex Task Storage</title></head><body><main class="report-shell">${companionControls(state)}${reportViewHeader(state)}${snapshot.diagnostics.map((diagnostic) => `<div class="notice warning">${escapeHtml(diagnostic)}</div>`).join("")}<section class="metric-strip" aria-label="Task storage summary"><div><span>Total corpus</span><strong>${formatBytes(totals.total_bytes)}</strong></div><div><span>Root tasks</span><strong>${formatBytes(totals.root_bytes)}</strong></div><div><span>Descendants</span><strong>${formatBytes(totals.descendant_bytes)}</strong></div><div><span>Task trees</span><strong>${totals.task_tree_count.toLocaleString()}</strong></div><div><span>Files</span><strong>${totals.physical_file_count.toLocaleString()}</strong></div></section><section class="report-section"><h2>Largest Task Trees</h2><p class="section-help">Analyze a selected tree to inspect history and inline-media amplification.</p><div class="table-scroll"><table><thead><tr><th>Task</th><th>Project</th><th>Total</th><th>Root</th><th>Descendants</th><th>Flags</th><th aria-label="Actions"></th></tr></thead><tbody>${rows}</tbody></table></div></section></main></body></html>`;
}

export function renderLoading(message: string, cspSource: string, theme: ReportTheme = "auto"): string {
  return `<!doctype html><html data-codex-theme="${escapeHtml(theme)}"><head>${companionCsp(cspSource)}${baseStyle()}</head><body><main class="loading"><span></span>${escapeHtml(message)}</main></body></html>`;
}

export function renderError(message: string, cspSource: string, theme: ReportTheme = "auto"): string {
  return `<!doctype html><html data-codex-theme="${escapeHtml(theme)}"><head>${companionCsp(cspSource)}${baseStyle()}</head><body><main class="report-shell"><h1>Codex Usage</h1><div class="notice error">${escapeHtml(message)}</div></main></body></html>`;
}

function companionControls(state: ControlState): string {
  const projectLabel = state.projectCount === 0 ? "All Projects" : state.projectCount === 1 ? "1 Project" : `${state.projectCount} Projects`;
  const rangeControl = state.view === "usage" ? `<a href="command:codexUsage.selectRange">Range: ${escapeHtml(state.range)}</a>` : "";
  const loadSource = state.view === "storage" ? "storage inventory" : state.cacheHit ? "render cache" : "ledger";
  return `<nav class="companion-actions" aria-label="Codex Usage controls"><span class="view-switch" aria-label="Report view"><a href="command:codexUsage.showUsageView"${state.view === "usage" ? ' aria-current="page"' : ""}>Usage</a><a href="command:codexUsage.showStorageView"${state.view === "storage" ? ' aria-current="page"' : ""}>Storage</a></span><span class="context-actions">${rangeControl}<a href="command:codexUsage.selectProjects">${projectLabel}</a><a href="command:codexUsage.selectTheme">Theme: ${escapeHtml(titleCase(state.theme))}</a></span><span class="global-actions"><a class="primary" title="Read changed Codex task files into the usage ledger" href="command:codexUsage.captureNow">Capture Usage</a><a href="command:codexUsage.openTaskTransfer">Task Transfer</a><a href="command:codexUsage.openNativeApp">Open App</a></span><span class="metadata"><span>Last captured ${escapeHtml(formatCaptureDate(state.lastCaptureAt))}</span><span>Loaded in ${state.loadedSeconds.toFixed(2)}s · ${loadSource} · v${escapeHtml(state.version)}</span></span></nav>`;
}

function reportViewHeader(state: ControlState): string {
  const usage = state.view === "usage";
  const eyebrow = usage ? "Usage ledger" : "Local corpus";
  const title = usage ? "Token Usage" : "Task Storage";
  const description = usage
    ? "Captured token usage for the selected range and projects."
    : "Read-only inventory and amplification diagnostics. Analysis runs only when requested.";
  const reloadLabel = usage ? "Reload usage from ledger" : "Reload storage inventory";
  return `<header class="report-header"><div><p class="eyebrow">${eyebrow}</p><h1>${title}</h1><p>${description}</p></div><a class="view-reload" title="${reloadLabel}" aria-label="${reloadLabel}" href="command:codexUsage.refreshDashboard">${refreshIcon()}</a></header>`;
}

function companionCsp(cspSource: string): string {
  const policy = `default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src ${cspSource}`;
  return `<meta http-equiv="Content-Security-Policy" content="${escapeHtml(policy)}">`;
}

function companionStyle(): string {
  return `<style>
    .companion-actions { position: sticky; top: 0; z-index: 10; display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin: 0 0 22px; padding: 8px; border: 1px solid var(--border); background: color-mix(in srgb, var(--surface) 96%, transparent); }
    .companion-actions > span { display: inline-flex; align-items: center; }
    .context-actions, .global-actions { gap: 7px; }
    .companion-actions a { display: inline-flex; align-items: center; justify-content: center; min-height: 31px; padding: 5px 9px; border: 1px solid var(--border); border-radius: 5px; color: var(--accent); text-decoration: none; font-size: 12px; white-space: nowrap; }
    .companion-actions a:hover, .companion-actions a:focus-visible, .companion-actions a[aria-current="page"] { background: var(--surface-soft); outline: none; }
    .companion-actions a:focus-visible, .view-reload:focus-visible { box-shadow: 0 0 0 2px var(--accent-soft); border-color: var(--accent); }
    .companion-actions a.primary { border-color: var(--accent); background: var(--accent); color: #fff; font-weight: 650; }
    .companion-actions a.primary:hover, .companion-actions a.primary:focus-visible { background: var(--accent-strong); }
    .view-switch { padding: 2px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-soft); }
    .view-switch a { min-height: 29px; border: 0; border-radius: 4px; color: var(--muted); }
    .view-switch a[aria-current="page"] { background: var(--surface); color: var(--text); box-shadow: var(--shadow-soft); }
    .metadata { display: grid !important; margin-left: auto; color: var(--muted); font-size: 11px; line-height: 1.35; text-align: right; white-space: nowrap; }
    .report-header { display: flex; align-items: end; justify-content: space-between; gap: 20px; margin: 0 0 20px; }
    .report-header h1 { margin: 1px 0 0; }
    .report-header p { margin: 0; color: var(--muted); }
    .report-header div > p:last-child { margin-top: 7px; }
    .eyebrow { color: var(--accent) !important; font-size: 11px; font-weight: 700; letter-spacing: 0; text-transform: uppercase; }
    .view-reload { display: inline-grid; place-items: center; width: 34px; height: 34px; flex: 0 0 auto; padding: 0; border: 1px solid var(--border); border-radius: 5px; background: var(--surface); color: var(--muted); text-decoration: none; }
    .view-reload:hover { background: var(--surface-soft); color: var(--text); }
    .view-reload svg { width: 17px; height: 17px; }
    @media (max-width: 880px) {
      .metadata { width: 100%; margin-left: 0; text-align: left; }
    }
    @media (max-width: 560px) {
      .context-actions, .global-actions { flex-wrap: wrap; }
      .report-header { align-items: start; }
    }
  </style>`;
}

function baseStyle(): string {
  return `<style>
    :root { color-scheme: light; --bg: #f5f7f9; --surface: #ffffff; --surface-soft: #edf1f4; --text: #172027; --muted: #64717b; --border: #d5dce1; --accent: #087ea4; --accent-strong: #05627f; --accent-soft: rgba(8,126,164,.10); --warning: #9b6900; --warning-soft: #fff4d2; --danger: #bb3748; --danger-soft: #fee9ec; --shadow-soft: 0 1px 2px rgba(23,32,39,.08); }
    html[data-codex-theme="night"] { color-scheme: dark; --bg: #101316; --surface: #15191d; --surface-soft: #1e242a; --text: #edf2f5; --muted: #9ba7b1; --border: #303840; --accent: #43b4da; --accent-strong: #75cbe7; --accent-soft: rgba(67,180,218,.16); --warning: #e0ab34; --warning-soft: #3b311c; --danger: #ff7485; --danger-soft: #3d2228; --shadow-soft: 0 1px 2px rgba(0,0,0,.22); }
    @media (prefers-color-scheme: dark) {
      html[data-codex-theme="auto"] { color-scheme: dark; --bg: #101316; --surface: #15191d; --surface-soft: #1e242a; --text: #edf2f5; --muted: #9ba7b1; --border: #303840; --accent: #43b4da; --accent-strong: #75cbe7; --accent-soft: rgba(67,180,218,.16); --warning: #e0ab34; --warning-soft: #3b311c; --danger: #ff7485; --danger-soft: #3d2228; --shadow-soft: 0 1px 2px rgba(0,0,0,.22); }
    }
    html[data-codex-theme="auto"] body.vscode-dark { color-scheme: dark; --bg: var(--vscode-editor-background, #101316); --surface: var(--vscode-sideBar-background, #15191d); --surface-soft: #1e242a; --text: var(--vscode-editor-foreground, #edf2f5); --muted: var(--vscode-descriptionForeground, #9ba7b1); --border: var(--vscode-panel-border, #303840); --accent: var(--vscode-textLink-foreground, #43b4da); --accent-strong: #75cbe7; --accent-soft: rgba(67,180,218,.16); --warning: #e0ab34; --warning-soft: #3b311c; --danger: #ff7485; --danger-soft: #3d2228; --shadow-soft: 0 1px 2px rgba(0,0,0,.22); }
    body.vscode-high-contrast { --bg: var(--vscode-editor-background, #000); --surface: var(--bg); --surface-soft: var(--bg); --text: var(--vscode-editor-foreground, #fff); --muted: var(--text); --border: var(--vscode-contrastBorder, #fff); --accent: var(--vscode-textLink-foreground, #0ff); --accent-strong: var(--vscode-textLink-activeForeground, #fff); --accent-soft: transparent; --warning-soft: transparent; --danger-soft: transparent; }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif; }
    .report-shell { max-width: 1180px; margin: 0 auto; padding: 24px; }
    h1 { font-size: 26px; letter-spacing: 0; }
    h2 { margin: 0 0 4px; font-size: 17px; letter-spacing: 0; }
    .section-help { margin: 0 0 12px; color: var(--muted); font-size: 12px; }
    .metric-strip { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); margin: 20px 0 26px; border-block: 1px solid var(--border); }
    .metric-strip div { display: grid; min-width: 0; gap: 3px; padding: 13px 12px; border-right: 1px solid var(--border); }
    .metric-strip div:last-child { border-right: 0; }
    .metric-strip span, small { display: block; color: var(--muted); font-size: 10px; }
    .metric-strip strong { font-size: 20px; font-variant-numeric: tabular-nums; overflow-wrap: anywhere; }
    .report-section { padding-top: 18px; border-top: 1px solid var(--border); }
    .table-scroll { overflow: auto; border: 1px solid var(--border); }
    table { width: 100%; border-collapse: collapse; background: var(--surface); font-variant-numeric: tabular-nums; }
    th, td { padding: 9px 10px; border-bottom: 1px solid var(--border); text-align: right; vertical-align: middle; }
    th:first-child, td:first-child { text-align: left; }
    th { background: var(--surface-soft); color: var(--muted); font-size: 11px; }
    tbody tr:last-child td { border-bottom: 0; }
    td strong, td small { display: block; }
    .icon-action { color: var(--accent); }
    .notice { margin: 10px 0; padding: 10px 12px; border-left: 4px solid var(--warning); background: var(--warning-soft); }
    .notice.error { border-left-color: var(--danger); background: var(--danger-soft); }
    .loading { display: flex; justify-content: center; align-items: center; gap: 10px; min-height: 50vh; color: var(--muted); }
    .loading span { width: 14px; height: 14px; border: 2px solid var(--border); border-top-color: var(--accent); border-radius: 50%; animation: spin .8s linear infinite; }
    @keyframes spin { to { transform: rotate(360deg); } }
    @media (max-width: 760px) {
      .report-shell { padding: 16px; }
      .metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .metric-strip div { border-bottom: 1px solid var(--border); }
      .metric-strip div:nth-child(2n) { border-right: 0; }
      .metric-strip div:last-child { grid-column: 1 / -1; border-bottom: 0; }
    }
    @media (max-width: 430px) {
      .metric-strip { grid-template-columns: minmax(0, 1fr); }
      .metric-strip div { border-right: 0; }
      .metric-strip div:last-child { grid-column: auto; }
    }
  </style>`;
}

function applyThemeAttribute(html: string, theme: ReportTheme): string {
  return /<html[^>]*data-codex-theme=/i.test(html)
    ? html.replace(/data-codex-theme="[^"]*"/i, `data-codex-theme="${escapeHtml(theme)}"`)
    : html.replace(/<html([^>]*)>/i, `<html$1 data-codex-theme="${escapeHtml(theme)}">`);
}

function formatCaptureDate(value: string): string {
  if (!value) return "not yet";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function refreshIcon(): string {
  // Lucide RefreshCw is inlined because VS Code webviews cannot load external assets.
  return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"></path><path d="M21 3v5h-5"></path><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"></path><path d="M8 16H3v5"></path></svg>';
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
