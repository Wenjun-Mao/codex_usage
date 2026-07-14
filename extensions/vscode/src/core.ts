import * as path from "path";

export { parseSyncStatusSummary } from "./syncProtocol";
export type { SyncStatusSummary } from "./syncProtocol";

export const RANGE_VALUES = ["today", "yesterday", "7d", "30d", "month", "all"] as const;
export type ReportRange = (typeof RANGE_VALUES)[number];
export const THEME_VALUES = ["auto", "day", "night"] as const;
export type ReportTheme = (typeof THEME_VALUES)[number];
export const WEBVIEW_COMMANDS = [
  "codexUsage.selectRange",
  "codexUsage.selectProjects",
  "codexUsage.selectTheme",
  "codexUsage.openSyncMenu",
  "codexUsage.refreshDashboard",
  "codexUsage.openSettings",
] as const;

export const SYNC_FILE_CHANGE_DEBOUNCE_MS = 30_000;
export const SYNC_FOCUS_COOLDOWN_MS = 5 * 60_000;
export const SYNC_AUTO_WARNING_COOLDOWN_MS = 5 * 60_000;

export const SYNC_STATUS_KIND_VALUES = ["off", "idle", "waiting", "scanning", "pulling", "pushing", "conflict", "issue"] as const;
export type SyncStatusKind = (typeof SYNC_STATUS_KIND_VALUES)[number];

export type ProjectTransitionsSettings = {
  autoDetect: boolean;
};

export type ReportCommandOptions = {
  range: string;
  outputPath: string;
  projectKeys?: string[];
  theme?: string;
  projectTransitions?: ProjectTransitionsSettings;
};

export type SummaryCommandOptions = {
  range: string;
  groupBy?: string;
  projectKeys?: string[];
  projectTransitions?: ProjectTransitionsSettings;
};

export type ThreadsCommandOptions = {
  projectKeys?: string[];
  projectTransitions?: ProjectTransitionsSettings;
};

export type SyncSettings = {
  enabled: boolean;
  dir: string;
  selectionVersion: number;
  threadIds: string[];
  autoPull: boolean;
  autoPush: boolean;
};

export type ExtensionSettings = {
  range: ReportRange;
  projectKeys: string[];
  theme: ReportTheme;
  sync: SyncSettings;
  projectTransitions: ProjectTransitionsSettings;
};

export type ProjectChoice = {
  key: string;
  label: string;
  description: string;
  detail: string;
  totalTokens: number;
  picked: boolean;
};

export type SyncMenuAction =
  | "syncNow"
  | "syncStatus"
  | "pauseSync"
  | "resumeSync"
  | "changeFolder"
  | "changeTasks"
  | "clearSync"
  | "openSyncFolder";

export type SyncMenuQuickPickItem = {
  label: string;
  description: string;
  detail: string;
  action: SyncMenuAction;
};

export type TransitionChoice = {
  label: string;
  description: string;
  detail: string;
  picked: boolean;
  transition: {
    source_key: string;
    source_label: string;
    target_key: string;
    target_label: string;
    effective_from: string;
    confidence: number;
    evidence: string[];
    thread_ids: string[];
  };
};

export type WebviewControlState = {
  range: ReportRange;
  projectKeys: string[];
  theme: ReportTheme;
  sync?: Pick<SyncSettings, "enabled" | "dir" | "selectionVersion" | "threadIds">;
  versionLabel?: string;
};

export const PROJECT_KEYS_STATE_KEY = "projectKeys";
export const SYNC_DIR_STATE_KEY = "syncDir";
export const SYNC_THREAD_IDS_STATE_KEY = "syncThreadIds";
export const SYNC_SELECTION_VERSION = 2;
export const SYNC_SELECTION_VERSION_STATE_KEY = "syncSelectionVersion";

export type GlobalStateReader = {
  get<T>(key: string, defaultValue: T): T;
};

export type SessionDirDiscoveryOptions = {
  codexHome?: string;
  userProfile?: string;
  homeDir?: string;
};

export function normalizeRange(value: unknown): ReportRange {
  return typeof value === "string" && RANGE_VALUES.includes(value as ReportRange)
    ? (value as ReportRange)
    : "30d";
}

export function normalizeTheme(value: unknown): ReportTheme {
  return typeof value === "string" && THEME_VALUES.includes(value as ReportTheme)
    ? (value as ReportTheme)
    : "auto";
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

export function normalizeThreadIds(values: unknown): string[] {
  return normalizeProjectKeys(values);
}

export function readProjectKeysState(state: GlobalStateReader): string[] {
  return normalizeProjectKeys(state.get(PROJECT_KEYS_STATE_KEY, []));
}

export function readSyncDirState(state?: GlobalStateReader): string {
  const value = state?.get(SYNC_DIR_STATE_KEY, "");
  return typeof value === "string" ? value.trim() : "";
}

export function readSyncThreadIdsState(state?: GlobalStateReader): string[] {
  return normalizeThreadIds(state?.get(SYNC_THREAD_IDS_STATE_KEY, []));
}

export function readSyncSelectionVersionState(state?: GlobalStateReader): number {
  return state?.get<number>(SYNC_SELECTION_VERSION_STATE_KEY, 0) === SYNC_SELECTION_VERSION
    ? SYNC_SELECTION_VERSION
    : 0;
}

export function normalizeSyncSettings(value: unknown): SyncSettings {
  const input = isRecord(value) ? value : {};
  const selectionVersion = input.selectionVersion === SYNC_SELECTION_VERSION ? SYNC_SELECTION_VERSION : 0;
  return {
    enabled: input.enabled === true,
    dir: typeof input.dir === "string" ? input.dir.trim() : "",
    selectionVersion,
    threadIds: selectionVersion === SYNC_SELECTION_VERSION ? normalizeThreadIds(input.threadIds) : [],
    autoPull: input.autoPull !== false,
    autoPush: input.autoPush !== false,
  };
}

export function hasValidSyncSelection(settings: SyncSettings): boolean {
  const normalized = normalizeSyncSettings(settings);
  return Boolean(
    normalized.dir &&
    normalized.selectionVersion === SYNC_SELECTION_VERSION &&
    normalized.threadIds.length > 0
  );
}

export function syncBackoffMs(failureCount: number): number {
  if (!Number.isFinite(failureCount) || failureCount <= 0) {
    return 0;
  }
  if (failureCount === 1) {
    return 60_000;
  }
  if (failureCount === 2) {
    return 5 * 60_000;
  }
  return 15 * 60_000;
}

export function syncFailureRequiresNotification(message: string): boolean {
  const text = message.toLowerCase();
  return (
    text.includes("conflict") ||
    text.includes("not configured") ||
    text.includes("bundled codex-usage executable was not found") ||
    text.includes("no codex tasks are selected")
  );
}

export function syncStatusKindLabel(kind: SyncStatusKind): string {
  if (kind === "off") {
    return "Off";
  }
  if (kind === "idle") {
    return "Idle";
  }
  if (kind === "waiting") {
    return "Waiting";
  }
  if (kind === "scanning") {
    return "Scanning";
  }
  if (kind === "pulling") {
    return "Pulling";
  }
  if (kind === "pushing") {
    return "Pushing";
  }
  if (kind === "conflict") {
    return "Conflict";
  }
  return "Issue";
}

export function candidateSessionDirs(options: SessionDirDiscoveryOptions): string[] {
  const candidates: string[] = [];
  if (options.codexHome?.trim()) {
    appendCodexSessionDirs(candidates, options.codexHome.trim());
  }
  if (options.userProfile?.trim()) {
    appendCodexSessionDirs(candidates, path.join(options.userProfile.trim(), ".codex"));
  }
  if (options.homeDir?.trim()) {
    appendCodexSessionDirs(candidates, path.join(options.homeDir.trim(), ".codex"));
  }
  return dedupePaths(candidates);
}

export function selectSessionDirsForWatcher(
  candidates: string[],
  codexHomeSet: boolean,
  exists: (dir: string) => boolean,
): string[] {
  if (candidates.length === 0) {
    return [];
  }
  if (codexHomeSet) {
    return siblingSessionDirs(candidates, candidates[0]);
  }
  const existing = candidates.find((candidate) => exists(candidate));
  return siblingSessionDirs(candidates, existing ?? candidates[0]);
}

export function cacheDirPath(globalStoragePath: string): string {
  return path.join(globalStoragePath, "cache");
}

export function cacheDbPath(globalStoragePath: string): string {
  return path.join(cacheDirPath(globalStoragePath), "usage-cache.sqlite3");
}

export function buildCodexUsageEnv(
  globalStoragePath: string,
  baseEnv: NodeJS.ProcessEnv = process.env,
): NodeJS.ProcessEnv {
  return {
    ...baseEnv,
    CODEX_USAGE_CACHE_DIR: cacheDirPath(globalStoragePath),
  };
}

export type SyncSetupStepOptions = {
  refreshDashboard?: boolean;
};

export function shouldRefreshAfterSyncSetupStep(options: SyncSetupStepOptions | undefined): boolean {
  return options?.refreshDashboard !== false;
}

export function extensionVersionLabel(packageJson: unknown): string {
  if (!isRecord(packageJson) || typeof packageJson.version !== "string") {
    return "";
  }
  const version = packageJson.version.trim();
  return version ? `v${version}` : "";
}

export function buildReportArgs(options: ReportCommandOptions): string[] {
  const args = [
    "report",
    "--range",
    normalizeRange(options.range),
    "--output",
    options.outputPath,
    "--theme",
    normalizeTheme(options.theme),
  ];
  appendProjectTransitionArgs(args, options);
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
  appendProjectTransitionArgs(args, options);
  appendProjectKeyArgs(args, options.projectKeys);
  return args;
}

export function buildThreadsArgs(options: ThreadsCommandOptions): string[] {
  const args = ["threads", "--json"];
  appendProjectTransitionArgs(args, options);
  appendProjectKeyArgs(args, options.projectKeys);
  return args;
}

export function buildTransitionSuggestArgs(): string[] {
  const args = ["transitions", "suggest", "--json"];
  return args;
}

function appendProjectTransitionArgs(
  args: string[],
  options: ReportCommandOptions | SummaryCommandOptions | ThreadsCommandOptions,
): void {
  if (options.projectTransitions?.autoDetect === false) {
    args.push("--no-auto-transitions");
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
  if (platform === "darwin" && arch === "arm64") {
    return path.join(extensionPath, "bin", "darwin-arm64", "codex-usage");
  }
  throw new Error(
    `Unsupported platform: ${platform}-${arch}. This VSIX currently bundles Windows x64 and macOS Apple Silicon.`,
  );
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

export function parseTransitionChoices(transitionsJson: string): TransitionChoice[] {
  let payload: unknown;
  try {
    payload = JSON.parse(transitionsJson);
  } catch (error) {
    throw new Error(`Could not parse Codex transition JSON: ${error instanceof Error ? error.message : String(error)}`);
  }

  if (!isRecord(payload) || !Array.isArray(payload.project_transitions)) {
    throw new Error("Codex transition JSON did not contain a project_transitions array.");
  }

  const choices: TransitionChoice[] = [];
  for (const row of payload.project_transitions) {
    if (!isRecord(row) || typeof row.source_key !== "string" || typeof row.target_key !== "string") {
      continue;
    }
    const sourceKey = row.source_key.trim();
    const targetKey = row.target_key.trim();
    if (!sourceKey || !targetKey) {
      continue;
    }
    const sourceLabel = stringValue(row.source_label) || sourceKey;
    const targetLabel = stringValue(row.target_label) || targetKey;
    const effectiveFrom = stringValue(row.effective_from);
    const confidence = numberValue(row.confidence);
    const evidence = stringArrayValue(row.evidence);
    const threadIds = stringArrayValue(row.thread_ids);
    choices.push({
      label: `${sourceLabel} -> ${targetLabel}`,
      description: `Confidence ${confidence}%`,
      detail: transitionDetail({
        effectiveFrom,
        sourceKey,
        targetKey,
        evidence,
        threadIds,
      }),
      picked: true,
      transition: {
        source_key: sourceKey,
        source_label: sourceLabel,
        target_key: targetKey,
        target_label: targetLabel,
        effective_from: effectiveFrom,
        confidence,
        evidence,
        thread_ids: threadIds,
      },
    });
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
  const version = state.versionLabel?.trim()
    ? `<span class="codex-usage-version" aria-label="Codex Usage extension version">${escapeHtml(state.versionLabel.trim())}</span>`
    : "";
  return (
    '<nav class="codex-usage-actions" aria-label="Codex Usage dashboard controls">' +
    `<a href="command:codexUsage.selectRange">Range: ${escapeHtml(state.range)}</a>` +
    `<a href="command:codexUsage.selectProjects">Projects: ${escapeHtml(projectFilterLabel(state.projectKeys))}</a>` +
    `<a href="command:codexUsage.selectTheme">Theme: ${escapeHtml(themeLabel(state.theme))}</a>` +
    `<a href="command:codexUsage.openSyncMenu">${escapeHtml(syncControlLabel(state.sync))}</a>` +
    '<a href="command:codexUsage.refreshDashboard">Refresh</a>' +
    '<a href="command:codexUsage.openSettings">Settings</a>' +
    version +
    "</nav>"
  );
}

export function syncControlLabel(sync: WebviewControlState["sync"]): string {
  const normalized = normalizeSyncSettings(sync ?? {});
  if (!hasValidSyncSelection(normalized)) {
    return "Sync: Setup required ▾";
  }
  if (!normalized.enabled) {
    return "Sync: Off ▾";
  }
  if (normalized.threadIds.length === 1) {
    return "Sync: 1 task ▾";
  }
  return `Sync: ${normalized.threadIds.length} tasks ▾`;
}

export function syncMenuQuickPickItems(sync: SyncSettings): SyncMenuQuickPickItem[] {
  const settings = normalizeSyncSettings(sync);
  const taskCount = settings.threadIds.length;
  const taskDescription = taskCount === 1 ? "1 selected" : `${taskCount} selected`;

  const primary: SyncMenuQuickPickItem = settings.enabled
    ? {
        label: "$(sync) Sync Now",
        description: "Pull then push selected tasks",
        detail: "Run one manual sync using the current folder and task selections.",
        action: "syncNow",
      }
    : {
        label: "$(play) Resume Sync",
        description: hasValidSyncSelection(settings) ? "Paused" : "Setup needed",
        detail: "Turn sync back on without changing the selected folder or tasks.",
        action: "resumeSync",
      };

  const items: SyncMenuQuickPickItem[] = [
    primary,
    {
      label: "$(info) Sync Status",
      description: "Inspect selected tasks",
      detail: "Show local/remote state, conflicts, missing files, and memory warnings.",
      action: "syncStatus",
    },
  ];

  if (settings.enabled) {
    items.push({
      label: "$(debug-pause) Pause Sync",
      description: "Stop automatic and manual sync",
      detail: "Keeps the selected folder and tasks so sync can be resumed later.",
      action: "pauseSync",
    });
  }

  items.push(
    {
      label: "$(folder-opened) Change Folder",
      description: settings.dir || "No folder selected",
      detail: "Choose a different bring-your-own sync folder.",
      action: "changeFolder",
    },
    {
      label: "$(checklist) Change Tasks",
      description: taskDescription,
      detail: "Choose the exact Codex tasks to sync.",
      action: "changeTasks",
    },
    {
      label: "$(trash) Clear Sync Setup",
      description: "Disable sync and forget selections",
      detail: "Does not delete local Codex files or anything inside the sync folder.",
      action: "clearSync",
    },
    {
      label: "$(folder) Open Sync Folder",
      description: settings.dir || "No folder selected",
      detail: "Open the configured bring-your-own sync folder.",
      action: "openSyncFolder",
    },
  );
  return items;
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function stringValue(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function stringArrayValue(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const strings: string[] = [];
  const seen = new Set<string>();
  for (const item of value) {
    const text = stringValue(item);
    if (!text || seen.has(text)) {
      continue;
    }
    strings.push(text);
    seen.add(text);
  }
  return strings;
}

function numberValue(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function transitionDetail(options: {
  effectiveFrom: string;
  sourceKey: string;
  targetKey: string;
  evidence: string[];
  threadIds: string[];
}): string {
  const parts = [
    options.effectiveFrom ? `Effective: ${options.effectiveFrom}` : "",
    `From: ${options.sourceKey}`,
    `To: ${options.targetKey}`,
    options.evidence.length > 0 ? `Evidence: ${options.evidence.join(" | ")}` : "",
    options.threadIds.length > 0 ? `Threads: ${options.threadIds.join(", ")}` : "",
  ].filter(Boolean);
  return parts.join("\n");
}

function formatInt(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

function appendCodexSessionDirs(candidates: string[], codexRoot: string): void {
  candidates.push(path.join(codexRoot, "sessions"));
  candidates.push(path.join(codexRoot, "archived_sessions"));
}

function siblingSessionDirs(candidates: string[], selected: string): string[] {
  const parent = path.dirname(selected);
  return candidates.filter((candidate) => path.dirname(candidate) === parent);
}

function dedupePaths(paths: string[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const candidate of paths) {
    const normalized = candidate.replace(/[\\/]+$/, "");
    const key = normalized.toLocaleLowerCase();
    if (!normalized || seen.has(key)) {
      continue;
    }
    seen.add(key);
    out.push(normalized);
  }
  return out;
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
