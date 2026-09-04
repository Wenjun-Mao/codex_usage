import { agentRequest, configureBackground } from "./host";
import type { AppState } from "./state";
import type { AgentSettings } from "./types";
import { errorMessage, refreshIcons, setBusy, showToast } from "./ui";

export async function runOnboarding(state: AppState): Promise<void> {
  if (state.settings.native_onboarding_complete) return;
  const dialog = document.createElement("dialog");
  dialog.className = "dialog onboarding-dialog";
  dialog.innerHTML = renderOnboarding(state.settings);
  document.body.append(dialog);
  refreshIcons(dialog);
  dialog.showModal();
  dialog.querySelector<HTMLButtonElement>("#onboarding-start")!.addEventListener("click", async (event) => {
    const button = event.currentTarget as HTMLButtonElement;
    setBusy(button, true, "Preparing");
    try {
      const background = dialog.querySelector<HTMLInputElement>("#onboarding-background")!.checked;
      const updateChecks = dialog.querySelector<HTMLInputElement>("#onboarding-updates")!.checked;
      await configureBackground(background);
      state.settings = await agentRequest<AgentSettings>({
        method: "POST",
        path: "/v1/settings",
        body: {
          background_capture: background,
          daily_update_checks: updateChecks,
          native_onboarding_complete: true,
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
  const existingSetup = settings.onboarding_complete
    ? "Your VS Code collector setup is already available here. Choose only the native app options below."
    : "The collector records Codex usage into a durable local ledger. Configure capture, projects, and Task Transfer from VS Code or Settings after setup.";
  return `<div class="onboarding-layout"><aside><i data-lucide="gauge"></i><span>Codex Usage</span><strong>2.0</strong></aside><section><p class="eyebrow">Native app setup</p><h1>Keep usage history available</h1><p class="onboarding-lead">${existingSetup}</p><div class="onboarding-fields"><label class="onboarding-field toggle-row"><span><strong>Run in the background</strong><small>Continue capturing when this window is closed.</small></span><input id="onboarding-background" type="checkbox" role="switch"></label><label class="onboarding-field toggle-row"><span><strong>Daily update checks</strong><small>Optional; installation always asks first.</small></span><input id="onboarding-updates" type="checkbox" role="switch"></label></div><div class="privacy-note"><i data-lucide="shield-check"></i><span>Local only. The app makes no model or API calls. Network access is limited to optional update checks.</span></div><footer><button class="button-primary" id="onboarding-start"><i data-lucide="arrow-right"></i><span data-button-label>Finish Setup</span></button></footer></section></div>`;
}
