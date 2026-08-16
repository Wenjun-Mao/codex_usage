import { randomUUID } from "crypto";
import * as fs from "fs/promises";
import { homedir } from "os";

import { inspectCodexDesktopProcess } from "./codexDesktopProcess";
import {
  applyAssignments,
  backupFilePath,
  canonicalPath,
  canonicalThreadIds,
  desktopStatePath,
  exactlyMatchingProjectId,
  fileExists,
  parseDesktopState,
  readStableSnapshot,
  removeIfPresent,
  requireCompatibleAssignments,
  requireDesktopClosed,
  requireRegisteredSubset,
  requireUnchangedSource,
  restoreAfterFailedCommit,
  serializeState,
  temporaryFilePath,
  validateBindingStateShape,
  verifyCommittedState,
  writeSyncedFile,
  DesktopProjectBindingError,
  type BindingDependencies,
  type DesktopProjectBindingPlan,
  type DesktopProjectBindingRequest,
  type DesktopProjectBindingResult,
} from "./codexDesktopBindingSupport";

export {
  DesktopProjectBindingError,
  type DesktopProjectBindingOutcome,
  type DesktopProjectBindingPlan,
  type DesktopProjectBindingRequest,
  type DesktopProjectBindingResult,
} from "./codexDesktopBindingSupport";

export type CreateDesktopProjectBinderOptions = {
  dependencies?: Partial<BindingDependencies>;
};

export type CodexDesktopProjectBinder = {
  preflight(request: DesktopProjectBindingRequest): Promise<DesktopProjectBindingPlan>;
  bind(
    plan: DesktopProjectBindingPlan,
    registeredThreadIds: readonly string[],
  ): Promise<DesktopProjectBindingResult>;
};

export function createCodexDesktopProjectBinder(
  options: CreateDesktopProjectBinderOptions = {},
): CodexDesktopProjectBinder {
  const platform = options.dependencies?.platform ?? process.platform;
  const dependencies: BindingDependencies = {
    platform,
    env: process.env,
    homeDir: homedir,
    inspectDesktop: () => inspectCodexDesktopProcess({ platform }),
    stat: fs.stat,
    readFile: fs.readFile,
    realpath: fs.realpath,
    open: fs.open,
    rename: fs.rename,
    unlink: fs.unlink,
    now: Date.now,
    randomId: randomUUID,
    ...options.dependencies,
  };
  return {
    preflight: (request) => preflightBinding(request, dependencies),
    bind: (plan, registeredThreadIds) => commitBinding(plan, registeredThreadIds, dependencies),
  };
}

async function preflightBinding(
  request: DesktopProjectBindingRequest,
  dependencies: BindingDependencies,
): Promise<DesktopProjectBindingPlan> {
  const threadIds = canonicalThreadIds(request.threadIds);
  const statePath = desktopStatePath(dependencies);
  if (!(await fileExists(statePath, dependencies))) {
    return { mode: "not-applicable", threadIds };
  }
  await requireDesktopClosed(dependencies);
  const snapshot = await readStableSnapshot(statePath, dependencies);
  const state = parseDesktopState(snapshot.bytes);
  validateBindingStateShape(state);
  const destinationPath = await canonicalPath(request.destinationPath, dependencies);
  const projectId = await exactlyMatchingProjectId(state, destinationPath, dependencies);
  await requireCompatibleAssignments(
    state,
    threadIds,
    projectId,
    destinationPath,
    dependencies,
  );
  return {
    mode: "ready",
    statePath,
    projectId,
    destinationPath,
    threadIds,
    sourceSha256: snapshot.sha256,
    sourceIdentity: snapshot.identity,
  };
}

async function commitBinding(
  plan: DesktopProjectBindingPlan,
  registeredThreadIds: readonly string[],
  dependencies: BindingDependencies,
): Promise<DesktopProjectBindingResult> {
  const registered = canonicalThreadIds(registeredThreadIds);
  requireRegisteredSubset(plan.threadIds, registered);
  if (plan.mode === "not-applicable") {
    return { status: "not-applicable", attempted: registered.length, bound: 0 };
  }
  if (registered.length === 0) {
    return { status: "unchanged", attempted: 0, bound: 0 };
  }

  await requireDesktopClosed(dependencies);
  const current = await readStableSnapshot(plan.statePath, dependencies);
  requireUnchangedSource(plan, current);
  const state = parseDesktopState(current.bytes);
  const projectId = await exactlyMatchingProjectId(state, plan.destinationPath, dependencies);
  if (projectId !== plan.projectId) {
    throw new DesktopProjectBindingError(
      "project-changed",
      "The matching Codex Desktop project changed; retry Import.",
    );
  }
  await requireCompatibleAssignments(
    state,
    registered,
    plan.projectId,
    plan.destinationPath,
    dependencies,
  );
  if (!applyAssignments(state, registered, plan.projectId, plan.destinationPath)) {
    return { status: "unchanged", attempted: registered.length, bound: registered.length };
  }

  const backupPath = backupFilePath(plan.statePath, dependencies);
  const temporaryPath = temporaryFilePath(plan.statePath, "state", dependencies);
  const mode = current.identity.mode & 0o777;
  let replaced = false;
  try {
    await writeSyncedFile(backupPath, current.bytes, 0o600, dependencies);
    await writeSyncedFile(temporaryPath, serializeState(state, current.bytes), mode, dependencies);
    await requireDesktopClosed(dependencies);
    requireUnchangedSource(plan, await readStableSnapshot(plan.statePath, dependencies));
    await dependencies.rename(temporaryPath, plan.statePath);
    replaced = true;
    await verifyCommittedState(plan, registered, dependencies);
  } catch (error) {
    await removeIfPresent(temporaryPath, dependencies);
    if (replaced && await fileExists(backupPath, dependencies)) {
      const restored = await restoreAfterFailedCommit(
        plan.statePath,
        backupPath,
        mode,
        dependencies,
      );
      if (!restored) {
        throw new DesktopProjectBindingError(
          "state-restore-failed",
          "Codex Desktop state verification and automatic restoration failed; keep Desktop closed.",
        );
      }
    }
    if (error instanceof DesktopProjectBindingError) {
      throw error;
    }
    throw new DesktopProjectBindingError(
      "state-write-failed",
      "Codex Desktop project assignment could not be saved safely.",
    );
  }
  return {
    status: "bound",
    attempted: registered.length,
    bound: registered.length,
    backupPath,
  };
}
