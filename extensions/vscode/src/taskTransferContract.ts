import type { TransferInventory, TransferProject, TransferTask } from "./types";

export type TransferOperation = "import" | "export" | "status";

export interface EligibleTransferProject {
  project: TransferProject;
  tasks: TransferTask[];
}

export function eligibleTransferTasks(
  tasks: TransferTask[],
  operation: TransferOperation,
): TransferTask[] {
  if (operation === "import") {
    return tasks.filter((task) => task.availability !== "local");
  }
  if (operation === "export") {
    return tasks.filter((task) => task.availability !== "remote");
  }
  return tasks;
}

export function eligibleTransferProjects(
  inventory: TransferInventory,
  operation: TransferOperation,
): EligibleTransferProject[] {
  return inventory.projects
    .map((project) => ({
      project,
      tasks: eligibleTransferTasks(project.tasks, operation),
    }))
    .filter((entry) => entry.tasks.length > 0);
}
