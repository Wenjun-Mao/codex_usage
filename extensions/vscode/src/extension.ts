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
  buildSyncExportArgs,
  buildSyncImportArgs,
  buildSyncStatusArgs,
  buildThreadsArgs,
  buildTransitionSuggestArgs,
  bundledExecutablePath,
  cacheDbPath,
  candidateSessionDirs,
  extensionVersionLabel,
  injectWebviewControls,
  injectWebviewCsp,
  normalizeProjectKeys,
  normalizeRange,
  normalizeSyncSettings,
  normalizeTheme,
  PROJECT_KEYS_STATE_KEY,
  SYNC_CONVERSATION_MODE_STATE_KEY,
  SYNC_DIR_STATE_KEY,
  SYNC_PROJECT_KEYS_STATE_KEY,
  SYNC_THREAD_IDS_STATE_KEY,
  parseProjectChoices,
  parseSyncProjectChoices,
  readProjectKeysState,
  readSyncConversationModeState,
  readSyncDirState,
  readSyncProjectKeysState,
  readSyncThreadIdsState,
  parseSyncStatusSummary,
  parseThreadChoices,
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
  syncConversationQuickPickItems,
  syncBackoffMs,
  syncFailureRequiresNotification,
  syncMenuQuickPickItems,
  syncProjectQuickPickItems,
  syncStatusKindLabel,
  RANGE_VALUES,
  THEME_VALUES,
  WEBVIEW_COMMANDS,
} from "./core";

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
  const selectSyncProjectsCommand = vscode.commands.registerCommand("codexUsage.selectSyncProjects", async () => {
    await selectSyncProjectSettings(context);
  });
  const selectSyncThreadsCommand = vscode.commands.registerCommand("codexUsage.selectSyncThreads", async () => {
    await selectSyncThreadSettings(context);
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
    selectSyncProjectsCommand,
    selectSyncThreadsCommand,
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

type UsageLoadingKind = "initializing" | "refreshing" | "projects" | "syncProjects" | "syncThreads";

function usageLoadingMessage(kind: UsageLoadingKind): string {
  if (kind === "initializing") {
    return "Initializing Codex usage cache. This can take a few seconds the first time.";
  }
  if (kind === "projects") {
    return "Loading Codex projects...";
  }
  if (kind === "syncProjects") {
    return "Loading sync projects...";
  }
  if (kind === "syncThreads") {
    return "Loading conversations...";
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

async function selectSyncProjectSettings(
  context: vscode.ExtensionContext,
  options: { refreshDashboard?: boolean } = {},
): Promise<boolean> {
  const settings = readSettings(context);
  const selectedProjectKeys = settings.sync.projectKeys.length > 0 ? settings.sync.projectKeys : settings.projectKeys;
  setUsageStatus(context, "Codex Usage: Loading Sync Projects");
  try {
    const executablePath = await resolveBundledExecutable(context);
    const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
    const result = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Window,
        title: "Loading Codex sync projects",
      },
      () =>
        runCodexUsage(
          executablePath,
          buildThreadsArgs({
            projectTransitions: settings.projectTransitions,
          }),
          env,
        ),
    );
    const choices = parseSyncProjectChoices(result.stdout, selectedProjectKeys);
    if (choices.length === 0) {
      void vscode.window.showInformationMessage("No Codex projects were found to sync.");
      return false;
    }

    const selected = await vscode.window.showQuickPick(syncProjectQuickPickItems(choices, selectedProjectKeys), {
      canPickMany: true,
      placeHolder: "Select Codex projects to sync. Disk estimates include all conversations in each project.",
    });
    if (!selected) {
      return false;
    }

    const projectKeys = normalizeProjectKeys(selected.map((item) => item.projectKey));
    await context.globalState.update(SYNC_PROJECT_KEYS_STATE_KEY, projectKeys);
    updateStatusItem(readSettings(context));
    if (panel && shouldRefreshAfterSyncSetupStep(options)) {
      await refreshDashboard(context, panel);
    }
    return true;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(`Codex Usage failed to load sync projects: ${message}`);
    return false;
  } finally {
    updateStatusItem(readSettings(context));
  }
}

async function selectSyncThreadSettings(
  context: vscode.ExtensionContext,
  options: { refreshDashboard?: boolean } = {},
): Promise<boolean> {
  const settings = readSettings(context);
  const projectKeys = settings.sync.projectKeys.length > 0 ? settings.sync.projectKeys : settings.projectKeys;
  setUsageStatus(context, "Codex Usage: Loading Conversations");
  try {
    const executablePath = await resolveBundledExecutable(context);
    const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
    const result = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Window,
        title: "Loading Codex conversations",
      },
      () =>
        runCodexUsage(
          executablePath,
          buildThreadsArgs({
            projectKeys,
            projectTransitions: settings.projectTransitions,
          }),
          env,
        ),
    );
    const choices = parseThreadChoices(result.stdout, settings.sync.threadIds);
    if (choices.length === 0) {
      void vscode.window.showInformationMessage("No Codex conversations were found for the selected sync projects.");
      return false;
    }
    const selected = await vscode.window.showQuickPick(syncConversationQuickPickItems(choices, settings.sync.conversationMode), {
      canPickMany: true,
      placeHolder: "Select Codex conversations to sync, or choose all conversations in selected projects",
    });
    if (!selected) {
      return false;
    }
    if (selected.some((item) => item.allConversations)) {
      await context.globalState.update(SYNC_CONVERSATION_MODE_STATE_KEY, "allInProjects");
      await context.globalState.update(SYNC_THREAD_IDS_STATE_KEY, []);
    } else {
      const threadIds = selected.map((item) => item.threadId).filter((threadId): threadId is string => Boolean(threadId));
      await context.globalState.update(SYNC_CONVERSATION_MODE_STATE_KEY, "selectedConversations");
      await context.globalState.update(SYNC_THREAD_IDS_STATE_KEY, threadIds);
    }
    updateStatusItem(readSettings(context));
    configureSyncWatcher(context);
    if (panel && shouldRefreshAfterSyncSetupStep(options)) {
      await refreshDashboard(context, panel);
    }
    return true;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(`Codex Usage failed to load sync conversations: ${message}`);
    return false;
  } finally {
    updateStatusItem(readSettings(context));
  }
}

async function configureSync(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  let syncDir = settings.sync.dir;
  if (syncDir) {
    const choice = await vscode.window.showQuickPick(
      [
        { label: "Keep Current Folder", description: syncDir, action: "keep" },
        { label: "Choose Another Folder", description: "Pick a different sync folder", action: "choose" },
      ],
      { placeHolder: "Configure Codex sync folder" },
    );
    if (!choice) {
      return;
    }
    if (choice.action === "choose") {
      const selectedDir = await selectSyncFolder(context);
      if (!selectedDir) {
        return;
      }
      syncDir = selectedDir;
    }
  } else {
    const selectedDir = await selectSyncFolder(context);
    if (!selectedDir) {
      return;
    }
    syncDir = selectedDir;
  }

  await vscode.workspace.getConfiguration("codexUsage").update("sync.enabled", true, vscode.ConfigurationTarget.Global);
  output.appendLine(`[sync] Sync folder configured: ${syncDir}`);
  const selectedProjects = await selectSyncProjectSettings(context, { refreshDashboard: false });
  if (!selectedProjects && readSettings(context).sync.projectKeys.length === 0) {
    updateStatusItem(readSettings(context));
    configureSyncWatcher(context);
    if (panel) {
      await refreshDashboard(context, panel);
    }
    return;
  }
  await selectSyncThreadSettings(context, { refreshDashboard: false });
  updateStatusItem(readSettings(context));
  configureSyncWatcher(context);
  if (panel) {
    await refreshDashboard(context, panel);
  }
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
  if (action === "changeProjects") {
    await selectSyncProjectSettings(context);
    return;
  }
  if (action === "changeConversations") {
    await selectSyncThreadSettings(context);
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
  await vscode.workspace.getConfiguration("codexUsage").update("sync.enabled", true, vscode.ConfigurationTarget.Global);
  output.appendLine("[sync] Sync resumed from dashboard menu.");
  await refreshSyncUi(context);
}

async function changeSyncFolder(context: vscode.ExtensionContext): Promise<void> {
  const selectedDir = await selectSyncFolder(context);
  if (!selectedDir) {
    return;
  }
  output.appendLine(`[sync] Sync folder changed: ${selectedDir}`);
  await refreshSyncUi(context);
}

async function clearSyncSetup(context: vscode.ExtensionContext): Promise<void> {
  const choice = await vscode.window.showWarningMessage(
    "Clear Codex sync setup? This disables sync and forgets the selected folder, projects, and conversations. It does not delete any files.",
    { modal: true },
    "Clear Sync Setup",
  );
  if (choice !== "Clear Sync Setup") {
    return;
  }

  await vscode.workspace.getConfiguration("codexUsage").update("sync.enabled", false, vscode.ConfigurationTarget.Global);
  await context.globalState.update(SYNC_DIR_STATE_KEY, undefined);
  await context.globalState.update(SYNC_PROJECT_KEYS_STATE_KEY, undefined);
  await context.globalState.update(SYNC_CONVERSATION_MODE_STATE_KEY, undefined);
  await context.globalState.update(SYNC_THREAD_IDS_STATE_KEY, undefined);
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

async function selectSyncFolder(context: vscode.ExtensionContext): Promise<string | undefined> {
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
  await context.globalState.update(SYNC_DIR_STATE_KEY, folder);
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

  if (!syncIsConfigured(settings)) {
    if (reason === "manual") {
      await offerConfigureSync(context, "Codex sync is not configured.");
    } else {
      setSyncStatus(context, settings.sync.enabled ? "idle" : "off");
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
  try {
    const executablePath = await resolveBundledExecutable(context);
    const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Window,
        title: "Syncing Codex conversations",
      },
      async () => {
        const options = await resolvedSyncOptions(context, settings);
        if (options.threadIds.length === 0) {
          throw new Error("No Codex conversations are selected for sync.");
        }
        setSyncStatus(context, "pulling");
        const status = await runCodexUsage(executablePath, buildSyncStatusArgs(options), env);
        const summary = parseSyncStatusSummary(status.stdout);
        if (summary.conflicts > 0) {
          setSyncStatus(context, "conflict", `${summary.conflicts} conflict${summary.conflicts === 1 ? "" : "s"}`);
          throw new Error(`Codex sync has ${summary.conflicts} conflict${summary.conflicts === 1 ? "" : "s"}. Run Codex Usage: Sync Status.`);
        }
        await runCodexUsage(executablePath, buildSyncImportArgs(options), env);
        setSyncStatus(context, "pushing");
        await runCodexUsage(executablePath, buildSyncExportArgs(options), env);
      },
    );
    if (reason === "manual") {
      void vscode.window.showInformationMessage("Codex sync complete.");
    } else {
      output.appendLine(`[sync] auto sync complete (${reason})`);
    }
    return true;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    setSyncStatus(context, message.toLowerCase().includes("conflict") ? "conflict" : "issue", message);
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
  if (!syncIsConfigured(settings)) {
    await offerConfigureSync(context, "Codex sync is not configured.");
    return;
  }
  try {
    const executablePath = await resolveBundledExecutable(context);
    const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
    const options = await resolvedSyncOptions(context, settings);
    if (options.threadIds.length === 0) {
      await offerConfigureSync(context, "No Codex conversations are selected for sync.");
      return;
    }
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
    const selectedDir = await selectSyncFolder(context);
    if (!selectedDir) {
      return;
    }
    settings = readSettings(context);
    updateStatusItem(settings);
    configureSyncWatcher(context);
    if (panel) {
      await refreshDashboard(context, panel);
    }
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

  const existingThreadIds = readSyncThreadIdsState(context.globalState);
  const legacyThreadIds = normalizeSyncSettings({
    threadIds: config.get<string[]>("sync.threadIds", []),
  }).threadIds;
  if (existingThreadIds.length === 0 && legacyThreadIds.length > 0) {
    await context.globalState.update(SYNC_THREAD_IDS_STATE_KEY, legacyThreadIds);
    await context.globalState.update(SYNC_CONVERSATION_MODE_STATE_KEY, "selectedConversations");
  }
}

function readSettings(context: vscode.ExtensionContext | undefined): ExtensionSettings {
  const config = vscode.workspace.getConfiguration("codexUsage");
  const sync = normalizeSyncSettings({
    enabled: config.get<boolean>("sync.enabled", false),
    dir: readSyncDirState(context?.globalState),
    projectKeys: readSyncProjectKeysState(context?.globalState),
    conversationMode: readSyncConversationModeState(context?.globalState),
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
        "Rebuild the Windows VSIX with `npm run package:vsix:win`.",
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
      projectKeys: settings.sync.projectKeys,
      conversationMode: settings.sync.conversationMode,
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
  if (!settings.sync.enabled || settings.sync.dir.length === 0) {
    return false;
  }
  if (settings.sync.conversationMode === "allInProjects") {
    return settings.sync.projectKeys.length > 0;
  }
  return settings.sync.threadIds.length > 0;
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

async function resolveSyncThreadIds(context: vscode.ExtensionContext, settings: ExtensionSettings): Promise<string[]> {
  if (settings.sync.conversationMode === "selectedConversations") {
    return settings.sync.threadIds;
  }
  if (settings.sync.projectKeys.length === 0) {
    return [];
  }
  const executablePath = await resolveBundledExecutable(context);
  const env = buildCodexUsageEnv(context.globalStorageUri.fsPath);
  const result = await runCodexUsage(
    executablePath,
    buildThreadsArgs({
      projectKeys: settings.sync.projectKeys,
      projectTransitions: settings.projectTransitions,
    }),
    env,
  );
  return parseThreadChoices(result.stdout, []).map((choice) => choice.threadId);
}

async function resolvedSyncOptions(context: vscode.ExtensionContext, settings: ExtensionSettings) {
  return {
    syncDir: settings.sync.dir,
    threadIds: await resolveSyncThreadIds(context, settings),
  };
}

function syncStatusBadge(settings: ExtensionSettings, status: SyncStatusKind): string {
  if (!settings.sync.enabled) {
    return "Sync:Off";
  }
  if (!syncIsConfigured(settings)) {
    return "Sync:Setup";
  }
  return `Sync:${syncStatusKindLabel(status === "off" ? "idle" : status)}`;
}

function syncStatusTooltip(settings: ExtensionSettings): string {
  if (!settings.sync.enabled) {
    return "Sync: disabled.";
  }
  const folder = settings.sync.dir ? "folder selected" : "folder not selected";
  const mode =
    settings.sync.conversationMode === "allInProjects"
      ? `all conversations in ${settings.sync.projectKeys.length} project${settings.sync.projectKeys.length === 1 ? "" : "s"}`
      : `${settings.sync.threadIds.length} conversation${settings.sync.threadIds.length === 1 ? "" : "s"} selected`;
  const auto = `auto pull ${settings.sync.autoPull ? "on" : "off"}, auto push ${settings.sync.autoPush ? "on" : "off"}`;
  const state = `state ${syncStatusKindLabel(syncScheduler.status === "off" ? "idle" : syncScheduler.status)}`;
  const lastSync = syncScheduler.lastSyncAt ? `last sync ${new Date(syncScheduler.lastSyncAt).toLocaleString()}` : "no completed sync yet";
  const nextRetry =
    syncScheduler.nextAutoSyncAllowedAt > Date.now()
      ? `next retry after ${new Date(syncScheduler.nextAutoSyncAllowedAt).toLocaleTimeString()}`
      : "";
  const lastError = syncScheduler.lastError ? `last error: ${syncScheduler.lastError}` : "";
  return ["Sync: enabled", folder, mode, auto, state, lastSync, nextRetry, lastError].filter(Boolean).join(". ") + ".";
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
