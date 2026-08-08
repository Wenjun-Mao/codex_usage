export type StorageTree = {
  rootTaskId: string;
  title: string;
  projectKey: string;
  projectLabel: string;
  totalBytes: number;
  rootBytes: number;
  descendantBytes: number;
  descendantCount: number;
  physicalFileCount: number;
  hasMissingRoot: boolean;
  hasRelationshipCycle: boolean;
  duplicateFileCount: number;
  metadataDiagnostics: string[];
  recoveryReady: boolean;
};

export type StorageProject = {
  projectKey: string;
  projectLabel: string;
  trees: StorageTree[];
};

export type StorageSnapshot = {
  projects: StorageProject[];
  trees: StorageTree[];
};

export type BackupCompression = "maximum" | "balanced";

export type BackupProgress = {
  event: "progress";
  phase: "preparing" | "compressing" | "verifying";
  completedBytes: number;
  totalBytes: number;
  fileIndex?: number;
  fileCount?: number;
};

export type BackupResult = {
  archivePath: string;
  sourceBytes: number;
  archiveBytes: number;
  fileCount: number;
  recoveryReady: boolean;
  warnings: string[];
  archiveSha256: string;
  compression: BackupCompression;
};

export function buildStorageSnapshotArgs(): string[] {
  return ["storage", "snapshot", "--json"];
}

export function buildStorageBackupArgs(options: {
  treeId: string;
  outputPath: string;
  compression: BackupCompression;
  replace: boolean;
}): string[] {
  const args = [
    "storage", "backup", "--tree-id", options.treeId,
    "--output", options.outputPath,
    "--compression", options.compression,
    "--json", "--progress-json",
  ];
  if (options.replace) {
    args.push("--replace");
  }
  return args;
}

export function parseStorageSnapshot(json: string): StorageSnapshot {
  const payload = parseJsonRecord(json, "storage snapshot");
  const trees = arrayField(payload, "task_trees", "storage snapshot").map((value, index) =>
    parseTree(value, `task_trees[${index}]`),
  );
  const byProject = new Map<string, StorageProject>();
  for (const tree of trees) {
    const key = tree.projectKey || "unassigned";
    const existing = byProject.get(key);
    if (existing) {
      existing.trees.push(tree);
    } else {
      byProject.set(key, {
        projectKey: key,
        projectLabel: tree.projectLabel || "Unassigned",
        trees: [tree],
      });
    }
  }
  const projects = [...byProject.values()]
    .map((project) => ({
      ...project,
      trees: [...project.trees].sort(compareTrees),
    }))
    .sort((left, right) => left.projectLabel.localeCompare(right.projectLabel));
  return { projects, trees: [...trees].sort(compareTrees) };
}

export function parseBackupProgressLine(line: string): BackupProgress | undefined {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    return undefined;
  }
  if (!isRecord(value) || value.event !== "progress") {
    return undefined;
  }
  if (value.phase !== "preparing" && value.phase !== "compressing" && value.phase !== "verifying") {
    return undefined;
  }
  if (!nonnegativeNumber(value.completed_bytes) || !nonnegativeNumber(value.total_bytes)) {
    return undefined;
  }
  const optionalIndex = optionalNonnegativeInteger(value.file_index);
  const optionalCount = optionalNonnegativeInteger(value.file_count);
  if (optionalIndex === null || optionalCount === null) {
    return undefined;
  }
  return {
    event: "progress",
    phase: value.phase,
    completedBytes: value.completed_bytes,
    totalBytes: value.total_bytes,
    ...(optionalIndex === undefined ? {} : { fileIndex: optionalIndex }),
    ...(optionalCount === undefined ? {} : { fileCount: optionalCount }),
  };
}

export function parseBackupResult(json: string): BackupResult {
  const value = parseJsonRecord(json, "backup result");
  const compression = stringField(value, "compression", "backup result");
  if (compression !== "maximum" && compression !== "balanced") {
    throw new Error("Invalid backup result: compression must be maximum or balanced.");
  }
  return {
    archivePath: stringField(value, "archive_path", "backup result"),
    sourceBytes: nonnegativeIntegerField(value, "source_bytes", "backup result"),
    archiveBytes: nonnegativeIntegerField(value, "archive_bytes", "backup result"),
    fileCount: nonnegativeIntegerField(value, "file_count", "backup result"),
    recoveryReady: booleanField(value, "recovery_ready", "backup result"),
    warnings: arrayField(value, "warnings", "backup result").map((item, index) => {
      if (typeof item !== "string") {
        throw new Error(`Invalid backup result: warnings[${index}] must be a string.`);
      }
      return item;
    }),
    archiveSha256: stringField(value, "archive_sha256", "backup result"),
    compression,
  };
}

export function backupFileName(title: string, treeId: string, now = new Date()): string {
  const safeTitle = title
    .trim()
    .replace(/[^A-Za-z0-9._-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 80) || "codex-task";
  const timestamp = now.toISOString().replace(/[-:]/g, "").replace(/\.\d{3}Z$/, "Z");
  const shortId = treeId.replace(/[^A-Za-z0-9]/g, "").slice(0, 12) || "task";
  return `${safeTitle}-${shortId}-${timestamp}.codex-task-backup`;
}

export function formatStorageBytes(bytes: number): string {
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let amount = Math.max(0, bytes);
  for (const unit of units) {
    if (amount < 1024 || unit === units.at(-1)) {
      return unit === "B" ? `${Math.round(amount).toLocaleString()} B` : `${amount.toFixed(2)} ${unit}`;
    }
    amount /= 1024;
  }
  return `${bytes.toLocaleString()} B`;
}

function parseTree(value: unknown, path: string): StorageTree {
  const tree = parseJsonRecordValue(value, path);
  return {
    rootTaskId: stringField(tree, "root_task_id", path),
    title: stringField(tree, "title", path),
    projectKey: stringField(tree, "project_key", path),
    projectLabel: stringField(tree, "project_label", path),
    totalBytes: nonnegativeIntegerField(tree, "total_bytes", path),
    rootBytes: nonnegativeIntegerField(tree, "root_bytes", path),
    descendantBytes: nonnegativeIntegerField(tree, "descendant_bytes", path),
    descendantCount: nonnegativeIntegerField(tree, "descendant_count", path),
    physicalFileCount: nonnegativeIntegerField(tree, "physical_file_count", path),
    hasMissingRoot: booleanField(tree, "has_missing_root", path),
    hasRelationshipCycle: booleanField(tree, "has_relationship_cycle", path),
    duplicateFileCount: nonnegativeIntegerField(tree, "duplicate_file_count", path),
    recoveryReady: booleanField(tree, "recovery_ready", path),
    metadataDiagnostics: arrayField(tree, "metadata_diagnostics", path).map((item, index) => {
      if (typeof item !== "string") {
        throw new Error(`Invalid ${path}: metadata_diagnostics[${index}] must be a string.`);
      }
      return item;
    }),
  };
}

function compareTrees(left: StorageTree, right: StorageTree): number {
  return right.totalBytes - left.totalBytes || left.title.localeCompare(right.title) || left.rootTaskId.localeCompare(right.rootTaskId);
}

function parseJsonRecord(json: string, label: string): Record<string, unknown> {
  try {
    return parseJsonRecordValue(JSON.parse(json), label);
  } catch (error) {
    if (error instanceof Error && error.message.startsWith("Invalid")) {
      throw error;
    }
    throw new Error(`Invalid ${label}: ${error instanceof Error ? error.message : String(error)}`);
  }
}

function parseJsonRecordValue(value: unknown, label: string): Record<string, unknown> {
  if (!isRecord(value)) {
    throw new Error(`Invalid ${label}: expected an object.`);
  }
  return value;
}

function arrayField(value: Record<string, unknown>, key: string, label: string): unknown[] {
  if (!Array.isArray(value[key])) {
    throw new Error(`Invalid ${label}: ${key} must be an array.`);
  }
  return value[key];
}

function stringField(value: Record<string, unknown>, key: string, label: string): string {
  if (typeof value[key] !== "string") {
    throw new Error(`Invalid ${label}: ${key} must be a string.`);
  }
  return value[key];
}

function booleanField(value: Record<string, unknown>, key: string, label: string): boolean {
  if (typeof value[key] !== "boolean") {
    throw new Error(`Invalid ${label}: ${key} must be a boolean.`);
  }
  return value[key];
}

function nonnegativeIntegerField(value: Record<string, unknown>, key: string, label: string): number {
  if (!nonnegativeInteger(value[key])) {
    throw new Error(`Invalid ${label}: ${key} must be a nonnegative safe integer.`);
  }
  return value[key];
}

function nonnegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function nonnegativeNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function optionalNonnegativeInteger(value: unknown): number | undefined | null {
  if (value === undefined) {
    return undefined;
  }
  return nonnegativeInteger(value) ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
