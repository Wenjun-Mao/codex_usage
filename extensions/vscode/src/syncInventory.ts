export type SyncTaskAvailability = "local" | "remote" | "both";

export type SyncInventoryTask = {
  threadId: string;
  title: string;
  updatedAt: string;
  estimatedSyncBytes: number;
  availability: SyncTaskAvailability;
};

export type SyncInventoryProject = {
  projectKey: string;
  projectLabel: string;
  tasks: SyncInventoryTask[];
};

export type SyncInventoryIssue = {
  code: string;
  message: string;
  threadId: string;
};

export type SyncInventory = {
  inventoryVersion: 1;
  projects: SyncInventoryProject[];
  issues: SyncInventoryIssue[];
};

export type SyncInventoryCommandOptions = {
  syncDir: string;
  autoTransitions: boolean;
};

const INVENTORY_KEYS = ["inventory_version", "projects", "issues"] as const;
const PROJECT_KEYS = ["project_key", "project_label", "tasks"] as const;
const TASK_KEYS = ["thread_id", "title", "updated_at", "estimated_sync_bytes", "availability"] as const;
const ISSUE_KEYS = ["code", "message", "thread_id"] as const;
const TASK_AVAILABILITIES = new Set<SyncTaskAvailability>(["local", "remote", "both"]);

export function buildSyncInventoryArgs(options: SyncInventoryCommandOptions): string[] {
  const args = ["sync", "inventory", "--json"];
  const syncDir = options.syncDir.trim();
  if (syncDir) {
    args.push("--sync-dir", syncDir);
  }
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
  if (inventory.inventory_version !== 1) {
    invalidInventory("inventory_version", "must equal 1");
  }

  const projectKeys = new Set<string>();
  const threadIds = new Set<string>();
  return {
    inventoryVersion: 1,
    projects: parseArray(
      inventory.projects,
      (project, index) => parseProject(project, index, projectKeys, threadIds),
      "projects",
    ),
    issues: parseArray(inventory.issues, parseIssue, "issues"),
  };
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

  return {
    projectKey,
    projectLabel: stringField(project.project_label, `${path}.project_label`),
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
  const threadId = stringField(task.thread_id, `${path}.thread_id`);
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
  };
}

function parseIssue(value: unknown, index: number): SyncInventoryIssue {
  const path = `issues[${index}]`;
  const issue = exactRecord(value, ISSUE_KEYS, path);
  return {
    code: stringField(issue.code, `${path}.code`),
    message: stringField(issue.message, `${path}.message`),
    threadId: stringField(issue.thread_id, `${path}.thread_id`),
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
