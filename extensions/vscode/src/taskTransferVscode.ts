import * as vscode from "vscode";

import {
  configurationScopeIds,
  TransferFolderUnavailableError,
  workspaceRootPaths,
  type TaskTransferPort,
  type TransferExecutionRequest,
} from "./taskTransfer";
import {
  buildSyncInventoryArgs,
  parseSyncInventory,
  type SyncInventoryProject,
} from "./syncInventory";
import { runSyncProcess } from "./syncProcess";
import {
  buildSyncPullArgs,
  buildSyncPushArgs,
  buildSyncStatusArgs,
  parseSyncStatusSummary,
} from "./syncProtocol";
import {
  migrateTaskTransferState,
  TRANSFER_FOLDER_STATE_KEY,
} from "./taskTransferState";
import {
  createTaskTransferVscodeStateStore,
  readTaskTransferFolder,
} from "./taskTransferVscodeState";
import { showTaskTransferPicker } from "./taskTransferVscodePicker";
import type {
  TransferMenuAction,
  TransferMenuQuickPickItem,
  TransferTransientStatus,
} from "./transferPresentation";
import type { CodexTaskRegistrationResult } from "./codexAppServer";

type CommandResult = { stdout: string; stderr: string };

export type TaskTransferVscodeDependencies = {
  output: vscode.OutputChannel;
  resolveExecutable(): Promise<string>;
  processEnv(): NodeJS.ProcessEnv;
  runCommand(args: string[]): Promise<CommandResult>;
  runSyncProcess?: typeof runSyncProcess;
  registerImportedTasks(threadIds: readonly string[]): Promise<CodexTaskRegistrationResult>;
  refreshUi(): Promise<void>;
  setTransientStatus(status: TransferTransientStatus | undefined): void;
};

export async function migrateVscodeTaskTransferState(
  context: vscode.ExtensionContext,
  logError: (message: string) => void,
): Promise<void> {
  await migrateTaskTransferState(createVscodeStateStore(context), logError);
}

export function createTaskTransferVscodePort(
  context: vscode.ExtensionContext,
  dependencies: TaskTransferVscodeDependencies,
): TaskTransferPort {
  return {
    readFolder: () => readTaskTransferFolder(context.globalState),
    async writeFolder(folder) {
      await context.globalState.update(TRANSFER_FOLDER_STATE_KEY, folder);
      await dependencies.refreshUi();
    },
    chooseMenu: (items) => chooseMenu(items),
    chooseTransferFolder,
    async openFolder(folder) {
      await requireAvailableTransferFolder(folder);
      await vscode.env.openExternal(vscode.Uri.file(folder));
    },
    workspaceRoots: () => workspaceRootPaths(vscode.workspace.workspaceFolders),
    async loadInventory(request) {
      await requireAvailableTransferFolder(request.syncDir);
      const result = await dependencies.runCommand(buildSyncInventoryArgs(request));
      return parseSyncInventory(result.stdout);
    },
    chooseTasks: (operation, rows) => showTaskTransferPicker(operation, rows),
    chooseProjectRoot,
    confirmUnverifiedProject,
    execute: (operation, request) => executeTransfer(operation, request, dependencies),
    async review(request) {
      const result = await dependencies.runCommand(buildSyncStatusArgs(request));
      return parseSyncStatusSummary(result.stdout);
    },
    registerImportedTasks: (threadIds) => dependencies.registerImportedTasks(threadIds),
    notify: showMessage,
    log: (message) => dependencies.output.appendLine(message),
    setTransientStatus: dependencies.setTransientStatus,
  };
}

async function chooseMenu(
  items: TransferMenuQuickPickItem[],
): Promise<TransferMenuAction | undefined> {
  const selected = await vscode.window.showQuickPick(items, {
    placeHolder: "Choose a Task Transfer action",
  });
  return selected?.action;
}

async function chooseTransferFolder(): Promise<string | undefined> {
  return chooseFolder({
    openLabel: "Use Transfer Folder",
    title: "Choose Transfer Folder",
  });
}

async function chooseProjectRoot(
  project: SyncInventoryProject,
  candidates: string[],
): Promise<string | undefined> {
  if (candidates.length > 0) {
    const selected = await vscode.window.showQuickPick(
      candidates.map((candidate) => ({ label: candidate, path: candidate })),
      {
        title: `Choose Destination Folder for ${project.projectLabel}`,
        placeHolder: "Choose the matching local project folder",
      },
    );
    return selected?.path;
  }
  return chooseFolder({
    openLabel: "Choose Local Project Folder",
    title: `Choose Destination Folder for ${project.projectLabel}`,
  });
}

async function confirmUnverifiedProject(
  project: SyncInventoryProject,
  chosenPath: string,
): Promise<boolean> {
  const selected = await vscode.window.showWarningMessage(
    `The transfer task identifies its project as ${project.projectKey}, but Git cannot ` +
      `verify the selected destination ${chosenPath}. Use this folder for this import?`,
    { modal: true },
    "Use Folder",
  );
  return selected === "Use Folder";
}

async function executeTransfer(
  operation: "import" | "export",
  request: TransferExecutionRequest,
  dependencies: TaskTransferVscodeDependencies,
) {
  const args = operation === "import"
    ? buildSyncPullArgs(request)
    : buildSyncPushArgs(request);
  const executablePath = await dependencies.resolveExecutable();
  const processRunner = dependencies.runSyncProcess ?? runSyncProcess;
  const direction = operation === "import" ? "into" : "from";
  const verb = operation === "import" ? "Importing" : "Exporting";
  const title =
    `${verb} ${request.threadIds.length} ` +
    `${taskWord(request.threadIds.length)} ${direction} ${request.projectLabel}`;

  const completion = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Window,
      title,
    },
    async () => {
      dependencies.output.appendLine(`> ${executablePath} ${args.join(" ")}`);
      return processRunner({
        executablePath,
        args,
        env: dependencies.processEnv(),
        onProgress: (event) => {
          if (event.phase === "pulling") {
            dependencies.setTransientStatus("importing");
          } else if (event.phase === "pushing") {
            dependencies.setTransientStatus("exporting");
          }
        },
        onOutput: (text) => dependencies.output.append(text),
      });
    },
  );
  return completion.result;
}

function taskWord(count: number): string {
  return count === 1 ? "task" : "tasks";
}

async function chooseFolder(options: {
  openLabel: string;
  title: string;
}): Promise<string | undefined> {
  const selected = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    ...options,
  });
  return selected?.[0]?.fsPath?.trim() || undefined;
}

async function requireAvailableTransferFolder(folder: string): Promise<void> {
  try {
    await vscode.workspace.fs.stat(vscode.Uri.file(folder));
  } catch {
    throw new TransferFolderUnavailableError(folder);
  }
}

function createVscodeStateStore(context: vscode.ExtensionContext) {
  return createTaskTransferVscodeStateStore({
    globalState: context.globalState,
    configuration: (resource?: vscode.Uri) =>
      vscode.workspace.getConfiguration("codexUsage", resource),
    workspaceFolders: migrationWorkspaceFolders,
    targets: {
      global: vscode.ConfigurationTarget.Global,
      workspace: vscode.ConfigurationTarget.Workspace,
      workspaceFolder: vscode.ConfigurationTarget.WorkspaceFolder,
    },
  });
}

function migrationWorkspaceFolders(): readonly vscode.WorkspaceFolder[] {
  const folders = vscode.workspace.workspaceFolders ?? [];
  const paths = configurationScopeIds(folders)
    .filter((scope) => scope.startsWith("folder:"))
    .map((scope) => scope.slice("folder:".length));
  return paths.flatMap((folderPath) => {
    const folder = folders.find((item) => item.uri.fsPath.trim() === folderPath);
    return folder ? [folder] : [];
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
