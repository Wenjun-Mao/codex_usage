import { createHash } from "crypto";
import type { Stats } from "fs";
import * as path from "path";

import type { CodexDesktopProcessState } from "./codexDesktopProcess";

export type JsonObject = Record<string, unknown>;
export type FileIdentity = { dev: number; ino: number; size: number; mtimeMs: number; mode: number };
export type StateSnapshot = { bytes: Buffer; sha256: string; identity: FileIdentity };

export type DesktopProjectBindingPlan =
  | { mode: "not-applicable"; threadIds: string[] }
  | {
      mode: "ready";
      statePath: string;
      projectId: string;
      destinationPath: string;
      threadIds: string[];
      sourceSha256: string;
      sourceIdentity: FileIdentity;
    };
export type DesktopProjectBindingResult =
  | { status: "not-applicable"; attempted: number; bound: number }
  | { status: "unchanged"; attempted: number; bound: number }
  | { status: "bound"; attempted: number; bound: number; backupPath: string };
export type DesktopProjectBindingOutcome = DesktopProjectBindingResult | {
  status: "failed";
  attempted: number;
  bound: number;
  code: string;
};
export type DesktopProjectBindingRequest = {
  destinationPath: string;
  threadIds: readonly string[];
};

export class DesktopProjectBindingError extends Error {
  constructor(readonly code: string, message: string) {
    super(message);
    this.name = "DesktopProjectBindingError";
  }
}

export type BindingDependencies = {
  platform: NodeJS.Platform;
  env: NodeJS.ProcessEnv;
  homeDir(): string;
  inspectDesktop(): Promise<CodexDesktopProcessState>;
  stat(candidate: string): Promise<Stats>;
  readFile(filePath: string): Promise<Buffer>;
  realpath(filePath: string): Promise<string>;
  open: typeof import("fs/promises").open;
  rename: typeof import("fs/promises").rename;
  unlink: typeof import("fs/promises").unlink;
  now(): number;
  randomId(): string;
};

export function desktopStatePath(dependencies: BindingDependencies): string {
  const pathApi = dependencies.platform === "win32" ? path.win32 : path.posix;
  const configured = dependencies.env.CODEX_HOME?.trim();
  return pathApi.join(configured || pathApi.join(dependencies.homeDir(), ".codex"), ".codex-global-state.json");
}

export async function exactlyMatchingProjectId(
  state: JsonObject,
  destinationPath: string,
  dependencies: BindingDependencies,
): Promise<string> {
  const projects = objectField(state, "local-projects", true);
  const matches = new Set<string>();
  for (const [key, rawProject] of Object.entries(projects)) {
    const project = requireObject(rawProject, `local-projects.${key}`);
    const id = requireString(project.id, `local-projects.${key}.id`);
    if (id !== key) {
      malformedState(`local-projects.${key}.id must match its key`);
    }
    const roots = requireStringArray(project.rootPaths, `local-projects.${key}.rootPaths`);
    for (const root of roots) {
      try {
        const candidate = await canonicalPath(root, dependencies);
        if (samePath(candidate, destinationPath, dependencies.platform)) {
          matches.add(id);
        }
      } catch {
        // A stale root in another project does not invalidate one exact live match.
      }
    }
  }
  if (matches.size === 0) {
    bindingError(
      "project-missing",
      "Add this destination folder as a Codex Desktop project, quit Desktop, and retry Import.",
    );
  }
  if (matches.size !== 1) {
    bindingError("project-ambiguous", "More than one Codex Desktop project matches this destination folder.");
  }
  return [...matches][0];
}

export async function requireCompatibleAssignments(
  state: JsonObject,
  threadIds: readonly string[],
  projectId: string,
  destinationPath: string,
  dependencies: BindingDependencies,
): Promise<void> {
  const assignments = objectField(state, "thread-project-assignments", false);
  for (const threadId of threadIds) {
    const raw = assignments[threadId];
    if (raw === undefined) {
      continue;
    }
    const assignment = requireObject(raw, `thread-project-assignments.${threadId}`);
    const recognizedKeys = new Set(["projectKind", "projectId", "cwd", "pendingCoreUpdate"]);
    if (Object.keys(assignment).some((key) => !recognizedKeys.has(key))) {
      malformedState(`thread-project-assignments.${threadId} has unrecognized fields`);
    }
    if (assignment.projectKind !== "local" || assignment.projectId !== projectId) {
      bindingError("assignment-conflict", "A selected task already belongs to a different Codex Desktop project.");
    }
    if (typeof assignment.pendingCoreUpdate !== "boolean" || typeof assignment.cwd !== "string") {
      malformedState(`thread-project-assignments.${threadId} has an unrecognized shape`);
    }
    let existingCwd: string;
    try {
      existingCwd = await canonicalPath(assignment.cwd, dependencies);
    } catch {
      bindingError(
        "assignment-conflict",
        "A selected task already has an unavailable Codex Desktop project folder.",
      );
    }
    if (!samePath(existingCwd, destinationPath, dependencies.platform)) {
      bindingError(
        "assignment-conflict",
        "A selected task already has a different Codex Desktop project folder.",
      );
    }
  }
}

export function applyAssignments(
  state: JsonObject,
  threadIds: readonly string[],
  projectId: string,
  destinationPath: string,
): boolean {
  const assignments = objectField(state, "thread-project-assignments", false);
  state["thread-project-assignments"] = assignments;
  let changed = false;
  for (const threadId of threadIds) {
    const existing = assignments[threadId];
    const next = {
      projectKind: "local",
      projectId,
      cwd: destinationPath,
      pendingCoreUpdate: false,
    };
    if (JSON.stringify(existing) !== JSON.stringify(next)) {
      assignments[threadId] = next;
      changed = true;
    }
  }
  const selected = new Set(threadIds);
  const projectless = optionalStringArray(state["projectless-thread-ids"], "projectless-thread-ids");
  const retained = projectless.filter((threadId) => !selected.has(threadId));
  if (retained.length !== projectless.length) {
    state["projectless-thread-ids"] = retained;
    changed = true;
  }
  const outputs = objectField(state, "thread-projectless-output-directories", false);
  for (const threadId of threadIds) {
    if (Object.hasOwn(outputs, threadId)) {
      delete outputs[threadId];
      changed = true;
    }
  }
  if (state["thread-projectless-output-directories"] !== undefined) {
    state["thread-projectless-output-directories"] = outputs;
  }
  return changed;
}

export function validateBindingStateShape(state: JsonObject): void {
  objectField(state, "thread-project-assignments", false);
  optionalStringArray(state["projectless-thread-ids"], "projectless-thread-ids");
  objectField(state, "thread-projectless-output-directories", false);
}

export async function verifyCommittedState(
  plan: Extract<DesktopProjectBindingPlan, { mode: "ready" }>,
  threadIds: readonly string[],
  dependencies: BindingDependencies,
): Promise<void> {
  const state = parseDesktopState((await readStableSnapshot(plan.statePath, dependencies)).bytes);
  const assignments = objectField(state, "thread-project-assignments", true);
  const projectless = new Set(optionalStringArray(state["projectless-thread-ids"], "projectless-thread-ids"));
  const outputs = objectField(state, "thread-projectless-output-directories", false);
  for (const threadId of threadIds) {
    const assignment = requireObject(assignments[threadId], `thread-project-assignments.${threadId}`);
    if (
      assignment.projectKind !== "local" || assignment.projectId !== plan.projectId ||
      assignment.pendingCoreUpdate !== false || typeof assignment.cwd !== "string" ||
      !samePath(assignment.cwd, plan.destinationPath, dependencies.platform) ||
      projectless.has(threadId) || Object.hasOwn(outputs, threadId)
    ) {
      bindingError("state-verification-failed", "Codex Desktop project assignment verification failed.");
    }
  }
}

export async function restoreAfterFailedCommit(
  statePath: string,
  backupPath: string,
  mode: number,
  dependencies: BindingDependencies,
): Promise<boolean> {
  if ((await dependencies.inspectDesktop()).status !== "closed") {
    return false;
  }
  const restorePath = temporaryFilePath(statePath, "restore", dependencies);
  try {
    await writeSyncedFile(restorePath, await dependencies.readFile(backupPath), mode, dependencies);
    await dependencies.rename(restorePath, statePath);
    return true;
  } catch {
    await removeIfPresent(restorePath, dependencies);
    return false;
  }
}

export async function requireDesktopClosed(dependencies: BindingDependencies): Promise<void> {
  const state = await dependencies.inspectDesktop();
  if (state.status === "running") {
    bindingError("desktop-running", "Quit Codex Desktop before importing tasks.");
  }
  if (state.status === "unknown") {
    bindingError(
      "desktop-process-unknown",
      "Codex Desktop closure could not be verified; close Desktop and retry Import.",
    );
  }
}

export async function canonicalPath(value: string, dependencies: BindingDependencies): Promise<string> {
  const trimmed = value.trim();
  if (!trimmed) {
    bindingError("destination-invalid", "The selected destination folder is invalid.");
  }
  return normalizeDesktopProjectPath(await dependencies.realpath(trimmed), dependencies.platform);
}

export function normalizeDesktopProjectPath(value: string, platform: NodeJS.Platform): string {
  const normalized = platform === "win32"
    ? path.win32.normalize(value).replace(/[\\/]+$/, "").toLowerCase()
    : path.posix.normalize(value).replace(/\/+$/, "");
  return normalized || (platform === "win32" ? path.win32.parse(value).root.toLowerCase() : "/");
}

export async function readStableSnapshot(
  filePath: string,
  dependencies: BindingDependencies,
): Promise<StateSnapshot> {
  const before = identityFromStat(await dependencies.stat(filePath));
  const bytes = await dependencies.readFile(filePath);
  const after = identityFromStat(await dependencies.stat(filePath));
  if (!sameIdentity(before, after) || bytes.byteLength !== after.size) {
    bindingError("state-changed", "Codex Desktop state changed while it was being inspected.");
  }
  return { bytes, sha256: sha256(bytes), identity: after };
}

export function requireUnchangedSource(
  plan: Extract<DesktopProjectBindingPlan, { mode: "ready" }>,
  snapshot: StateSnapshot,
): void {
  if (snapshot.sha256 !== plan.sourceSha256 || !sameIdentity(snapshot.identity, plan.sourceIdentity)) {
    bindingError("state-changed", "Codex Desktop state changed; retry Import.");
  }
}

export function parseDesktopState(bytes: Buffer): JsonObject {
  let parsed: unknown;
  try {
    parsed = JSON.parse(bytes.toString("utf8"));
  } catch {
    malformedState("Desktop global state is not valid JSON");
  }
  return requireObject(parsed, "Desktop global state");
}

export function serializeState(state: JsonObject, previous: Buffer): Buffer {
  return Buffer.from(`${JSON.stringify(state)}${previous.toString("utf8").endsWith("\n") ? "\n" : ""}`, "utf8");
}

export async function writeSyncedFile(
  filePath: string,
  bytes: Buffer,
  mode: number,
  dependencies: BindingDependencies,
): Promise<void> {
  const handle = await dependencies.open(filePath, "wx", mode);
  try {
    await handle.writeFile(bytes);
    await handle.sync();
  } finally {
    await handle.close();
  }
}

export function backupFilePath(statePath: string, dependencies: BindingDependencies): string {
  return `${statePath}.codex-usage-${dependencies.now()}-${dependencies.randomId()}.bak`;
}

export function temporaryFilePath(
  statePath: string,
  purpose: string,
  dependencies: BindingDependencies,
): string {
  return `${statePath}.codex-usage-${purpose}-${process.pid}-${dependencies.randomId()}.tmp`;
}

export async function fileExists(filePath: string, dependencies: BindingDependencies): Promise<boolean> {
  try {
    return (await dependencies.stat(filePath)).isFile();
  } catch (error) {
    if (isMissing(error)) {
      return false;
    }
    throw error;
  }
}

export async function removeIfPresent(filePath: string, dependencies: BindingDependencies): Promise<void> {
  try {
    await dependencies.unlink(filePath);
  } catch (error) {
    if (!isMissing(error)) {
      throw error;
    }
  }
}

export function canonicalThreadIds(values: readonly string[]): string[] {
  const threadIds = [...new Set(values)];
  if (threadIds.some((threadId) => !threadId || threadId !== threadId.trim())) {
    bindingError("thread-id-invalid", "Desktop project binding received an invalid task ID.");
  }
  return threadIds;
}

export function requireRegisteredSubset(selected: readonly string[], registered: readonly string[]): void {
  const selectedIds = new Set(selected);
  if (registered.some((threadId) => !selectedIds.has(threadId))) {
    bindingError("registration-invalid", "Desktop project binding received an unselected task ID.");
  }
}

function samePath(left: string, right: string, platform: NodeJS.Platform): boolean {
  return normalizeDesktopProjectPath(left, platform) === normalizeDesktopProjectPath(right, platform);
}

function identityFromStat(stat: Stats): FileIdentity {
  if (!stat.isFile()) {
    malformedState("Desktop global state must be a regular file");
  }
  if (
    !Number.isFinite(stat.dev) || !Number.isFinite(stat.ino) || stat.ino <= 0 ||
    !Number.isFinite(stat.size) || !Number.isFinite(stat.mtimeMs)
  ) {
    bindingError(
      "state-identity-unavailable",
      "Codex Desktop state identity could not be verified safely.",
    );
  }
  return { dev: stat.dev, ino: stat.ino, size: stat.size, mtimeMs: stat.mtimeMs, mode: stat.mode };
}

function sameIdentity(left: FileIdentity, right: FileIdentity): boolean {
  return left.dev === right.dev && left.ino === right.ino &&
    left.size === right.size && left.mtimeMs === right.mtimeMs;
}

function objectField(state: JsonObject, key: string, required: boolean): JsonObject {
  const value = state[key];
  if (value === undefined && !required) {
    return {};
  }
  return requireObject(value, key);
}

function requireObject(value: unknown, label: string): JsonObject {
  if (!isObject(value)) {
    malformedState(`${label} must be an object`);
  }
  return value;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function requireString(value: unknown, label: string): string {
  if (typeof value !== "string" || !value.trim()) {
    malformedState(`${label} must be a nonempty string`);
  }
  return value;
}

function requireStringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value) || value.some((entry) => typeof entry !== "string")) {
    malformedState(`${label} must be an array of strings`);
  }
  return value;
}

function optionalStringArray(value: unknown, label: string): string[] {
  return value === undefined ? [] : requireStringArray(value, label);
}

function isMissing(error: unknown): boolean {
  return isObject(error) && error.code === "ENOENT";
}

function sha256(bytes: Buffer): string {
  return createHash("sha256").update(bytes).digest("hex");
}

function malformedState(detail: string): never {
  bindingError("state-malformed", `Codex Desktop state is incompatible: ${detail}.`);
}

function bindingError(code: string, message: string): never {
  throw new DesktopProjectBindingError(code, message);
}
