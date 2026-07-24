import {
  filterInventoryForOperation,
  type SyncInventory,
  type SyncInventoryProject,
} from "./syncInventory";
import type { TaskPickerSelection } from "./syncTaskPicker";
import type { TaskTransferPort } from "./taskTransfer";
import type { ProjectBinding } from "./syncProtocol";

export type SelectedTransferProject = {
  project: SyncInventoryProject;
  projectKey: string;
  projectLabel: string;
  threadIds: string[];
};

export class TransferProjectScopeError extends Error {
  constructor(operation: "import" | "export") {
    const verb = operation === "import" ? "Import" : "Export";
    super(`${verb} tasks from one project at a time. Choose one project and try again.`);
    this.name = "TransferProjectScopeError";
  }
}

export function requireSelectedTransferProject(
  inventory: SyncInventory,
  operation: "import" | "export",
  selection: TaskPickerSelection,
): SelectedTransferProject {
  const visibleInventory = filterInventoryForOperation(inventory, operation);
  const project = visibleInventory.projects.find(
    (candidate) => candidate.projectKey === selection.projectKey,
  );
  const threadIds = [...new Set(selection.threadIds)];
  const projectThreadIds = new Set(project?.tasks.map((task) => task.threadId));

  if (
    !project ||
    threadIds.length === 0 ||
    threadIds.some((threadId) => !projectThreadIds.has(threadId))
  ) {
    throw new TransferProjectScopeError(operation);
  }

  return {
    project,
    projectKey: project.projectKey,
    projectLabel: project.projectLabel,
    threadIds,
  };
}

export async function resolveImportProjectBindings(
  selected: SelectedTransferProject,
  port: Pick<
    TaskTransferPort,
    "chooseProjectRoot" | "confirmUnverifiedProject"
  >,
): Promise<ProjectBinding[] | undefined> {
  const selectedThreadIds = new Set(selected.threadIds);
  const requiresDestination = selected.project.tasks.some(
    (task) =>
      selectedThreadIds.has(task.threadId) &&
      task.availability === "remote",
  );
  if (!requiresDestination) {
    return [];
  }

  const candidates = normalizedPaths(selected.project.candidateRoots);
  if (candidates.length === 1) {
    return [{
      projectKey: selected.projectKey,
      path: candidates[0],
      confirmedUnverified: false,
    }];
  }

  const chosenPath = await port.chooseProjectRoot(selected.project, candidates);
  if (!chosenPath) {
    return undefined;
  }

  let confirmedUnverified = false;
  if (
    selected.project.identityKind === "path" &&
    chosenPath.trim() !== selected.projectKey.trim()
  ) {
    confirmedUnverified = await port.confirmUnverifiedProject(
      selected.project,
      chosenPath,
    );
    if (!confirmedUnverified) {
      return undefined;
    }
  }
  return [{
    projectKey: selected.projectKey,
    path: chosenPath,
    confirmedUnverified,
  }];
}

function normalizedPaths(paths: readonly string[]): string[] {
  const normalized: string[] = [];
  const seen = new Set<string>();
  for (const value of paths) {
    const path = value.trim();
    if (path && !seen.has(path)) {
      seen.add(path);
      normalized.push(path);
    }
  }
  return normalized;
}
