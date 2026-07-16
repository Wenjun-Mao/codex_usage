import * as vscode from "vscode";
import { buildSyncInventoryArgs, parseSyncInventory } from "./syncInventory";
import { runSyncProcess } from "./syncProcess";
import {
  buildSyncPullArgs,
  buildSyncPushArgs,
  buildSyncStatusArgs,
  parseSyncStatusSummary,
} from "./syncProtocol";
import { buildTaskPickerItems } from "./syncTaskPicker";
import { selectTaskTransferOperation } from "./taskTransferOperation";
import {
  migrateTaskTransferState,
  TRANSFER_FOLDER_STATE_KEY,
} from "./taskTransferState";
import {
  createTaskTransferVscodeStateStore,
  readTaskTransferFolder,
} from "./taskTransferVscodeState";
import { showTaskTransferPicker } from "./taskTransferVscodePicker";
import {
  formatTransferResult,
  taskInventoryWarningMessage,
  taskTransferMenuItems,
  type TransferMenuAction,
  type TransferOperation,
  type TransferTransientStatus,
} from "./transferPresentation";

type CommandResult = { stdout: string; stderr: string };

export type TaskTransferVscodeDependencies = {
  output: vscode.OutputChannel;
  readAutoTransitions(): boolean;
  resolveExecutable(): Promise<string>;
  processEnv(): NodeJS.ProcessEnv;
  runCommand(args: string[]): Promise<CommandResult>;
  refreshUi(): Promise<void>;
  setTransientStatus(status: TransferTransientStatus | undefined): void;
};

export type TaskTransferVscodeActions = {
  showMenu(): Promise<void>;
  chooseFolder(): Promise<void>;
  importTasks(): Promise<void>;
  exportTasks(): Promise<void>;
  reviewStatus(): Promise<void>;
  openFolder(): Promise<void>;
};

export async function migrateVscodeTaskTransferState(
  context: vscode.ExtensionContext,
  logError: (message: string) => void,
): Promise<void> {
  await migrateTaskTransferState(createVscodeStateStore(context), logError);
}

export function createTaskTransferVscode(
  context: vscode.ExtensionContext,
  dependencies: TaskTransferVscodeDependencies,
): TaskTransferVscodeActions {
  let inFlight = false;

  async function showMenu(): Promise<void> {
    const selected = await vscode.window.showQuickPick(
      taskTransferMenuItems(readTaskTransferFolder(context.globalState)),
      { placeHolder: "Choose a Task Transfer action" },
    );
    if (selected) {
      await handleMenuAction(selected.action);
    }
  }

  async function handleMenuAction(action: TransferMenuAction): Promise<void> {
    if (action === "importTasks") {
      await runOperation("import");
    } else if (action === "exportTasks") {
      await runOperation("export");
    } else if (action === "reviewStatus") {
      await reviewStatus();
    } else if (action === "chooseFolder" || action === "changeFolder") {
      await chooseFolder();
    } else if (action === "openFolder") {
      await openFolder();
    } else {
      await forgetFolder();
    }
  }

  async function chooseFolder(): Promise<void> {
    await chooseAndRememberFolder();
  }

  async function chooseAndRememberFolder(): Promise<string | undefined> {
    const selected = await vscode.window.showOpenDialog({
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
      openLabel: "Use Transfer Folder",
      title: "Choose Transfer Folder",
    });
    const folder = selected?.[0]?.fsPath?.trim();
    if (!folder) {
      return undefined;
    }
    await context.globalState.update(TRANSFER_FOLDER_STATE_KEY, folder);
    await dependencies.refreshUi();
    return folder;
  }

  async function ensureFolder(): Promise<string | undefined> {
    return readTaskTransferFolder(context.globalState) || chooseAndRememberFolder();
  }

  async function forgetFolder(): Promise<void> {
    await context.globalState.update(TRANSFER_FOLDER_STATE_KEY, undefined);
    await dependencies.refreshUi();
  }

  async function openFolder(): Promise<void> {
    const folder = await ensureFolder();
    if (folder) {
      await vscode.env.openExternal(vscode.Uri.file(folder));
    }
  }

  async function selectTasks(
    operation: TransferOperation,
    folder: string,
  ): Promise<string[] | undefined> {
    return selectTaskTransferOperation(operation, folder, {
      async loadRows(syncDir) {
        dependencies.setTransientStatus("checking");
        const result = await dependencies.runCommand(buildSyncInventoryArgs({
          syncDir,
          autoTransitions: dependencies.readAutoTransitions(),
        }));
        const inventory = parseSyncInventory(result.stdout);
        for (const issue of inventory.issues) {
          dependencies.output.appendLine(
            `[sync inventory:${issue.code}] ${issue.message}${issue.threadId ? ` (${issue.threadId})` : ""}`,
          );
        }
        if (inventory.issues.length > 0) {
          void vscode.window.showWarningMessage(taskInventoryWarningMessage());
        }
        return buildTaskPickerItems(inventory, operation);
      },
      chooseTasks: (_operation, rows, initialThreadIds) =>
        showTaskTransferPicker(rows, initialThreadIds),
    });
  }

  async function runOperation(operation: "import" | "export"): Promise<void> {
    const folder = await ensureFolder();
    if (!folder) {
      return;
    }
    let threadIds: string[] | undefined;
    try {
      threadIds = await selectTasks(operation, folder);
    } catch (error) {
      reportSelectionFailure(error);
      return;
    } finally {
      dependencies.setTransientStatus(undefined);
    }
    if (!threadIds) {
      return;
    }
    if (inFlight) {
      void vscode.window.showInformationMessage(
        "A Task Transfer operation is already running. Try again when it finishes.",
      );
      return;
    }
    inFlight = true;
    try {
      await executeDirection(operation, folder, threadIds);
    } finally {
      inFlight = false;
      dependencies.setTransientStatus(undefined);
    }
  }

  async function executeDirection(
    operation: "import" | "export",
    folder: string,
    threadIds: string[],
  ): Promise<void> {
    try {
      const options = {
        syncDir: folder,
        threadIds,
        autoTransitions: dependencies.readAutoTransitions(),
      };
      const executablePath = await dependencies.resolveExecutable();
      const completion = await vscode.window.withProgress(
        {
          location: vscode.ProgressLocation.Window,
          title: operation === "import" ? "Importing Codex tasks" : "Exporting Codex tasks",
        },
        async () => {
          const args = operation === "import" ? buildSyncPullArgs(options) : buildSyncPushArgs(options);
          dependencies.output.appendLine(`> ${executablePath} ${args.join(" ")}`);
          dependencies.setTransientStatus("checking");
          return runSyncProcess({
            executablePath,
            args,
            env: dependencies.processEnv(),
            onProgress: () => dependencies.setTransientStatus(
              operation === "import" ? "importing" : "exporting",
            ),
            onOutput: (text) => dependencies.output.append(text),
          });
        },
      );
      for (const issue of completion.result.issues) {
        dependencies.output.appendLine(`[task transfer:${issue.code}] ${issue.message} (${issue.thread_id})`);
      }
      if (completion.result.outcome === "conflict") {
        dependencies.setTransientStatus("conflict");
      } else if (completion.result.outcome === "issue") {
        dependencies.setTransientStatus("issue");
      }
      const formatted = formatTransferResult(operation, completion.result);
      showMessage(formatted.kind, formatted.message);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      dependencies.output.appendLine(`[error] ${detail}`);
      dependencies.setTransientStatus("issue");
      const label = operation === "import" ? "Import" : "Export";
      void vscode.window.showErrorMessage(
        `${label} could not be completed. No tasks were copied. See the Codex Usage output for details.`,
      );
    }
  }

  async function reviewStatus(): Promise<void> {
    const folder = await ensureFolder();
    if (!folder) {
      return;
    }
    try {
      const threadIds = await selectTasks("review", folder);
      if (!threadIds) {
        return;
      }
      const result = await dependencies.runCommand(buildSyncStatusArgs({
        syncDir: folder,
        threadIds,
        autoTransitions: dependencies.readAutoTransitions(),
      }));
      const summary = parseSyncStatusSummary(result.stdout);
      dependencies.output.appendLine(`[task transfer] ${summary.message}`);
      void vscode.window.showInformationMessage(`Task Transfer status: ${summary.message}`);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      dependencies.output.appendLine(`[error] ${detail}`);
      void vscode.window.showErrorMessage(
        "Task Transfer status could not be reviewed. See the Codex Usage output for details.",
      );
    } finally {
      dependencies.setTransientStatus(undefined);
    }
  }

  function reportSelectionFailure(error: unknown): void {
    const detail = error instanceof Error ? error.message : String(error);
    dependencies.output.appendLine(`[error] ${detail}`);
    void vscode.window.showErrorMessage(
      "Task Transfer could not load tasks. See the Codex Usage output for details.",
    );
  }

  return {
    showMenu,
    chooseFolder,
    importTasks: () => runOperation("import"),
    exportTasks: () => runOperation("export"),
    reviewStatus,
    openFolder,
  };
}

function createVscodeStateStore(context: vscode.ExtensionContext) {
  return createTaskTransferVscodeStateStore({
    globalState: context.globalState,
    configuration: (resource?: vscode.Uri) =>
      vscode.workspace.getConfiguration("codexUsage", resource),
    workspaceFolders: () => vscode.workspace.workspaceFolders ?? [],
    targets: {
      global: vscode.ConfigurationTarget.Global,
      workspace: vscode.ConfigurationTarget.Workspace,
      workspaceFolder: vscode.ConfigurationTarget.WorkspaceFolder,
    },
  });
}

function showMessage(kind: "info" | "warning" | "error", message: string): void {
  if (kind === "info") {
    void vscode.window.showInformationMessage(message);
  } else if (kind === "warning") {
    void vscode.window.showWarningMessage(message);
  } else {
    void vscode.window.showErrorMessage(message);
  }
}
