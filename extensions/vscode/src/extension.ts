import * as fs from "fs/promises";
import * as path from "path";
import { spawn } from "child_process";
import * as vscode from "vscode";
import {
  ExtensionSettings,
  buildReportArgs,
  inferProjectRoot,
  injectWebviewCsp,
  normalizeRange,
  renderErrorHtml,
} from "./core";

let panel: vscode.WebviewPanel | undefined;
let output: vscode.OutputChannel;
let statusItem: vscode.StatusBarItem;

export function activate(context: vscode.ExtensionContext) {
  output = vscode.window.createOutputChannel("Codex Usage");
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusItem.text = "Codex Usage";
  statusItem.tooltip = "Open Codex Usage Dashboard";
  statusItem.command = "codexUsage.openDashboard";
  statusItem.show();

  const openDashboard = vscode.commands.registerCommand("codexUsage.openDashboard", async () => {
    await openOrRefreshDashboard(context);
  });
  const refreshDashboard = vscode.commands.registerCommand("codexUsage.refreshDashboard", async () => {
    await openOrRefreshDashboard(context);
  });
  const openSettings = vscode.commands.registerCommand("codexUsage.openSettings", async () => {
    await vscode.commands.executeCommand("workbench.action.openSettings", "codexUsage");
  });

  context.subscriptions.push(openDashboard, refreshDashboard, openSettings, output, statusItem);
}

export function deactivate() {
  panel = undefined;
}

async function openOrRefreshDashboard(context: vscode.ExtensionContext): Promise<void> {
  if (!panel) {
    panel = vscode.window.createWebviewPanel("codexUsageDashboard", "Codex Usage", vscode.ViewColumn.One, {
      enableScripts: false,
      localResourceRoots: [],
      retainContextWhenHidden: true,
    });
    panel.onDidDispose(() => {
      panel = undefined;
    }, null, context.subscriptions);
  } else {
    panel.reveal(vscode.ViewColumn.One);
  }

  panel.webview.html = injectWebviewCsp(renderLoadingHtml(), panel.webview.cspSource);
  await refreshDashboard(context, panel);
}

async function refreshDashboard(context: vscode.ExtensionContext, targetPanel: vscode.WebviewPanel): Promise<void> {
  const settings = readSettings();
  const projectRoot = inferProjectRoot(context.extensionUri.fsPath, settings.projectRoot);
  const reportPath = path.join(context.globalStorageUri.fsPath, "report.html");

  try {
    await fs.mkdir(context.globalStorageUri.fsPath, { recursive: true });
    const args = buildReportArgs({
      range: settings.range,
      outputPath: reportPath,
      sessionsDir: settings.sessionsDir,
      subscriptionUsd: settings.subscriptionUsd,
    });
    await runUv(projectRoot, args);
    const reportHtml = await fs.readFile(reportPath, "utf8");
    targetPanel.webview.html = injectWebviewCsp(reportHtml, targetPanel.webview.cspSource);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    output.appendLine(`[error] ${message}`);
    targetPanel.webview.html = injectWebviewCsp(renderErrorHtml(message), targetPanel.webview.cspSource);
    void vscode.window.showErrorMessage(`Codex Usage failed: ${message}`);
  }
}

function readSettings(): ExtensionSettings {
  const config = vscode.workspace.getConfiguration("codexUsage");
  const subscription = config.get<number | null>("subscriptionUsd", null);
  return {
    range: normalizeRange(config.get<string>("range", "30d")),
    sessionsDir: config.get<string>("sessionsDir", ""),
    subscriptionUsd: typeof subscription === "number" ? subscription : null,
    projectRoot: config.get<string>("projectRoot", ""),
  };
}

function runUv(cwd: string, args: string[]): Promise<void> {
  output.appendLine(`> uv ${args.join(" ")}`);
  output.appendLine(`cwd: ${cwd}`);
  return new Promise((resolve, reject) => {
    const child = spawn("uv", args, {
      cwd,
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
        reject(new Error("Could not find `uv` on PATH. Install uv or launch VS Code from a shell where uv is available."));
        return;
      }
      reject(error);
    });
    child.on("close", (code) => {
      if (code === 0) {
        resolve();
        return;
      }
      const details = stderr.trim() || stdout.trim() || `uv exited with code ${code}`;
      reject(new Error(details));
    });
  });
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
