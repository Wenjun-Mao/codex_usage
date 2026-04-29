import * as path from "path";

export const RANGE_VALUES = ["today", "yesterday", "7d", "30d", "month", "all"] as const;
export type ReportRange = (typeof RANGE_VALUES)[number];

export type ReportCommandOptions = {
  range: string;
  outputPath: string;
  sessionsDir?: string;
  subscriptionUsd?: number | null;
};

export type ExtensionSettings = {
  range: ReportRange;
  sessionsDir?: string;
  subscriptionUsd?: number | null;
  projectRoot?: string;
};

export function normalizeRange(value: unknown): ReportRange {
  return typeof value === "string" && RANGE_VALUES.includes(value as ReportRange)
    ? (value as ReportRange)
    : "30d";
}

export function buildReportArgs(options: ReportCommandOptions): string[] {
  const args = ["run", "codex-usage", "report", "--range", normalizeRange(options.range), "--output", options.outputPath];
  if (options.sessionsDir?.trim()) {
    args.push("--sessions-dir", options.sessionsDir.trim());
  }
  if (typeof options.subscriptionUsd === "number" && Number.isFinite(options.subscriptionUsd)) {
    args.push("--subscription-usd", String(options.subscriptionUsd));
  }
  return args;
}

export function inferProjectRoot(extensionPath: string, configuredProjectRoot?: string): string {
  const configured = configuredProjectRoot?.trim();
  if (configured) {
    return configured;
  }
  return path.resolve(extensionPath, "..", "..");
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
