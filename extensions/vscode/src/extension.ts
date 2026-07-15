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
  hasValidSyncSelection,
  normalizeProjectKeys,
  normalizeRange,
  normalizeSyncSettings,
  normalizeTheme,
  PROJECT_KEYS_STATE_KEY,
  SYNC_DIR_STATE_KEY,
  SYNC_SELECTION_VERSION_STATE_KEY,
  SYNC_THREAD_IDS_STATE_KEY,
  parseProjectChoices,
  readProjectKeysState,
  readSyncDirState,
  readSyncSelectionVersionState,
  readSyncThreadIdsState,
  parseTransitionChoices,
  renderErrorHtml,
  renderLoadingHtml,
  shouldRefreshAfterSyncSetupStep,
  SyncMenuAction,
  SyncStatusKind,
  syncMenuQuickPickItems,
  syncStatusKindLabel,
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
  SyncSetupMutationCoordinator,
  type AsyncSyncSetupStore,
} from "./syncSetupTransaction";
import {
  buildTaskPickerItems,
  reduceTaskSelection,
  selectedPickerItemIds,
  type TaskPickerItem,
} from "./syncTaskPicker";

let panel: vscode.WebviewPanel | undefined;
let output: vscode.OutputChannel;
let statusItem: vscode.StatusBarItem;
const syncSetupMutations = new SyncSetupMutationCoordinator();

type SyncDirection = "pull" | "push";

type SyncRuntimeState = {
  inFlight: boolean;
  status: SyncStatusKind;
  lastSyncAt: number;
  lastError: string;
};

const syncRuntime: SyncRuntimeState = {
  inFlight: false,
  status: "off",
  lastSyncAt: 0,
  lastError: "",
};

const SYNC_SETUP_REQUIRED_MESSAGE = "Sync setup is required. Select a folder and at least one Codex task.";

export async function activate(context: vscode.ExtensionContext) {
  output = vscode.window.createOutputChannel("Codex Usage");
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusItem.command = "codexUsage.openDashboard";
  await migrateDeprecatedSyncSettings(context);
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
    await configureSync(context);
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
    if (syncSetupMutations.isMutating) {
      return;
    }
    updateStatusItem(readSettings(context));
    resetSyncRuntimeWhenDisabled(context);
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

  quickPick.title = "Select Codex tasks to sync";
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
          quickPick.title = "Select Codex tasks to sync";
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
  options: { enableAfterAccept?: boolean; refreshDashboard?: boolean } = {},
): Promise<boolean> {
  const settings = readSettings(context);
  setUsageStatus(context, "Codex Usage: Loading Sync Tasks");
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
    const rows = buildTaskPickerItems(inventory, settings.sync.threadIds);
    const selectedThreadIds = await showSyncTaskPicker(rows, settings.sync.threadIds);
    if (!selectedThreadIds) {
      return false;
    }

    await syncSetupMutations.commit(syncSetupStore(context), {
      folder: syncDir,
      threadIds: selectedThreadIds,
      enabled: options.enableAfterAccept ? true : undefined,
    });
    await syncSetupMutations.whenIdle();
    output.appendLine(
      `[sync] Sync configured for ${selectedThreadIds.length} task${selectedThreadIds.length === 1 ? "" : "s"}: ${syncDir}`,
    );
    await refreshSyncUi(context, shouldRefreshAfterSyncSetupStep(options));
    return true;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(`Codex Usage failed to configure sync tasks: ${message}`);
    await syncSetupMutations.whenIdle();
    await refreshSyncUi(context, shouldRefreshAfterSyncSetupStep(options));
    return false;
  } finally {
    updateStatusItem(readSettings(context));
  }
}

async function selectSyncTasks(context: vscode.ExtensionContext): Promise<void> {
  const syncDir = readSettings(context).sync.dir;
  if (!syncDir) {
    await configureSync(context);
    return;
  }
  await selectSyncTaskSettings(context, syncDir);
}

async function configureSync(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  let candidate = settings.sync.dir;
  if (candidate) {
    const choice = await vscode.window.showQuickPick(
      [
        { label: "Keep Current Folder", description: candidate, action: "keep" },
        { label: "Choose Another Folder", description: "Pick a different sync folder", action: "choose" },
      ],
      { placeHolder: "Configure Codex sync folder" },
    );
    if (!choice) {
      return;
    }
    if (choice.action === "choose") {
      const selectedDir = await pickSyncFolder();
      if (!selectedDir) {
        return;
      }
      candidate = selectedDir;
    }
  } else {
    const selectedDir = await pickSyncFolder();
    if (!selectedDir) {
      return;
    }
    candidate = selectedDir;
  }
  await selectSyncTaskSettings(context, candidate, { enableAfterAccept: true });
}

async function showSyncMenu(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  const selected = await vscode.window.showQuickPick(syncMenuQuickPickItems(settings.sync), {
    placeHolder: "Choose a Codex sync action",
  });
  if (!selected) {
    return;
  }

  await handleSyncMenuAction(context, selected.action);
}

async function handleSyncMenuAction(context: vscode.ExtensionContext, action: SyncMenuAction): Promise<void> {
  if (action === "pullTasks") {
    await runManualSync(context, "pull");
    return;
  }
  if (action === "pushTasks") {
    await runManualSync(context, "push");
    return;
  }
  if (action === "syncStatus") {
    await showSyncStatus(context);
    return;
  }
  if (action === "pauseSync") {
    await pauseSync(context);
    return;
  }
  if (action === "resumeSync") {
    await resumeSync(context);
    return;
  }
  if (action === "changeFolder") {
    await changeSyncFolder(context);
    return;
  }
  if (action === "changeTasks") {
    await selectSyncTasks(context);
    return;
  }
  if (action === "clearSync") {
    await clearSyncSetup(context);
    return;
  }
  await openSyncFolder(context);
}

async function pauseSync(context: vscode.ExtensionContext): Promise<void> {
  try {
    await syncSetupMutations.setEnabled(syncSetupStore(context), false);
  } catch (error) {
    await reportSyncSetupMutationFailure(context, "pause sync", error);
    return;
  }
  await syncSetupMutations.whenIdle();
  output.appendLine("[sync] Sync paused from dashboard menu.");
  await refreshSyncUi(context);
}

async function resumeSync(context: vscode.ExtensionContext): Promise<void> {
  let resumed: boolean;
  try {
    resumed = await syncSetupMutations.setEnabled(syncSetupStore(context), true);
  } catch (error) {
    await reportSyncSetupMutationFailure(context, "resume sync", error);
    return;
  }
  await syncSetupMutations.whenIdle();
  if (!resumed) {
    await offerConfigureSync(context, SYNC_SETUP_REQUIRED_MESSAGE);
    return;
  }
  output.appendLine("[sync] Sync resumed from dashboard menu.");
  await refreshSyncUi(context);
}

async function changeSyncFolder(context: vscode.ExtensionContext): Promise<void> {
  const selectedDir = await pickSyncFolder();
  if (!selectedDir) {
    return;
  }
  await selectSyncTaskSettings(context, selectedDir);
}

async function clearSyncSetup(context: vscode.ExtensionContext): Promise<void> {
  const choice = await vscode.window.showWarningMessage(
    "Clear Codex sync setup? This disables sync and forgets the selected folder and tasks. It does not delete any files.",
    { modal: true },
    "Clear Sync Setup",
  );
  if (choice !== "Clear Sync Setup") {
    return;
  }

  try {
    await syncSetupMutations.clear(syncSetupStore(context));
  } catch (error) {
    await reportSyncSetupMutationFailure(context, "clear sync setup", error);
    return;
  }
  await syncSetupMutations.whenIdle();
  output.appendLine("[sync] Sync setup cleared from dashboard menu.");
  await refreshSyncUi(context);
}

async function reportSyncSetupMutationFailure(
  context: vscode.ExtensionContext,
  action: string,
  error: unknown,
): Promise<void> {
  const message = error instanceof Error ? error.message : String(error);
  output.appendLine(`[error] ${message}`);
  void vscode.window.showErrorMessage(`Codex Usage failed to ${action}: ${message}`);
  await syncSetupMutations.whenIdle();
  await refreshSyncUi(context);
}

async function refreshSyncUi(
  context: vscode.ExtensionContext,
  refreshDashboardPanel = true,
): Promise<void> {
  updateStatusItem(readSettings(context));
  resetSyncRuntimeWhenDisabled(context);
  if (panel && refreshDashboardPanel) {
    await refreshDashboard(context, panel);
  }
}

async function pickSyncFolder(): Promise<string | undefined> {
  const selected = await vscode.window.showOpenDialog({
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
    openLabel: "Use Sync Folder",
    title: "Select Codex Sync Folder",
  });
  const folder = selected?.[0]?.fsPath?.trim();
  if (!folder) {
    return undefined;
  }
  return folder;
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
  let settings = readSettings(context);

  if (!hasValidSyncSelection(settings.sync)) {
    await offerConfigureSync(context, SYNC_SETUP_REQUIRED_MESSAGE);
    return;
  }
  if (!settings.sync.enabled) {
    await resumeSync(context);
    settings = readSettings(context);
    if (!settings.sync.enabled) {
      return;
    }
  }

  if (syncRuntime.inFlight) {
    void vscode.window.showInformationMessage(
      "A Codex task transfer is already running. Try again when it finishes.",
    );
    return;
  }

  await runDirectionalSync(context, direction);
}

async function runDirectionalSync(context: vscode.ExtensionContext, direction: SyncDirection): Promise<void> {
  syncRuntime.inFlight = true;
  try {
    const ok = await executeSyncDirection(context, direction);
    if (ok) {
      syncRuntime.lastError = "";
      syncRuntime.lastSyncAt = Date.now();
      setSyncStatus(context, readSettings(context).sync.enabled ? "idle" : "off");
    }
  } finally {
    syncRuntime.inFlight = false;
  }
}

async function executeSyncDirection(context: vscode.ExtensionContext, direction: SyncDirection): Promise<boolean> {
  const settings = readSettings(context);
  if (!hasValidSyncSelection(settings.sync)) {
    await offerConfigureSync(context, SYNC_SETUP_REQUIRED_MESSAGE);
    return false;
  }
  let outcomeStatus: "conflict" | "issue" | undefined;
  try {
    const options = {
      syncDir: settings.sync.dir,
      threadIds: settings.sync.threadIds,
      autoTransitions: settings.projectTransitions.autoDetect,
    };
    const executablePath = await resolveBundledExecutable(context);
    const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
    const completion = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Window,
        title: direction === "pull" ? "Pulling Codex tasks" : "Pushing Codex tasks",
      },
      async () => {
        const args = direction === "pull" ? buildSyncPullArgs(options) : buildSyncPushArgs(options);
        output.appendLine(`> ${executablePath} ${args.join(" ")}`);
        setSyncStatus(context, "scanning");
        return runSyncProcess({
          executablePath,
          args,
          env,
          onProgress: (event) => setSyncStatus(context, event.phase),
          onOutput: (text) => output.append(text),
        });
      },
    );
    if (completion.result.outcome === "conflict") {
      outcomeStatus = "conflict";
      const count = completion.result.counts.conflicts;
      const detail = count > 0 ? `${count} conflict${count === 1 ? "" : "s"}` : "conflicts";
      const message = `Codex sync has ${detail}. Run Codex Usage: Sync Status.`;
      setSyncStatus(context, "conflict", message);
      throw new Error(message);
    }
    if (completion.result.outcome === "issue") {
      outcomeStatus = "issue";
      const firstIssue = completion.result.issues.find((issue) => issue.message.trim())?.message.trim();
      const count = completion.result.counts.issues;
      const message = firstIssue || `Codex sync reported ${count} issue${count === 1 ? "" : "s"}.`;
      setSyncStatus(context, "issue", message);
      throw new Error(message);
    }
    const transferred = direction === "pull" ? completion.result.counts.pulled : completion.result.counts.pushed;
    const oppositeAction = direction === "pull" ? "push" : "pull";
    const pending = completion.result.threads.filter((thread) => thread.action === oppositeAction).length;
    const verb = direction === "pull" ? "Pulled" : "Pushed";
    const pendingText = pending
      ? ` ${pending} selected task${pending === 1 ? "" : "s"} still need${pending === 1 ? "s" : ""} to ${oppositeAction}.`
      : "";
    void vscode.window.showInformationMessage(
      `${verb} ${transferred} task${transferred === 1 ? "" : "s"}.${pendingText}`,
    );
    return true;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    const failureStatus = outcomeStatus ?? (message.toLowerCase().includes("conflict") ? "conflict" : "issue");
    setSyncStatus(context, failureStatus, message);
    void vscode.window.showWarningMessage(`Codex ${direction} failed: ${message}`);
    return false;
  }
}

async function showSyncStatus(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  if (!hasValidSyncSelection(settings.sync)) {
    await offerConfigureSync(context, SYNC_SETUP_REQUIRED_MESSAGE);
    return;
  }
  try {
    const options = {
      syncDir: settings.sync.dir,
      threadIds: settings.sync.threadIds,
      autoTransitions: settings.projectTransitions.autoDetect,
    };
    const executablePath = await resolveBundledExecutable(context);
    const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
    const result = await runCodexUsage(executablePath, buildSyncStatusArgs(options), env);
    const summary = parseSyncStatusSummary(result.stdout);
    output.appendLine(`[sync] ${summary.message}`);
    void vscode.window.showInformationMessage(`Codex sync status: ${summary.message}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(`Codex sync status failed: ${message}`);
  }
}

async function openSyncFolder(context: vscode.ExtensionContext): Promise<void> {
  let settings = readSettings(context);
  if (!settings.sync.dir) {
    await configureSync(context);
    settings = readSettings(context);
  }
  if (!settings.sync.dir) {
    return;
  }
  await fs.mkdir(settings.sync.dir, { recursive: true });
  await vscode.env.openExternal(vscode.Uri.file(settings.sync.dir));
}

async function offerConfigureSync(context: vscode.ExtensionContext, message: string): Promise<void> {
  const choice = await vscode.window.showInformationMessage(message, "Configure Sync");
  if (choice === "Configure Sync") {
    await configureSync(context);
  }
}

async function migrateDeprecatedSyncSettings(context: vscode.ExtensionContext): Promise<void> {
  const config = vscode.workspace.getConfiguration("codexUsage");
  const existingDir = readSyncDirState(context.globalState);
  const legacyDir = config.get<string>("sync.dir", "");
  if (!existingDir && typeof legacyDir === "string" && legacyDir.trim()) {
    await context.globalState.update(SYNC_DIR_STATE_KEY, legacyDir.trim());
  }
}

function readSettings(context: vscode.ExtensionContext | undefined): ExtensionSettings {
  const config = vscode.workspace.getConfiguration("codexUsage");
  const sync = normalizeSyncSettings({
    enabled: config.get<boolean>("sync.enabled", false),
    dir: readSyncDirState(context?.globalState),
    selectionVersion: readSyncSelectionVersionState(context?.globalState),
    threadIds: readSyncThreadIdsState(context?.globalState),
  });
  return {
    range: normalizeRange(config.get<string>("range", "30d")),
    projectKeys: context ? readProjectKeysState(context.globalState) : [],
    theme: normalizeTheme(config.get<string>("theme", "auto")),
    sync,
    projectTransitions: {
      autoDetect: config.get<boolean>("projectTransitions.autoDetect", true),
    },
  };
}

function syncSetupStore(context: vscode.ExtensionContext): AsyncSyncSetupStore {
  const config = vscode.workspace.getConfiguration("codexUsage");
  return {
    async read() {
      const threadIds = context.globalState.get<string[] | undefined>(SYNC_THREAD_IDS_STATE_KEY);
      return {
        folder: context.globalState.get<string | undefined>(SYNC_DIR_STATE_KEY),
        threadIds: threadIds === undefined ? undefined : [...threadIds],
        enabled: config.get<boolean>("sync.enabled", false),
        version: context.globalState.get<number>(SYNC_SELECTION_VERSION_STATE_KEY, 0),
      };
    },
    async writeVersion(value) {
      await context.globalState.update(SYNC_SELECTION_VERSION_STATE_KEY, value);
    },
    async writeFolder(value) {
      await context.globalState.update(SYNC_DIR_STATE_KEY, value);
    },
    async writeThreadIds(value) {
      await context.globalState.update(SYNC_THREAD_IDS_STATE_KEY, value);
    },
    async writeEnabled(value) {
      await config.update("sync.enabled", value, vscode.ConfigurationTarget.Global);
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
    sync: {
      enabled: settings.sync.enabled,
      dir: settings.sync.dir,
      selectionVersion: settings.sync.selectionVersion,
      threadIds: settings.sync.threadIds,
    },
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
  const syncStatus = syncStatusBadge(settings, syncRuntime.status);
  if (syncStatus) {
    statusItem.text += ` ${syncStatus}`;
  }
  const syncText = syncStatusTooltip(settings);
  statusItem.tooltip =
    projectCount > 0
      ? `Open Codex Usage Dashboard. Range: ${settings.range}. Projects: ${projectCount} selected. Theme: ${theme}. ${syncText}`
      : `Open Codex Usage Dashboard. Range: ${settings.range}. Projects: All Projects. Theme: ${theme}. ${syncText}`;
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

function setSyncStatus(context: vscode.ExtensionContext, status: SyncStatusKind, lastError = ""): void {
  syncRuntime.status = status;
  if (lastError) {
    syncRuntime.lastError = lastError;
  }
  updateStatusItem(readSettings(context));
}

function syncStatusBadge(settings: ExtensionSettings, status: SyncStatusKind): string {
  if (!hasValidSyncSelection(settings.sync)) {
    return "Sync: Setup required";
  }
  if (!settings.sync.enabled) {
    return "Sync:Off";
  }
  return `Sync:${syncStatusKindLabel(status === "off" ? "idle" : status)}`;
}

function syncStatusTooltip(settings: ExtensionSettings): string {
  if (!hasValidSyncSelection(settings.sync)) {
    return "Sync: Setup required. Select a folder and at least one Codex task.";
  }
  if (!settings.sync.enabled) {
    return "Sync: disabled.";
  }
  const folder = settings.sync.dir ? "folder selected" : "folder not selected";
  const tasks = `${settings.sync.threadIds.length} task${settings.sync.threadIds.length === 1 ? "" : "s"} selected`;
  const state = `state ${syncStatusKindLabel(syncRuntime.status === "off" ? "idle" : syncRuntime.status)}`;
  const lastSync = syncRuntime.lastSyncAt ? `last transfer ${new Date(syncRuntime.lastSyncAt).toLocaleString()}` : "no completed transfer yet";
  const lastError = syncRuntime.lastError ? `last error: ${syncRuntime.lastError}` : "";
  return ["Sync: manual", folder, tasks, state, lastSync, lastError].filter(Boolean).join(". ") + ".";
}

function resetSyncRuntimeWhenDisabled(context: vscode.ExtensionContext): void {
  const settings = readSettings(context);
  if (settings.sync.enabled) {
    return;
  }
  syncRuntime.lastError = "";
  setSyncStatus(context, "off");
}
