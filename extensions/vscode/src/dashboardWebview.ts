import {
  normalizeProjectKeys,
  type ReportRange,
  type ReportTheme,
  type TaskTransferSettings,
} from "./core";
import { taskTransferControlLabel } from "./transferPresentation";

export type WebviewControlState = {
  range: ReportRange;
  projectKeys: string[];
  theme: ReportTheme;
  taskTransfer: TaskTransferSettings;
  versionLabel?: string;
};

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
    .codex-usage-version {
      margin-left: auto;
      color: var(--vscode-descriptionForeground, var(--muted));
      font-size: 12px;
      white-space: nowrap;
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
<html lang="en" data-codex-theme="auto">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
${basicWebviewCss()}
    .error { border-left: 4px solid var(--danger); background: var(--warn-bg); padding: 12px; }
  </style>
</head>
<body>
  <h1>Codex Usage Dashboard</h1>
  <div class="error">${escaped}</div>
</body>
</html>`;
}

export function renderLoadingHtml(message = "Generating Codex usage dashboard..."): string {
  const escaped = escapeHtml(message);
  return `<!doctype html>
<html lang="en" data-codex-theme="auto">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
${basicWebviewCss()}
  </style>
</head>
<body>
  <main class="report-shell">
    <section class="notice loading" role="status" aria-live="polite">${escaped}</section>
  </main>
</body>
</html>`;
}

function renderWebviewControls(state: WebviewControlState): string {
  const version = state.versionLabel?.trim()
    ? `<span class="codex-usage-version" aria-label="Codex Usage extension version">${escapeHtml(state.versionLabel.trim())}</span>`
    : "";
  return (
    '<nav class="codex-usage-actions" aria-label="Codex Usage dashboard controls">' +
    `<a href="command:codexUsage.selectRange">Range: ${escapeHtml(state.range)}</a>` +
    `<a href="command:codexUsage.selectProjects">Projects: ${escapeHtml(projectFilterLabel(state.projectKeys))}</a>` +
    `<a href="command:codexUsage.selectTheme">Theme: ${escapeHtml(themeLabel(state.theme))}</a>` +
    `<a href="command:codexUsage.openSyncMenu">${escapeHtml(taskTransferControlLabel())}</a>` +
    '<a href="command:codexUsage.refreshDashboard">Refresh</a>' +
    '<a href="command:codexUsage.openSettings">Settings</a>' +
    version +
    "</nav>"
  );
}

function themeLabel(theme: ReportTheme): string {
  if (theme === "day") {
    return "Day";
  }
  if (theme === "night") {
    return "Night";
  }
  return "Auto";
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

function basicWebviewCss(): string {
  return `    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --text: #0a0b0d;
      --muted: #5b616e;
      --danger: #cf202f;
      --warn-bg: #fef3f2;
    }
    body.vscode-dark {
      color-scheme: dark;
      --bg: var(--vscode-editor-background, #0d0f12);
      --text: var(--vscode-editor-foreground, #eef2f6);
      --muted: var(--vscode-descriptionForeground, #a7b0bc);
      --danger: #ff6b78;
      --warn-bg: rgba(255, 107, 120, 0.14);
    }
    body.vscode-high-contrast {
      --bg: var(--vscode-editor-background, #000000);
      --text: var(--vscode-editor-foreground, #ffffff);
      --muted: var(--vscode-editor-foreground, #ffffff);
      --danger: var(--vscode-errorForeground, #ffffff);
      --warn-bg: transparent;
    }
    body {
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
      margin: 24px;
      background: var(--bg);
      color: var(--text);
    }`;
}
