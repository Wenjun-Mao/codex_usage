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

export type TaskTransferSettings = {
  folder: string;
};

export type ExtensionSettings = {
  range: ReportRange;
  projectKeys: string[];
  theme: ReportTheme;
  taskTransfer: TaskTransferSettings;
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

export const PROJECT_KEYS_STATE_KEY = "projectKeys";

export type GlobalStateReader = {
  get<T>(key: string, defaultValue: T): T;
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

export function readProjectKeysState(state: GlobalStateReader): string[] {
  return normalizeProjectKeys(state.get(PROJECT_KEYS_STATE_KEY, []));
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
