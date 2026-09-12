import { agentRequest, saveTextFile } from "./host";
import { openProjectFilter, projectFilterLabel } from "./projectFilter";
import type { AppState, CustomDateRange } from "./state";
import type { AgentActivityExport, RenderedReport } from "./types";
import { errorMessage, refreshIcons, setBusy, showToast } from "./ui";
import { usageStatusFingerprint } from "./usageRefreshPolicy";

const ranges = [
  ["today", "Today"],
  ["yesterday", "Yesterday"],
  ["7d", "7 days"],
  ["30d", "30 days"],
  ["month", "This month"],
  ["all", "All time"],
] as const;

const CUSTOM_RANGE_STORAGE_KEY = "codex-usage-custom-report-range";

export function loadStoredCustomRange(): CustomDateRange | null {
  try {
    const value = JSON.parse(localStorage.getItem(CUSTOM_RANGE_STORAGE_KEY) || "null") as unknown;
    if (typeof value === "object" && value !== null
      && typeof (value as CustomDateRange).startDate === "string"
      && typeof (value as CustomDateRange).endDate === "string") {
      return value as CustomDateRange;
    }
  } catch {
    // A malformed local preference should not block access to the ledger.
  }
  return null;
}

export async function renderUsageView(root: HTMLElement, state: AppState): Promise<void> {
  root.innerHTML = `
    <section class="view-heading">
      <div><p class="eyebrow">Usage ledger</p><h1>Token Usage</h1><p>Captured token usage for the selected range and projects.</p></div>
      <div class="view-filters">
        <label class="select-control"><span>Range</span><select id="usage-range">
          ${ranges.map(([value, label]) => `<option value="${value}"${state.range === value ? " selected" : ""}>${label}</option>`).join("")}
          <option value="custom"${state.range === "custom" ? " selected" : ""}>Custom date range…</option>
        </select></label>
        <button class="button-secondary" id="usage-project-filter" type="button">
          <i data-lucide="folders"></i><span>${projectFilterLabel(state)}</span>
        </button>
        <button class="button-secondary" id="export-agent-activity" type="button"><i data-lucide="download"></i><span>Export Agent Activity CSV</span></button>
        <button class="icon-button" id="usage-reload" type="button" title="Reload usage from ledger" aria-label="Reload usage from ledger"><i data-lucide="refresh-cw"></i></button>
      </div>
    </section>
    <div id="baseline-warning"></div>
    <section class="report-frame-wrap" aria-label="Token usage report">
      <div class="view-loading" id="report-loading"><span class="spinner"></span>Reading the local ledger</div>
      <iframe id="usage-report" title="Codex token usage report" sandbox=""></iframe>
    </section>
    <footer class="view-footer" id="report-diagnostics"></footer>
    <dialog class="dialog custom-range-dialog" id="custom-range-dialog"><form method="dialog" id="custom-range-form"><header><div><h2>Custom date range</h2><p>Select inclusive local calendar dates.</p></div></header><div class="custom-range-fields"><label>Start date<input id="custom-range-start" type="date" required></label><label>End date<input id="custom-range-end" type="date" required></label><p id="custom-range-error" class="field-error" role="alert" hidden></p></div><footer><button class="button-quiet" value="cancel" type="button" id="custom-range-cancel">Cancel</button><button class="button-primary" type="submit">Apply range</button></footer></form></dialog>`;
  refreshIcons(root);
  root.querySelector<HTMLSelectElement>("#usage-range")!.addEventListener("change", async (event) => {
    const range = (event.currentTarget as HTMLSelectElement).value;
    if (range === "custom") {
      if (!hasCapabilities(state)) {
        showToast("This collector is out of date and does not support custom report ranges.", "error");
        (event.currentTarget as HTMLSelectElement).value = state.range;
        return;
      }
      openCustomRangeDialog(root, state);
      return;
    }
    state.range = range;
    await refreshUsageReport(root, state);
  });
  root.querySelector<HTMLButtonElement>("#usage-project-filter")!.addEventListener("click", () => {
    openProjectFilter(state, async () => {
      const button = root.querySelector<HTMLElement>("#usage-project-filter span");
      if (button) button.textContent = projectFilterLabel(state);
      await refreshUsageReport(root, state);
    });
  });
  root.querySelector<HTMLButtonElement>("#usage-reload")!.addEventListener("click", () => refreshUsageReport(root, state));
  root.querySelector<HTMLButtonElement>("#export-agent-activity")!.addEventListener("click", () => void exportAgentActivity(root, state));
  bindCustomRangeDialog(root, state);
  if (!supportsImageAccounting(state)) {
    root.querySelector<HTMLElement>("#report-loading")!.hidden = true;
    root.querySelector<HTMLIFrameElement>("#usage-report")!.hidden = true;
    root.querySelector<HTMLElement>("#baseline-warning")!.innerHTML = `
      <div class="notice warning" role="alert"><strong>Update the Codex Usage collector.</strong>
      This version cannot provide image-generation accounting. Update from Settings or reinstall the matching app or extension package before loading this report.</div>`;
    root.querySelector<HTMLElement>("#report-diagnostics")!.textContent = "Usage report blocked until the collector is updated.";
    return;
  }
  await refreshUsageReport(root, state);
}

export async function refreshUsageReport(
  root: HTMLElement,
  state: AppState,
  options: { showLoading?: boolean } = {},
): Promise<void> {
  const loading = root.querySelector<HTMLElement>("#report-loading");
  const frame = root.querySelector<HTMLIFrameElement>("#usage-report");
  const diagnostics = root.querySelector<HTMLElement>("#report-diagnostics");
  if (!loading || !frame || !diagnostics) return;
  const showLoading = options.showLoading ?? true;
  if (showLoading) {
    loading.hidden = false;
    frame.hidden = true;
  }
  try {
    const query = reportQuery(state, true);
    for (const key of state.selectedProjectKeys) query.append("project_key", key);
    const report = await agentRequest<RenderedReport>({ method: "GET", path: `/v1/report?${query}` });
    frame.srcdoc = decorateNativeUsageReport(report.html);
    frame.hidden = false;
    root.dataset.usageStatusFingerprint = usageStatusFingerprint(report.status);
    root.dataset.usageRenderedAt = String(Date.now());
    const cacheLabel = report.cache_hit ? "render cache" : "ledger query";
    diagnostics.textContent = `Loaded in ${report.elapsed_seconds.toFixed(2)} seconds from ${cacheLabel} · Ledger revision ${report.ledger_revision}`;
    renderCoverage(root, report.status.coverage);
  } catch (error) {
    if (showLoading) {
      frame.srcdoc = "";
      showToast(`Could not load usage: ${errorMessage(error)}`, "error");
      diagnostics.textContent = "Usage report unavailable.";
    }
  } finally {
    if (showLoading) loading.hidden = true;
  }
}

function bindCustomRangeDialog(root: HTMLElement, state: AppState): void {
  const dialog = root.querySelector<HTMLDialogElement>("#custom-range-dialog")!;
  const form = root.querySelector<HTMLFormElement>("#custom-range-form")!;
  root.querySelector<HTMLButtonElement>("#custom-range-cancel")!.addEventListener("click", () => dialog.close());
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const start = root.querySelector<HTMLInputElement>("#custom-range-start")!.value;
    const end = root.querySelector<HTMLInputElement>("#custom-range-end")!.value;
    const error = root.querySelector<HTMLElement>("#custom-range-error")!;
    if (!start || !end || start > end) {
      error.textContent = "Choose a start date on or before the end date.";
      error.hidden = false;
      return;
    }
    if (end > localDate(new Date())) {
      error.textContent = "Custom ranges cannot include future dates.";
      error.hidden = false;
      return;
    }
    state.customRange = { startDate: start, endDate: end };
    localStorage.setItem(CUSTOM_RANGE_STORAGE_KEY, JSON.stringify(state.customRange));
    state.range = "custom";
    dialog.close();
    await refreshUsageReport(root, state);
  });
}

function openCustomRangeDialog(root: HTMLElement, state: AppState): void {
  const dialog = root.querySelector<HTMLDialogElement>("#custom-range-dialog")!;
  const defaults = state.customRange || sevenDayDefault();
  const today = localDate(new Date());
  const start = root.querySelector<HTMLInputElement>("#custom-range-start")!;
  const end = root.querySelector<HTMLInputElement>("#custom-range-end")!;
  const error = root.querySelector<HTMLElement>("#custom-range-error")!;
  start.value = defaults.startDate;
  start.max = today;
  end.value = defaults.endDate;
  end.max = today;
  error.hidden = true;
  dialog.showModal();
}

async function exportAgentActivity(root: HTMLElement, state: AppState): Promise<void> {
  if (!hasCapabilities(state)) {
    showToast("This collector is out of date and does not support Agent Activity exports.", "error");
    return;
  }
  const button = root.querySelector<HTMLButtonElement>("#export-agent-activity")!;
  setBusy(button, true, "Exporting…");
  try {
    const query = reportQuery(state, false);
    const payload = await agentRequest<AgentActivityExport>({ method: "GET", path: `/v1/agent-activity?${query}` });
    const saved = await saveTextFile("Export Agent Activity CSV", payload.filename, payload.csv);
    if (saved) showToast(`Exported ${payload.row_count.toLocaleString()} agent-day rows.`, "success");
  } catch (error) {
    showToast(`Could not export Agent Activity: ${errorMessage(error)}`, "error");
  } finally {
    setBusy(button, false, "Export Agent Activity CSV");
  }
}

function reportQuery(state: AppState, includeTheme: boolean): URLSearchParams {
  const query = new URLSearchParams({ range: state.range });
  if (includeTheme) query.set("theme", state.settings.theme);
  if (state.range === "custom" && state.customRange) {
    query.set("start_date", state.customRange.startDate);
    query.set("end_date", state.customRange.endDate);
  }
  for (const key of state.selectedProjectKeys) query.append("project_key", key);
  return query;
}

function hasCapabilities(state: AppState): boolean {
  const capabilities = state.status.capabilities || [];
  return capabilities.includes("custom-report-range") && capabilities.includes("agent-activity");
}

function supportsImageAccounting(state: AppState): boolean {
  return (state.status.capabilities || []).includes("image-generation-accounting");
}

function sevenDayDefault(): CustomDateRange {
  const end = new Date();
  const start = new Date(end);
  start.setDate(start.getDate() - 6);
  return { startDate: localDate(start), endDate: localDate(end) };
}

function localDate(value: Date): string {
  const offset = value.getTimezoneOffset() * 60_000;
  return new Date(value.getTime() - offset).toISOString().slice(0, 10);
}

function decorateNativeUsageReport(html: string): string {
  return html
    .replace(/<html([^>]*)>/i, '<html$1 data-codex-host="native">')
    .replace(
      /<head([^>]*)>/i,
      '<head$1><style>html[data-codex-host="native"] main.report-shell{max-width:none;padding:0}</style>',
    );
}

function renderCoverage(root: HTMLElement, coverage: RenderedReport["status"]["coverage"]): void {
  const warning = root.querySelector<HTMLElement>("#baseline-warning");
  if (!warning) return;
  if (coverage.complete) {
    warning.replaceChildren();
    return;
  }
  const percentage = Math.max(0, Math.min(100, coverage.fraction * 100));
  warning.innerHTML = `<div class="inline-notice warning" role="status"><i data-lucide="database"></i><div><strong>Baseline ${percentage.toFixed(1)}% complete</strong><span>Current totals are partial. ${coverage.pending_files.toLocaleString()} source files remain.</span></div><progress max="100" value="${percentage}"></progress></div>`;
  refreshIcons(warning);
}
