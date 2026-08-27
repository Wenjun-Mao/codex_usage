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
  analysisStatus: "not_analyzed" | "partial" | "complete";
  analyzedBytes: number;
  analysisCoverage: number;
  compactedRecordCount: number;
  compactedBytes: number;
  compactedShare: number;
  largestCompactedRecordBytes: number;
  mediaCompactedRecordCount: number;
  embeddedMediaOccurrenceCount: number;
  largeDescendantFileCount: number;
  largeDescendantBytes: number;
  largeDescendantShare: number;
  activeRootCompactedBytes: number;
  hasHistoryAmplification: boolean;
  hasMediaAmplification: boolean;
  hasActiveRootHistoryRisk: boolean;
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

export type AnalysisProgress = {
  phase: "analyzing";
  completedFiles: number;
  totalFiles: number;
  completedBytes: number;
  totalBytes: number;
  path: string;
};

export type AnalysisResult = {
  treeId: string;
  filesTotal: number;
  filesAnalyzed: number;
  filesUnchanged: number;
  filesAppended: number;
  fullScans: number;
  appendFallbacks: number;
  sourceBytesRead: number;
  workerCount: number;
};

export function buildStorageSnapshotArgs(): string[] {
  return ["storage", "snapshot", "--json"];
}

export function buildStorageAnalyzeArgs(treeId: string): string[] {
  return ["storage", "analyze", "--tree-id", treeId, "--json", "--progress-json"];
}

export function parseStorageSnapshot(json: string): StorageSnapshot {
  const payload = parseJsonRecord(json, "storage snapshot");
  if (nonnegativeIntegerField(payload, "schema_version", "storage snapshot") !== 4) {
    throw new Error("Invalid storage snapshot: schema_version must be 4.");
  }
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

export function parseAnalysisProgressLine(line: string): AnalysisProgress | undefined {
  let value: unknown;
  try {
    value = JSON.parse(line);
  } catch {
    return undefined;
  }
  if (!isRecord(value) || value.phase !== "analyzing") {
    return undefined;
  }
  try {
    return {
      phase: "analyzing",
      completedFiles: nonnegativeIntegerField(value, "completed_files", "analysis progress"),
      totalFiles: nonnegativeIntegerField(value, "total_files", "analysis progress"),
      completedBytes: nonnegativeIntegerField(value, "completed_bytes", "analysis progress"),
      totalBytes: nonnegativeIntegerField(value, "total_bytes", "analysis progress"),
      path: stringField(value, "path", "analysis progress"),
    };
  } catch {
    return undefined;
  }
}

export function parseAnalysisResult(json: string): AnalysisResult {
  const payload = parseJsonRecord(json, "storage analysis result");
  if (nonnegativeIntegerField(payload, "schema_version", "storage analysis result") !== 1) {
    throw new Error("Invalid storage analysis result: schema_version must be 1.");
  }
  const value = parseJsonRecordValue(payload.analysis, "storage analysis result.analysis");
  return {
    treeId: stringField(value, "tree_id", "storage analysis result.analysis"),
    filesTotal: nonnegativeIntegerField(value, "files_total", "storage analysis result.analysis"),
    filesAnalyzed: nonnegativeIntegerField(value, "files_analyzed", "storage analysis result.analysis"),
    filesUnchanged: nonnegativeIntegerField(value, "files_unchanged", "storage analysis result.analysis"),
    filesAppended: nonnegativeIntegerField(value, "files_appended", "storage analysis result.analysis"),
    fullScans: nonnegativeIntegerField(value, "full_scans", "storage analysis result.analysis"),
    appendFallbacks: nonnegativeIntegerField(value, "append_fallbacks", "storage analysis result.analysis"),
    sourceBytesRead: nonnegativeIntegerField(value, "source_bytes_read", "storage analysis result.analysis"),
    workerCount: nonnegativeIntegerField(value, "worker_count", "storage analysis result.analysis"),
  };
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
  const analysisStatus = stringField(tree, "analysis_status", path);
  if (analysisStatus !== "not_analyzed" && analysisStatus !== "partial" && analysisStatus !== "complete") {
    throw new Error(`Invalid ${path}: analysis_status is unsupported.`);
  }
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
    analysisStatus,
    analyzedBytes: nonnegativeIntegerField(tree, "analyzed_bytes", path),
    analysisCoverage: nonnegativeNumberField(tree, "analysis_coverage", path),
    compactedRecordCount: nonnegativeIntegerField(tree, "compacted_record_count", path),
    compactedBytes: nonnegativeIntegerField(tree, "compacted_bytes", path),
    compactedShare: nonnegativeNumberField(tree, "compacted_share", path),
    largestCompactedRecordBytes: nonnegativeIntegerField(tree, "largest_compacted_record_bytes", path),
    mediaCompactedRecordCount: nonnegativeIntegerField(tree, "media_compacted_record_count", path),
    embeddedMediaOccurrenceCount: nonnegativeIntegerField(tree, "embedded_media_occurrence_count", path),
    largeDescendantFileCount: nonnegativeIntegerField(tree, "large_descendant_file_count", path),
    largeDescendantBytes: nonnegativeIntegerField(tree, "large_descendant_bytes", path),
    largeDescendantShare: nonnegativeNumberField(tree, "large_descendant_share", path),
    activeRootCompactedBytes: nonnegativeIntegerField(tree, "active_root_compacted_bytes", path),
    hasHistoryAmplification: booleanField(tree, "has_history_amplification", path),
    hasMediaAmplification: booleanField(tree, "has_media_amplification", path),
    hasActiveRootHistoryRisk: booleanField(tree, "has_active_root_history_risk", path),
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

function nonnegativeNumberField(value: Record<string, unknown>, key: string, label: string): number {
  if (!nonnegativeNumber(value[key])) {
    throw new Error(`Invalid ${label}: ${key} must be a nonnegative number.`);
  }
  return value[key];
}

function nonnegativeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function nonnegativeNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
