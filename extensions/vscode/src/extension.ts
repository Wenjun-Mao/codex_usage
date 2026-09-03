import * as vscode from "vscode";
import { AgentClient, AgentUnavailableError } from "./agentClient";
import { findNativeApp, INSTALL_URL, openNativeApp } from "./nativeApp";
import { decorateUsageReport, renderError, renderLoading, renderStorageReport, WEBVIEW_COMMANDS } from "./reportHtml";
import { StorageClient } from "./storageClient";
import { TaskTransferClient } from "./taskTransferClient";
import type { AgentStatus, ProjectSummary, RenderedReport, ReportRange, ReportTheme, ReportView, StorageSnapshot } from "./types";

const RANGE_VALUES: readonly ReportRange[] = ["today", "yesterday", "7d", "30d", "month", "all"];
const THEME_VALUES: readonly ReportTheme[] = ["auto", "day", "night"];
const PROJECT_STATE_KEY = "selectedProjectKeys";

let panel: vscode.WebviewPanel | undefined;
let output: vscode.OutputChannel;
let statusItem: vscode.StatusBarItem;
let contextRef: vscode.ExtensionContext;
let activeView: ReportView = "usage";
let refreshSerial = 0;
let statusTimer: NodeJS.Timeout | undefined;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  contextRef = context;
  output = vscode.window.createOutputChannel("Codex Usage");
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusItem.command = "codexUsage.openDashboard";
  statusItem.text = "$(pulse) Codex Usage: Connecting";
  statusItem.show();
  const acquireClient = () => acquireAgentClient(true);
  const taskTransfer = new TaskTransferClient(acquireClient, output);
  const storage = new StorageClient(acquireClient, output, refreshVisibleDashboard);
  context.subscriptions.push(
    output,
    statusItem,
    vscode.commands.registerCommand("codexUsage.openDashboard", openDashboard),
    vscode.commands.registerCommand("codexUsage.refreshDashboard", refreshVisibleDashboard),
    vscode.commands.registerCommand("codexUsage.captureNow", captureNow),
    vscode.commands.registerCommand("codexUsage.selectRange", selectRange),
    vscode.commands.registerCommand("codexUsage.selectProjects", selectProjects),
    vscode.commands.registerCommand("codexUsage.selectTheme", selectTheme),
    vscode.commands.registerCommand("codexUsage.showUsageView", () => selectView("usage")),
    vscode.commands.registerCommand("codexUsage.showStorageView", () => selectView("storage")),
    vscode.commands.registerCommand("codexUsage.reviewProjectTransitions", reviewTransitions),
    vscode.commands.registerCommand("codexUsage.openTaskTransfer", () => taskTransfer.menu()),
    vscode.commands.registerCommand("codexUsage.importTasks", () => taskTransfer.run("import")),
    vscode.commands.registerCommand("codexUsage.exportTasks", () => taskTransfer.run("export")),
    vscode.commands.registerCommand("codexUsage.reviewTransferStatus", () => taskTransfer.run("status")),
    vscode.commands.registerCommand("codexUsage.chooseTransferFolder", () => taskTransfer.chooseFolder()),
    vscode.commands.registerCommand("codexUsage.analyzeTaskStorage", (treeId?: unknown) => storage.analyze(treeId)),
    vscode.commands.registerCommand("codexUsage.openNativeApp", () => launchNativeApp(true)),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("codexUsage") && panel) void refreshVisibleDashboard();
    }),
  );
  await refreshStatus(false);
  statusTimer = setInterval(() => void refreshStatus(false), 60_000);
}

export function deactivate(): void {
  if (statusTimer) clearInterval(statusTimer);
  panel = undefined;
}

async function openDashboard(): Promise<void> {
  if (!panel) {
    panel = vscode.window.createWebviewPanel("codexUsageDashboard", "Codex Usage", vscode.ViewColumn.One, {
      enableScripts: false,
      enableCommandUris: [...WEBVIEW_COMMANDS],
      localResourceRoots: [],
      retainContextWhenHidden: true,
    });
    panel.onDidDispose(() => { panel = undefined; }, null, contextRef.subscriptions);
  } else {
    panel.reveal(vscode.ViewColumn.One);
  }
  await refreshVisibleDashboard();
}

async function refreshVisibleDashboard(): Promise<void> {
  if (!panel) return;
  const target = panel;
  const requestId = ++refreshSerial;
  target.webview.html = renderLoading(activeView === "usage" ? "Loading usage from the local ledger" : "Checking Task Storage metadata", target.webview.cspSource);
  const client = await acquireAgentClient(true);
  if (!client || !panel || panel !== target || requestId !== refreshSerial) return;
  const started = performance.now();
  try {
    const controls = controlState();
    if (activeView === "usage") {
      const query = new URLSearchParams({ range: controls.range, theme: controls.theme });
      for (const key of selectedProjects()) query.append("project_key", key);
      const report = await client.get<RenderedReport>(`/v1/report?${query.toString()}`);
      if (panel === target && requestId === refreshSerial) {
        target.webview.html = decorateUsageReport(report.html, {
          ...controls,
          loadedSeconds: report.elapsed_seconds,
          cacheHit: report.cache_hit,
          view: "usage",
        }, target.webview.cspSource);
      }
    } else {
      const query = new URLSearchParams();
      for (const key of selectedProjects()) query.append("project_key", key);
      const snapshot = await client.get<StorageSnapshot>(`/v1/storage/snapshot${query.size ? `?${query}` : ""}`);
      if (panel === target && requestId === refreshSerial) {
        target.webview.html = renderStorageReport(snapshot, {
          ...controls,
          loadedSeconds: (performance.now() - started) / 1000,
          cacheHit: false,
          view: "storage",
        }, target.webview.cspSource);
      }
    }
  } catch (error) {
    if (panel === target && requestId === refreshSerial) {
      target.webview.html = renderError(errorMessage(error), target.webview.cspSource);
    }
  }
}

async function captureNow(): Promise<void> {
  const client = await acquireAgentClient(true);
  if (!client) return;
  statusItem.text = "$(sync~spin) Codex Usage: Capturing";
  try {
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Capturing Codex usage changes" },
      () => client.post<{ outcome: string; elapsed_seconds: number }>("/v1/capture"),
    );
    if (result.outcome !== "success") throw new Error("The collector reported a failed capture.");
    void vscode.window.showInformationMessage(`Codex usage captured in ${result.elapsed_seconds.toFixed(1)} seconds.`);
    await refreshStatus(false);
    await refreshVisibleDashboard();
  } catch (error) {
    void vscode.window.showErrorMessage(`Codex Usage capture failed: ${errorMessage(error)}`);
    await refreshStatus(false);
  }
}

async function selectRange(): Promise<void> {
  const current = reportRange();
  const selected = await vscode.window.showQuickPick(RANGE_VALUES.map((range) => ({ label: range, range, picked: range === current })), { placeHolder: "Choose a usage range" });
  if (!selected) return;
  await vscode.workspace.getConfiguration("codexUsage").update("range", selected.range, vscode.ConfigurationTarget.Global);
}

async function selectTheme(): Promise<void> {
  const current = reportTheme();
  const selected = await vscode.window.showQuickPick(THEME_VALUES.map((theme) => ({ label: titleCase(theme), theme, picked: theme === current })), { placeHolder: "Choose a report theme" });
  if (!selected) return;
  await vscode.workspace.getConfiguration("codexUsage").update("theme", selected.theme, vscode.ConfigurationTarget.Global);
}

async function selectProjects(): Promise<void> {
  const client = await acquireAgentClient(true);
  if (!client) return;
  const payload = await client.get<{ projects: ProjectSummary[] }>("/v1/projects");
  const current = new Set(selectedProjects());
  const picked = await vscode.window.showQuickPick(payload.projects.map((project) => ({
    label: project.project_label,
    description: `${project.task_count.toLocaleString()} tasks`,
    key: project.project_key,
    picked: current.has(project.project_key),
  })), { canPickMany: true, placeHolder: "Select projects, or clear all for every project" });
  if (!picked) return;
  await contextRef.globalState.update(PROJECT_STATE_KEY, picked.map((item) => item.key));
  await refreshVisibleDashboard();
}

async function reviewTransitions(): Promise<void> {
  const client = await acquireAgentClient(true);
  if (!client) return;
  const payload = await client.get<{ transitions: Array<Record<string, unknown>> }>("/v1/transitions");
  if (!payload.transitions.length) {
    void vscode.window.showInformationMessage("No verified project transitions are recorded.");
    return;
  }
  await vscode.window.showQuickPick(payload.transitions.map((transition) => ({
    label: `${String(transition.source_label ?? transition.source_key)} → ${String(transition.target_label ?? transition.target_key)}`,
    description: String(transition.effective_from ?? ""),
    detail: `Confidence ${String(transition.confidence ?? "")}`,
  })), { title: "Verified Project Transitions", placeHolder: "Usage is split at these local repository switch points" });
}

async function selectView(view: ReportView): Promise<void> {
  activeView = view;
  await refreshVisibleDashboard();
}

async function acquireAgentClient(interactive: boolean): Promise<AgentClient | undefined> {
  try {
    return await AgentClient.discover();
  } catch (error) {
    output.appendLine(`[collector] ${errorMessage(error)}`);
    if (!interactive) return undefined;
    const appPath = await findNativeApp();
    if (appPath) {
      const selected = await vscode.window.showWarningMessage("The Codex Usage collector is not running.", "Open Codex Usage");
      if (selected === "Open Codex Usage") {
        openNativeApp(appPath);
        return waitForAgent();
      }
    } else {
      const selected = await vscode.window.showErrorMessage("Codex Usage 2.0 or later must be installed to use this companion extension.", "Install Codex Usage");
      if (selected === "Install Codex Usage") await vscode.env.openExternal(vscode.Uri.parse(INSTALL_URL));
    }
    return undefined;
  }
}

async function waitForAgent(): Promise<AgentClient | undefined> {
  const deadline = Date.now() + 20_000;
  while (Date.now() < deadline) {
    try {
      return await AgentClient.discover();
    } catch (error) {
      if (!(error instanceof AgentUnavailableError)) throw error;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  void vscode.window.showErrorMessage("Codex Usage opened, but its collector did not become ready.");
  return undefined;
}

async function launchNativeApp(interactive: boolean): Promise<void> {
  const appPath = await findNativeApp();
  if (appPath) {
    openNativeApp(appPath);
  } else if (interactive) {
    const selected = await vscode.window.showInformationMessage("Codex Usage is not installed.", "Download");
    if (selected === "Download") await vscode.env.openExternal(vscode.Uri.parse(INSTALL_URL));
  }
}

async function refreshStatus(interactive: boolean): Promise<void> {
  const client = await acquireAgentClient(interactive);
  if (!client) {
    statusItem.text = "$(circle-slash) Codex Usage: App Required";
    statusItem.tooltip = "Open or install Codex Usage to start its collector.";
    return;
  }
  try {
    const status = await client.get<AgentStatus>("/v1/status");
    statusItem.text = status.capture_running ? "$(sync~spin) Codex Usage: Capturing" : `$(pulse) Codex Usage: ${relativeCapture(status.last_capture_at)}`;
    statusItem.tooltip = `${status.coverage.pending_files.toLocaleString()} files pending · ${status.coverage.stale_sources.toLocaleString()} stale sources · Ledger revision ${status.ledger_revision}`;
  } catch (error) {
    statusItem.text = "$(warning) Codex Usage: Unavailable";
    statusItem.tooltip = errorMessage(error);
  }
}

function controlState(): Pick<Parameters<typeof decorateUsageReport>[1], "range" | "theme" | "projectCount" | "version"> {
  return {
    range: reportRange(),
    theme: reportTheme(),
    projectCount: selectedProjects().length,
    version: String(contextRef.extension.packageJSON.version ?? "2.0.0"),
  };
}

function reportRange(): ReportRange {
  const value = vscode.workspace.getConfiguration("codexUsage").get<string>("range", "30d");
  return RANGE_VALUES.includes(value as ReportRange) ? value as ReportRange : "30d";
}

function reportTheme(): ReportTheme {
  const value = vscode.workspace.getConfiguration("codexUsage").get<string>("theme", "auto");
  return THEME_VALUES.includes(value as ReportTheme) ? value as ReportTheme : "auto";
}

function selectedProjects(): string[] {
  const value = contextRef.globalState.get<unknown>(PROJECT_STATE_KEY, []);
  return Array.isArray(value) ? [...new Set(value.filter((item): item is string => typeof item === "string" && Boolean(item.trim())).map((item) => item.trim()))] : [];
}

function relativeCapture(value: string): string {
  const elapsed = Date.now() - new Date(value).getTime();
  if (!value || !Number.isFinite(elapsed)) return "Not Captured";
  if (elapsed < 60_000) return "Captured Now";
  if (elapsed < 3_600_000) return `Captured ${Math.floor(elapsed / 60_000)}m Ago`;
  return `Captured ${Math.floor(elapsed / 3_600_000)}h Ago`;
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
