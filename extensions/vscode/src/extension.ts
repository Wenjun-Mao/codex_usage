import * as vscode from "vscode";
import { AgentClient, resolveCodexHome, settingsFilePath } from "./agentClient";
import { AgentSupervisor } from "./agentSupervisor";
import { resolveBundledAgent } from "./bundledAgent";
import { findNativeApp, INSTALL_URL, openNativeApp } from "./nativeApp";
import { decorateUsageReport, renderError, renderLoading, renderStorageReport, WEBVIEW_COMMANDS } from "./reportHtml";
import { captureIntervalChoices, captureScheduleMessage, collectorSetupChoices, projectTransitionChoices, validateCaptureInterval } from "./setupPresentation";
import { StorageClient } from "./storageClient";
import { TaskTransferClient } from "./taskTransferClient";
import type { AgentSettings, AgentStatus, ProjectSummary, RenderedReport, ReportRange, ReportTheme, ReportView, StorageSnapshot } from "./types";
import { usageReportNeedsRefresh, usageStatusFingerprint } from "./usageRefreshPolicy";

const RANGE_VALUES: readonly ReportRange[] = ["today", "yesterday", "7d", "30d", "month", "all"];
const THEME_VALUES: readonly ReportTheme[] = ["auto", "day", "night"];
const PROJECT_STATE_KEY = "selectedProjectKeys";

let panel: vscode.WebviewPanel | undefined;
let output: vscode.OutputChannel;
let statusItem: vscode.StatusBarItem;
let contextRef: vscode.ExtensionContext;
let agentSupervisor: AgentSupervisor;
let taskTransferClient: TaskTransferClient;
let activeView: ReportView = "usage";
let refreshSerial = 0;
let statusTimer: NodeJS.Timeout | undefined;
let renderedUsageFingerprint: string | undefined;
let latestStatus: RenderedReport["status"] | undefined;

const STATUS_REFRESH_INTERVAL_MS = 30_000;

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  contextRef = context;
  output = vscode.window.createOutputChannel("Codex Usage");
  statusItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusItem.command = "codexUsage.openDashboard";
  statusItem.text = "$(pulse) Codex Usage: Connecting";
  statusItem.show();
  agentSupervisor = new AgentSupervisor({
    settingsFile: settingsFilePath(),
    getCodexHome: resolveCodexHome,
    resolveExecutable: () => resolveBundledAgent(context.extensionUri.fsPath),
  });
  const acquireClient = () => acquireAgentClient(true);
  taskTransferClient = new TaskTransferClient(acquireClient, output);
  const storage = new StorageClient(acquireClient, output, refreshVisibleDashboard);
  context.subscriptions.push(
    output,
    statusItem,
    vscode.commands.registerCommand("codexUsage.openDashboard", openDashboard),
    vscode.commands.registerCommand("codexUsage.refreshDashboard", () => refreshVisibleDashboard()),
    vscode.commands.registerCommand("codexUsage.captureNow", captureNow),
    vscode.commands.registerCommand("codexUsage.selectRange", selectRange),
    vscode.commands.registerCommand("codexUsage.selectProjects", selectProjects),
    vscode.commands.registerCommand("codexUsage.selectTheme", selectTheme),
    vscode.commands.registerCommand("codexUsage.showUsageView", () => selectView("usage")),
    vscode.commands.registerCommand("codexUsage.showStorageView", () => selectView("storage")),
    vscode.commands.registerCommand("codexUsage.reviewProjectTransitions", reviewTransitions),
    vscode.commands.registerCommand("codexUsage.openTaskTransfer", () => taskTransferClient.menu()),
    vscode.commands.registerCommand("codexUsage.importTasks", () => taskTransferClient.run("import")),
    vscode.commands.registerCommand("codexUsage.exportTasks", () => taskTransferClient.run("export")),
    vscode.commands.registerCommand("codexUsage.reviewTransferStatus", () => taskTransferClient.run("status")),
    vscode.commands.registerCommand("codexUsage.chooseTransferFolder", () => taskTransferClient.chooseFolder()),
    vscode.commands.registerCommand("codexUsage.analyzeTaskStorage", (treeId?: unknown) => storage.analyze(treeId)),
    vscode.commands.registerCommand("codexUsage.configure", configureCollector),
    vscode.commands.registerCommand("codexUsage.openNativeApp", () => launchNativeApp(true)),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("codexUsage") && panel) void refreshVisibleDashboard();
    }),
  );
  await refreshStatus(false);
  statusTimer = setInterval(() => void refreshStatus(false), STATUS_REFRESH_INTERVAL_MS);
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
    panel.onDidDispose(() => {
      panel = undefined;
      renderedUsageFingerprint = undefined;
    }, null, contextRef.subscriptions);
  } else {
    panel.reveal(vscode.ViewColumn.One);
  }
  await refreshVisibleDashboard();
}

async function refreshVisibleDashboard(
  options: { showLoading?: boolean } = {},
): Promise<void> {
  if (!panel) return;
  const showLoading = options.showLoading ?? true;
  const target = panel;
  const requestId = ++refreshSerial;
  if (showLoading) {
    target.webview.html = renderLoading(activeView === "usage" ? "Loading usage from the local ledger" : "Checking Task Storage metadata", target.webview.cspSource, reportTheme());
  }
  const client = await acquireAgentClient(showLoading);
  if (!client || !panel || panel !== target || requestId !== refreshSerial) return;
  const started = performance.now();
  try {
    const controls = controlState();
    if (activeView === "usage") {
      const query = new URLSearchParams({ range: controls.range, theme: controls.theme });
      for (const key of selectedProjects()) query.append("project_key", key);
      const report = await client.get<RenderedReport>(`/v1/report?${query.toString()}`);
      if (panel === target && requestId === refreshSerial) {
        latestStatus = report.status;
        renderedUsageFingerprint = usageStatusFingerprint(report.status);
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
    if (showLoading && panel === target && requestId === refreshSerial) {
      target.webview.html = renderError(errorMessage(error), target.webview.cspSource, reportTheme());
    } else {
      output.appendLine(`[dashboard] Automatic refresh failed: ${errorMessage(error)}`);
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
    await refreshStatus(false, false);
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
    return await agentSupervisor.acquire();
  } catch (error) {
    output.appendLine(`[collector] ${errorMessage(error)}`);
    if (!interactive) return undefined;
    const selected = await vscode.window.showErrorMessage(
      `Codex Usage could not start its bundled collector: ${errorMessage(error)}`,
      "Set Up Collector",
    );
    if (selected === "Set Up Collector") await configureCollector();
    return undefined;
  }
}

async function configureCollector(): Promise<void> {
  const codexHome = await agentSupervisor.currentCodexHome();
  const selected = await vscode.window.showQuickPick(
    collectorSetupChoices(codexHome),
    { title: "Set Up Codex Usage", placeHolder: "Choose a collector setup action" },
  );
  if (!selected) return;
  if (selected.action === "home") {
    await chooseCodexHome();
    return;
  }
  const client = await acquireAgentClient(false);
  if (!client) {
    void vscode.window.showErrorMessage("Choose a valid CODEX_HOME folder before configuring the collector.");
    return;
  }
  if (selected.action === "interval") await configureCaptureInterval(client);
  else if (selected.action === "transitions") await configureProjectTransitions(client);
  else if (selected.action === "transferFolder") await taskTransferClient.chooseFolder(client);
  else if (selected.action === "migration") await migrateLegacyUsage(client);
  else await captureNow();
}

async function configureProjectTransitions(client: AgentClient): Promise<void> {
  const settings = await client.get<AgentSettings>("/v1/settings");
  const selected = await vscode.window.showQuickPick(projectTransitionChoices(settings.auto_project_transitions), {
    title: "Project Transitions",
    placeHolder: "Choose how Codex Usage groups verified repository switches",
  });
  if (!selected) return;
  await client.post<AgentSettings>("/v1/settings", { auto_project_transitions: selected.enabled });
  void vscode.window.showInformationMessage(
    selected.enabled ? "Project transition detection enabled." : "Project transition detection disabled.",
  );
}

async function chooseCodexHome(): Promise<void> {
  const selected = await vscode.window.showOpenDialog({
    title: "Choose CODEX_HOME",
    openLabel: "Use CODEX_HOME",
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
  });
  const codexHome = selected?.[0]?.fsPath;
  if (!codexHome) return;
  try {
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Starting the Codex Usage collector" },
      () => agentSupervisor.configureCodexHome(codexHome),
    );
    await refreshStatus(false);
    void vscode.window.showInformationMessage(
      "Codex Usage is ready. Scheduled capture runs only while VS Code is open unless the optional native app has installed background capture.",
    );
  } catch (error) {
    void vscode.window.showErrorMessage(`Could not use that CODEX_HOME: ${errorMessage(error)}`);
  }
}

async function configureCaptureInterval(client: AgentClient): Promise<void> {
  const settings = await client.get<AgentSettings>("/v1/settings");
  const selected = await vscode.window.showQuickPick(
    captureIntervalChoices(settings.capture_interval_minutes),
    { title: "Set Capture Interval", placeHolder: "Select how often to capture while VS Code is open" },
  );
  if (!selected) return;
  let interval: number | null;
  if (selected.value === "custom") {
    const entered = await vscode.window.showInputBox({
      title: "Custom Capture Interval",
      prompt: "Enter a whole number of minutes from 1 to 1,440.",
      validateInput: validateCaptureInterval,
    });
    if (entered === undefined) return;
    interval = Number(entered);
  } else {
    interval = selected.value;
  }
  await client.post<AgentSettings>("/v1/settings", {
    capture_interval_minutes: interval,
    onboarding_complete: true,
  });
  await refreshStatus(false);
  void vscode.window.showInformationMessage(captureScheduleMessage(interval));
}

async function migrateLegacyUsage(client: AgentClient): Promise<void> {
  const plan = await client.get<LegacyMigrationPlan>("/v1/migration/plan");
  if (!plan.candidates.length) {
    void vscode.window.showInformationMessage("No compatible legacy Codex Usage caches were found for this CODEX_HOME.");
    return;
  }
  const precedence: Record<string, string> = {};
  for (const conflict of plan.conflicts) {
    const selected = await vscode.window.showQuickPick(
      conflict.sources.map((source) => ({ label: source, source })),
      {
        title: "Choose a migration source",
        placeHolder: `Histories disagree for ${conflict.file_key}. Choose the source to retain.`,
      },
    );
    if (!selected) return;
    precedence[conflict.file_key] = selected.source;
  }
  const result = await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `Migrating ${plan.candidates.length} legacy ${plan.candidates.length === 1 ? "cache" : "caches"}`,
    },
    () => client.post<LegacyMigrationResult>("/v1/migration/run", { precedence }),
  );
  await refreshStatus(false, false);
  await refreshVisibleDashboard();
  void vscode.window.showInformationMessage(
    `Migration complete: ${result.imported_caches} imported, ${result.skipped_caches} already present.`,
  );
}

async function launchNativeApp(interactive: boolean): Promise<void> {
  const appPath = await findNativeApp();
  if (appPath) {
    openNativeApp(appPath);
  } else if (interactive) {
    const selected = await vscode.window.showInformationMessage(
      "The optional Codex Usage native preview is not installed.",
      "View Preview Builds",
    );
    if (selected === "View Preview Builds") {
      await vscode.env.openExternal(vscode.Uri.parse(INSTALL_URL));
    }
  }
}

async function refreshStatus(
  interactive: boolean,
  refreshDashboard = true,
): Promise<void> {
  const client = await acquireAgentClient(interactive);
  if (!client) {
    statusItem.text = "$(tools) Codex Usage: Setup Required";
    statusItem.tooltip = "Run Codex Usage: Set Up Collector. Scheduled capture runs only while VS Code is open unless the optional native app has installed background capture.";
    return;
  }
  try {
    const status = await client.get<AgentStatus>("/v1/status");
    latestStatus = status;
    statusItem.text = status.capture_running ? "$(sync~spin) Codex Usage: Capturing" : `$(pulse) Codex Usage: ${relativeCapture(status.last_capture_at)}`;
    statusItem.tooltip = `${status.coverage.pending_files.toLocaleString()} files pending · ${status.coverage.stale_sources.toLocaleString()} stale sources · Ledger revision ${status.ledger_revision}\nScheduled capture runs only while VS Code is open unless the optional native app has installed background capture.`;
    if (
      panel
      && panel.visible
      && activeView === "usage"
      && refreshDashboard
      && usageReportNeedsRefresh(renderedUsageFingerprint, status)
    ) {
      await refreshVisibleDashboard({ showLoading: false });
    }
  } catch (error) {
    statusItem.text = "$(warning) Codex Usage: Unavailable";
    statusItem.tooltip = errorMessage(error);
  }
}

function controlState(): Pick<Parameters<typeof decorateUsageReport>[1], "range" | "theme" | "projectCount" | "version" | "lastCaptureAt"> {
  return {
    range: reportRange(),
    theme: reportTheme(),
    projectCount: selectedProjects().length,
    version: String(contextRef.extension.packageJSON.version ?? "2.2.0"),
    lastCaptureAt: latestStatus?.last_capture_at ?? "",
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

interface LegacyMigrationPlan {
  candidates: Array<{ path: string; digest: string; source_kind: string }>;
  conflicts: Array<{ file_key: string; sources: string[]; reason: string }>;
  importable_generations: number;
  identical_generations: number;
  superseding_generations: number;
  requires_precedence: boolean;
}

interface LegacyMigrationResult {
  imported_caches: number;
  skipped_caches: number;
  ledger_revision: number;
  ledger_changed: boolean;
  plan: LegacyMigrationPlan;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
