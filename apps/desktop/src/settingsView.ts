import { escapeHtml } from "./format";
import { agentRequest, checkForUpdate, chooseDirectory, configureBackground, installUpdate, resetLocalData, switchCodexHome } from "./host";
import type { AppState, RefreshStatus } from "./state";
import type { AgentSettings, ServiceStatus } from "./types";
import { confirmDialog, errorMessage, refreshIcons, setBusy, showToast } from "./ui";

export async function renderSettingsView(root: HTMLElement, state: AppState, refreshStatus: RefreshStatus): Promise<void> {
  const service = await loadService();
  root.innerHTML = `<section class="view-heading"><div><p class="eyebrow">Application</p><h1>Settings</h1></div></section><form id="settings-form" class="settings-form"><section class="settings-section"><header><h2>Capture</h2><p>Automatic capture runs independently of Codex and this window.</p></header><div class="setting-row"><label for="capture-interval"><strong>Capture interval</strong><span>Counted from the last successful capture.</span></label><select id="capture-interval">${intervalOptions(state.settings.capture_interval_minutes)}</select></div><div class="setting-row" id="custom-interval-row"${isPreset(state.settings.capture_interval_minutes) ? " hidden" : ""}><label for="custom-interval"><strong>Custom interval</strong><span>Between 1 minute and 24 hours.</span></label><div class="number-control"><input id="custom-interval" type="number" min="1" max="1440" value="${state.settings.capture_interval_minutes ?? 15}"><span>minutes</span></div></div><label class="setting-row toggle-row"><span><strong>Background capture</strong><span>${service.supported ? service.installed ? "Registered for this user." : "Stops when Codex Usage closes." : "Unavailable on this platform."}</span></span><input id="background-capture" type="checkbox" role="switch"${state.settings.background_capture && service.installed ? " checked" : ""}${service.supported ? "" : " disabled"}></label>${service.installed ? `<div class="setting-row"><span><strong>Background registration</strong><span>Stop the collector from launching for this user.</span></span><button type="button" class="button-secondary" id="unregister-agent"><i data-lucide="pause-circle"></i><span data-button-label>Unregister</span></button></div>` : ""}</section><section class="settings-section"><header><h2>Data</h2><p>One Codex home is active at a time.</p></header><div class="setting-row path-setting"><span><strong>Codex home</strong><span>${escapeHtml(state.settings.codex_home)}</span></span><button type="button" class="button-secondary" id="choose-codex-home"><i data-lucide="folder-search"></i>Change</button></div><label class="setting-row toggle-row"><span><strong>Project transitions</strong><span>Split usage at verified local repository changes.</span></span><input id="project-transitions" type="checkbox" role="switch"${state.settings.auto_project_transitions ? " checked" : ""}></label><div class="setting-row danger-row"><span><strong>Reset Local Data</strong><span>Remove the ledger and disposable diagnostics. Codex tasks and legacy caches stay untouched.</span></span><button type="button" class="button-danger" id="reset-local-data"><i data-lucide="database-zap"></i><span data-button-label>Reset</span></button></div></section><section class="settings-section"><header><h2>Appearance And Updates</h2></header><div class="setting-row"><label for="theme"><strong>Theme</strong><span>Auto follows the operating system.</span></label><select id="theme"><option value="auto"${state.settings.theme === "auto" ? " selected" : ""}>Auto</option><option value="day"${state.settings.theme === "day" ? " selected" : ""}>Day</option><option value="night"${state.settings.theme === "night" ? " selected" : ""}>Night</option></select></div><label class="setting-row toggle-row"><span><strong>Daily update checks</strong><span>Checks GitHub at most once per day. Installation always requires confirmation.</span></span><input id="update-checks" type="checkbox" role="switch"${state.settings.daily_update_checks ? " checked" : ""}></label><div class="setting-row"><span><strong>Application update</strong><span>Check the signed update channel now.</span></span><button type="button" class="button-secondary" id="check-update"><i data-lucide="download"></i><span data-button-label>Check Now</span></button></div></section><footer class="form-actions"><span id="settings-state" aria-live="polite"></span><button class="button-primary" id="save-settings" type="submit"><i data-lucide="save"></i><span data-button-label>Save Settings</span></button></footer></form>`;
  refreshIcons(root);
  bindSettings(root, state, refreshStatus, service);
}

function bindSettings(root: HTMLElement, state: AppState, refreshStatus: RefreshStatus, service: ServiceStatus): void {
  let nextHome = state.settings.codex_home;
  const interval = root.querySelector<HTMLSelectElement>("#capture-interval")!;
  const customRow = root.querySelector<HTMLElement>("#custom-interval-row")!;
  interval.addEventListener("change", () => { customRow.hidden = interval.value !== "custom"; });
  root.querySelector<HTMLButtonElement>("#unregister-agent")?.addEventListener("click", async (event) => {
    const confirmed = await confirmDialog({ title: "Unregister background collector?", message: "Capture will continue only while Codex Usage is open. Your ledger and settings will be preserved.", confirmLabel: "Unregister" });
    if (!confirmed) return;
    const button = event.currentTarget as HTMLButtonElement;
    setBusy(button, true, "Unregistering");
    try {
      await configureBackground(false);
      state.settings = await agentRequest<AgentSettings>({ method: "GET", path: "/v1/settings" });
      showToast("Background collector unregistered.", "success");
      await renderSettingsView(root, state, refreshStatus);
    } catch (error) {
      showToast(`Could not unregister background capture: ${errorMessage(error)}`, "error");
      setBusy(button, false, "Unregister");
    }
  });
  root.querySelector<HTMLButtonElement>("#reset-local-data")!.addEventListener("click", async (event) => {
    const confirmed = await confirmDialog({ title: "Reset local Codex Usage data?", message: "This removes the durable usage ledger and Task Storage diagnostics, then starts a new baseline. Codex task files and legacy caches are not changed.", confirmLabel: "Reset Data", destructive: true });
    if (!confirmed) return;
    const button = event.currentTarget as HTMLButtonElement;
    setBusy(button, true, "Resetting");
    try {
      await resetLocalData();
      state.projects = [];
      state.selectedProjectKeys = [];
      await refreshStatus();
      showToast("Local data reset. A new baseline capture has started.", "success");
    } catch (error) {
      showToast(`Could not reset local data: ${errorMessage(error)}`, "error");
    } finally {
      setBusy(button, false, "Reset");
    }
  });
  root.querySelector<HTMLButtonElement>("#choose-codex-home")!.addEventListener("click", async () => {
    const selected = await chooseDirectory("Choose a Codex home");
    if (!selected) return;
    nextHome = selected;
    root.querySelector<HTMLElement>(".path-setting span span")!.textContent = selected;
  });
  root.querySelector<HTMLButtonElement>("#check-update")!.addEventListener("click", async (event) => {
    const button = event.currentTarget as HTMLButtonElement;
    setBusy(button, true, "Checking");
    try {
      const update = await checkForUpdate();
      if (!update.available) {
        showToast("Codex Usage is up to date.", "success");
      } else if (await confirmDialog({ title: `Install Codex Usage ${update.version}?`, message: update.body || "The signed update will be downloaded and installed, then the app will restart.", confirmLabel: "Install Update" })) {
        setBusy(button, true, "Installing");
        await installUpdate();
      }
    } catch (error) {
      showToast(`Update check failed: ${errorMessage(error)}`, "error");
    } finally {
      setBusy(button, false, "Check Now");
    }
  });
  root.querySelector<HTMLFormElement>("#settings-form")!.addEventListener("submit", async (event) => {
    event.preventDefault();
    const save = root.querySelector<HTMLButtonElement>("#save-settings")!;
    setBusy(save, true, "Saving");
    try {
      if (nextHome !== state.settings.codex_home) {
        const confirmed = await confirmDialog({ title: "Switch Codex home?", message: "The collector will stop, validate the new home, switch ledgers, repair background registration, and restart.", confirmLabel: "Switch Home" });
        if (!confirmed) return;
        await switchCodexHome(nextHome);
        await refreshStatus();
        state.settings = await agentRequest<AgentSettings>({ method: "GET", path: "/v1/settings" });
      }
      const requestedBackground = root.querySelector<HTMLInputElement>("#background-capture")!.checked;
      const captureInterval = selectedInterval(root);
      const changes: Partial<AgentSettings> = {
        capture_interval_minutes: captureInterval,
        background_capture: requestedBackground,
        daily_update_checks: root.querySelector<HTMLInputElement>("#update-checks")!.checked,
        auto_project_transitions: root.querySelector<HTMLInputElement>("#project-transitions")!.checked,
        theme: root.querySelector<HTMLSelectElement>("#theme")!.value as AgentSettings["theme"],
      };
      if (requestedBackground !== service.installed) {
        await configureBackground(requestedBackground);
      }
      state.settings = await agentRequest<AgentSettings>({ method: "POST", path: "/v1/settings", body: changes as Record<string, unknown> });
      document.documentElement.dataset.theme = state.settings.theme;
      await refreshStatus();
      showToast("Settings saved.", "success");
      await renderSettingsView(root, state, refreshStatus);
    } catch (error) {
      showToast(`Could not save settings: ${errorMessage(error)}`, "error");
    } finally {
      setBusy(save, false, "Save Settings");
    }
  });
}

function selectedInterval(root: HTMLElement): number | null {
  const value = root.querySelector<HTMLSelectElement>("#capture-interval")!.value;
  if (value === "manual") return null;
  if (value === "custom") return Number(root.querySelector<HTMLInputElement>("#custom-interval")!.value);
  return Number(value);
}

function intervalOptions(selected: number | null): string {
  const options: Array<[string, string]> = [["manual", "Manual Only"], ["5", "Every 5 minutes"], ["15", "Every 15 minutes"], ["30", "Every 30 minutes"], ["60", "Every hour"], ["240", "Every 4 hours"], ["1440", "Every 24 hours"], ["custom", "Custom"]];
  const selectedValue = selected === null ? "manual" : isPreset(selected) ? String(selected) : "custom";
  return options.map(([value, label]) => `<option value="${value}"${value === selectedValue ? " selected" : ""}>${label}</option>`).join("");
}

function isPreset(value: number | null): boolean {
  return value === null || [5, 15, 30, 60, 240, 1440].includes(value);
}

async function loadService(): Promise<ServiceStatus> {
  try {
    return await agentRequest<ServiceStatus>({ method: "GET", path: "/v1/service" });
  } catch {
    return { supported: false, installed: false, detail: "Unavailable" };
  }
}
