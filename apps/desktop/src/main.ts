import "./styles.css";
import {
  agentRequest,
  checkForUpdate,
  chooseDirectory,
  codexHomeStatus,
  ensureAgent,
  installUpdate,
  prepareCodexHome,
} from "./host";
import { escapeHtml, formatBytes, formatDate, formatDuration } from "./format";
import { runOnboarding } from "./onboarding";
import { renderSettingsView } from "./settingsView";
import type { AppState } from "./state";
import { renderStorageView } from "./storageView";
import { renderTransferView } from "./transferView";
import type { AgentHealth, AgentSettings, AgentStatus, ProjectSummary, ViewName } from "./types";
import { confirmDialog, errorMessage, refreshIcons, setBusy, showToast } from "./ui";
import { refreshUsageReport, renderUsageView } from "./usageView";
import { usageReportNeedsRefresh } from "./usageRefreshPolicy";

const app = document.querySelector<HTMLElement>("#app")!;
let state: AppState | null = null;
let statusTimer = 0;

const USAGE_AUTO_REFRESH_INTERVAL_MS = 30_000;

void boot();

async function boot(): Promise<void> {
  renderShell();
  bindShell();
  try {
    await prepareInitialCodexHome();
    await ensureAgent();
    const [settings, health, projectPayload] = await Promise.all([
      agentRequest<AgentSettings>({ method: "GET", path: "/v1/settings" }),
      agentRequest<AgentHealth>({ method: "GET", path: "/v1/health" }),
      agentRequest<{ projects: ProjectSummary[] }>({ method: "GET", path: "/v1/projects" }),
    ]);
    state = {
      settings,
      status: health.status,
      projects: projectPayload.projects,
      selectedProjectKeys: [],
      range: "30d",
      view: "usage",
    };
    document.documentElement.dataset.theme = settings.theme;
    renderAgentStatus();
    await runOnboarding(state);
    state.settings = await agentRequest<AgentSettings>({ method: "GET", path: "/v1/settings" });
    await refreshStatus();
    await navigate("usage");
    scheduleStatusRefresh();
    void maybeCheckForUpdate();
  } catch (error) {
    renderFatal(error);
  }
}

async function prepareInitialCodexHome(): Promise<void> {
  const status = await codexHomeStatus();
  if (status.valid) return;
  const selected = await chooseDirectory(
    "Choose a Codex home containing sessions or archived_sessions",
  );
  if (!selected) {
    throw new Error(
      `${status.issue}. Choose a valid Codex home to finish setup.`,
    );
  }
  await prepareCodexHome(selected);
}

function renderShell(): void {
  app.innerHTML = `<div class="app-shell"><aside class="sidebar"><div class="brand"><span class="brand-mark"><i data-lucide="gauge"></i></span><span><strong>Codex Usage</strong><small>Local ledger</small></span></div><nav aria-label="Primary navigation"><button class="nav-item active" data-view="usage"><i data-lucide="chart-no-axes-combined"></i><span>Usage</span></button><button class="nav-item" data-view="storage"><i data-lucide="hard-drive"></i><span>Task Storage</span></button><button class="nav-item" data-view="transfer"><i data-lucide="arrow-left-right"></i><span>Task Transfer</span></button><button class="nav-item" data-view="settings"><i data-lucide="settings-2"></i><span>Settings</span></button></nav><div class="agent-indicator" id="agent-indicator"><span class="status-dot"></span><span><strong>Starting collector</strong><small>Connecting locally</small></span></div></aside><div class="main-shell"><header class="topbar"><div class="capture-summary" id="capture-summary"><span class="spinner"></span><span>Connecting to local collector</span></div><button class="button-capture" id="capture-now" title="Read changed Codex task files into the usage ledger"><i data-lucide="scan-line"></i><span data-button-label>Capture Usage</span></button></header><main id="view-root" tabindex="-1"><div class="view-loading tall"><span class="spinner"></span>Starting Codex Usage</div></main></div></div><div id="toast-region" class="toast-region" aria-live="polite"></div><template id="confirm-dialog-template"><dialog class="dialog confirm-dialog"><div><h2 data-dialog-title></h2><p data-dialog-message></p><footer><button class="button-quiet" data-dialog-cancel>Cancel</button><button class="button-primary" data-dialog-confirm>Confirm</button></footer></div></dialog></template>`;
  refreshIcons(app);
}

function bindShell(): void {
  app.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.view as ViewName)));
  app.querySelector<HTMLButtonElement>("#capture-now")!.addEventListener("click", captureNow);
}

async function navigate(view: ViewName): Promise<void> {
  if (!state) return;
  state.view = view;
  app.querySelectorAll<HTMLElement>("[data-view]").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  const root = app.querySelector<HTMLElement>("#view-root")!;
  root.dataset.view = view;
  root.focus({ preventScroll: true });
  if (view === "usage") await renderUsageView(root, state);
  else if (view === "storage") await renderStorageView(root, state);
  else if (view === "transfer") await renderTransferView(root, state);
  else await renderSettingsView(root, state, refreshStatus);
}

async function captureNow(): Promise<void> {
  if (!state) return;
  const button = app.querySelector<HTMLButtonElement>("#capture-now")!;
  setBusy(button, true, state.status.capture_running ? "Capture Running" : "Capturing");
  try {
    const result = await agentRequest<{ outcome: string; elapsed_seconds: number; status: AgentStatus }>({ method: "POST", path: "/v1/capture", body: {} });
    state.status = { ...state.status, ...result.status, capture_running: false };
    showToast(`Capture completed in ${formatDuration(result.elapsed_seconds)}.`, "success");
    await refreshProjects();
    renderAgentStatus();
    if (state.view === "usage") await navigate("usage");
  } catch (error) {
    showToast(`Capture failed: ${errorMessage(error)}`, "error");
  } finally {
    setBusy(button, false, "Capture Usage");
  }
}

async function refreshStatus(): Promise<void> {
  if (!state) return;
  try {
    const status = await agentRequest<AgentStatus>({ method: "GET", path: "/v1/status" });
    state.status = status;
    renderAgentStatus();
    const root = app.querySelector<HTMLElement>("#view-root");
    if (root?.dataset.view === "usage") {
      const renderedAt = Number(root.dataset.usageRenderedAt || 0);
      if (
        Date.now() - renderedAt >= USAGE_AUTO_REFRESH_INTERVAL_MS
        && usageReportNeedsRefresh(root.dataset.usageStatusFingerprint, status)
      ) {
        await refreshUsageReport(root, state, { showLoading: false });
      }
    }
  } catch (error) {
    const indicator = app.querySelector<HTMLElement>("#agent-indicator");
    if (indicator) {
      indicator.classList.add("offline");
      indicator.querySelector("strong")!.textContent = "Collector unavailable";
      indicator.querySelector("small")!.textContent = errorMessage(error);
    }
  }
}

function renderAgentStatus(): void {
  if (!state) return;
  const { status } = state;
  const indicator = app.querySelector<HTMLElement>("#agent-indicator")!;
  indicator.classList.toggle("warning", status.coverage.stale_sources > 0);
  indicator.classList.remove("offline");
  indicator.querySelector("strong")!.textContent = status.capture_running ? "Capture running" : "Collector active";
  indicator.querySelector("small")!.textContent = state.settings.background_capture ? "Runs in background" : "Runs with this app";
  const summary = app.querySelector<HTMLElement>("#capture-summary")!;
  const next = status.next_capture_seconds === null ? "Manual only" : `Next in ${formatDuration(status.next_capture_seconds)}`;
  const pending = status.coverage.pending_files ? ` · ${status.coverage.pending_files.toLocaleString()} files / ${formatBytes(status.coverage.pending_bytes)} pending` : "";
  const stale = status.coverage.stale_sources ? ` · ${status.coverage.stale_sources.toLocaleString()} stale` : "";
  summary.innerHTML = `<span class="status-dot ${status.capture_running ? "pulse" : ""}"></span><span><strong>${status.capture_running ? "Capturing changes" : `Last capture ${formatDate(status.last_capture_at)}`}</strong><small>${next}${pending}${stale}</small></span>`;
  const button = app.querySelector<HTMLButtonElement>("#capture-now")!;
  button.disabled = status.capture_running;
}

async function refreshProjects(): Promise<void> {
  if (!state) return;
  const payload = await agentRequest<{ projects: ProjectSummary[] }>({ method: "GET", path: "/v1/projects" });
  state.projects = payload.projects;
}

function scheduleStatusRefresh(): void {
  window.clearInterval(statusTimer);
  statusTimer = window.setInterval(() => void refreshStatus(), 15_000);
}

async function maybeCheckForUpdate(): Promise<void> {
  if (!state?.settings.daily_update_checks) return;
  const last = Number(localStorage.getItem("codex-usage-last-update-check") || 0);
  if (Date.now() - last < 86_400_000) return;
  localStorage.setItem("codex-usage-last-update-check", String(Date.now()));
  try {
    const update = await checkForUpdate();
    if (update.available && await confirmDialog({ title: `Codex Usage ${update.version} is available`, message: update.body || "A signed update is ready to install.", confirmLabel: "Install Update" })) {
      await installUpdate();
    }
  } catch (error) {
    showToast(`Automatic update check failed: ${errorMessage(error)}`, "error");
  }
}

function renderFatal(error: unknown): void {
  const root = app.querySelector<HTMLElement>("#view-root")!;
  root.innerHTML = `<div class="empty-state fatal"><i data-lucide="circle-alert"></i><h1>Could not start Codex Usage</h1><p>${escapeHtml(errorMessage(error))}</p><button class="button-primary" id="retry-start"><i data-lucide="refresh-cw"></i>Try Again</button></div>`;
  root.querySelector<HTMLButtonElement>("#retry-start")!.addEventListener("click", () => window.location.reload());
  refreshIcons(root);
}
