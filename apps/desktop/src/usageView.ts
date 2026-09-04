import { agentRequest } from "./host";
import { openProjectFilter, projectFilterLabel } from "./projectFilter";
import type { AppState } from "./state";
import type { RenderedReport } from "./types";
import { errorMessage, refreshIcons, showToast } from "./ui";
import { usageStatusFingerprint } from "./usageRefreshPolicy";

const ranges = [
  ["today", "Today"],
  ["yesterday", "Yesterday"],
  ["7d", "7 days"],
  ["30d", "30 days"],
  ["month", "This month"],
  ["all", "All time"],
] as const;

export async function renderUsageView(root: HTMLElement, state: AppState): Promise<void> {
  root.innerHTML = `
    <section class="view-heading">
      <div><p class="eyebrow">Usage ledger</p><h1>Token Usage</h1><p>Captured token usage for the selected range and projects.</p></div>
      <div class="view-filters">
        <label class="select-control"><span>Range</span><select id="usage-range">
          ${ranges.map(([value, label]) => `<option value="${value}"${state.range === value ? " selected" : ""}>${label}</option>`).join("")}
        </select></label>
        <button class="button-secondary" id="usage-project-filter" type="button">
          <i data-lucide="folders"></i><span>${projectFilterLabel(state)}</span>
        </button>
        <button class="icon-button" id="usage-reload" type="button" title="Reload usage from ledger" aria-label="Reload usage from ledger"><i data-lucide="refresh-cw"></i></button>
      </div>
    </section>
    <div id="baseline-warning"></div>
    <section class="report-frame-wrap" aria-label="Token usage report">
      <div class="view-loading" id="report-loading"><span class="spinner"></span>Reading the local ledger</div>
      <iframe id="usage-report" title="Codex token usage report" sandbox=""></iframe>
    </section>
    <footer class="view-footer" id="report-diagnostics"></footer>`;
  refreshIcons(root);
  root.querySelector<HTMLSelectElement>("#usage-range")!.addEventListener("change", async (event) => {
    state.range = (event.currentTarget as HTMLSelectElement).value;
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
    const query = new URLSearchParams({ range: state.range, theme: state.settings.theme });
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
