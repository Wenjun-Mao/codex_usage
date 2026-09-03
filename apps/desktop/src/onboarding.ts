import { escapeHtml } from "./format";
import { agentRequest, chooseDirectory, configureBackground, switchCodexHome } from "./host";
import type { AppState } from "./state";
import type { AgentSettings, MigrationPlan } from "./types";
import { errorMessage, refreshIcons, setBusy, showToast } from "./ui";

export async function runOnboarding(state: AppState): Promise<void> {
  if (state.settings.onboarding_complete) return;
  const dialog = document.createElement("dialog");
  dialog.className = "dialog onboarding-dialog";
  dialog.innerHTML = renderOnboarding(state.settings);
  document.body.append(dialog);
  refreshIcons(dialog);
  dialog.showModal();
  let selectedHome = state.settings.codex_home;
  dialog.querySelector<HTMLButtonElement>("#onboarding-home")!.addEventListener("click", async () => {
    const path = await chooseDirectory("Choose the Codex home to capture");
    if (!path) return;
    selectedHome = path;
    dialog.querySelector<HTMLElement>("#onboarding-home-path")!.textContent = path;
  });
  dialog.querySelector<HTMLSelectElement>("#onboarding-interval")!.addEventListener("change", (event) => {
    dialog.querySelector<HTMLElement>("#onboarding-custom-row")!.hidden = (event.currentTarget as HTMLSelectElement).value !== "custom";
  });
  dialog.querySelector<HTMLButtonElement>("#onboarding-start")!.addEventListener("click", async (event) => {
    const button = event.currentTarget as HTMLButtonElement;
    setBusy(button, true, "Preparing");
    try {
      const background = dialog.querySelector<HTMLInputElement>("#onboarding-background")!.checked;
      const updateChecks = dialog.querySelector<HTMLInputElement>("#onboarding-updates")!.checked;
      const captureInterval = onboardingInterval(dialog);
      if (selectedHome !== state.settings.codex_home) await switchCodexHome(selectedHome);
      const plan = await agentRequest<MigrationPlan>({ method: "GET", path: "/v1/migration/plan" });
      if (plan.candidates.length) {
        setBusy(button, true, "Importing History");
        const precedence = plan.requires_precedence ? await choosePrecedence(dialog, plan) : {};
        await agentRequest({ method: "POST", path: "/v1/migration/run", body: { precedence } });
      }
      await configureBackground(background);
      state.settings = await agentRequest<AgentSettings>({
        method: "POST",
        path: "/v1/settings",
        body: {
          capture_interval_minutes: captureInterval,
          background_capture: background,
          daily_update_checks: updateChecks,
          onboarding_complete: true,
        },
      });
      dialog.close();
      dialog.remove();
      showToast("Codex Usage is ready. The first baseline will continue in the background.", "success");
    } catch (error) {
      showToast(`Setup could not finish: ${errorMessage(error)}`, "error");
      setBusy(button, false, "Finish Setup");
    }
  });
}

export function renderOnboarding(settings: AgentSettings): string {
  return `<div class="onboarding-layout"><aside><i data-lucide="gauge"></i><span>Codex Usage</span><strong>2.0</strong></aside><section><p class="eyebrow">First run</p><h1>Keep usage history available</h1><p class="onboarding-lead">The collector records Codex usage into a durable local ledger. No task content leaves this computer.</p><div class="onboarding-fields"><div class="onboarding-field"><div><strong>Codex home</strong><span id="onboarding-home-path">${escapeHtml(settings.codex_home)}</span></div><button class="button-secondary" id="onboarding-home"><i data-lucide="folder-search"></i>Choose</button></div><label class="onboarding-field"><span><strong>Capture interval</strong><small>15 minutes is a balanced default.</small></span><select id="onboarding-interval"><option value="manual">Manual Only</option><option value="5">5 minutes</option><option value="15" selected>15 minutes</option><option value="30">30 minutes</option><option value="60">1 hour</option><option value="240">4 hours</option><option value="1440">24 hours</option><option value="custom">Custom</option></select></label><label class="onboarding-field" id="onboarding-custom-row" hidden><span><strong>Custom interval</strong><small>1 to 1,440 minutes.</small></span><input id="onboarding-custom" type="number" min="1" max="1440" value="15"></label><label class="onboarding-field toggle-row"><span><strong>Run in the background</strong><small>Continue capturing when this window is closed.</small></span><input id="onboarding-background" type="checkbox" role="switch"></label><label class="onboarding-field toggle-row"><span><strong>Daily update checks</strong><small>Optional; installation always asks first.</small></span><input id="onboarding-updates" type="checkbox" role="switch"></label></div><div class="privacy-note"><i data-lucide="shield-check"></i><span>Local only. The app makes no model or API calls. Network access is limited to optional update checks.</span></div><footer><button class="button-primary" id="onboarding-start"><i data-lucide="arrow-right"></i><span data-button-label>Finish Setup</span></button></footer></section></div>`;
}

async function choosePrecedence(dialog: HTMLDialogElement, plan: MigrationPlan): Promise<Record<string, string>> {
  const precedence: Record<string, string> = {};
  const panel = dialog.querySelector<HTMLElement>("section")!;
  panel.innerHTML = `<p class="eyebrow">History migration</p><h1>Resolve ${plan.conflicts.length} history conflict${plan.conflicts.length === 1 ? "" : "s"}</h1><p class="onboarding-lead">Choose the cache whose complete task history should be retained. Legacy databases will not be changed.</p><div class="conflict-list">${plan.conflicts.map((conflict, index) => `<label><strong>${escapeHtml(conflict.file_key)}</strong><span>${escapeHtml(conflict.reason)}</span><select data-conflict="${index}">${conflict.sources.map((source) => `<option value="${escapeHtml(source)}">Use ${escapeHtml(source)}</option>`).join("")}</select></label>`).join("")}</div><footer><button class="button-primary" id="resolve-conflicts">Continue</button></footer>`;
  return new Promise((resolve) => {
    panel.querySelector<HTMLButtonElement>("#resolve-conflicts")!.addEventListener("click", () => {
      plan.conflicts.forEach((conflict, index) => {
        precedence[conflict.file_key] = panel.querySelector<HTMLSelectElement>(`[data-conflict="${index}"]`)!.value;
      });
      resolve(precedence);
    }, { once: true });
  });
}

function onboardingInterval(dialog: HTMLDialogElement): number | null {
  const value = dialog.querySelector<HTMLSelectElement>("#onboarding-interval")!.value;
  if (value === "manual") return null;
  if (value === "custom") return Number(dialog.querySelector<HTMLInputElement>("#onboarding-custom")!.value);
  return Number(value);
}
