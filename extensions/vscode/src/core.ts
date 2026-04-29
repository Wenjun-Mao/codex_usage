import * as path from "path";

export const RANGE_VALUES = ["today", "yesterday", "7d", "30d", "month", "all"] as const;
export type ReportRange = (typeof RANGE_VALUES)[number];
export const WEBVIEW_COMMANDS = [
  "codexUsage.selectRange",
  "codexUsage.selectProjects",
  "codexUsage.refreshDashboard",
  "codexUsage.openSettings",
] as const;

export type ReportCommandOptions = {
  range: string;
  outputPath: string;
  sessionsDir?: string;
  subscriptionUsd?: number | null;
  projectKeys?: string[];
};

export type SummaryCommandOptions = {
  range: string;
  groupBy?: string;
  sessionsDir?: string;
  subscriptionUsd?: number | null;
  projectKeys?: string[];
};

export type ExtensionSettings = {
  range: ReportRange;
  sessionsDir?: string;
  subscriptionUsd?: number | null;
  projectKeys: string[];
};

export type ProjectChoice = {
  key: string;
  label: string;
  description: string;
  detail: string;
  totalTokens: number;
  picked: boolean;
};

export type WebviewControlState = {
  range: ReportRange;
  projectKeys: string[];
};

export function normalizeRange(value: unknown): ReportRange {
  return typeof value === "string" && RANGE_VALUES.includes(value as ReportRange)
    ? (value as ReportRange)
    : "30d";
}

export function normalizeProjectKeys(values: unknown): string[] {
  if (!Array.isArray(values)) {
    return [];
  }
  const selected: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    if (typeof value !== "string") {
      continue;
    }
    const key = value.trim();
    if (!key || seen.has(key)) {
      continue;
    }
    selected.push(key);
    seen.add(key);
  }
  return selected;
}

export function buildReportArgs(options: ReportCommandOptions): string[] {
  const args = ["report", "--range", normalizeRange(options.range), "--output", options.outputPath];
  appendCommonArgs(args, options);
  appendProjectKeyArgs(args, options.projectKeys);
  return args;
}

export function buildSummaryArgs(options: SummaryCommandOptions): string[] {
  const args = [
    "summary",
    "--range",
    normalizeRange(options.range),
    "--by",
    options.groupBy?.trim() || "project",
    "--json",
  ];
  appendCommonArgs(args, options);
  appendProjectKeyArgs(args, options.projectKeys);
  return args;
}

function appendCommonArgs(args: string[], options: ReportCommandOptions | SummaryCommandOptions): void {
  if (options.sessionsDir?.trim()) {
    args.push("--sessions-dir", options.sessionsDir.trim());
  }
  if (typeof options.subscriptionUsd === "number" && Number.isFinite(options.subscriptionUsd)) {
    args.push("--subscription-usd", String(options.subscriptionUsd));
  }
}

function appendProjectKeyArgs(args: string[], projectKeys: string[] | undefined): void {
  for (const key of normalizeProjectKeys(projectKeys)) {
    args.push("--project-key", key);
  }
}

export function bundledExecutablePath(extensionPath: string, platform: string, arch: string): string {
  if (platform === "win32" && arch === "x64") {
    return path.join(extensionPath, "bin", "win32-x64", "codex-usage.exe");
  }
  throw new Error(`Unsupported platform: ${platform}-${arch}. This VSIX currently bundles only Windows x64.`);
}

export function parseProjectChoices(summaryJson: string, selectedProjectKeys: string[] = []): ProjectChoice[] {
  let payload: unknown;
  try {
    payload = JSON.parse(summaryJson);
  } catch (error) {
    throw new Error(`Could not parse Codex project summary JSON: ${error instanceof Error ? error.message : String(error)}`);
  }

  if (!isRecord(payload) || !Array.isArray(payload.rows)) {
    throw new Error("Codex project summary JSON did not contain a rows array.");
  }

  const selected = new Set(normalizeProjectKeys(selectedProjectKeys));
  const seen = new Set<string>();
  const choices: ProjectChoice[] = [];
  for (const row of payload.rows) {
    if (!isRecord(row) || typeof row.key !== "string") {
      continue;
    }
    const key = row.key.trim();
    if (!key || seen.has(key)) {
      continue;
    }
    const label = typeof row.label === "string" && row.label.trim() ? row.label.trim() : key;
    const usage = isRecord(row.usage) ? row.usage : {};
    const cost = isRecord(row.cost) ? row.cost : {};
    const totalTokens = numberValue(usage.total_tokens);
    const costUsd = numberValue(cost.total_usd);
    choices.push({
      key,
      label,
      totalTokens,
      description: `${formatInt(totalTokens)} tokens | $${costUsd.toFixed(4)}`,
      detail: key,
      picked: selected.has(key),
    });
    seen.add(key);
  }
  return choices;
}

export function injectWebviewControls(reportHtml: string, state: WebviewControlState): string {
  const controls = renderWebviewControls(state);
  const style = `<style id="codex-usage-extension-style">
    .codex-usage-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      margin: 0 0 18px;
      padding: 8px;
      border: 1px solid var(--vscode-panel-border, var(--border));
      border-radius: 8px;
      background: var(--vscode-editor-background, var(--surface));
    }
    .codex-usage-actions a {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 4px 9px;
      border: 1px solid var(--vscode-button-border, var(--border));
      border-radius: 6px;
      color: var(--vscode-textLink-foreground, var(--accent));
      text-decoration: none;
      font-size: 13px;
    }
    .codex-usage-actions a:hover {
      background: var(--vscode-toolbar-hoverBackground, var(--surface-soft));
    }
  </style>`;

  let html = reportHtml
    .replace(/<style id="codex-usage-extension-style">[\s\S]*?<\/style>\s*/i, "")
    .replace(/<nav class="codex-usage-actions"[\s\S]*?<\/nav>\s*/i, "");
  html = html.replace(/<\/head>/i, `${style}\n</head>`);
  if (/<main[^>]*>/i.test(html)) {
    return html.replace(/<main[^>]*>/i, (match) => `${match}\n    ${controls}`);
  }
  if (/<body[^>]*>/i.test(html)) {
    return html.replace(/<body[^>]*>/i, (match) => `${match}\n  ${controls}`);
  }
  return `${controls}\n${html}`;
}

export function injectWebviewCsp(reportHtml: string, cspSource: string): string {
  const csp = [
    "default-src 'none'",
    "img-src data:",
    "style-src 'unsafe-inline'",
    `font-src ${cspSource}`,
  ].join("; ");
  const meta = `<meta http-equiv="Content-Security-Policy" content="${escapeAttribute(csp)}" />`;

  const existingCsp = /<meta\s+http-equiv=["']Content-Security-Policy["'][^>]*>\s*/i;
  if (existingCsp.test(reportHtml)) {
    return reportHtml.replace(existingCsp, meta);
  }
  return reportHtml.replace(/<head[^>]*>/i, (match) => `${match}\n  ${meta}`);
}

export function renderErrorHtml(message: string): string {
  const escaped = escapeHtml(message);
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 24px; color: #1f2937; }
    .error { border-left: 4px solid #b42318; background: #fef3f2; padding: 12px; }
  </style>
</head>
<body>
  <h1>Codex Usage Dashboard</h1>
  <div class="error">${escaped}</div>
</body>
</html>`;
}

function escapeAttribute(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll('"', "&quot;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderWebviewControls(state: WebviewControlState): string {
  return (
    '<nav class="codex-usage-actions" aria-label="Codex Usage dashboard controls">' +
    `<a href="command:codexUsage.selectRange">Range: ${escapeHtml(state.range)}</a>` +
    `<a href="command:codexUsage.selectProjects">Projects: ${escapeHtml(projectFilterLabel(state.projectKeys))}</a>` +
    '<a href="command:codexUsage.refreshDashboard">Refresh</a>' +
    '<a href="command:codexUsage.openSettings">Settings</a>' +
    "</nav>"
  );
}

function projectFilterLabel(projectKeys: string[]): string {
  const selected = normalizeProjectKeys(projectKeys);
  if (selected.length === 0) {
    return "All Projects";
  }
  if (selected.length === 1) {
    return "1 selected";
  }
  return `${selected.length} selected`;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function formatInt(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}
