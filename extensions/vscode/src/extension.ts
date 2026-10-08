import * as vscode from "vscode";
import * as os from "os";
import * as path from "path";
import { AgentClient, resolveCodexHome, settingsFilePath } from "./agentClient";
import { AgentSupervisor } from "./agentSupervisor";
import { resolveBundledAgent } from "./bundledAgent";
import { decorateUsageReport, renderError, renderLoading, renderStorageReport, WEBVIEW_COMMANDS } from "./reportHtml";
import { collectorSetupChoices, projectTransitionChoices } from "./setupPresentation";
import { chooseCodexHome, configureCaptureInterval } from "./collectorConfiguration";
import { StorageClient } from "./storageClient";
import { TaskTransferClient } from "./taskTransferClient";
import type { AgentActivityExport, AgentSettings, AgentStatus, CustomDateRange, ProjectSummary, RenderedReport, ReportRange, ReportTheme, ReportView, StorageSnapshot } from "./types";
import { usageReportNeedsRefresh, usageStatusFingerprint } from "./usageRefreshPolicy";
import { chooseProjects } from "./projectSelection";
import { selectCustomRange } from "./customRangeSelection";
import { migrateLegacyUsage } from "./legacyMigration";
import { chartQuery, validateSpeedNavigation, type SpeedChartState } from "./speedNavigation";
import type { SpeedNavigation } from "./types";

const RANGE_VALUES: readonly Exclude<ReportRange, "custom">[] = ["today", "yesterday", "7d", "30d", "month", "all"];
const THEME_VALUES: readonly ReportTheme[] = ["auto", "day", "night"];
const PROJECT_STATE_KEY = "selectedProjectKeys";
const CUSTOM_RANGE_STATE_KEY = "customReportRange";

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
let latestStatus: AgentStatus | undefined;
let speedNavigation: SpeedNavigation | undefined;
let speedChartState: SpeedChartState | undefined;
let speedFilterIdentity: string | undefined;

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
    vscode.commands.registerCommand("codexUsage.exportAgentActivityCsv", exportAgentActivityCsv),
    vscode.commands.registerCommand("codexUsage.selectProjects", selectProjects),
    vscode.commands.registerCommand("codexUsage.navigateSpeed", async (args: unknown) => {
      const state = validateSpeedNavigation(args, speedNavigation);
      if (!state) return;
      speedChartState = state;
      await refreshVisibleDashboard({ showLoading: false });
    }),
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
    vscode.commands.registerCommand("codexUsage.handoffLegacyService", handoffLegacyService),
    vscode.workspace.onDidChangeConfiguration((event) => {
      if (event.affectsConfiguration("codexUsage") && panel) void refreshVisibleDashboard();
    }),
  );
  await refreshStatus(false);
  statusTimer = setInterval(() => void refreshStatus(false), STATUS_REFRESH_INTERVAL_MS);
}

export async function deactivate(): Promise<void> {
  if (statusTimer) clearInterval(statusTimer);
  panel = undefined;
  await agentSupervisor?.stopManagedAgent();
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
      const status = latestStatus ?? await client.get<AgentStatus>("/v1/status");
      latestStatus = status;
      if (!(status.capabilities || []).includes("image-generation-accounting") || !(status.capabilities || []).includes("observed-output-speed-v1") || status.speed?.metric_version !== 1) {
        target.webview.html = renderError(
          "Update the Codex Usage collector before loading this report. The current collector does not support matching image accounting and observed output speed; reinstall the matching VSIX package.",
          target.webview.cspSource,
          reportTheme(),
        );
        return;
      }
      const query = reportQuery(controls.theme);
      const identity = reportQuery().toString();
      if (identity !== speedFilterIdentity) {
        speedChartState = undefined;
        speedNavigation = undefined;
        speedFilterIdentity = identity;
      }
      chartQuery(query, speedChartState, speedNavigation?.scope);
      const report = await client.get<RenderedReport>(`/v1/report?${query.toString()}`);
      if (panel === target && requestId === refreshSerial) {
        renderedUsageFingerprint = usageStatusFingerprint(report.status);
        speedNavigation = report.speed_navigation;
        if (speedChartState && speedNavigation) speedChartState.windowStart = speedNavigation.window_start;
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
  const selected = await vscode.window.showQuickPick([
    ...RANGE_VALUES.map((range) => ({ label: rangeLabel(range), range, picked: range === current })),
    { label: "Custom date range…", range: "custom" as const, picked: current === "custom" },
  ], { placeHolder: "Choose a usage range" });
  if (!selected) return;
  if (selected.range === "custom") {
    const client = await acquireAgentClient(true);
    if (!client) return;
    const status = await client.get<AgentStatus>("/v1/status");
    if (!supportsAgentActivity(status)) {
      void vscode.window.showErrorMessage("The current collector is out of date and does not support custom report ranges.");
      return;
    }
    const selectedCustom = await selectCustomRange(customRange());
    if (!selectedCustom) return;
    await contextRef.globalState.update(CUSTOM_RANGE_STATE_KEY, selectedCustom);
  }
  await vscode.workspace.getConfiguration("codexUsage").update("range", selected.range, vscode.ConfigurationTarget.Global);
}


async function exportAgentActivityCsv(): Promise<void> {
  const client = await acquireAgentClient(true);
  if (!client) return;
  const status = await client.get<AgentStatus>("/v1/status");
  if (!supportsAgentActivity(status)) {
    void vscode.window.showErrorMessage("The current collector is out of date and does not support Agent Activity exports.");
    return;
  }
  try {
    const payload = await client.get<AgentActivityExport>(`/v1/agent-activity?${reportQuery().toString()}`);
    const target = await vscode.window.showSaveDialog({
      title: "Export Agent Activity CSV",
      defaultUri: vscode.Uri.file(path.join(os.homedir(), payload.filename)),
      filters: { CSV: ["csv"] },
      saveLabel: "Export",
    });
    if (!target) return;
    await vscode.workspace.fs.writeFile(target, Buffer.from(payload.csv, "utf8"));
    void vscode.window.showInformationMessage(`Exported ${payload.row_count.toLocaleString()} Agent Activity rows.`);
  } catch (error) {
    void vscode.window.showErrorMessage(`Could not export Agent Activity: ${errorMessage(error)}`);
  }
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
  const picked = await chooseProjects(payload.projects, selectedProjects(), async () => {
    const selected = await vscode.window.showQuickPick([
      { label: "All Projects", description: "Includes projects discovered later", mode: "all" as const },
      { label: "Choose Projects", description: "Keep a fixed selection", mode: "subset" as const },
    ], { placeHolder: "Choose project scope" });
    return selected?.mode;
  }, async (choices) => vscode.window.showQuickPick(choices, { canPickMany: true, placeHolder: "Select projects" }));
  if (picked === undefined) return;
  await contextRef.globalState.update(PROJECT_STATE_KEY, picked);
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
    await chooseCodexHome(agentSupervisor, refreshStatus);
    return;
  }
  if (selected.action === "handoff") {
    await handoffLegacyService();
    return;
  }
  const client = await acquireAgentClient(false);
  if (!client) {
    void vscode.window.showErrorMessage("Choose a valid CODEX_HOME folder before configuring the collector.");
    return;
  }
  if (selected.action === "interval") await configureCaptureInterval(client, refreshStatus);
  else if (selected.action === "transitions") await configureProjectTransitions(client);
  else if (selected.action === "transferFolder") await taskTransferClient.chooseFolder(client);
  else if (selected.action === "migration") {
    if (await migrateLegacyUsage(client)) {
      await refreshStatus(false, false);
      await refreshVisibleDashboard();
    }
  }
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



async function handoffLegacyService(): Promise<void> {
  try {
    const status = await agentSupervisor.legacyServiceStatus();
    if (!status.installed) {
      void vscode.window.showInformationMessage("No legacy Codex Usage background service is registered.");
      return;
    }
    if (!status.recognized) {
      throw new Error("The service registration does not match Codex Usage. It was left untouched.");
    }
    const choice = await vscode.window.showWarningMessage(
      "Retire the legacy Codex Usage background service? Scheduled capture will run while VS Code is open and stop when it closes. Quota snapshots missed while closed may not be recoverable. Your ledger and task files will be kept.",
      { modal: true },
      "Retire Service and Continue",
    );
    if (choice !== "Retire Service and Continue") return;
    const result = await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: "Handing capture to VS Code" },
      () => agentSupervisor.handoffLegacyService(),
    );
    await refreshStatus(false);
    void vscode.window.showInformationMessage(
      `VS Code now owns capture for ${result.codexHome}. Ledger revision ${result.ledgerRevision} is available. You can uninstall the old native preview without deleting shared Codex Usage data.`,
    );
  } catch (error) {
    output.appendLine(`Legacy service handoff failed: ${errorMessage(error)}`);
    void vscode.window.showErrorMessage(
      `Codex Usage handoff needs attention: ${errorMessage(error)} Your ledger was not reset. See Codex Usage output for details.`,
    );
  }
}

async function refreshStatus(
  interactive: boolean,
  refreshDashboard = true,
): Promise<void> {
  const client = await acquireAgentClient(interactive);
  if (!client) {
    statusItem.text = "$(tools) Codex Usage: Setup Required";
    statusItem.tooltip = "Run Codex Usage: Set Up Collector. Scheduled capture runs while VS Code is open.";
    return;
  }
  try {
    const status = await client.get<AgentStatus>("/v1/status");
    latestStatus = status;
    statusItem.text = status.capture_running ? "$(sync~spin) Codex Usage: Capturing" : `$(pulse) Codex Usage: ${relativeCapture(status.last_capture_at)}`;
    statusItem.tooltip = `${status.coverage.pending_files.toLocaleString()} files pending · ${status.coverage.stale_sources.toLocaleString()} stale sources · Ledger revision ${status.ledger_revision}\nScheduled capture runs while VS Code is open. Missed quota snapshots may not be recoverable.`;
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
  const selectedRange = reportRange();
  return {
    range: selectedRange === "custom" ? customRangeLabel() : rangeLabel(selectedRange),
    theme: reportTheme(),
    projectCount: selectedProjects().length,
    version: String(contextRef.extension.packageJSON.version),
    lastCaptureAt: latestStatus?.last_capture_at ?? "",
  };
}

function reportRange(): ReportRange {
  const value = vscode.workspace.getConfiguration("codexUsage").get<string>("range", "30d");
  return value === "custom" || RANGE_VALUES.includes(value as Exclude<ReportRange, "custom">)
    ? value as ReportRange
    : "30d";
}

function reportQuery(theme?: ReportTheme): URLSearchParams {
  const range = reportRange();
  const query = new URLSearchParams({ range });
  if (theme) query.set("theme", theme);
  if (range === "custom") {
    const selected = customRange();
    if (!selected) throw new Error("Choose a custom start and end date before loading this report.");
    query.set("start_date", selected.startDate);
    query.set("end_date", selected.endDate);
  }
  for (const key of selectedProjects()) query.append("project_key", key);
  return query;
}

function customRange(): CustomDateRange | undefined {
  const value = contextRef.globalState.get<unknown>(CUSTOM_RANGE_STATE_KEY);
  if (!value || typeof value !== "object") return undefined;
  const range = value as Partial<CustomDateRange>;
  return typeof range.startDate === "string" && typeof range.endDate === "string"
    ? { startDate: range.startDate, endDate: range.endDate }
    : undefined;
}

function supportsAgentActivity(status: AgentStatus): boolean {
  const capabilities = status.capabilities || [];
  return capabilities.includes("custom-report-range") && capabilities.includes("agent-activity");
}



function rangeLabel(range: Exclude<ReportRange, "custom">): string {
  return ({ today: "Today", yesterday: "Yesterday", "7d": "Last 7 days", "30d": "Last 30 days", month: "This month", all: "All time" })[range];
}

function customRangeLabel(): string {
  const selected = customRange();
  return selected ? `${selected.startDate} to ${selected.endDate}` : "Custom date range";
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
