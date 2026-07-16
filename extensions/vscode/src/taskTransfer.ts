import {
  buildTaskPickerItems,
  type TaskPickerItem,
} from "./syncTaskPicker";
import type {
  SyncInventory,
  SyncInventoryCommandOptions,
  SyncInventoryProject,
} from "./syncInventory";
import type {
  ProjectBinding,
  SyncRunResult,
  SyncStatusSummary,
} from "./syncProtocol";
import { chooseFreshTaskTransferSelection } from "./taskTransferOperation";
import {
  formatTransferResult,
  taskInventoryWarningMessage,
  taskTransferMenuItems,
  type TransferMenuAction,
  type TransferMenuQuickPickItem,
  type TransferOperation,
  type TransferTransientStatus,
} from "./transferPresentation";

export type TransferExecutionRequest = {
  syncDir: string;
  threadIds: string[];
  autoTransitions: boolean;
  candidateProjectRoots: string[];
  projectBindings: ProjectBinding[];
};

export interface TaskTransferPort {
  readFolder(): string;
  writeFolder(folder: string | undefined): Promise<void>;
  chooseMenu(items: TransferMenuQuickPickItem[]): Promise<TransferMenuAction | undefined>;
  chooseTransferFolder(): Promise<string | undefined>;
  openFolder(folder: string): Promise<void>;
  workspaceRoots(): string[];
  loadInventory(request: SyncInventoryCommandOptions): Promise<SyncInventory>;
  chooseTasks(
    operation: TransferOperation,
    rows: TaskPickerItem[],
    initialThreadIds: string[],
  ): Promise<string[] | undefined>;
  chooseProjectRoot(
    project: SyncInventoryProject,
    candidates: string[],
  ): Promise<string | undefined>;
  confirmUnverifiedProject(
    project: SyncInventoryProject,
    chosenPath: string,
  ): Promise<boolean>;
  execute(
    operation: "import" | "export",
    request: TransferExecutionRequest,
  ): Promise<SyncRunResult>;
  review(request: TransferExecutionRequest): Promise<SyncStatusSummary>;
  notify(kind: "info" | "warning" | "error", message: string): void;
  log(message: string): void;
  setTransientStatus(status: TransferTransientStatus | undefined): void;
}

export class TransferFolderUnavailableError extends Error {
  constructor(readonly folder: string) {
    super(`Transfer folder is not available: ${folder}`);
    this.name = "TransferFolderUnavailableError";
  }
}

export class TaskTransferController {
  constructor(
    private readonly port: TaskTransferPort,
    private readonly autoTransitions: () => boolean,
  ) {}

  async showMenu(): Promise<void> {
    const action = await this.port.chooseMenu(taskTransferMenuItems(this.port.readFolder()));
    if (!action) {
      return;
    }
    await this.runMenuAction(action);
  }

  async importTasks(): Promise<void> {
    await this.runTransfer("import");
  }

  async exportTasks(): Promise<void> {
    await this.runTransfer("export");
  }

  async reviewStatus(): Promise<void> {
    const folder = await this.ensureFolder();
    if (!folder) {
      return;
    }

    this.port.setTransientStatus("checking");
    let stage: "selection" | "review" = "selection";
    try {
      const requestContext = this.requestContext(folder);
      const inventory = await this.loadInventory(requestContext);
      const rows = buildTaskPickerItems(inventory, "review");
      if (!hasTaskRows(rows)) {
        this.port.notify(
          "info",
          "No tasks are available to review on this computer or in the transfer folder.",
        );
        return;
      }
      const threadIds = await chooseFreshTaskTransferSelection("review", rows, this.port);
      if (!threadIds || threadIds.length === 0) {
        return;
      }

      stage = "review";
      const summary = await this.port.review({
        ...requestContext,
        candidateProjectRoots: executionCandidateRoots(requestContext, inventory),
        threadIds,
        projectBindings: [],
      });
      this.port.log(`[task transfer] ${summary.message}`);
      this.port.notify("info", formatReviewStatus(summary));
    } catch (error) {
      this.reportFailure(error, stage === "review" ? "review" : "selection");
    } finally {
      this.port.setTransientStatus(undefined);
    }
  }

  async chooseFolder(): Promise<void> {
    await this.chooseAndRememberFolder();
  }

  async changeFolder(): Promise<void> {
    await this.chooseAndRememberFolder();
  }

  async openFolder(): Promise<void> {
    const folder = await this.ensureFolder();
    if (folder) {
      try {
        await this.port.openFolder(folder);
      } catch (error) {
        if (error instanceof TransferFolderUnavailableError) {
          this.notifyUnavailableFolder(error.folder);
          return;
        }
        const detail = error instanceof Error ? error.message : String(error);
        this.port.log(`[error] ${detail}`);
        this.port.notify(
          "error",
          "The transfer folder could not be opened. See the Codex Usage output for details.",
        );
      }
    }
  }

  async forgetFolder(): Promise<void> {
    if (this.port.readFolder().trim()) {
      await this.port.writeFolder(undefined);
    }
  }

  private async runTransfer(operation: "import" | "export"): Promise<void> {
    const folder = await this.ensureFolder();
    if (!folder) {
      return;
    }

    this.port.setTransientStatus("checking");
    let stage: "selection" | "execution" = "selection";
    try {
      const requestContext = this.requestContext(folder);
      const inventory = await this.loadInventory(requestContext);
      const rows = buildTaskPickerItems(inventory, operation);
      if (!hasTaskRows(rows)) {
        this.port.notify("info", emptySourceMessage(operation));
        return;
      }

      const threadIds = await chooseFreshTaskTransferSelection(operation, rows, this.port);
      if (!threadIds || threadIds.length === 0) {
        return;
      }

      const projectBindings = operation === "import"
        ? await this.resolveImportBindings(inventory, threadIds)
        : [];
      if (projectBindings === undefined) {
        return;
      }

      stage = "execution";
      const result = await this.port.execute(operation, {
        ...requestContext,
        candidateProjectRoots: executionCandidateRoots(requestContext, inventory),
        threadIds: [...threadIds],
        projectBindings,
      });
      this.logIssues(result);
      if (result.outcome === "conflict") {
        this.port.setTransientStatus("conflict");
      } else if (result.outcome === "issue" || result.issues.length > 0) {
        this.port.setTransientStatus("issue");
      }
      const formatted = formatTransferResult(operation, result);
      this.port.notify(formatted.kind, formatted.message);
    } catch (error) {
      this.reportFailure(error, stage, operation);
    } finally {
      this.port.setTransientStatus(undefined);
    }
  }

  private requestContext(folder: string): Omit<TransferExecutionRequest, "threadIds" | "projectBindings"> {
    return {
      syncDir: folder,
      autoTransitions: this.autoTransitions(),
      candidateProjectRoots: this.port.workspaceRoots(),
    };
  }

  private async loadInventory(
    request: Omit<TransferExecutionRequest, "threadIds" | "projectBindings">,
  ): Promise<SyncInventory> {
    const inventory = await this.port.loadInventory(request);
    for (const issue of inventory.issues) {
      this.port.log(formatIssue("sync inventory", issue));
    }
    if (inventory.issues.length > 0) {
      this.port.notify("warning", taskInventoryWarningMessage());
    }
    return inventory;
  }

  private async resolveImportBindings(
    inventory: SyncInventory,
    threadIds: string[],
  ): Promise<ProjectBinding[] | undefined> {
    const selected = new Set(threadIds);
    const bindings: ProjectBinding[] = [];

    for (const project of inventory.projects) {
      const requiresDestination = project.tasks.some(
        (task) => selected.has(task.threadId) && task.availability === "remote",
      );
      if (!requiresDestination) {
        continue;
      }

      const candidates = normalizedPaths(project.candidateRoots);
      if (candidates.length === 1) {
        bindings.push({
          projectKey: project.projectKey,
          path: candidates[0],
          confirmedUnverified: false,
        });
        continue;
      }
      const chosenPath = await this.port.chooseProjectRoot(project, candidates);
      if (!chosenPath) {
        return undefined;
      }

      let confirmedUnverified = false;
      if (project.identityKind === "path" && chosenPath.trim() !== project.projectKey.trim()) {
        confirmedUnverified = await this.port.confirmUnverifiedProject(project, chosenPath);
        if (!confirmedUnverified) {
          return undefined;
        }
      }
      bindings.push({
        projectKey: project.projectKey,
        path: chosenPath,
        confirmedUnverified,
      });
    }
    return bindings;
  }

  private logIssues(result: SyncRunResult): void {
    for (const issue of result.issues) {
      this.port.log(formatIssue("task transfer", {
        code: issue.code,
        message: issue.message,
        threadId: issue.thread_id,
      }));
    }
  }

  private reportFailure(
    error: unknown,
    stage: "selection" | "execution" | "review",
    operation?: "import" | "export",
  ): void {
    if (error instanceof TransferFolderUnavailableError) {
      this.notifyUnavailableFolder(error.folder);
      return;
    }

    const detail = error instanceof Error ? error.message : String(error);
    this.port.log(`[error] ${detail}`);
    this.port.setTransientStatus("issue");
    if (stage === "review") {
      this.port.notify(
        "error",
        "Task Transfer status could not be reviewed. See the Codex Usage output for details.",
      );
      return;
    }
    if (stage === "selection") {
      this.port.notify(
        "error",
        "Task Transfer could not load tasks. See the Codex Usage output for details.",
      );
      return;
    }
    const operationLabel = operation === "export" ? "Export" : "Import";
    this.port.notify(
      "error",
      `${operationLabel} could not be completed. No tasks were copied. ` +
        "See the Codex Usage output for details.",
    );
  }

  private notifyUnavailableFolder(folder: string): void {
    this.port.notify(
      "error",
      `The transfer folder is not available: ${folder}. ` +
        "Choose another transfer folder and try again.",
    );
  }

  private async ensureFolder(): Promise<string | undefined> {
    const current = this.port.readFolder().trim();
    return current || this.chooseAndRememberFolder();
  }

  private async chooseAndRememberFolder(): Promise<string | undefined> {
    const chosen = (await this.port.chooseTransferFolder())?.trim();
    if (!chosen) {
      return undefined;
    }
    await this.port.writeFolder(chosen);
    return chosen;
  }

  private async runMenuAction(action: TransferMenuAction): Promise<void> {
    const actions: Record<TransferMenuAction, () => Promise<void>> = {
      importTasks: () => this.importTasks(),
      exportTasks: () => this.exportTasks(),
      reviewStatus: () => this.reviewStatus(),
      chooseFolder: () => this.chooseFolder(),
      changeFolder: () => this.changeFolder(),
      openFolder: () => this.openFolder(),
      forgetFolder: () => this.forgetFolder(),
    };
    await actions[action]();
  }
}

export function workspaceRootPaths(
  folders: readonly { uri: { fsPath: string } }[] | undefined,
): string[] {
  return normalizedPaths((folders ?? []).map((folder) => folder.uri.fsPath));
}

export function configurationScopeIds(
  folders: readonly { uri: { fsPath: string } }[] | undefined,
): string[] {
  return ["global", "workspace", ...workspaceRootPaths(folders).map((root) => `folder:${root}`)];
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

function executionCandidateRoots(
  request: Omit<TransferExecutionRequest, "threadIds" | "projectBindings">,
  inventory: SyncInventory,
): string[] {
  return normalizedPaths([
    ...request.candidateProjectRoots,
    ...inventory.projects.flatMap((project) => project.candidateRoots),
  ]);
}

function hasTaskRows(rows: TaskPickerItem[]): boolean {
  return rows.some((row) => row.kind === "task");
}

function emptySourceMessage(operation: "import" | "export"): string {
  return operation === "import"
    ? "No tasks are available to import from this transfer folder."
    : "No active Codex tasks are available to export from this computer.";
}

function formatIssue(
  source: string,
  issue: { code: string; message: string; threadId: string },
): string {
  const thread = issue.threadId ? ` (${issue.threadId})` : "";
  return `[${source}:${issue.code}] ${issue.message}${thread}`;
}

function formatReviewStatus(summary: SyncStatusSummary): string {
  const parts = [
    `${summary.total} task${summary.total === 1 ? "" : "s"}`,
    `${summary.synced} up to date`,
  ];
  appendReviewCount(parts, summary.localChanges, "newer on this computer");
  appendReviewCount(parts, summary.remoteChanges, "newer in the transfer folder");
  appendReviewCount(parts, summary.fastForwards, "ready to transfer");
  appendReviewCount(parts, summary.conflicts, "in conflict");
  appendReviewCount(parts, summary.missing, "missing");
  appendReviewCount(parts, summary.memoryWarnings, "with memory warnings");
  appendReviewCount(parts, summary.issues, "with issues");
  return `Task Transfer status: ${parts.join(", ")}.`;
}

function appendReviewCount(parts: string[], count: number, label: string): void {
  if (count > 0) {
    parts.push(`${count} ${label}`);
  }
}
