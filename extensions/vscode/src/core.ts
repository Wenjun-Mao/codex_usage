import * as path from "path";

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

export const SYNC_STATUS_KIND_VALUES = ["off", "idle", "waiting", "pulling", "pushing", "conflict", "issue"] as const;
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

export type SyncCommandOptions = {
  syncDir: string;
  threadIds: string[];
};

export type SyncImportCommandOptions = SyncCommandOptions & {
  conflictPolicy?: string;
};

export const SYNC_CONVERSATION_MODE_VALUES = ["selectedConversations", "allInProjects"] as const;
export type SyncConversationMode = (typeof SYNC_CONVERSATION_MODE_VALUES)[number];

export type SyncSettings = {
  enabled: boolean;
  dir: string;
  projectKeys: string[];
  conversationMode: SyncConversationMode;
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

export type ThreadChoice = {
  threadId: string;
  label: string;
  description: string;
  detail: string;
  totalTokens: number;
  estimatedSyncBytes: number;
  picked: boolean;
};

export type SyncProjectChoice = {
  key: string;
  label: string;
  description: string;
  detail: string;
  totalTokens: number;
  conversationCount: number;
  estimatedSyncBytes: number;
  picked: boolean;
};

export type SyncProjectQuickPickItem = {
  label: string;
  description?: string;
  detail?: string;
  picked?: boolean;
  projectKey: string;
};

export type SyncConversationQuickPickItem = {
  label: string;
  description?: string;
  detail?: string;
  picked?: boolean;
  threadId?: string;
  allConversations?: boolean;
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

export type SyncStatusSummary = {
  total: number;
  synced: number;
  conflicts: number;
  missing: number;
  memoryWarnings: number;
  localChanges: number;
  remoteChanges: number;
  fastForwards: number;
  message: string;
};

export type WebviewControlState = {
  range: ReportRange;
  projectKeys: string[];
  theme: ReportTheme;
  sync?: Pick<SyncSettings, "enabled" | "dir" | "projectKeys" | "conversationMode" | "threadIds">;
  versionLabel?: string;
};

export const PROJECT_KEYS_STATE_KEY = "projectKeys";
export const SYNC_DIR_STATE_KEY = "syncDir";
export const SYNC_THREAD_IDS_STATE_KEY = "syncThreadIds";
export const SYNC_PROJECT_KEYS_STATE_KEY = "syncProjectKeys";
export const SYNC_CONVERSATION_MODE_STATE_KEY = "syncConversationMode";

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

export function normalizeSyncConversationMode(value: unknown): SyncConversationMode {
  return typeof value === "string" && SYNC_CONVERSATION_MODE_VALUES.includes(value as SyncConversationMode)
    ? (value as SyncConversationMode)
    : "selectedConversations";
}

export function readSyncProjectKeysState(state?: GlobalStateReader): string[] {
  return normalizeProjectKeys(state?.get(SYNC_PROJECT_KEYS_STATE_KEY, []));
}

export function readSyncConversationModeState(state?: GlobalStateReader): SyncConversationMode {
  return normalizeSyncConversationMode(state?.get(SYNC_CONVERSATION_MODE_STATE_KEY, "selectedConversations"));
}

export function normalizeSyncSettings(value: unknown): SyncSettings {
  const input = isRecord(value) ? value : {};
  return {
    enabled: input.enabled === true,
    dir: typeof input.dir === "string" ? input.dir.trim() : "",
    projectKeys: normalizeProjectKeys(input.projectKeys),
    conversationMode: normalizeSyncConversationMode(input.conversationMode),
    threadIds: normalizeThreadIds(input.threadIds),
    autoPull: input.autoPull === false ? false : true,
    autoPush: input.autoPush === false ? false : true,
  };
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
    text.includes("no codex conversations are selected")
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
    candidates.push(path.join(options.codexHome.trim(), "sessions"));
  }
  if (options.userProfile?.trim()) {
    candidates.push(path.join(options.userProfile.trim(), ".codex", "sessions"));
  }
  if (options.homeDir?.trim()) {
    candidates.push(path.join(options.homeDir.trim(), ".codex", "sessions"));
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
    return [candidates[0]];
  }
  const existing = candidates.find((candidate) => exists(candidate));
  return [existing ?? candidates[0]];
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

export function buildSyncExportArgs(options: SyncCommandOptions): string[] {
  const args = ["sync", "export"];
  appendSyncArgs(args, options);
  return args;
}

export function buildSyncImportArgs(options: SyncImportCommandOptions): string[] {
  const args = ["sync", "import"];
  appendSyncArgs(args, options);
  const policy = options.conflictPolicy === "remote" ? "remote" : "skip";
  args.push("--conflict-policy", policy);
  return args;
}

export function buildSyncStatusArgs(options: SyncCommandOptions): string[] {
  const args = ["sync", "status", "--json"];
  appendSyncArgs(args, options);
  return args;
}

function appendSyncArgs(args: string[], options: SyncCommandOptions): void {
  if (options.syncDir.trim()) {
    args.push("--sync-dir", options.syncDir.trim());
  }
  for (const threadId of normalizeThreadIds(options.threadIds)) {
    args.push("--thread-id", threadId);
  }
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

export function parseThreadChoices(threadsJson: string, selectedThreadIds: string[] = []): ThreadChoice[] {
  let payload: unknown;
  try {
    payload = JSON.parse(threadsJson);
  } catch (error) {
    throw new Error(`Could not parse Codex thread JSON: ${error instanceof Error ? error.message : String(error)}`);
  }

  if (!isRecord(payload) || !Array.isArray(payload.threads)) {
    throw new Error("Codex thread JSON did not contain a threads array.");
  }

  const selected = new Set(normalizeThreadIds(selectedThreadIds));
  const seen = new Set<string>();
  const choices: ThreadChoice[] = [];
  for (const row of payload.threads) {
    if (!isRecord(row) || typeof row.thread_id !== "string") {
      continue;
    }
    const threadId = row.thread_id.trim();
    if (!threadId || seen.has(threadId)) {
      continue;
    }
    const label = typeof row.title === "string" && row.title.trim() ? row.title.trim() : threadId;
    const project = typeof row.project_label === "string" && row.project_label.trim() ? row.project_label.trim() : "unknown";
    const updated = typeof row.updated_at === "string" ? row.updated_at : "";
    const totalTokens = numberValue(row.total_tokens);
    const estimatedSyncBytes = numberValue(row.estimated_sync_bytes);
    choices.push({
      threadId,
      label,
      totalTokens,
      estimatedSyncBytes,
      description: `${project} | ${formatInt(totalTokens)} tokens | ${formatBytes(estimatedSyncBytes)}`,
      detail: updated ? `${threadId} | ${updated}` : threadId,
      picked: selected.has(threadId),
    });
    seen.add(threadId);
  }
  return choices;
}

export function parseSyncProjectChoices(threadsJson: string, selectedProjectKeys: string[] = []): SyncProjectChoice[] {
  let payload: unknown;
  try {
    payload = JSON.parse(threadsJson);
  } catch (error) {
    throw new Error(`Could not parse Codex thread JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
  if (!isRecord(payload) || !Array.isArray(payload.threads)) {
    throw new Error("Codex thread JSON did not contain a threads array.");
  }

  const selected = new Set(normalizeProjectKeys(selectedProjectKeys));
  const byProject = new Map<string, SyncProjectChoice>();
  for (const row of payload.threads) {
    if (!isRecord(row) || typeof row.project_key !== "string") {
      continue;
    }
    const key = row.project_key.trim();
    if (!key) {
      continue;
    }
    const label = stringValue(row.project_label) || key;
    const totalTokens = numberValue(row.total_tokens);
    const estimatedBytes = numberValue(row.estimated_sync_bytes);
    const existing = byProject.get(key);
    if (existing) {
      existing.totalTokens += totalTokens;
      existing.conversationCount += 1;
      existing.estimatedSyncBytes += estimatedBytes;
      existing.description = syncProjectDescription(existing.conversationCount, existing.estimatedSyncBytes);
      continue;
    }
    byProject.set(key, {
      key,
      label,
      totalTokens,
      conversationCount: 1,
      estimatedSyncBytes: estimatedBytes,
      description: syncProjectDescription(1, estimatedBytes),
      detail: key,
      picked: selected.has(key),
    });
  }
  return [...byProject.values()].sort((a, b) => b.estimatedSyncBytes - a.estimatedSyncBytes);
}

export function syncProjectQuickPickItems(
  choices: SyncProjectChoice[],
  selectedProjectKeys: string[],
): SyncProjectQuickPickItem[] {
  const selected = new Set(normalizeProjectKeys(selectedProjectKeys));
  return choices.map((choice) => ({
    label: choice.label,
    description: choice.description,
    detail: choice.detail,
    picked: selected.has(choice.key),
    projectKey: choice.key,
  }));
}

export function syncConversationQuickPickItems(
  choices: ThreadChoice[],
  mode: SyncConversationMode,
): SyncConversationQuickPickItem[] {
  return [
    {
      label: "All conversations in selected projects",
      description: "Automatically include current and future conversations for these projects",
      picked: mode === "allInProjects",
      allConversations: true,
    },
    ...choices.map((choice) => ({
      label: choice.label,
      description: choice.description,
      detail: choice.detail,
      picked: mode === "selectedConversations" ? choice.picked : false,
      threadId: choice.threadId,
    })),
  ];
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

export function parseSyncStatusSummary(statusJson: string): SyncStatusSummary {
  let payload: unknown;
  try {
    payload = JSON.parse(statusJson);
  } catch (error) {
    throw new Error(`Could not parse Codex sync status JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
  const rows = isRecord(payload) && Array.isArray(payload.threads) ? payload.threads : [];
  let synced = 0;
  let conflicts = 0;
  let missing = 0;
  let memoryWarnings = 0;
  let localChanges = 0;
  let remoteChanges = 0;
  let fastForwards = 0;
  for (const row of rows) {
    if (!isRecord(row)) {
      continue;
    }
    const state = typeof row.state === "string" ? row.state : "";
    if (state === "synced") {
      synced += 1;
    } else if (state === "conflict") {
      conflicts += 1;
    } else if (state === "missing") {
      missing += 1;
    } else if (state === "local_ahead" || state === "local_only") {
      localChanges += 1;
    } else if (state === "remote_ahead" || state === "remote_only") {
      remoteChanges += 1;
    } else if (state === "fast_forward_push" || state === "fast_forward_pull") {
      fastForwards += 1;
    }
    if (numberValue(row.memory_database_rows) > 0) {
      memoryWarnings += 1;
    }
  }
  const total = rows.length;
  const parts = [`${total} conversation${total === 1 ? "" : "s"}`, `${synced} synced`];
  if (localChanges) {
    parts.push(`${localChanges} local change${localChanges === 1 ? "" : "s"}`);
  }
  if (remoteChanges) {
    parts.push(`${remoteChanges} remote change${remoteChanges === 1 ? "" : "s"}`);
  }
  if (fastForwards) {
    parts.push(`${fastForwards} fast-forward${fastForwards === 1 ? "" : "s"}`);
  }
  if (conflicts) {
    parts.push(`${conflicts} conflict${conflicts === 1 ? "" : "s"}`);
  }
  if (missing) {
    parts.push(`${missing} missing`);
  }
  if (memoryWarnings) {
    parts.push(`${memoryWarnings} memory warning${memoryWarnings === 1 ? "" : "s"}`);
  }
  return {
    total,
    synced,
    conflicts,
    missing,
    memoryWarnings,
    localChanges,
    remoteChanges,
    fastForwards,
    message: parts.join(", "),
  };
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

function syncControlLabel(sync: WebviewControlState["sync"]): string {
  const normalized = normalizeSyncSettings(sync ?? {});
  if (!normalized.enabled) {
    return "Sync: Off";
  }
  if (!normalized.dir) {
    return "Sync: Select Folder";
  }
  if (normalized.projectKeys.length === 0 && normalized.threadIds.length === 0) {
    return "Sync: Select Projects";
  }
  if (normalized.conversationMode === "allInProjects") {
    const count = normalized.projectKeys.length;
    if (count === 1) {
      return "Sync: All conversations in 1 project";
    }
    return `Sync: All conversations in ${count} projects`;
  }
  if (normalized.threadIds.length === 0) {
    return "Sync: Select Conversations";
  }
  if (normalized.threadIds.length === 1) {
    return "Sync: 1 conversation";
  }
  return `Sync: ${normalized.threadIds.length} conversations`;
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

function syncProjectDescription(conversationCount: number, estimatedBytes: number): string {
  const conversationLabel = `${conversationCount} conversation${conversationCount === 1 ? "" : "s"}`;
  return `${conversationLabel} | ${formatBytes(estimatedBytes)} estimated sync size`;
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  if (unitIndex === 0) {
    return `${Math.round(size)} ${units[unitIndex]}`;
  }
  return `${size.toFixed(1)} ${units[unitIndex]}`;
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
