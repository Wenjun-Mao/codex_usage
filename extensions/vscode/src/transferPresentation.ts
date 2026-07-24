import type { SyncTaskAvailability } from "./syncInventory";
import type { SyncRunResult } from "./syncProtocol";
import type { CodexTaskRegistrationResult } from "./codexAppServer";
import type { TaskRegistrationSummary } from "./taskTransferRegistration";

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
  | "registering"
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

export type TransferResultContext = {
  projectLabel: string;
  registration?: CodexTaskRegistrationResult;
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
    registering: "Registering imported tasks",
    conflict: "Task transfer conflict",
    issue: "Task transfer issue",
  };
  return labels[value];
}

export function formatTransferResult(
  operation: "import" | "export",
  result: SyncRunResult,
  context: TransferResultContext,
): TransferResultMessage {
  const operationSubject = operation === "import"
    ? `Import into ${context.projectLabel}`
    : `Export from ${context.projectLabel}`;
  const oppositeCode = operation === "import" ? "pull_requires_push" : "push_requires_pull";
  const oppositeCount = result.issues.filter((issue) => issue.code === oppositeCode).length;
  const completedIds = operation === "import" ? result.pulled : result.pushed;
  const transferred = operation === "import" ? result.counts.pulled : result.counts.pushed;
  const hasIssue = result.outcome === "issue" || result.issues.length > 0;
  const hasFilesystemFailure = result.issues.some(
    (issue) => issue.code === "transfer_filesystem_failure",
  );

  if (context.registration && context.registration.failures.length > 0) {
    return registrationFailureMessage(result, context, hasIssue);
  }

  if (hasIssue && completedIds.length > 0) {
    if (operation === "import") {
      const pronoun = transferred === 1 ? "it" : "them";
      const registered = context.registration?.registeredThreadIds.length ?? 0;
      const registrationCopy = registered > 0
        ? ` Registered ${pronoun} with Codex. ${refreshGuidance(registered)}`
        : "";
      return {
        kind: "error",
        message:
          `${operationSubject} could not be completed. Imported files for ${transferred} ` +
          `${taskWord(transferred)} before the issue occurred.${registrationCopy} ` +
          "See the Codex Usage output for details.",
      };
    }
    return {
      kind: "error",
      message:
        `${operationSubject} could not be completed. Exported ${transferred} ` +
        `${taskWord(transferred)} ` +
        "to the transfer folder before the issue occurred. " +
        "See the Codex Usage output for details.",
    };
  }

  if (hasFilesystemFailure) {
    return {
      kind: "error",
      message:
        `${operationSubject} could not be completed. Task completion could not be determined. ` +
        "See the Codex Usage output for details.",
    };
  }

  if (oppositeCount > 0) {
    const source = operation === "import" ? "on this computer" : "in the transfer folder";
    const remedy = operation === "import" ? "Export" : "Import";
    const pronoun = oppositeCount === 1 ? "it" : "them";
    return {
      kind: "warning",
      message:
        `${operationSubject} was blocked because ${oppositeCount} selected ` +
        `${taskWord(oppositeCount)} ${oppositeCount === 1 ? "is" : "are"} newer ${source}. ` +
        `${remedy} ${pronoun} first.`,
    };
  }

  if (result.outcome === "conflict") {
    const count = result.counts.conflicts;
    const detail = count > 0 ? ` by ${count} ${conflictWord(count)}` : " by a conflict";
    return {
      kind: "warning",
      message: `${operationSubject} was blocked${detail}. No tasks were copied.`,
    };
  }

  if (hasIssue) {
    return {
      kind: "error",
      message:
        `${operationSubject} could not be completed. No tasks were copied. ` +
        "See the Codex Usage output for details.",
    };
  }

  if (transferred > 0) {
    if (operation === "import") {
      const registered = context.registration?.registeredThreadIds.length ?? 0;
      if (result.counts.unchanged > 0 && registered !== transferred) {
        return {
          kind: "info",
          message:
            `Imported ${transferred} ${taskWord(transferred)} into ${context.projectLabel} ` +
            `and registered ${registered} ${taskWord(registered)} with Codex. ` +
            refreshGuidance(registered),
        };
      }
      return {
        kind: "info",
        message:
          `Imported ${transferred} ${taskWord(transferred)} into ${context.projectLabel}. ` +
          refreshGuidance(registered),
      };
    }
    return {
      kind: "info",
      message:
        `Exported ${transferred} ${taskWord(transferred)} from ${context.projectLabel} ` +
        "to the transfer folder.",
    };
  }

  if (operation === "import" && context.registration) {
    const count = context.registration.registeredThreadIds.length;
    const pronoun = count === 1 ? "it" : "them";
    return {
      kind: "info",
      message:
        `No file changes were needed for ${count} ${taskWord(count)} in ` +
        `${context.projectLabel}. Registered ${pronoun} with Codex. ` +
        refreshGuidance(count),
    };
  }

  const count = result.counts.selected;
  const status = count === 1 ? "It is up to date." : "They are up to date.";
  return {
    kind: "info",
    message:
      `No file changes were needed for ${count} ${taskWord(count)} in ` +
      `${context.projectLabel}. ${status}`,
  };
}

function registrationFailureMessage(
  result: SyncRunResult,
  context: TransferResultContext,
  hasTransferIssue: boolean,
): TransferResultMessage {
  const registration = context.registration as CodexTaskRegistrationResult;
  const summary = summarizeRegistration(registration);
  const fileOutcome = registrationFileOutcome(result, context.projectLabel, summary);
  const registrationOutcome =
    `Codex registered ${summary.registered} ${taskWord(summary.registered)} ` +
    `and failed to register ${summary.failed} ${taskWord(summary.failed)}.`;
  const refresh = summary.registered > 0
    ? (
      " Open or restart Codex to display the successfully registered " +
      `${taskWord(summary.registered)}.`
    )
    : "";
  const safeFiles = summary.attempted === 1 ? "The file is safe." : "The files are safe.";
  const transferIssue = hasTransferIssue
    ? " Import also stopped before all selected tasks were copied. See the Codex Usage output for details."
    : "";
  return {
    kind: "warning",
    message:
      `${fileOutcome}, but ${registrationOutcome}${refresh} ${safeFiles} ` +
      `Retry Import after resolving Codex availability.${transferIssue}`,
  };
}

function summarizeRegistration(
  registration: CodexTaskRegistrationResult,
): TaskRegistrationSummary {
  return {
    attempted: registration.attemptedThreadIds.length,
    registered: registration.registeredThreadIds.length,
    failed: registration.failures.length,
  };
}

function registrationFileOutcome(
  result: SyncRunResult,
  projectLabel: string,
  summary: TaskRegistrationSummary,
): string {
  if (result.counts.pulled === 0) {
    return (
      `No file changes were needed for ${summary.attempted} ` +
      `${taskWord(summary.attempted)} in ${projectLabel}`
    );
  }
  if (result.counts.unchanged > 0) {
    return (
      `Imported files for ${result.counts.pulled} ${taskWord(result.counts.pulled)} ` +
      `into ${projectLabel}; ${result.counts.unchanged} ` +
      `${taskWord(result.counts.unchanged)} ` +
      `${result.counts.unchanged === 1 ? "was" : "were"} already current`
    );
  }
  return (
    `Imported files for ${result.counts.pulled} ${taskWord(result.counts.pulled)} ` +
    `into ${projectLabel}`
  );
}

function refreshGuidance(count: number): string {
  const pronoun = count === 1 ? "it" : "them";
  return `Open or restart Codex to display ${pronoun}.`;
}

function taskWord(count: number): string {
  return count === 1 ? "task" : "tasks";
}

function conflictWord(count: number): string {
  return count === 1 ? "conflict" : "conflicts";
}
