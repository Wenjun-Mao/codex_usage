import type { SyncTaskAvailability } from "./syncInventory";
import type { SyncRunResult } from "./syncProtocol";

export type TransferOperation = "import" | "export" | "review";
export type TransferMenuAction =
  | "importTasks"
  | "exportTasks"
  | "reviewStatus"
  | "chooseFolder"
  | "changeFolder"
  | "openFolder"
  | "forgetFolder";

export type TransferTransientStatus =
  | "checking"
  | "importing"
  | "exporting"
  | "conflict"
  | "issue";

export type TransferMenuQuickPickItem = {
  label: string;
  description: string;
  detail: string;
  action: TransferMenuAction;
};

export type TransferResultMessage = {
  kind: "info" | "warning" | "error";
  message: string;
};

export function taskTransferControlLabel(): string {
  return "Task Transfer ▾";
}

export function taskTransferMenuItems(folder: string): TransferMenuQuickPickItem[] {
  const rememberedFolder = folder.trim();
  const items: TransferMenuQuickPickItem[] = [
    {
      label: "$(cloud-download) Import Tasks",
      description: "From transfer folder",
      detail: "Choose tasks to copy from the transfer folder to this computer.",
      action: "importTasks",
    },
    {
      label: "$(cloud-upload) Export Tasks",
      description: "To transfer folder",
      detail: "Choose active tasks to copy from this computer to the transfer folder.",
      action: "exportTasks",
    },
    {
      label: "$(info) Review Transfer Status",
      description: "Compare both locations",
      detail: "Review task state on this computer and in the transfer folder.",
      action: "reviewStatus",
    },
  ];

  if (!rememberedFolder) {
    items.push({
      label: "$(folder-opened) Choose Transfer Folder",
      description: "Remember a folder",
      detail: "Choose the folder used to move tasks between computers.",
      action: "chooseFolder",
    });
    return items;
  }

  items.push(
    {
      label: "$(folder-opened) Change Transfer Folder",
      description: rememberedFolder,
      detail: "Choose a different folder for moving tasks between computers.",
      action: "changeFolder",
    },
    {
      label: "$(folder) Open Transfer Folder",
      description: rememberedFolder,
      detail: "Open the remembered transfer folder.",
      action: "openFolder",
    },
    {
      label: "$(trash) Forget Transfer Folder",
      description: rememberedFolder,
      detail: "Forget this path without deleting files from either location.",
      action: "forgetFolder",
    },
  );
  return items;
}

export function taskAvailabilityLabel(value: SyncTaskAvailability): string {
  if (value === "local") {
    return "On this computer";
  }
  if (value === "remote") {
    return "In transfer folder";
  }
  return "On both";
}

export function taskPickerDetail(taskId: string, estimatedTransferSize?: string): string {
  const id = `Task ID: ${taskId}`;
  return estimatedTransferSize
    ? `${id} | Estimated task transfer size: ${estimatedTransferSize}`
    : id;
}

export function taskInventoryWarningMessage(): string {
  return "Some tasks in the transfer folder could not be identified and were omitted. See Codex Usage output for details.";
}

export function taskStateLabel(action: string, state: string): string {
  if (action === "pull") {
    return "Ready to import";
  }
  if (action === "push") {
    return "Ready to export";
  }
  if (state === "synced") {
    return "Up to date";
  }
  if (state === "conflict" || action === "conflict") {
    return "Conflict";
  }
  if (state === "missing") {
    return "Missing";
  }
  return "Issue";
}

export function transientStatusLabel(value: TransferTransientStatus): string {
  const labels: Record<TransferTransientStatus, string> = {
    checking: "Checking tasks",
    importing: "Importing tasks",
    exporting: "Exporting tasks",
    conflict: "Task transfer conflict",
    issue: "Task transfer issue",
  };
  return labels[value];
}

export function formatTransferResult(
  operation: "import" | "export",
  result: SyncRunResult,
): TransferResultMessage {
  const operationLabel = operation === "import" ? "Import" : "Export";
  const oppositeCode = operation === "import" ? "pull_requires_push" : "push_requires_pull";
  const oppositeCount = result.issues.filter((issue) => issue.code === oppositeCode).length;

  if (oppositeCount > 0) {
    const source = operation === "import" ? "on this computer" : "in the transfer folder";
    const remedy = operation === "import" ? "Export" : "Import";
    const pronoun = oppositeCount === 1 ? "it" : "them";
    return {
      kind: "warning",
      message:
        `${operationLabel} was blocked because ${oppositeCount} selected ` +
        `${taskWord(oppositeCount)} ${oppositeCount === 1 ? "is" : "are"} newer ${source}. ` +
        `${remedy} ${pronoun} first.`,
    };
  }

  if (result.outcome === "conflict") {
    const count = result.counts.conflicts;
    const detail = count > 0 ? ` by ${count} ${conflictWord(count)}` : " by a conflict";
    return {
      kind: "warning",
      message: `${operationLabel} was blocked${detail}. No tasks were copied.`,
    };
  }

  if (result.outcome === "issue" || result.issues.length > 0) {
    return {
      kind: "error",
      message: `${operationLabel} could not be completed. No tasks were copied. See the Codex Usage output for details.`,
    };
  }

  const transferred = operation === "import" ? result.counts.pulled : result.counts.pushed;
  if (transferred > 0) {
    if (operation === "import") {
      const pronoun = transferred === 1 ? "it" : "them";
      return {
        kind: "info",
        message:
          `Imported ${transferred} ${taskWord(transferred)}. ` +
          `Reload VS Code or restart the Codex app to see ${pronoun}.`,
      };
    }
    return {
      kind: "info",
      message: `Exported ${transferred} ${taskWord(transferred)} to the transfer folder.`,
    };
  }

  if (result.counts.selected === 1) {
    return { kind: "info", message: "No changes were needed. The selected task is up to date." };
  }
  if (result.counts.selected > 1) {
    return {
      kind: "info",
      message: `No changes were needed. All ${result.counts.selected} selected tasks are up to date.`,
    };
  }
  return { kind: "info", message: "No changes were needed. The chosen tasks are up to date." };
}

function taskWord(count: number): string {
  return count === 1 ? "task" : "tasks";
}

function conflictWord(count: number): string {
  return count === 1 ? "conflict" : "conflicts";
}
