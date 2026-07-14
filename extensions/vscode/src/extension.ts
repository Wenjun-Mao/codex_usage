import * as fs from "fs/promises";
import { existsSync } from "fs";
import * as os from "os";
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
  candidateSessionDirs,
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
  SYNC_SELECTION_VERSION,
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
  selectSessionDirsForWatcher,
  shouldRefreshAfterSyncSetupStep,
  SYNC_AUTO_WARNING_COOLDOWN_MS,
  SYNC_FILE_CHANGE_DEBOUNCE_MS,
  SYNC_FOCUS_COOLDOWN_MS,
  SyncMenuAction,
  SyncStatusKind,
  syncBackoffMs,
  syncFailureRequiresNotification,
  syncMenuQuickPickItems,
  syncStatusKindLabel,
  RANGE_VALUES,
  THEME_VALUES,
  WEBVIEW_COMMANDS,
} from "./core";
import { buildSyncInventoryArgs, parseSyncInventory } from "./syncInventory";
import { buildSyncRunArgs, buildSyncStatusArgs, parseSyncStatusSummary } from "./syncProtocol";
import { runSyncProcess } from "./syncProcess";
import {
  buildTaskPickerItems,
  reduceTaskSelection,
  selectedPickerItemIds,
  type TaskPickerItem,
} from "./syncTaskPicker";

let panel: vscode.WebviewPanel | undefined;
let output: vscode.OutputChannel;
let statusItem: vscode.StatusBarItem;
let syncWatchers: vscode.FileSystemWatcher[] = [];
let syncWatcherDisposables: vscode.Disposable[] = [];
let syncDebounce: NodeJS.Timeout | undefined;

type SyncReason = "manual" | "auto" | "watch";

type SyncSchedulerState = {
  inFlight: boolean;
  pendingReason: SyncReason | undefined;
  status: SyncStatusKind;
  lastAutoSyncAt: number;
  nextAutoSyncAllowedAt: number;
  autoFailureCount: number;
  lastAutoWarningAt: number;
  lastSyncAt: number;
  lastError: string;
};

const syncScheduler: SyncSchedulerState = {
  inFlight: false,
  pendingReason: undefined,
  status: "off",
  lastAutoSyncAt: 0,
  nextAutoSyncAllowedAt: 0,
  autoFailureCount: 0,
  lastAutoWarningAt: 0,
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
  const syncNowCommand = vscode.commands.registerCommand("codexUsage.syncNow", async () => {
    await requestSync(context, "manual");
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
    configureSyncWatcher(context);
    resetSyncSchedulerWhenDisabled(context);
    if (panel) {
      void refreshDashboard(context, panel);
    }
  });
  const focusWatcher = vscode.window.onDidChangeWindowState((state) => {
    if (state.focused) {
      void syncOnFocus(context);
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
    syncNowCommand,
    syncStatusCommand,
    openSyncFolderCommand,
    settingsWatcher,
    focusWatcher,
    output,
    statusItem,
  );
  configureSyncWatcher(context);
  void syncOnFocus(context);
}

export function deactivate() {
  disposeSyncWatchers();
  clearSyncDebounce();
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

    await context.globalState.update(SYNC_DIR_STATE_KEY, syncDir);
    await context.globalState.update(SYNC_THREAD_IDS_STATE_KEY, selectedThreadIds);
    await context.globalState.update(SYNC_SELECTION_VERSION_STATE_KEY, SYNC_SELECTION_VERSION);
    if (options.enableAfterAccept) {
      await vscode.workspace.getConfiguration("codexUsage").update(
        "sync.enabled",
        true,
        vscode.ConfigurationTarget.Global,
      );
    }
    output.appendLine(
      `[sync] Sync configured for ${selectedThreadIds.length} task${selectedThreadIds.length === 1 ? "" : "s"}: ${syncDir}`,
    );
    updateStatusItem(readSettings(context));
    configureSyncWatcher(context);
    if (panel && shouldRefreshAfterSyncSetupStep(options)) {
      await refreshDashboard(context, panel);
    }
    return true;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(`Codex Usage failed to load sync tasks: ${message}`);
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
  if (action === "syncNow") {
    const settings = readSettings(context);
    if (!settings.sync.enabled) {
      await resumeSync(context);
      return;
    }
    await requestSync(context, "manual");
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
  await vscode.workspace.getConfiguration("codexUsage").update("sync.enabled", false, vscode.ConfigurationTarget.Global);
  output.appendLine("[sync] Sync paused from dashboard menu.");
  await refreshSyncUi(context);
}

async function resumeSync(context: vscode.ExtensionContext): Promise<void> {
  if (!hasValidSyncSelection(readSettings(context).sync)) {
    await offerConfigureSync(context, SYNC_SETUP_REQUIRED_MESSAGE);
    return;
  }
  await vscode.workspace.getConfiguration("codexUsage").update("sync.enabled", true, vscode.ConfigurationTarget.Global);
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

  await context.globalState.update(SYNC_SELECTION_VERSION_STATE_KEY, 0);
  await context.globalState.update(SYNC_DIR_STATE_KEY, undefined);
  await context.globalState.update(SYNC_THREAD_IDS_STATE_KEY, undefined);
  await vscode.workspace.getConfiguration("codexUsage").update("sync.enabled", false, vscode.ConfigurationTarget.Global);
  output.appendLine("[sync] Sync setup cleared from dashboard menu.");
  await refreshSyncUi(context);
}

async function refreshSyncUi(context: vscode.ExtensionContext): Promise<void> {
  updateStatusItem(readSettings(context));
  configureSyncWatcher(context);
  resetSyncSchedulerWhenDisabled(context);
  if (panel) {
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

async function requestSync(context: vscode.ExtensionContext, reason: SyncReason): Promise<void> {
  const settings = readSettings(context);
  const now = Date.now();

  if (!hasValidSyncSelection(settings.sync)) {
    if (reason === "manual") {
      await offerConfigureSync(context, SYNC_SETUP_REQUIRED_MESSAGE);
    } else {
      setSyncStatus(context, settings.sync.enabled ? "idle" : "off");
    }
    return;
  }
  if (!settings.sync.enabled) {
    if (reason === "manual") {
      await resumeSync(context);
    } else {
      setSyncStatus(context, "off");
    }
    return;
  }

  if (autoReason(reason)) {
    if (now < syncScheduler.nextAutoSyncAllowedAt) {
      output.appendLine(`[sync] auto sync skipped during backoff until ${new Date(syncScheduler.nextAutoSyncAllowedAt).toLocaleString()}`);
      setSyncStatus(context, "waiting");
      return;
    }
    if (reason === "auto" && now - syncScheduler.lastAutoSyncAt < SYNC_FOCUS_COOLDOWN_MS) {
      output.appendLine("[sync] auto sync skipped during focus cooldown");
      return;
    }
  }

  if (syncScheduler.inFlight) {
    syncScheduler.pendingReason = mergePendingSyncReason(syncScheduler.pendingReason, reason);
    output.appendLine(`[sync] sync already running; queued ${reason} follow-up`);
    if (reason === "manual") {
      void vscode.window.showInformationMessage("Codex sync is already running; another run will start afterward.");
    }
    return;
  }

  await runScheduledSync(context, reason);
}

async function runScheduledSync(context: vscode.ExtensionContext, reason: SyncReason): Promise<void> {
  syncScheduler.inFlight = true;
  syncScheduler.pendingReason = undefined;
  if (autoReason(reason)) {
    syncScheduler.lastAutoSyncAt = Date.now();
  }
  try {
    const ok = await runSyncNow(context, reason);
    if (ok) {
      syncScheduler.autoFailureCount = 0;
      syncScheduler.nextAutoSyncAllowedAt = 0;
      syncScheduler.lastError = "";
      syncScheduler.lastSyncAt = Date.now();
      setSyncStatus(context, readSettings(context).sync.enabled ? "idle" : "off");
    }
  } finally {
    syncScheduler.inFlight = false;
    const pending = syncScheduler.pendingReason;
    syncScheduler.pendingReason = undefined;
    if (pending && syncIsConfigured(readSettings(context))) {
      void requestSync(context, pending);
    }
  }
}

async function runSyncNow(context: vscode.ExtensionContext, reason: SyncReason): Promise<boolean> {
  const settings = readSettings(context);
  if (!hasValidSyncSelection(settings.sync)) {
    if (reason === "manual") {
      await offerConfigureSync(context, SYNC_SETUP_REQUIRED_MESSAGE);
    }
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
        title: "Syncing Codex tasks",
      },
      async () => {
        const args = buildSyncRunArgs(options);
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
    if (reason === "manual") {
      void vscode.window.showInformationMessage("Codex sync complete.");
    } else {
      output.appendLine(`[sync] auto sync complete (${reason})`);
    }
    return true;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    const failureStatus = outcomeStatus ?? (message.toLowerCase().includes("conflict") ? "conflict" : "issue");
    setSyncStatus(context, failureStatus, message);
    if (reason === "manual") {
      void vscode.window.showWarningMessage(`Codex sync failed: ${message}`);
      return false;
    }

    syncScheduler.autoFailureCount += 1;
    const delay = syncBackoffMs(syncScheduler.autoFailureCount);
    syncScheduler.nextAutoSyncAllowedAt = Date.now() + delay;
    output.appendLine(`[sync] auto sync backoff ${Math.round(delay / 1000)}s after ${syncScheduler.autoFailureCount} failure(s)`);

    const shouldNotify = syncFailureRequiresNotification(message);
    const canNotify = Date.now() - syncScheduler.lastAutoWarningAt >= SYNC_AUTO_WARNING_COOLDOWN_MS;
    if (shouldNotify && canNotify && readSettings(context).sync.enabled) {
      syncScheduler.lastAutoWarningAt = Date.now();
      void vscode.window.showWarningMessage(`Codex sync needs attention: ${message}`);
    }
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
    autoPull: config.get<boolean>("sync.autoPull", true),
    autoPush: config.get<boolean>("sync.autoPush", true),
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
  const syncStatus = syncStatusBadge(settings, syncScheduler.status);
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

function syncIsConfigured(settings: ExtensionSettings): boolean {
  return settings.sync.enabled && hasValidSyncSelection(settings.sync);
}

function setSyncStatus(context: vscode.ExtensionContext, status: SyncStatusKind, lastError = ""): void {
  syncScheduler.status = status;
  if (lastError) {
    syncScheduler.lastError = lastError;
  }
  updateStatusItem(readSettings(context));
}

function autoReason(reason: SyncReason): boolean {
  return reason !== "manual";
}

function mergePendingSyncReason(existing: SyncReason | undefined, next: SyncReason): SyncReason {
  if (existing === "manual" || next === "manual") {
    return "manual";
  }
  if (existing === "watch" || next === "watch") {
    return "watch";
  }
  return "auto";
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
  const auto = `auto pull ${settings.sync.autoPull ? "on" : "off"}, auto push ${settings.sync.autoPush ? "on" : "off"}`;
  const state = `state ${syncStatusKindLabel(syncScheduler.status === "off" ? "idle" : syncScheduler.status)}`;
  const lastSync = syncScheduler.lastSyncAt ? `last sync ${new Date(syncScheduler.lastSyncAt).toLocaleString()}` : "no completed sync yet";
  const nextRetry =
    syncScheduler.nextAutoSyncAllowedAt > Date.now()
      ? `next retry after ${new Date(syncScheduler.nextAutoSyncAllowedAt).toLocaleTimeString()}`
      : "";
  const lastError = syncScheduler.lastError ? `last error: ${syncScheduler.lastError}` : "";
  return ["Sync: enabled", folder, tasks, auto, state, lastSync, nextRetry, lastError].filter(Boolean).join(". ") + ".";
}

async function syncOnFocus(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  if (!syncIsConfigured(settings)) {
    return;
  }
  if (!settings.sync.autoPull && !settings.sync.autoPush) {
    return;
  }
  await requestSync(context, "auto");
}

function configureSyncWatcher(context: vscode.ExtensionContext): void {
  disposeSyncWatchers();
  clearSyncDebounce();
  const settings = readSettings(context);
  if (!settings.sync.enabled || !settings.sync.autoPush) {
    return;
  }
  const sessionDirs = selectSessionDirsForWatcher(
    candidateSessionDirs({
      codexHome: process.env.CODEX_HOME,
      userProfile: process.env.USERPROFILE,
      homeDir: os.homedir(),
    }),
    Boolean(process.env.CODEX_HOME?.trim()),
    existsSync,
  );
  const schedule = () => {
    const latestSettings = readSettings(context);
    if (!latestSettings.sync.enabled || !latestSettings.sync.autoPush) {
      clearSyncDebounce();
      setSyncStatus(context, latestSettings.sync.enabled ? "idle" : "off");
      return;
    }
    clearSyncDebounce();
    setSyncStatus(context, "waiting");
    syncDebounce = setTimeout(() => {
      syncDebounce = undefined;
      void requestSync(context, "watch");
    }, SYNC_FILE_CHANGE_DEBOUNCE_MS);
  };
  for (const sessionDir of sessionDirs) {
    const watcher = vscode.workspace.createFileSystemWatcher(new vscode.RelativePattern(sessionDir, "**/*.jsonl"));
    syncWatchers.push(watcher);
    syncWatcherDisposables.push(watcher.onDidCreate(schedule));
    syncWatcherDisposables.push(watcher.onDidChange(schedule));
  }
}

function resetSyncSchedulerWhenDisabled(context: vscode.ExtensionContext): void {
  const settings = readSettings(context);
  if (settings.sync.enabled) {
    return;
  }
  clearSyncDebounce();
  syncScheduler.pendingReason = undefined;
  syncScheduler.nextAutoSyncAllowedAt = 0;
  syncScheduler.autoFailureCount = 0;
  syncScheduler.lastError = "";
  setSyncStatus(context, "off");
}

function clearSyncDebounce(): void {
  if (syncDebounce) {
    clearTimeout(syncDebounce);
    syncDebounce = undefined;
  }
}

function disposeSyncWatchers(): void {
  for (const disposable of syncWatcherDisposables) {
    disposable.dispose();
  }
  for (const watcher of syncWatchers) {
    watcher.dispose();
  }
  syncWatcherDisposables = [];
  syncWatchers = [];
}
