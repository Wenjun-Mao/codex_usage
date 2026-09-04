import { agentRequest } from "./host";
import { escapeHtml } from "./format";
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
      <div><p class="eyebrow">Usage ledger</p><h1>Token Usage</h1></div>
      <div class="view-filters">
        <label class="select-control"><span>Range</span><select id="usage-range">
          ${ranges.map(([value, label]) => `<option value="${value}"${state.range === value ? " selected" : ""}>${label}</option>`).join("")}
        </select></label>
        <button class="button-secondary" id="usage-project-filter" type="button">
          <i data-lucide="folders"></i><span>${projectLabel(state)}</span>
        </button>
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
    openProjectFilter(root, state);
  });
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
    frame.srcdoc = report.html;
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

function openProjectFilter(root: HTMLElement, state: AppState): void {
  const dialog = document.createElement("dialog");
  dialog.className = "dialog project-dialog";
  const selected = new Set(state.selectedProjectKeys);
  dialog.innerHTML = `<form method="dialog"><header><div><p class="eyebrow">Usage filter</p><h2>Choose Projects</h2></div><button class="icon-button" value="cancel" aria-label="Close"><i data-lucide="x"></i></button></header><div class="dialog-list"><label class="check-row"><input type="checkbox" data-all${selected.size === 0 ? " checked" : ""}><span><strong>All projects</strong><small>Include every project in the ledger</small></span></label>${state.projects.map((project) => `<label class="check-row"><input type="checkbox" value="${escapeHtml(project.project_key)}"${selected.has(project.project_key) ? " checked" : ""}><span><strong>${escapeHtml(project.project_label)}</strong><small>${project.task_count.toLocaleString()} tasks</small></span></label>`).join("")}</div><footer><button class="button-quiet" value="cancel">Cancel</button><button class="button-primary" value="apply">Apply</button></footer></form>`;
  const all = dialog.querySelector<HTMLInputElement>("[data-all]")!;
  const projectChecks = [...dialog.querySelectorAll<HTMLInputElement>('input[type="checkbox"]:not([data-all])')];
  all.addEventListener("change", () => {
    if (all.checked) projectChecks.forEach((input) => { input.checked = false; });
  });
  projectChecks.forEach((input) => input.addEventListener("change", () => {
    if (input.checked) all.checked = false;
    if (!projectChecks.some((candidate) => candidate.checked)) all.checked = true;
  }));
  dialog.addEventListener("close", async () => {
    if (dialog.returnValue === "apply") {
      state.selectedProjectKeys = all.checked ? [] : projectChecks.filter((input) => input.checked).map((input) => input.value);
      const button = root.querySelector<HTMLElement>("#usage-project-filter span");
      if (button) button.textContent = projectLabel(state);
      await refreshUsageReport(root, state);
    }
    dialog.remove();
  });
  document.body.append(dialog);
  refreshIcons(dialog);
  dialog.showModal();
}

function projectLabel(state: AppState): string {
  if (state.selectedProjectKeys.length === 0) return "All projects";
  if (state.selectedProjectKeys.length === 1) {
    return state.projects.find((project) => project.project_key === state.selectedProjectKeys[0])?.project_label ?? "1 project";
  }
  return `${state.selectedProjectKeys.length} projects`;
}
