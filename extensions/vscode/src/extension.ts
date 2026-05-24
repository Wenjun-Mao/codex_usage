import * as fs from "fs/promises";
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
  injectWebviewControls,
  injectWebviewCsp,
  normalizeProjectAliases,
  normalizeProjectKeys,
  normalizeRange,
  normalizeSyncSettings,
  normalizeTheme,
  parseProjectChoices,
  parseSyncStatusSummary,
  parseThreadChoices,
  parseTransitionChoices,
  renderErrorHtml,
  renderLoadingHtml,
  RANGE_VALUES,
  THEME_VALUES,
  WEBVIEW_COMMANDS,
} from "./core";

let panel: vscode.WebviewPanel | undefined;
let output: vscode.OutputChannel;
let statusItem: vscode.StatusBarItem;
let syncWatcher: vscode.FileSystemWatcher | undefined;
let syncDebounce: NodeJS.Timeout | undefined;

export function activate(context: vscode.ExtensionContext) {
  output = vscode.window.createOutputChannel("Codex Usage");
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusItem.command = "codexUsage.openDashboard";
  updateStatusItem(readSettings());
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
    await selectRangeSetting();
  });
  const selectProjectsCommand = vscode.commands.registerCommand("codexUsage.selectProjects", async () => {
    await selectProjectSettings(context);
  });
  const selectThemeCommand = vscode.commands.registerCommand("codexUsage.selectTheme", async () => {
    await selectThemeSetting();
  });
  const reviewProjectTransitionsCommand = vscode.commands.registerCommand("codexUsage.reviewProjectTransitions", async () => {
    await reviewProjectTransitions(context);
  });
  const selectSyncThreadsCommand = vscode.commands.registerCommand("codexUsage.selectSyncThreads", async () => {
    await selectSyncThreadSettings(context);
  });
  const syncNowCommand = vscode.commands.registerCommand("codexUsage.syncNow", async () => {
    await syncNow(context, "manual");
  });
  const syncStatusCommand = vscode.commands.registerCommand("codexUsage.syncStatus", async () => {
    await showSyncStatus(context);
  });
  const openSyncFolderCommand = vscode.commands.registerCommand("codexUsage.openSyncFolder", async () => {
    await openSyncFolder();
  });
  const settingsWatcher = vscode.workspace.onDidChangeConfiguration((event) => {
    if (!event.affectsConfiguration("codexUsage")) {
      return;
    }
    updateStatusItem(readSettings());
    configureSyncWatcher(context);
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
  syncWatcher?.dispose();
  if (syncDebounce) {
    clearTimeout(syncDebounce);
  }
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

  panel.webview.html = renderWebviewHtml(renderLoadingHtml(), panel.webview, readSettings());
  await refreshDashboard(context, panel);
}

async function refreshDashboard(context: vscode.ExtensionContext, targetPanel: vscode.WebviewPanel): Promise<void> {
  const settings = readSettings();
  const reportPath = path.join(context.globalStorageUri.fsPath, "report.html");

  try {
    const executablePath = await resolveBundledExecutable(context);
    await fs.mkdir(context.globalStorageUri.fsPath, { recursive: true });
    const env = buildCodexUsageEnv(settings.projectAliases);
    const args = buildReportArgs({
      range: settings.range,
      outputPath: reportPath,
      sessionsDir: settings.sessionsDir,
      subscriptionUsd: settings.subscriptionUsd,
      projectKeys: settings.projectKeys,
      theme: settings.theme,
      projectTransitions: settings.projectTransitions,
    });
    await runCodexUsage(executablePath, args, env);
    const reportHtml = await fs.readFile(reportPath, "utf8");
    targetPanel.webview.html = renderWebviewHtml(reportHtml, targetPanel.webview, settings);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    targetPanel.webview.html = renderWebviewHtml(renderErrorHtml(message), targetPanel.webview, settings);
    void vscode.window.showErrorMessage(`Codex Usage failed: ${message}`);
  }
}

async function selectRangeSetting(): Promise<void> {
  const settings = readSettings();
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

async function selectThemeSetting(): Promise<void> {
  const settings = readSettings();
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
  const settings = readSettings();
  try {
    const executablePath = await resolveBundledExecutable(context);
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
            sessionsDir: settings.sessionsDir,
            subscriptionUsd: settings.subscriptionUsd,
            projectTransitions: settings.projectTransitions,
          }),
          buildCodexUsageEnv(settings.projectAliases),
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
    await vscode.workspace
      .getConfiguration("codexUsage")
      .update("projectKeys", nextProjectKeys, vscode.ConfigurationTarget.Global);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(`Codex Usage failed to load projects: ${message}`);
  }
}

async function selectSyncThreadSettings(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings();
  try {
    const executablePath = await resolveBundledExecutable(context);
    const result = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Window,
        title: "Loading Codex threads",
      },
      () =>
        runCodexUsage(
          executablePath,
          buildThreadsArgs({
            sessionsDir: settings.sessionsDir,
            projectKeys: settings.projectKeys,
            projectTransitions: settings.projectTransitions,
          }),
          buildCodexUsageEnv(settings.projectAliases),
        ),
    );
    const choices = parseThreadChoices(result.stdout, settings.sync.threadIds);
    if (choices.length === 0) {
      void vscode.window.showInformationMessage("No Codex threads were found for the selected dashboard projects.");
      return;
    }
    const selected = await vscode.window.showQuickPick(threadQuickPickItems(choices), {
      canPickMany: true,
      placeHolder: "Select Codex threads to sync",
    });
    if (!selected) {
      return;
    }
    const threadIds = selected.map((item) => item.threadId).filter((threadId): threadId is string => Boolean(threadId));
    await vscode.workspace.getConfiguration("codexUsage").update("sync.threadIds", threadIds, vscode.ConfigurationTarget.Global);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(`Codex Usage failed to load sync threads: ${message}`);
  }
}

async function reviewProjectTransitions(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings();
  try {
    const executablePath = await resolveBundledExecutable(context);
    const result = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Window,
        title: "Detecting Codex project transitions",
      },
      () =>
        runCodexUsage(
          executablePath,
          buildTransitionSuggestArgs({ sessionsDir: settings.sessionsDir }),
          buildCodexUsageEnv(settings.projectAliases),
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

async function syncNow(context: vscode.ExtensionContext, reason: string): Promise<void> {
  const settings = readSettings();
  if (!syncIsConfigured(settings)) {
    return;
  }
  try {
    const executablePath = await resolveBundledExecutable(context);
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Window,
        title: "Syncing Codex threads",
      },
      async () => {
        const env = buildCodexUsageEnv(settings.projectAliases);
        const status = await runCodexUsage(executablePath, syncStatusArgs(settings), env);
        const summary = parseSyncStatusSummary(status.stdout);
        if (summary.conflicts > 0) {
          throw new Error(`Codex sync has ${summary.conflicts} conflict${summary.conflicts === 1 ? "" : "s"}. Run Codex Usage: Sync Status.`);
        }
        await runCodexUsage(executablePath, buildSyncImportArgs(syncOptions(settings)), env);
        await runCodexUsage(executablePath, buildSyncExportArgs(syncOptions(settings)), env);
      },
    );
    void vscode.window.showInformationMessage(`Codex sync complete (${reason}).`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showWarningMessage(`Codex sync skipped: ${message}`);
  }
}

async function showSyncStatus(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings();
  if (!syncIsConfigured(settings)) {
    void vscode.window.showInformationMessage("Codex sync is not configured. Set codexUsage.sync.dir and select sync threads.");
    return;
  }
  try {
    const executablePath = await resolveBundledExecutable(context);
    const result = await runCodexUsage(executablePath, syncStatusArgs(settings), buildCodexUsageEnv(settings.projectAliases));
    const summary = parseSyncStatusSummary(result.stdout);
    output.appendLine(`[sync] ${summary.message}`);
    void vscode.window.showInformationMessage(`Codex sync status: ${summary.message}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(`Codex sync status failed: ${message}`);
  }
}

async function openSyncFolder(): Promise<void> {
  const settings = readSettings();
  if (!settings.sync.dir) {
    void vscode.window.showInformationMessage("Codex sync folder is not configured.");
    return;
  }
  await fs.mkdir(settings.sync.dir, { recursive: true });
  await vscode.env.openExternal(vscode.Uri.file(settings.sync.dir));
}

function readSettings(): ExtensionSettings {
  const config = vscode.workspace.getConfiguration("codexUsage");
  const subscription = config.get<number | null>("subscriptionUsd", null);
  const sync = normalizeSyncSettings({
    enabled: config.get<boolean>("sync.enabled", false),
    dir: config.get<string>("sync.dir", ""),
    threadIds: config.get<string[]>("sync.threadIds", []),
    autoPull: config.get<boolean>("sync.autoPull", true),
    autoPush: config.get<boolean>("sync.autoPush", true),
  });
  return {
    range: normalizeRange(config.get<string>("range", "30d")),
    sessionsDir: config.get<string>("sessionsDir", ""),
    subscriptionUsd: typeof subscription === "number" ? subscription : null,
    projectKeys: normalizeProjectKeys(config.get<string[]>("projectKeys", [])),
    projectAliases: normalizeProjectAliases(config.get<Record<string, string>>("projectAliases", {})),
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

function runCodexUsage(executablePath: string, args: string[], extraEnv: Record<string, string> = {}): Promise<{ stdout: string; stderr: string }> {
  output.appendLine(`> ${executablePath} ${args.join(" ")}`);
  return new Promise((resolve, reject) => {
    const child = spawn(executablePath, args, {
      shell: false,
      windowsHide: true,
      env: { ...process.env, ...extraEnv },
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

type ThreadQuickPickItem = vscode.QuickPickItem & {
  threadId?: string;
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

function threadQuickPickItems(choices: ReturnType<typeof parseThreadChoices>): ThreadQuickPickItem[] {
  return choices.map((choice) => ({
    label: choice.label,
    description: choice.description,
    detail: choice.detail,
    picked: choice.picked,
    threadId: choice.threadId,
  }));
}

function renderWebviewHtml(rawHtml: string, webview: vscode.Webview, settings: ExtensionSettings): string {
  const withControls = injectWebviewControls(rawHtml, {
    range: settings.range,
    projectKeys: settings.projectKeys,
    theme: settings.theme,
  });
  return injectWebviewCsp(withControls, webview.cspSource);
}

function updateStatusItem(settings: ExtensionSettings): void {
  const projectCount = settings.projectKeys.length;
  const syncCount = settings.sync.threadIds.length;
  const theme = themeLabel(settings.theme);
  statusItem.text =
    projectCount > 0
      ? `Codex Usage: ${settings.range} (${projectCount})`
      : `Codex Usage: ${settings.range}`;
  if (settings.sync.enabled && syncCount > 0) {
    statusItem.text += ` Sync:${syncCount}`;
  }
  const syncText = settings.sync.enabled
    ? `Sync: enabled, ${syncCount} thread${syncCount === 1 ? "" : "s"} selected.`
    : "Sync: disabled.";
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
  return settings.sync.enabled && settings.sync.dir.length > 0 && settings.sync.threadIds.length > 0;
}

function syncOptions(settings: ExtensionSettings) {
  return {
    sessionsDir: settings.sessionsDir,
    syncDir: settings.sync.dir,
    threadIds: settings.sync.threadIds,
  };
}

function syncStatusArgs(settings: ExtensionSettings): string[] {
  return buildSyncStatusArgs(syncOptions(settings));
}

async function syncOnFocus(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings();
  if (!syncIsConfigured(settings)) {
    return;
  }
  if (!settings.sync.autoPull && !settings.sync.autoPush) {
    return;
  }
  await syncNow(context, "auto");
}

function configureSyncWatcher(context: vscode.ExtensionContext): void {
  syncWatcher?.dispose();
  syncWatcher = undefined;
  const settings = readSettings();
  if (!settings.sync.enabled || !settings.sync.autoPush || !settings.sessionsDir?.trim()) {
    return;
  }
  syncWatcher = vscode.workspace.createFileSystemWatcher(
    new vscode.RelativePattern(settings.sessionsDir.trim(), "**/*.jsonl"),
  );
  const schedule = () => {
    if (syncDebounce) {
      clearTimeout(syncDebounce);
    }
    syncDebounce = setTimeout(() => {
      void syncNow(context, "watch");
    }, 2000);
  };
  syncWatcher.onDidCreate(schedule, null, context.subscriptions);
  syncWatcher.onDidChange(schedule, null, context.subscriptions);
}
