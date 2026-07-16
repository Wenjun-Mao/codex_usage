import * as fs from "fs/promises";
import * as path from "path";
import { spawn } from "child_process";
import * as vscode from "vscode";
import {
  ExtensionSettings,
  buildCodexUsageEnv,
  buildReportArgs,
  buildSummaryArgs,
  buildTransitionSuggestArgs,
  bundledExecutablePath,
  cacheDbPath,
  extensionVersionLabel,
  injectWebviewControls,
  injectWebviewCsp,
  normalizeProjectKeys,
  normalizeRange,
  normalizeTheme,
  PROJECT_KEYS_STATE_KEY,
  parseProjectChoices,
  readProjectKeysState,
  parseTransitionChoices,
  renderErrorHtml,
  renderLoadingHtml,
  RANGE_VALUES,
  THEME_VALUES,
  WEBVIEW_COMMANDS,
} from "./core";
import { buildSyncInventoryArgs, parseSyncInventory } from "./syncInventory";
import {
  buildSyncPullArgs,
  buildSyncPushArgs,
  buildSyncStatusArgs,
  parseSyncStatusSummary,
} from "./syncProtocol";
import { runSyncProcess } from "./syncProcess";
import {
  migrateTaskTransferState,
  TRANSFER_FOLDER_STATE_KEY,
  type TaskTransferStateStore,
} from "./taskTransferState";
import {
  buildTaskPickerItems,
  reduceTaskSelection,
  selectedPickerItemIds,
  type TaskPickerItem,
} from "./syncTaskPicker";
import {
  formatTransferResult,
  taskTransferMenuItems,
  transientStatusLabel,
  type TransferMenuAction,
  type TransferTransientStatus,
} from "./transferPresentation";

let panel: vscode.WebviewPanel | undefined;
let output: vscode.OutputChannel;
let statusItem: vscode.StatusBarItem;
let transientThreadIds: string[] = [];
let transferInFlight = false;
let transferStatus: TransferTransientStatus | undefined;

type SyncDirection = "pull" | "push";

export async function activate(context: vscode.ExtensionContext) {
  output = vscode.window.createOutputChannel("Codex Usage");
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusItem.command = "codexUsage.openDashboard";
  await migrateTaskTransferState(
    taskTransferStateStore(context),
    (message) => output.appendLine(`[task transfer migration] ${message}`),
  );
  updateStatusItem(readSettings(context));
  statusItem.show();

  const openDashboardCommand = vscode.commands.registerCommand("codexUsage.openDashboard", async () => {
    await openOrRefreshDashboard(context);
  });
  const refreshDashboardCommand = vscode.commands.registerCommand("codexUsage.refreshDashboard", async () => {
    await openOrRefreshDashboard(context);
  });
  const openSettingsCommand = vscode.commands.registerCommand("codexUsage.openSettings", async () => {
    await vscode.commands.executeCommand("workbench.action.openSettings", "codexUsage");
  });
  const selectRangeCommand = vscode.commands.registerCommand("codexUsage.selectRange", async () => {
    await selectRangeSetting(context);
  });
  const selectProjectsCommand = vscode.commands.registerCommand("codexUsage.selectProjects", async () => {
    await selectProjectSettings(context);
  });
  const selectThemeCommand = vscode.commands.registerCommand("codexUsage.selectTheme", async () => {
    await selectThemeSetting(context);
  });
  const reviewProjectTransitionsCommand = vscode.commands.registerCommand("codexUsage.reviewProjectTransitions", async () => {
    await reviewProjectTransitions(context);
  });
  const openSyncMenuCommand = vscode.commands.registerCommand("codexUsage.openSyncMenu", async () => {
    await showSyncMenu(context);
  });
  const configureSyncCommand = vscode.commands.registerCommand("codexUsage.configureSync", async () => {
    await changeTransferFolder(context);
  });
  const selectSyncTasksCommand = vscode.commands.registerCommand("codexUsage.selectSyncTasks", async () => {
    await selectSyncTasks(context);
  });
  const pullTasksCommand = vscode.commands.registerCommand("codexUsage.pullTasks", async () => {
    await runManualSync(context, "pull");
  });
  const pushTasksCommand = vscode.commands.registerCommand("codexUsage.pushTasks", async () => {
    await runManualSync(context, "push");
  });
  const syncStatusCommand = vscode.commands.registerCommand("codexUsage.syncStatus", async () => {
    await showSyncStatus(context);
  });
  const openSyncFolderCommand = vscode.commands.registerCommand("codexUsage.openSyncFolder", async () => {
    await openSyncFolder(context);
  });
  const settingsWatcher = vscode.workspace.onDidChangeConfiguration((event) => {
    if (!event.affectsConfiguration("codexUsage")) {
      return;
    }
    updateStatusItem(readSettings(context));
    if (panel) {
      void refreshDashboard(context, panel);
    }
  });
  context.subscriptions.push(
    openDashboardCommand,
    refreshDashboardCommand,
    openSettingsCommand,
    selectRangeCommand,
    selectProjectsCommand,
    selectThemeCommand,
    reviewProjectTransitionsCommand,
    openSyncMenuCommand,
    configureSyncCommand,
    selectSyncTasksCommand,
    pullTasksCommand,
    pushTasksCommand,
    syncStatusCommand,
    openSyncFolderCommand,
    settingsWatcher,
    output,
    statusItem,
  );
}

export function deactivate() {
  panel = undefined;
}

async function openOrRefreshDashboard(context: vscode.ExtensionContext): Promise<void> {
  if (!panel) {
    panel = vscode.window.createWebviewPanel("codexUsageDashboard", "Codex Usage", vscode.ViewColumn.One, {
      enableScripts: false,
      enableCommandUris: WEBVIEW_COMMANDS,
      localResourceRoots: [],
      retainContextWhenHidden: true,
    });
    panel.onDidDispose(() => {
      panel = undefined;
    }, null, context.subscriptions);
  } else {
    panel.reveal(vscode.ViewColumn.One);
  }

  await refreshDashboard(context, panel);
}

async function refreshDashboard(context: vscode.ExtensionContext, targetPanel: vscode.WebviewPanel): Promise<void> {
  const settings = readSettings(context);
  const reportPath = path.join(context.globalStorageUri.fsPath, "report.html");
  const loadingKind = await dashboardLoadingKind(context);
  setDashboardLoading(context, targetPanel, loadingKind);
  setUsageStatus(context, loadingKind === "initializing" ? "Codex Usage: Initializing" : "Codex Usage: Loading");

  try {
    const executablePath = await resolveBundledExecutable(context);
    await fs.mkdir(context.globalStorageUri.fsPath, { recursive: true });
    const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
    const args = buildReportArgs({
      range: settings.range,
      outputPath: reportPath,
      projectKeys: settings.projectKeys,
      theme: settings.theme,
      projectTransitions: settings.projectTransitions,
    });
    await runCodexUsage(executablePath, args, env);
    const reportHtml = await fs.readFile(reportPath, "utf8");
    targetPanel.webview.html = renderWebviewHtml(
      reportHtml,
      targetPanel.webview,
      settings,
      extensionVersionLabel(context.extension.packageJSON),
    );
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    targetPanel.webview.html = renderWebviewHtml(
      renderErrorHtml(`${message}\n\nCheck the Codex Usage output channel for details.`),
      targetPanel.webview,
      settings,
      extensionVersionLabel(context.extension.packageJSON),
    );
    void vscode.window.showErrorMessage(`Codex Usage failed: ${message}`);
  } finally {
    updateStatusItem(readSettings(context));
  }
}

type UsageLoadingKind = "initializing" | "refreshing" | "projects";

function usageLoadingMessage(kind: UsageLoadingKind): string {
  if (kind === "initializing") {
    return "Initializing Codex usage cache. This can take a few seconds the first time.";
  }
  if (kind === "projects") {
    return "Loading Codex projects...";
  }
  return "Refreshing Codex usage...";
}

async function dashboardLoadingKind(context: vscode.ExtensionContext): Promise<UsageLoadingKind> {
  try {
    await fs.access(cacheDbPath(context.globalStorageUri.fsPath));
    return "refreshing";
  } catch {
    return "initializing";
  }
}

function setDashboardLoading(
  context: vscode.ExtensionContext,
  targetPanel: vscode.WebviewPanel,
  kind: UsageLoadingKind,
): void {
  targetPanel.webview.html = renderWebviewHtml(
    renderLoadingHtml(usageLoadingMessage(kind)),
    targetPanel.webview,
    readSettings(context),
    extensionVersionLabel(context.extension.packageJSON),
  );
}

function setUsageStatus(context: vscode.ExtensionContext, label: string): void {
  statusItem.text = label;
  statusItem.tooltip = label;
}

async function selectRangeSetting(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  const items = RANGE_VALUES.map((range) => ({
    label: range,
    description: range === settings.range ? "Current" : "",
    range,
    picked: range === settings.range,
  }));
  const selected = await vscode.window.showQuickPick(items, {
    placeHolder: "Select Codex usage report range",
  });
  if (!selected || selected.range === settings.range) {
    return;
  }
  await vscode.workspace.getConfiguration("codexUsage").update("range", selected.range, vscode.ConfigurationTarget.Global);
}

async function selectThemeSetting(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  const items = THEME_VALUES.map((theme) => ({
    label: themeLabel(theme),
    description: theme === settings.theme ? "Current" : "",
    theme,
    picked: theme === settings.theme,
  }));
  const selected = await vscode.window.showQuickPick(items, {
    placeHolder: "Select Codex usage dashboard theme",
  });
  if (!selected || selected.theme === settings.theme) {
    return;
  }
  await vscode.workspace.getConfiguration("codexUsage").update("theme", selected.theme, vscode.ConfigurationTarget.Global);
}

async function selectProjectSettings(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  setUsageStatus(context, "Codex Usage: Loading Projects");
  try {
    const executablePath = await resolveBundledExecutable(context);
    const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
    const result = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Window,
        title: "Loading Codex usage projects",
      },
      () =>
        runCodexUsage(
          executablePath,
          buildSummaryArgs({
            range: settings.range,
            projectTransitions: settings.projectTransitions,
          }),
          env,
        ),
    );
    const choices = parseProjectChoices(result.stdout, settings.projectKeys);
    if (choices.length === 0) {
      void vscode.window.showInformationMessage("No Codex projects were found for the current range.");
      return;
    }

    const selected = await vscode.window.showQuickPick(projectQuickPickItems(choices, settings.projectKeys), {
      canPickMany: true,
      placeHolder: "Select Codex projects for the dashboard, or choose All Projects",
    });
    if (!selected) {
      return;
    }

    const nextProjectKeys =
      selected.length === 0 || selected.some((item) => item.allProjects)
        ? []
        : normalizeProjectKeys(selected.map((item) => item.projectKey));
    await context.globalState.update(PROJECT_KEYS_STATE_KEY, nextProjectKeys);
    updateStatusItem(readSettings(context));
    if (panel) {
      await refreshDashboard(context, panel);
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(`Codex Usage failed to load projects: ${message}`);
  } finally {
    updateStatusItem(readSettings(context));
  }
}

type TaskQuickPickItem = vscode.QuickPickItem & { task?: TaskPickerItem };

function showSyncTaskPicker(
  rows: TaskPickerItem[],
  initialThreadIds: string[],
): Promise<string[] | undefined> {
  const quickPick = vscode.window.createQuickPick<TaskQuickPickItem>();
  const pickerItems: TaskQuickPickItem[] = rows.map((row): TaskQuickPickItem => {
    if (row.kind === "separator") {
      return { label: row.label, kind: vscode.QuickPickItemKind.Separator };
    }
    return {
      label: row.label,
      description: row.description,
      detail: row.detail,
      task: row,
    };
  });
  const pickerItemsById = new Map(
    pickerItems.flatMap((item) => (item.task ? [[item.task.id, item] as const] : [])),
  );
  const rowsById = new Map(rows.map((row) => [row.id, row]));
  let selectedThreadIds = [...initialThreadIds];
  let previousSelectedRowIds = new Set(selectedPickerItemIds(rows, selectedThreadIds));
  let applyingCanonicalSelection = false;
  let settled = false;

  quickPick.title = "Select tasks for Task Transfer";
  quickPick.placeholder = "Select tasks or toggle a project to select all of its tasks";
  quickPick.canSelectMany = true;
  quickPick.matchOnDescription = true;
  quickPick.matchOnDetail = true;
  quickPick.items = pickerItems;
  quickPick.selectedItems = [...previousSelectedRowIds]
    .map((rowId) => pickerItemsById.get(rowId))
    .filter((item): item is TaskQuickPickItem => item !== undefined);

  return new Promise((resolve) => {
    const disposables: vscode.Disposable[] = [];
    const finish = (value: string[] | undefined): void => {
      if (settled) {
        return;
      }
      settled = true;
      for (const disposable of disposables) {
        disposable.dispose();
      }
      quickPick.dispose();
      resolve(value);
    };

    disposables.push(
      quickPick.onDidChangeSelection((selectedItems) => {
        if (applyingCanonicalSelection) {
          return;
        }
        const nextSelectedRowIds = new Set(
          selectedItems.flatMap((item) => (item.task ? [item.task.id] : [])),
        );
        const removedRowIds = [...previousSelectedRowIds].filter((rowId) => !nextSelectedRowIds.has(rowId));
        const addedRowIds = [...nextSelectedRowIds].filter((rowId) => !previousSelectedRowIds.has(rowId));

        for (const removedRowId of removedRowIds) {
          const removedItem = rowsById.get(removedRowId);
          if (removedItem) {
            selectedThreadIds = reduceTaskSelection(selectedThreadIds, removedItem, false);
          }
        }
        for (const addedRowId of addedRowIds) {
          const addedItem = rowsById.get(addedRowId);
          if (addedItem) {
            selectedThreadIds = reduceTaskSelection(selectedThreadIds, addedItem, true);
          }
        }

        previousSelectedRowIds = new Set(selectedPickerItemIds(rows, selectedThreadIds));
        applyingCanonicalSelection = true;
        quickPick.selectedItems = [...previousSelectedRowIds]
          .map((rowId) => pickerItemsById.get(rowId))
          .filter((item): item is TaskQuickPickItem => item !== undefined);
        applyingCanonicalSelection = false;
        if (selectedThreadIds.length > 0) {
          quickPick.title = "Select tasks for Task Transfer";
        }
      }),
      quickPick.onDidAccept(() => {
        if (selectedThreadIds.length === 0) {
          quickPick.title = "Select at least one Codex task";
          return;
        }
        finish([...selectedThreadIds]);
      }),
      quickPick.onDidHide(() => finish(undefined)),
    );
    quickPick.show();
  });
}

async function selectSyncTaskSettings(
  context: vscode.ExtensionContext,
  syncDir: string,
): Promise<string[] | undefined> {
  const settings = readSettings(context);
  setTransferStatus(context, "checking");
  try {
    const executablePath = await resolveBundledExecutable(context);
    const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
    const result = await runCodexUsage(
      executablePath,
      buildSyncInventoryArgs({
        syncDir,
        autoTransitions: settings.projectTransitions.autoDetect,
      }),
      env,
    );
    const inventory = parseSyncInventory(result.stdout);
    for (const issue of inventory.issues) {
      output.appendLine(
        `[sync inventory:${issue.code}] ${issue.message}${issue.threadId ? ` (${issue.threadId})` : ""}`,
      );
    }
    if (inventory.issues.length > 0) {
      void vscode.window.showWarningMessage(
        "Some remote task files could not be identified and were omitted from selection. See Codex Usage output for details.",
      );
    }
    const rows = buildTaskPickerItems(inventory, transientThreadIds);
    const selectedThreadIds = await showSyncTaskPicker(rows, transientThreadIds);
    if (!selectedThreadIds) {
      return undefined;
    }

    output.appendLine(
      `[task transfer] Chose ${selectedThreadIds.length} task${selectedThreadIds.length === 1 ? "" : "s"} for this session.`,
    );
    return selectedThreadIds;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(
      "Task Transfer could not load tasks. See the Codex Usage output for details.",
    );
    return undefined;
  } finally {
    clearTransferStatus(context);
  }
}

async function selectSyncTasks(context: vscode.ExtensionContext): Promise<void> {
  const syncDir = await ensureTransferFolder(context);
  if (!syncDir) {
    return;
  }
  const selected = await selectSyncTaskSettings(context, syncDir);
  if (selected) {
    transientThreadIds = selected;
  }
}

async function showSyncMenu(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  const selected = await vscode.window.showQuickPick(taskTransferMenuItems(settings.taskTransfer.folder), {
    placeHolder: "Choose a Task Transfer action",
  });
  if (!selected) {
    return;
  }

  await handleSyncMenuAction(context, selected.action);
}

async function handleSyncMenuAction(context: vscode.ExtensionContext, action: TransferMenuAction): Promise<void> {
  if (action === "importTasks") {
    await runManualSync(context, "pull");
    return;
  }
  if (action === "exportTasks") {
    await runManualSync(context, "push");
    return;
  }
  if (action === "reviewStatus") {
    await showSyncStatus(context);
    return;
  }
  if (action === "chooseFolder" || action === "changeFolder") {
    await changeTransferFolder(context);
    return;
  }
  if (action === "openFolder") {
    await openSyncFolder(context);
    return;
  }
  await forgetTransferFolder(context);
}

async function pickSyncFolder(): Promise<string | undefined> {
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
  return folder;
}

async function ensureTransferFolder(context: vscode.ExtensionContext): Promise<string | undefined> {
  const remembered = readSettings(context).taskTransfer.folder;
  if (remembered) {
    return remembered;
  }
  return chooseAndRememberTransferFolder(context);
}

async function changeTransferFolder(context: vscode.ExtensionContext): Promise<void> {
  await chooseAndRememberTransferFolder(context);
}

async function chooseAndRememberTransferFolder(context: vscode.ExtensionContext): Promise<string | undefined> {
  const folder = await pickSyncFolder();
  if (!folder) {
    return undefined;
  }
  await context.globalState.update(TRANSFER_FOLDER_STATE_KEY, folder);
  transientThreadIds = [];
  await refreshTaskTransferUi(context);
  return folder;
}

async function forgetTransferFolder(context: vscode.ExtensionContext): Promise<void> {
  await context.globalState.update(TRANSFER_FOLDER_STATE_KEY, undefined);
  transientThreadIds = [];
  await refreshTaskTransferUi(context);
}

async function refreshTaskTransferUi(context: vscode.ExtensionContext): Promise<void> {
  updateStatusItem(readSettings(context));
  if (panel) {
    await refreshDashboard(context, panel);
  }
}

async function reviewProjectTransitions(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  try {
    const executablePath = await resolveBundledExecutable(context);
    const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
    const result = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Window,
        title: "Detecting Codex project transitions",
      },
      () =>
        runCodexUsage(
          executablePath,
          buildTransitionSuggestArgs(),
          env,
        ),
    );
    const choices = parseTransitionChoices(result.stdout);
    if (choices.length === 0) {
      void vscode.window.showInformationMessage("No high-confidence Codex project transitions were found.");
      return;
    }

    const selected = await vscode.window.showQuickPick(choices, {
      canPickMany: true,
      placeHolder: "Review detected project transitions",
    });
    if (!selected) {
      return;
    }

    const autoDetectText = settings.projectTransitions.autoDetect
      ? "Automatic high-confidence transitions apply in reports."
      : "Automatic high-confidence transitions are disabled in settings.";
    const message =
      selected.length === 0
        ? `No project transitions selected. ${autoDetectText}`
        : `${selected.length} project transition${selected.length === 1 ? "" : "s"} selected for review. ${autoDetectText}`;
    void vscode.window.showInformationMessage(message);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(`Codex Usage failed to review project transitions: ${message}`);
  }
}

async function runManualSync(context: vscode.ExtensionContext, direction: SyncDirection): Promise<void> {
  const folder = await ensureTransferFolder(context);
  if (!folder) {
    return;
  }
  if (transientThreadIds.length === 0) {
    const selected = await selectSyncTaskSettings(context, folder);
    if (!selected) {
      return;
    }
    transientThreadIds = selected;
  }
  if (transferInFlight) {
    void vscode.window.showInformationMessage(
      "A Task Transfer operation is already running. Try again when it finishes.",
    );
    return;
  }

  await runDirectionalSync(context, direction, folder, transientThreadIds);
}

async function runDirectionalSync(
  context: vscode.ExtensionContext,
  direction: SyncDirection,
  folder: string,
  threadIds: string[],
): Promise<void> {
  transferInFlight = true;
  try {
    await executeSyncDirection(context, direction, folder, threadIds);
  } finally {
    transferInFlight = false;
    clearTransferStatus(context);
  }
}

async function executeSyncDirection(
  context: vscode.ExtensionContext,
  direction: SyncDirection,
  folder: string,
  threadIds: string[],
): Promise<void> {
  const settings = readSettings(context);
  try {
    const options = {
      syncDir: folder,
      threadIds,
      autoTransitions: settings.projectTransitions.autoDetect,
    };
    const executablePath = await resolveBundledExecutable(context);
    const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
    const completion = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Window,
        title: direction === "pull" ? "Importing Codex tasks" : "Exporting Codex tasks",
      },
      async () => {
        const args = direction === "pull" ? buildSyncPullArgs(options) : buildSyncPushArgs(options);
        output.appendLine(`> ${executablePath} ${args.join(" ")}`);
        setTransferStatus(context, "checking");
        return runSyncProcess({
          executablePath,
          args,
          env,
          onProgress: () => setTransferStatus(context, direction === "pull" ? "importing" : "exporting"),
          onOutput: (text) => output.append(text),
        });
      },
    );
    for (const issue of completion.result.issues) {
      output.appendLine(`[task transfer:${issue.code}] ${issue.message} (${issue.thread_id})`);
    }
    const operation = direction === "pull" ? "import" : "export";
    const formatted = formatTransferResult(operation, completion.result);
    if (completion.result.outcome === "conflict") {
      setTransferStatus(context, "conflict");
    } else if (completion.result.outcome === "issue") {
      setTransferStatus(context, "issue");
    }
    showTransferMessage(formatted.kind, formatted.message);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    setTransferStatus(context, "issue");
    const operation = direction === "pull" ? "Import" : "Export";
    void vscode.window.showErrorMessage(
      `${operation} could not be completed. No tasks were copied. See the Codex Usage output for details.`,
    );
  }
}

async function showSyncStatus(context: vscode.ExtensionContext): Promise<void> {
  const folder = await ensureTransferFolder(context);
  if (!folder) {
    return;
  }
  if (transientThreadIds.length === 0) {
    const selected = await selectSyncTaskSettings(context, folder);
    if (!selected) {
      return;
    }
    transientThreadIds = selected;
  }
  const settings = readSettings(context);
  try {
    setTransferStatus(context, "checking");
    const options = {
      syncDir: folder,
      threadIds: transientThreadIds,
      autoTransitions: settings.projectTransitions.autoDetect,
    };
    const executablePath = await resolveBundledExecutable(context);
    const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
    const result = await runCodexUsage(executablePath, buildSyncStatusArgs(options), env);
    const summary = parseSyncStatusSummary(result.stdout);
    output.appendLine(`[task transfer] ${summary.message}`);
    void vscode.window.showInformationMessage(`Task Transfer status: ${summary.message}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(
      "Task Transfer status could not be reviewed. See the Codex Usage output for details.",
    );
  } finally {
    clearTransferStatus(context);
  }
}

async function openSyncFolder(context: vscode.ExtensionContext): Promise<void> {
  const folder = await ensureTransferFolder(context);
  if (!folder) {
    return;
  }
  await vscode.env.openExternal(vscode.Uri.file(folder));
}

function readTransferFolder(context: vscode.ExtensionContext | undefined): string {
  const value = context?.globalState.get<unknown>(TRANSFER_FOLDER_STATE_KEY, "");
  return typeof value === "string" ? value.trim() : "";
}

function readSettings(context: vscode.ExtensionContext | undefined): ExtensionSettings {
  const config = vscode.workspace.getConfiguration("codexUsage");
  return {
    range: normalizeRange(config.get<string>("range", "30d")),
    projectKeys: context ? readProjectKeysState(context.globalState) : [],
    theme: normalizeTheme(config.get<string>("theme", "auto")),
    taskTransfer: { folder: readTransferFolder(context) },
    projectTransitions: {
      autoDetect: config.get<boolean>("projectTransitions.autoDetect", true),
    },
  };
}

function taskTransferStateStore(context: vscode.ExtensionContext): TaskTransferStateStore {
  const baseConfig = vscode.workspace.getConfiguration("codexUsage");
  const folders = vscode.workspace.workspaceFolders ?? [];
  return {
    readFolder: () => readTransferFolder(context),
    readLegacyFolder: () => baseConfig.get<string>("sync.dir", ""),
    async writeFolder(value) {
      await context.globalState.update(TRANSFER_FOLDER_STATE_KEY, value);
    },
    async removeGlobalState(key) {
      await context.globalState.update(key, undefined);
    },
    obsoleteConfigurationScopes() {
      const scopes: string[] = [];
      const base = baseConfig.inspect<boolean>("sync.enabled");
      if (base?.globalValue !== undefined) {
        scopes.push("global");
      }
      if (base?.workspaceValue !== undefined) {
        scopes.push("workspace");
      }
      for (const folder of folders) {
        const inspected = vscode.workspace
          .getConfiguration("codexUsage", folder.uri)
          .inspect<boolean>("sync.enabled");
        if (inspected?.workspaceFolderValue !== undefined) {
          scopes.push(`folder:${folder.uri.fsPath}`);
        }
      }
      return scopes;
    },
    async removeEnabledConfiguration(scope) {
      if (scope === "global") {
        await baseConfig.update("sync.enabled", undefined, vscode.ConfigurationTarget.Global);
        return;
      }
      if (scope === "workspace") {
        await baseConfig.update("sync.enabled", undefined, vscode.ConfigurationTarget.Workspace);
        return;
      }
      const folderPath = scope.slice("folder:".length);
      const folder = folders.find((item) => item.uri.fsPath === folderPath);
      if (!folder) {
        throw new Error(`Workspace folder is no longer available: ${folderPath}`);
      }
      await vscode.workspace
        .getConfiguration("codexUsage", folder.uri)
        .update("sync.enabled", undefined, vscode.ConfigurationTarget.WorkspaceFolder);
    },
  };
}

async function resolveBundledExecutable(context: vscode.ExtensionContext): Promise<string> {
  const executablePath = bundledExecutablePath(context.extensionUri.fsPath, process.platform, process.arch);
  try {
    await fs.access(executablePath);
    return executablePath;
  } catch {
    throw new Error(
      `Bundled codex-usage executable was not found at ${executablePath}. ` +
        "Rebuild the VSIX for this platform with `npm run package:vsix:win` or `npm run package:vsix:mac`.",
    );
  }
}

function runCodexUsage(
  executablePath: string,
  args: string[],
  env: NodeJS.ProcessEnv = process.env,
): Promise<{ stdout: string; stderr: string }> {
  output.appendLine(`> ${executablePath} ${args.join(" ")}`);
  return new Promise((resolve, reject) => {
    const child = spawn(executablePath, args, {
      shell: false,
      windowsHide: true,
      env,
    });

    let stdout = "";
    let stderr = "";

    child.stdout.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      stdout += text;
      output.append(text);
    });
    child.stderr.on("data", (chunk: Buffer) => {
      const text = chunk.toString();
      stderr += text;
      output.append(text);
    });
    child.on("error", (error: NodeJS.ErrnoException) => {
      if (error.code === "ENOENT") {
        reject(new Error(`Could not start bundled codex-usage executable: ${executablePath}`));
        return;
      }
      reject(error);
    });
    child.on("close", (code) => {
      if (code === 0) {
        resolve({ stdout, stderr });
        return;
      }
      const details = stderr.trim() || stdout.trim() || `codex-usage exited with code ${code}`;
      reject(new Error(details));
    });
  });
}

type ProjectQuickPickItem = vscode.QuickPickItem & {
  allProjects?: boolean;
  projectKey?: string;
};

function projectQuickPickItems(
  choices: ReturnType<typeof parseProjectChoices>,
  selectedProjectKeys: string[],
): ProjectQuickPickItem[] {
  const hasProjectFilter = normalizeProjectKeys(selectedProjectKeys).length > 0;
  return [
    {
      label: "All Projects",
      description: hasProjectFilter ? "Clear project filter" : "Current",
      picked: false,
      allProjects: true,
    },
    ...choices.map((choice) => ({
      label: choice.label,
      description: choice.description,
      detail: choice.detail,
      picked: choice.picked,
      projectKey: choice.key,
    })),
  ];
}

function renderWebviewHtml(
  rawHtml: string,
  webview: vscode.Webview,
  settings: ExtensionSettings,
  versionLabel: string,
): string {
  const withControls = injectWebviewControls(rawHtml, {
    range: settings.range,
    projectKeys: settings.projectKeys,
    theme: settings.theme,
    taskTransfer: settings.taskTransfer,
    versionLabel,
  });
  return injectWebviewCsp(withControls, webview.cspSource);
}

function updateStatusItem(settings: ExtensionSettings): void {
  const projectCount = settings.projectKeys.length;
  const theme = themeLabel(settings.theme);
  statusItem.text =
    projectCount > 0
      ? `Codex Usage: ${settings.range} (${projectCount})`
      : `Codex Usage: ${settings.range}`;
  if (transferStatus) {
    statusItem.text += ` | ${transientStatusLabel(transferStatus)}`;
  }
  statusItem.tooltip =
    projectCount > 0
      ? `Open Codex Usage Dashboard. Range: ${settings.range}. Projects: ${projectCount} selected. Theme: ${theme}.`
      : `Open Codex Usage Dashboard. Range: ${settings.range}. Projects: All Projects. Theme: ${theme}.`;
}

function themeLabel(theme: ExtensionSettings["theme"]): string {
  if (theme === "day") {
    return "Day";
  }
  if (theme === "night") {
    return "Night";
  }
  return "Auto";
}

function setTransferStatus(context: vscode.ExtensionContext, status: TransferTransientStatus): void {
  transferStatus = status;
  updateStatusItem(readSettings(context));
}

function clearTransferStatus(context: vscode.ExtensionContext): void {
  transferStatus = undefined;
  updateStatusItem(readSettings(context));
}

function showTransferMessage(kind: "info" | "warning" | "error", message: string): void {
  if (kind === "info") {
    void vscode.window.showInformationMessage(message);
    return;
  }
  if (kind === "warning") {
    void vscode.window.showWarningMessage(message);
    return;
  }
  void vscode.window.showErrorMessage(message);
}
