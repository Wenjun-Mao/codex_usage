import type { TransferOperation } from "./transferPresentation";

export type SyncTaskAvailability = "local" | "remote" | "both";
export type SyncProjectIdentityKind = "git" | "path";

export type SyncInventoryTask = {
  threadId: string;
  title: string;
  updatedAt: string;
  estimatedSyncBytes: number;
  availability: SyncTaskAvailability;
  state: string;
  action: string;
};

export type SyncInventoryProject = {
  projectKey: string;
  projectLabel: string;
  identityKind: SyncProjectIdentityKind;
  candidateRoots: string[];
  tasks: SyncInventoryTask[];
};

export type SyncInventoryIssue = {
  code: string;
  message: string;
  threadId: string;
};

export type SyncInventory = {
  inventoryVersion: 2;
  projects: SyncInventoryProject[];
  issues: SyncInventoryIssue[];
};

export type SyncInventoryCommandOptions = {
  syncDir: string;
  autoTransitions: boolean;
  candidateProjectRoots?: string[];
};

const INVENTORY_KEYS = ["inventory_version", "projects", "issues"] as const;
const PROJECT_KEYS = ["project_key", "project_label", "identity_kind", "candidate_roots", "tasks"] as const;
const TASK_KEYS = [
  "thread_id",
  "title",
  "updated_at",
  "estimated_sync_bytes",
  "availability",
  "state",
  "action",
] as const;
const ISSUE_KEYS = ["code", "message", "thread_id"] as const;
const TASK_AVAILABILITIES = new Set<SyncTaskAvailability>(["local", "remote", "both"]);
const PROJECT_IDENTITY_KINDS = new Set<SyncProjectIdentityKind>(["git", "path"]);

export function buildSyncInventoryArgs(options: SyncInventoryCommandOptions): string[] {
  const args = ["sync", "inventory", "--json"];
  const syncDir = options.syncDir.trim();
  if (syncDir) {
    args.push("--sync-dir", syncDir);
  }
  appendSelectors(args, "--candidate-project-root", options.candidateProjectRoots);
  if (options.autoTransitions === false) {
    args.push("--no-auto-transitions");
  }
  return args;
}

export function parseSyncInventory(json: string): SyncInventory {
  let payload: unknown;
  try {
    payload = JSON.parse(json);
  } catch (error) {
    invalidInventory("json", `must be valid JSON: ${error instanceof Error ? error.message : String(error)}`);
  }

  const inventory = exactRecord(payload, INVENTORY_KEYS, "");
  if (inventory.inventory_version !== 2) {
    invalidInventory("inventory_version", "must equal 2");
  }

  const projectKeys = new Set<string>();
  const threadIds = new Set<string>();
  return {
    inventoryVersion: 2,
    projects: parseArray(
      inventory.projects,
      (project, index) => parseProject(project, index, projectKeys, threadIds),
      "projects",
    ),
    issues: parseArray(inventory.issues, parseIssue, "issues"),
  };
}

export function filterInventoryForOperation(
  inventory: SyncInventory,
  operation: TransferOperation,
): SyncInventory {
  const projects = inventory.projects.flatMap((project) => {
    const tasks = project.tasks.filter((task) => availableForOperation(task.availability, operation));
    return tasks.length > 0 ? [{ ...project, tasks }] : [];
  });
  return { ...inventory, projects, issues: [...inventory.issues] };
}

function availableForOperation(
  availability: SyncTaskAvailability,
  operation: TransferOperation,
): boolean {
  if (operation === "import") {
    return availability === "remote" || availability === "both";
  }
  if (operation === "export") {
    return availability === "local" || availability === "both";
  }
  return true;
}

function parseProject(
  value: unknown,
  index: number,
  projectKeys: Set<string>,
  threadIds: Set<string>,
): SyncInventoryProject {
  const path = `projects[${index}]`;
  const project = exactRecord(value, PROJECT_KEYS, path);
  const projectKey = stringField(project.project_key, `${path}.project_key`);
  if (projectKeys.has(projectKey)) {
    invalidInventory(`${path}.project_key`, "must be unique");
  }
  projectKeys.add(projectKey);
  const identityKind = stringField(project.identity_kind, `${path}.identity_kind`);
  if (!PROJECT_IDENTITY_KINDS.has(identityKind as SyncProjectIdentityKind)) {
    invalidInventory(`${path}.identity_kind`, "must be git or path");
  }

  return {
    projectKey,
    projectLabel: stringField(project.project_label, `${path}.project_label`),
    identityKind: identityKind as SyncProjectIdentityKind,
    candidateRoots: parseStringArray(project.candidate_roots, `${path}.candidate_roots`),
    tasks: parseArray(
      project.tasks,
      (task, taskIndex) => parseTask(task, taskIndex, `${path}.tasks`, threadIds),
      `${path}.tasks`,
    ),
  };
}

function parseTask(value: unknown, index: number, parentPath: string, threadIds: Set<string>): SyncInventoryTask {
  const path = `${parentPath}[${index}]`;
  const task = exactRecord(value, TASK_KEYS, path);
  const threadId = canonicalThreadIdField(task.thread_id, `${path}.thread_id`);
  if (threadIds.has(threadId)) {
    invalidInventory(`${path}.thread_id`, "must be unique across projects");
  }
  threadIds.add(threadId);

  const availability = stringField(task.availability, `${path}.availability`);
  if (!TASK_AVAILABILITIES.has(availability as SyncTaskAvailability)) {
    invalidInventory(`${path}.availability`, "must be local, remote, or both");
  }

  return {
    threadId,
    title: stringField(task.title, `${path}.title`),
    updatedAt: stringField(task.updated_at, `${path}.updated_at`),
    estimatedSyncBytes: nonnegativeInteger(task.estimated_sync_bytes, `${path}.estimated_sync_bytes`),
    availability: availability as SyncTaskAvailability,
    state: stringField(task.state, `${path}.state`),
    action: stringField(task.action, `${path}.action`),
  };
}

function appendSelectors(args: string[], flag: string, values: unknown): void {
  if (!Array.isArray(values)) {
    return;
  }
  const seen = new Set<string>();
  for (const value of values) {
    if (typeof value !== "string") {
      continue;
    }
    const selector = value.trim();
    if (selector && !seen.has(selector)) {
      seen.add(selector);
      args.push(flag, selector);
    }
  }
}

function parseIssue(value: unknown, index: number): SyncInventoryIssue {
  const path = `issues[${index}]`;
  const issue = exactRecord(value, ISSUE_KEYS, path);
  return {
    code: stringField(issue.code, `${path}.code`),
    message: stringField(issue.message, `${path}.message`),
    threadId: optionalCanonicalThreadIdField(issue.thread_id, `${path}.thread_id`),
  };
}

function parseArray<T>(
  value: unknown,
  parseItem: (item: unknown, index: number) => T,
  path: string,
): T[] {
  if (!Array.isArray(value)) {
    invalidInventory(path, "must be an array");
  }
  return value.map(parseItem);
}

function parseStringArray(value: unknown, path: string): string[] {
  return parseArray(
    value,
    (item, index) => stringField(item, `${path}[${index}]`),
    path,
  );
}

function exactRecord(value: unknown, requiredKeys: readonly string[], path: string): Record<string, unknown> {
  if (!isRecord(value)) {
    invalidInventory(path || "inventory", "must be an object");
  }

  for (const key of requiredKeys) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) {
      invalidInventory(fieldPath(path, key), "is required");
    }
  }

  const allowedKeys = new Set(requiredKeys);
  for (const key of Object.keys(value)) {
    if (!allowedKeys.has(key)) {
      invalidInventory(fieldPath(path, key), "is not allowed");
    }
  }
  return value;
}

function stringField(value: unknown, path: string): string {
  if (typeof value !== "string") {
    invalidInventory(path, "must be a string");
  }
  return value;
}

function canonicalThreadIdField(value: unknown, path: string): string {
  const threadId = stringField(value, path);
  if (!threadId || threadId !== threadId.trim()) {
    invalidInventory(path, "must be nonempty and equal to its own trim");
  }
  return threadId;
}

function optionalCanonicalThreadIdField(value: unknown, path: string): string {
  const threadId = stringField(value, path);
  if (threadId && threadId !== threadId.trim()) {
    invalidInventory(path, "must be blank or equal to its own trim");
  }
  return threadId;
}

function nonnegativeInteger(value: unknown, path: string): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    invalidInventory(path, "must be a nonnegative safe integer");
  }
  return value;
}

function fieldPath(parent: string, field: string): string {
  return parent ? `${parent}.${field}` : field;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function invalidInventory(path: string, reason: string): never {
  throw new Error(`Invalid sync inventory: ${path} ${reason}`);
}
