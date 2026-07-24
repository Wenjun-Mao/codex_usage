import type {
  ProjectBinding,
  SyncCommandOptions,
  SyncTransferCommandOptions,
} from "./syncProtocol";

export function buildSyncPullArgs(options: SyncTransferCommandOptions): string[] {
  return buildTransferArgs("pull", options);
}

export function buildSyncPushArgs(options: SyncTransferCommandOptions): string[] {
  return buildTransferArgs("push", options);
}

export function buildSyncStatusArgs(options: SyncCommandOptions): string[] {
  return buildSyncArgs("status", options);
}

function buildTransferArgs(
  command: "pull" | "push",
  options: SyncTransferCommandOptions,
): string[] {
  const projectKey = options.projectKey.trim();
  if (!projectKey) {
    throw new Error("Transfer project key must not be blank.");
  }
  return buildSyncArgs(command, options, projectKey);
}

function buildSyncArgs(
  command: "pull" | "push" | "status",
  options: SyncCommandOptions,
  projectKey?: string,
): string[] {
  const args = ["sync", command, "--json"];
  const syncDir = options.syncDir.trim();
  if (syncDir) {
    args.push("--sync-dir", syncDir);
  }
  if (projectKey !== undefined) {
    args.push("--project-key", projectKey);
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
