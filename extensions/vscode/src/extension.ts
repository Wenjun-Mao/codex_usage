import * as fs from "fs/promises";
import * as path from "path";
import { spawn } from "child_process";
import * as vscode from "vscode";
import {
  ExtensionSettings,
  buildReportArgs,
  buildSummaryArgs,
  bundledExecutablePath,
  injectWebviewControls,
  injectWebviewCsp,
  normalizeProjectKeys,
  normalizeRange,
  parseProjectChoices,
  renderErrorHtml,
  RANGE_VALUES,
  WEBVIEW_COMMANDS,
} from "./core";

let panel: vscode.WebviewPanel | undefined;
let output: vscode.OutputChannel;
let statusItem: vscode.StatusBarItem;

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
  const settingsWatcher = vscode.workspace.onDidChangeConfiguration((event) => {
    if (!event.affectsConfiguration("codexUsage")) {
      return;
    }
    updateStatusItem(readSettings());
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

  panel.webview.html = renderWebviewHtml(renderLoadingHtml(), panel.webview, readSettings());
  await refreshDashboard(context, panel);
}

async function refreshDashboard(context: vscode.ExtensionContext, targetPanel: vscode.WebviewPanel): Promise<void> {
  const settings = readSettings();
  const reportPath = path.join(context.globalStorageUri.fsPath, "report.html");

  try {
    const executablePath = await resolveBundledExecutable(context);
    await fs.mkdir(context.globalStorageUri.fsPath, { recursive: true });
    const args = buildReportArgs({
      range: settings.range,
      outputPath: reportPath,
      sessionsDir: settings.sessionsDir,
      subscriptionUsd: settings.subscriptionUsd,
      projectKeys: settings.projectKeys,
    });
    await runCodexUsage(executablePath, args);
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
          }),
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

function readSettings(): ExtensionSettings {
  const config = vscode.workspace.getConfiguration("codexUsage");
  const subscription = config.get<number | null>("subscriptionUsd", null);
  return {
    range: normalizeRange(config.get<string>("range", "30d")),
    sessionsDir: config.get<string>("sessionsDir", ""),
    subscriptionUsd: typeof subscription === "number" ? subscription : null,
    projectKeys: normalizeProjectKeys(config.get<string[]>("projectKeys", [])),
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

function runCodexUsage(executablePath: string, args: string[]): Promise<{ stdout: string; stderr: string }> {
  output.appendLine(`> ${executablePath} ${args.join(" ")}`);
  return new Promise((resolve, reject) => {
    const child = spawn(executablePath, args, {
      shell: false,
      windowsHide: true,
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

function renderWebviewHtml(rawHtml: string, webview: vscode.Webview, settings: ExtensionSettings): string {
  const withControls = injectWebviewControls(rawHtml, {
    range: settings.range,
    projectKeys: settings.projectKeys,
  });
  return injectWebviewCsp(withControls, webview.cspSource);
}

function updateStatusItem(settings: ExtensionSettings): void {
  const projectCount = settings.projectKeys.length;
  statusItem.text = projectCount > 0 ? `Codex Usage: ${settings.range} (${projectCount})` : `Codex Usage: ${settings.range}`;
  statusItem.tooltip =
    projectCount > 0
      ? `Open Codex Usage Dashboard. Range: ${settings.range}. Projects: ${projectCount} selected.`
      : `Open Codex Usage Dashboard. Range: ${settings.range}. Projects: All Projects.`;
}

function renderLoadingHtml(): string {
  return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, sans-serif; margin: 24px; color: #667085; }
  </style>
</head>
<body>
  Generating Codex usage dashboard...
</body>
</html>`;
}
