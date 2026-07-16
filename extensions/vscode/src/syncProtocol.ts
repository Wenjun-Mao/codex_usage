import { requireValidPlannerRows } from "./syncPlanContract";

export type ProjectBinding = {
  projectKey: string;
  path: string;
  confirmedUnverified: boolean;
};

export type SyncCommandOptions = {
  syncDir: string;
  threadIds: string[];
  autoTransitions: boolean;
  candidateProjectRoots: string[];
  projectBindings: ProjectBinding[];
};

type SyncCommandBuilderOptions = Omit<
  SyncCommandOptions,
  "candidateProjectRoots" | "projectBindings"
> &
  Partial<Pick<SyncCommandOptions, "candidateProjectRoots" | "projectBindings">>;

export type SyncProgressPhase = "scanning" | "pulling" | "pushing";

export type SyncProgressEvent = {
  type: "sync_progress";
  phase: SyncProgressPhase;
};

export type SyncCounts = {
  discovered: number;
  selected: number;
  remote: number;
  pulled: number;
  pushed: number;
  unchanged: number;
  conflicts: number;
  issues: number;
};

export type SyncTimings = {
  discovery: number;
  planning: number;
  pull: number;
  push: number;
  index: number;
  total: number;
};

export type SyncPlanItem = {
  thread_id: string;
  state: string;
  action: string;
  reason: string;
  local_path: string;
  remote_path: string;
  local_sha256: string;
  remote_sha256: string;
  base_sha256: string;
  updated_at: string;
  source_relative_path: string;
  project_key: string;
  project_label: string;
  memory_database_rows: number;
  memory_note?: string;
};

export type SyncIssue = {
  code: string;
  message: string;
  thread_id: string;
};

export type SyncRunResult = {
  outcome: "completed" | "conflict" | "issue";
  counts: SyncCounts;
  timings_ms: SyncTimings;
  threads: SyncPlanItem[];
  pulled: string[];
  pushed: string[];
  issues: SyncIssue[];
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
  issues: number;
  message: string;
};

const RESULT_KEYS = ["outcome", "counts", "timings_ms", "threads", "pulled", "pushed", "issues"] as const;
const COUNT_KEYS = [
  "discovered",
  "selected",
  "remote",
  "pulled",
  "pushed",
  "unchanged",
  "conflicts",
  "issues",
] as const;
const TIMING_KEYS = ["discovery", "planning", "pull", "push", "index", "total"] as const;
const THREAD_KEYS = [
  "thread_id",
  "state",
  "action",
  "reason",
  "local_path",
  "remote_path",
  "local_sha256",
  "remote_sha256",
  "base_sha256",
  "updated_at",
  "source_relative_path",
  "project_key",
  "project_label",
  "memory_database_rows",
] as const;
const ISSUE_KEYS = ["code", "message", "thread_id"] as const;
const STATUS_KEYS = ["threads", "issues"] as const;
const PROGRESS_PHASES = new Set<SyncProgressPhase>(["scanning", "pulling", "pushing"]);
type ValidationFailure = (message: string) => never;

export function buildSyncPullArgs(options: SyncCommandBuilderOptions): string[] {
  return buildSyncArgs("pull", options);
}

export function buildSyncPushArgs(options: SyncCommandBuilderOptions): string[] {
  return buildSyncArgs("push", options);
}

export function buildSyncStatusArgs(options: SyncCommandBuilderOptions): string[] {
  return buildSyncArgs("status", options);
}

function buildSyncArgs(command: "pull" | "push" | "status", options: SyncCommandBuilderOptions): string[] {
  const args = ["sync", command, "--json"];
  const syncDir = options.syncDir.trim();
  if (syncDir) {
    args.push("--sync-dir", syncDir);
  }
  appendSelectors(args, "--candidate-project-root", options.candidateProjectRoots);
  if (options.autoTransitions === false) {
    args.push("--no-auto-transitions");
  }
  appendProjectBindings(args, options.projectBindings);
  appendSelectors(args, "--thread-id", options.threadIds);
  return args;
}

function appendProjectBindings(args: string[], values: unknown): void {
  const bindings = normalizeProjectBindings(values);
  for (const binding of bindings) {
    args.push("--project-binding", binding.projectKey, binding.path);
  }
  for (const binding of bindings) {
    if (binding.confirmedUnverified) {
      args.push("--confirm-unverified-project", binding.projectKey);
    }
  }
}

function normalizeProjectBindings(values: unknown): ProjectBinding[] {
  if (!Array.isArray(values)) {
    return [];
  }
  const bindings: ProjectBinding[] = [];
  for (const value of values) {
    if (
      !isRecord(value) ||
      typeof value.projectKey !== "string" ||
      typeof value.path !== "string" ||
      typeof value.confirmedUnverified !== "boolean"
    ) {
      continue;
    }
    const projectKey = value.projectKey.trim();
    const path = value.path.trim();
    if (projectKey && path) {
      bindings.push({ projectKey, path, confirmedUnverified: value.confirmedUnverified });
    }
  }
  return bindings;
}

function appendSelectors(args: string[], flag: string, values: unknown): void {
  for (const value of normalizeSelectors(values)) {
    args.push(flag, value);
  }
}

function normalizeSelectors(values: unknown): string[] {
  if (!Array.isArray(values)) {
    return [];
  }
  const normalized: string[] = [];
  const seen = new Set<string>();
  for (const value of values) {
    if (typeof value !== "string") {
      continue;
    }
    const selector = value.trim();
    if (!selector || seen.has(selector)) {
      continue;
    }
    seen.add(selector);
    normalized.push(selector);
  }
  return normalized;
}

export function parseSyncProgressLine(line: string): SyncProgressEvent | undefined {
  let payload: unknown;
  try {
    payload = JSON.parse(line);
  } catch {
    return undefined;
  }
  if (
    !isRecord(payload) ||
    payload.type !== "sync_progress" ||
    typeof payload.phase !== "string" ||
    !PROGRESS_PHASES.has(payload.phase as SyncProgressPhase)
  ) {
    return undefined;
  }
  return { type: "sync_progress", phase: payload.phase as SyncProgressPhase };
}

export function parseSyncRunResult(resultJson: string): SyncRunResult {
  let payload: unknown;
  try {
    payload = JSON.parse(resultJson);
  } catch (error) {
    throw new Error(`Could not parse Codex sync result JSON: ${error instanceof Error ? error.message : String(error)}`);
  }

  const result = exactRecord(payload, RESULT_KEYS, [], "result");
  if (result.outcome !== "completed" && result.outcome !== "conflict" && result.outcome !== "issue") {
    invalidResult("outcome must be completed, conflict, or issue");
  }
  return {
    outcome: result.outcome,
    counts: parseCounts(result.counts),
    timings_ms: parseTimings(result.timings_ms),
    threads: requireValidPlannerRows(
      parseArray(result.threads, (item, index) => parseThread(item, index), "threads"),
      invalidResult,
    ),
    pulled: parseStringArray(result.pulled, "pulled"),
    pushed: parseStringArray(result.pushed, "pushed"),
    issues: parseArray(result.issues, (item, index) => parseIssue(item, index), "issues"),
  };
}

function parseCounts(value: unknown): SyncCounts {
  const counts = exactRecord(value, COUNT_KEYS, [], "counts");
  return {
    discovered: nonnegativeInteger(counts.discovered, "counts.discovered"),
    selected: nonnegativeInteger(counts.selected, "counts.selected"),
    remote: nonnegativeInteger(counts.remote, "counts.remote"),
    pulled: nonnegativeInteger(counts.pulled, "counts.pulled"),
    pushed: nonnegativeInteger(counts.pushed, "counts.pushed"),
    unchanged: nonnegativeInteger(counts.unchanged, "counts.unchanged"),
    conflicts: nonnegativeInteger(counts.conflicts, "counts.conflicts"),
    issues: nonnegativeInteger(counts.issues, "counts.issues"),
  };
}

function parseTimings(value: unknown): SyncTimings {
  const timings = exactRecord(value, TIMING_KEYS, [], "timings_ms");
  return {
    discovery: nonnegativeInteger(timings.discovery, "timings_ms.discovery"),
    planning: nonnegativeInteger(timings.planning, "timings_ms.planning"),
    pull: nonnegativeInteger(timings.pull, "timings_ms.pull"),
    push: nonnegativeInteger(timings.push, "timings_ms.push"),
    index: nonnegativeInteger(timings.index, "timings_ms.index"),
    total: nonnegativeInteger(timings.total, "timings_ms.total"),
  };
}

function parseThread(
  value: unknown,
  index: number,
  invalid: ValidationFailure = invalidResult,
): SyncPlanItem {
  const label = `threads[${index}]`;
  const thread = exactRecord(value, THREAD_KEYS, ["memory_note"], label, invalid);
  const parsed: SyncPlanItem = {
    thread_id: stringField(thread.thread_id, `${label}.thread_id`, invalid),
    state: stringField(thread.state, `${label}.state`, invalid),
    action: stringField(thread.action, `${label}.action`, invalid),
    reason: stringField(thread.reason, `${label}.reason`, invalid),
    local_path: stringField(thread.local_path, `${label}.local_path`, invalid),
    remote_path: stringField(thread.remote_path, `${label}.remote_path`, invalid),
    local_sha256: stringField(thread.local_sha256, `${label}.local_sha256`, invalid),
    remote_sha256: stringField(thread.remote_sha256, `${label}.remote_sha256`, invalid),
    base_sha256: stringField(thread.base_sha256, `${label}.base_sha256`, invalid),
    updated_at: stringField(thread.updated_at, `${label}.updated_at`, invalid),
    source_relative_path: stringField(
      thread.source_relative_path,
      `${label}.source_relative_path`,
      invalid,
    ),
    project_key: stringField(thread.project_key, `${label}.project_key`, invalid),
    project_label: stringField(thread.project_label, `${label}.project_label`, invalid),
    memory_database_rows: nonnegativeInteger(
      thread.memory_database_rows,
      `${label}.memory_database_rows`,
      invalid,
    ),
  };
  if ("memory_note" in thread) {
    parsed.memory_note = stringField(thread.memory_note, `${label}.memory_note`, invalid);
  }
  return parsed;
}

function parseIssue(
  value: unknown,
  index: number,
  invalid: ValidationFailure = invalidResult,
): SyncIssue {
  const label = `issues[${index}]`;
  const issue = exactRecord(value, ISSUE_KEYS, [], label, invalid);
  return {
    code: stringField(issue.code, `${label}.code`, invalid),
    message: stringField(issue.message, `${label}.message`, invalid),
    thread_id: stringField(issue.thread_id, `${label}.thread_id`, invalid),
  };
}

function parseArray<T>(
  value: unknown,
  parseItem: (item: unknown, index: number) => T,
  label: string,
  invalid: ValidationFailure = invalidResult,
): T[] {
  if (!Array.isArray(value)) {
    invalid(`${label} must be an array`);
  }
  return value.map(parseItem);
}

function parseStringArray(value: unknown, label: string): string[] {
  return parseArray(value, (item, index) => stringField(item, `${label}[${index}]`), label);
}

function exactRecord(
  value: unknown,
  requiredKeys: readonly string[],
  optionalKeys: readonly string[],
  label: string,
  invalid: ValidationFailure = invalidResult,
): Record<string, unknown> {
  if (!isRecord(value)) {
    invalid(`${label} must be an object`);
  }
  const allowed = new Set([...requiredKeys, ...optionalKeys]);
  if (requiredKeys.some((key) => !(key in value)) || Object.keys(value).some((key) => !allowed.has(key))) {
    invalid(`${label} does not match the task transfer payload contract`);
  }
  return value;
}

function nonnegativeInteger(
  value: unknown,
  label: string,
  invalid: ValidationFailure = invalidResult,
): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    invalid(`${label} must be a nonnegative safe integer`);
  }
  return value;
}

function stringField(
  value: unknown,
  label: string,
  invalid: ValidationFailure = invalidResult,
): string {
  if (typeof value !== "string") {
    invalid(`${label} must be a string`);
  }
  return value;
}

function invalidResult(message: string): never {
  throw new Error(`Invalid Codex sync result: ${message}`);
}

function invalidStatus(message: string): never {
  throw new Error(`Invalid Codex sync status: ${message}`);
}

export function parseSyncStatusSummary(statusJson: string): SyncStatusSummary {
  let payload: unknown;
  try {
    payload = JSON.parse(statusJson);
  } catch (error) {
    throw new Error(`Could not parse Codex sync status JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
  const status = exactRecord(payload, STATUS_KEYS, [], "status", invalidStatus);
  const rows = requireValidPlannerRows(
    parseArray(
      status.threads,
      (row, index) => parseThread(row, index, invalidStatus),
      "threads",
      invalidStatus,
    ),
    invalidStatus,
  );
  const issueRows = parseArray(
    status.issues,
    (issue, index) => parseIssue(issue, index, invalidStatus),
    "issues",
    invalidStatus,
  );
  let synced = 0;
  let conflicts = 0;
  let missing = 0;
  let memoryWarnings = 0;
  let localChanges = 0;
  let remoteChanges = 0;
  let fastForwards = 0;
  for (const row of rows) {
    const state = row.state;
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
    if (row.memory_database_rows > 0) {
      memoryWarnings += 1;
    }
  }

  let issues = 0;
  let firstIssueMessage = "";
  for (const issue of issueRows) {
    issues += 1;
    if (!firstIssueMessage && issue.message.trim()) {
      firstIssueMessage = issue.message.trim();
    }
  }

  const total = rows.length;
  const parts = [`${total} task${total === 1 ? "" : "s"}`, `${synced} synced`];
  appendCount(parts, localChanges, "local change");
  appendCount(parts, remoteChanges, "remote change");
  appendCount(parts, fastForwards, "fast-forward");
  appendCount(parts, conflicts, "conflict");
  if (missing) {
    parts.push(`${missing} missing`);
  }
  appendCount(parts, memoryWarnings, "memory warning");
  appendCount(parts, issues, "issue");
  if (firstIssueMessage) {
    parts.push(firstIssueMessage);
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
    issues,
    message: parts.join(", "),
  };
}

function appendCount(parts: string[], count: number, label: string): void {
  if (count) {
    parts.push(`${count} ${label}${count === 1 ? "" : "s"}`);
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
