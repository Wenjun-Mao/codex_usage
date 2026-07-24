import { spawn } from "child_process";
import * as fs from "fs/promises";
import * as path from "path";
import * as vscode from "vscode";
import {
  type ExtensionSettings,
  buildCodexUsageEnv,
  buildReportArgs,
  buildSummaryArgs,
  buildTransitionSuggestArgs,
  bundledExecutablePath,
  cacheDbPath,
  extensionVersionLabel,
  normalizeProjectKeys,
  normalizeRange,
  normalizeTheme,
  PROJECT_KEYS_STATE_KEY,
  parseProjectChoices,
  parseTransitionChoices,
  RANGE_VALUES,
  readProjectKeysState,
  THEME_VALUES,
  WEBVIEW_COMMANDS,
} from "./core";
import {
  injectWebviewControls,
  injectWebviewCsp,
  renderErrorHtml,
  renderLoadingHtml,
} from "./dashboardWebview";
import {
  createTaskTransferVscodePort,
  migrateVscodeTaskTransferState,
} from "./taskTransferVscode";
import { createCodexTaskRegistrar } from "./codexRegistrationVscode";
import { TaskTransferController } from "./taskTransfer";
import { readTaskTransferFolder } from "./taskTransferVscodeState";
import {
  transientStatusLabel,
  type TransferTransientStatus,
} from "./transferPresentation";

let panel: vscode.WebviewPanel | undefined;
let output: vscode.OutputChannel;
let statusItem: vscode.StatusBarItem;
let transientStatus: TransferTransientStatus | undefined;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  output = vscode.window.createOutputChannel("Codex Usage");
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusItem.command = "codexUsage.openDashboard";
  await migrateVscodeTaskTransferState(
    context,
    (message) => output.appendLine(`[task transfer migration] ${message}`),
  );
  updateStatusItem(readSettings(context));
  statusItem.show();

  const registerImportedTasks = createCodexTaskRegistrar({
    extensionVersion: context.extension.packageJSON.version,
  });
  const taskTransferPort = createTaskTransferVscodePort(context, {
    output,
    resolveExecutable: () => resolveBundledExecutable(context),
    processEnv: () => buildCodexUsageEnv(context.globalStorageUri.fsPath),
    runCommand: async (args) => runCodexUsage(
      await resolveBundledExecutable(context),
      args,
      buildCodexUsageEnv(context.globalStorageUri.fsPath),
    ),
    registerImportedTasks,
    refreshUi: async () => {
      updateStatusItem(readSettings(context));
      if (panel) {
        await refreshDashboard(context, panel);
      }
    },
    setTransientStatus: (status) => {
      transientStatus = status;
      updateStatusItem(readSettings(context));
    },
  });
  const taskTransfer = new TaskTransferController(
    taskTransferPort,
    () => readSettings(context).projectTransitions.autoDetect,
  );

  const commands = [
    vscode.commands.registerCommand("codexUsage.openDashboard", () => openOrRefreshDashboard(context)),
    vscode.commands.registerCommand("codexUsage.refreshDashboard", () => openOrRefreshDashboard(context)),
    vscode.commands.registerCommand("codexUsage.openSettings", () =>
      vscode.commands.executeCommand("workbench.action.openSettings", "codexUsage")),
    vscode.commands.registerCommand("codexUsage.selectRange", () => selectRangeSetting(context)),
    vscode.commands.registerCommand("codexUsage.selectProjects", () => selectProjectSettings(context)),
    vscode.commands.registerCommand("codexUsage.selectTheme", () => selectThemeSetting(context)),
    vscode.commands.registerCommand("codexUsage.reviewProjectTransitions", () =>
      reviewProjectTransitions(context)),
    vscode.commands.registerCommand("codexUsage.openSyncMenu", () => taskTransfer.showMenu()),
    vscode.commands.registerCommand("codexUsage.configureSync", () => taskTransfer.chooseFolder()),
    vscode.commands.registerCommand("codexUsage.selectSyncTasks", () => taskTransfer.showMenu()),
    vscode.commands.registerCommand("codexUsage.pullTasks", () => taskTransfer.importTasks()),
    vscode.commands.registerCommand("codexUsage.pushTasks", () => taskTransfer.exportTasks()),
    vscode.commands.registerCommand("codexUsage.syncStatus", () => taskTransfer.reviewStatus()),
    vscode.commands.registerCommand("codexUsage.openSyncFolder", () => taskTransfer.openFolder()),
  ];
  const settingsWatcher = vscode.workspace.onDidChangeConfiguration((event) => {
    if (!event.affectsConfiguration("codexUsage")) {
      return;
    }
    updateStatusItem(readSettings(context));
    if (panel) {
      void refreshDashboard(context, panel);
    }
  });
  context.subscriptions.push(...commands, settingsWatcher, output, statusItem);
}

export function deactivate(): void {
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
  setUsageStatus(loadingKind === "initializing" ? "Codex Usage: Initializing" : "Codex Usage: Loading");

  try {
    const executablePath = await resolveBundledExecutable(context);
    await fs.mkdir(context.globalStorageUri.fsPath, { recursive: true });
    const args = buildReportArgs({
      range: settings.range,
      outputPath: reportPath,
      projectKeys: settings.projectKeys,
      theme: settings.theme,
      projectTransitions: settings.projectTransitions,
    });
    await runCodexUsage(executablePath, args, buildCodexUsageEnv(context.globalStorageUri.fsPath));
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

type UsageLoadingKind = "initializing" | "refreshing";

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
  const message = kind === "initializing"
    ? "Initializing Codex usage cache. This can take a few seconds the first time."
    : "Refreshing Codex usage...";
  targetPanel.webview.html = renderWebviewHtml(
    renderLoadingHtml(message),
    targetPanel.webview,
    readSettings(context),
    extensionVersionLabel(context.extension.packageJSON),
  );
}

function setUsageStatus(label: string): void {
  statusItem.text = label;
  statusItem.tooltip = label;
}

async function selectRangeSetting(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  const selected = await vscode.window.showQuickPick(
    RANGE_VALUES.map((range) => ({
      label: range,
      description: range === settings.range ? "Current" : "",
      range,
      picked: range === settings.range,
    })),
    { placeHolder: "Select Codex usage report range" },
  );
  if (selected && selected.range !== settings.range) {
    await vscode.workspace.getConfiguration("codexUsage").update(
      "range",
      selected.range,
      vscode.ConfigurationTarget.Global,
    );
  }
}

async function selectThemeSetting(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  const selected = await vscode.window.showQuickPick(
    THEME_VALUES.map((theme) => ({
      label: themeLabel(theme),
      description: theme === settings.theme ? "Current" : "",
      theme,
      picked: theme === settings.theme,
    })),
    { placeHolder: "Select Codex usage dashboard theme" },
  );
  if (selected && selected.theme !== settings.theme) {
    await vscode.workspace.getConfiguration("codexUsage").update(
      "theme",
      selected.theme,
      vscode.ConfigurationTarget.Global,
    );
  }
}

async function selectProjectSettings(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  setUsageStatus("Codex Usage: Loading Projects");
  try {
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Window, title: "Loading Codex usage projects" },
      async () => runCodexUsage(
        await resolveBundledExecutable(context),
        buildSummaryArgs({ range: settings.range, projectTransitions: settings.projectTransitions }),
        buildCodexUsageEnv(context.globalStorageUri.fsPath),
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
    const nextProjectKeys = selected.length === 0 || selected.some((item) => item.allProjects)
      ? []
      : normalizeProjectKeys(selected.map((item) => item.projectKey));
    await context.globalState.update(PROJECT_KEYS_STATE_KEY, nextProjectKeys);
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

async function reviewProjectTransitions(context: vscode.ExtensionContext): Promise<void> {
  const settings = readSettings(context);
  try {
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Window, title: "Detecting Codex project transitions" },
      async () => runCodexUsage(
        await resolveBundledExecutable(context),
        buildTransitionSuggestArgs(),
        buildCodexUsageEnv(context.globalStorageUri.fsPath),
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
    const message = selected.length === 0
      ? `No project transitions selected. ${autoDetectText}`
      : `${selected.length} project transition${selected.length === 1 ? "" : "s"} selected for review. ${autoDetectText}`;
    void vscode.window.showInformationMessage(message);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    void vscode.window.showErrorMessage(`Codex Usage failed to review project transitions: ${message}`);
  }
}

function readSettings(context: vscode.ExtensionContext | undefined): ExtensionSettings {
  const config = vscode.workspace.getConfiguration("codexUsage");
  return {
    range: normalizeRange(config.get<string>("range", "30d")),
    projectKeys: context ? readProjectKeysState(context.globalState) : [],
    theme: normalizeTheme(config.get<string>("theme", "auto")),
    taskTransfer: { folder: context ? readTaskTransferFolder(context.globalState) : "" },
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
    const child = spawn(executablePath, args, { shell: false, windowsHide: true, env });
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
      reject(error.code === "ENOENT"
        ? new Error(`Could not start bundled codex-usage executable: ${executablePath}`)
        : error);
    });
    child.on("close", (code) => {
      if (code === 0) {
        resolve({ stdout, stderr });
      } else {
        reject(new Error(stderr.trim() || stdout.trim() || `codex-usage exited with code ${code}`));
      }
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
  return injectWebviewCsp(injectWebviewControls(rawHtml, {
    range: settings.range,
    projectKeys: settings.projectKeys,
    theme: settings.theme,
    taskTransfer: settings.taskTransfer,
    versionLabel,
  }), webview.cspSource);
}

function updateStatusItem(settings: ExtensionSettings): void {
  const projectCount = settings.projectKeys.length;
  const theme = themeLabel(settings.theme);
  const usageText = projectCount > 0
    ? `Codex Usage: ${settings.range} (${projectCount})`
    : `Codex Usage: ${settings.range}`;
  statusItem.text = transientStatus
    ? `${usageText} | ${transientStatusLabel(transientStatus)}`
    : usageText;
  statusItem.tooltip = projectCount > 0
    ? `Open Codex Usage Dashboard. Range: ${settings.range}. Projects: ${projectCount} selected. Theme: ${theme}.`
    : `Open Codex Usage Dashboard. Range: ${settings.range}. Projects: All Projects. Theme: ${theme}.`;
}

function themeLabel(theme: ExtensionSettings["theme"]): string {
  return theme === "day" ? "Day" : theme === "night" ? "Night" : "Auto";
}
