import { escapeHtml, formatBytes } from "./format";
import { agentRequest } from "./host";
import { openProjectFilter, projectFilterLabel } from "./projectFilter";
import type { AppState } from "./state";
import type { StorageSnapshot, StorageTree } from "./types";
import { errorMessage, refreshIcons, showToast } from "./ui";

interface AnalysisJob {
  operation_id: string;
  state: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: Record<string, unknown>;
  result: Record<string, unknown>;
  error: string;
}

export async function renderStorageView(root: HTMLElement, state: AppState): Promise<void> {
  root.innerHTML = `<section class="view-heading"><div><p class="eyebrow">Local corpus</p><h1>Task Storage</h1><p>Read-only inventory and amplification diagnostics. Analysis runs only when requested.</p></div><div class="view-filters"><button class="button-secondary" id="storage-project-filter" type="button"><i data-lucide="folders"></i><span>${projectFilterLabel(state)}</span></button><button class="icon-button" id="storage-refresh" title="Reload storage inventory" aria-label="Reload storage inventory"><i data-lucide="refresh-cw"></i></button></div></section><div class="view-loading" id="storage-loading"><span class="spinner"></span>Checking task storage metadata</div><div id="storage-content"></div>`;
  refreshIcons(root);
  root.querySelector<HTMLButtonElement>("#storage-refresh")!.addEventListener("click", () => loadStorage(root, state));
  root.querySelector<HTMLButtonElement>("#storage-project-filter")!.addEventListener("click", () => {
    openProjectFilter(state, async () => {
      const button = root.querySelector<HTMLElement>("#storage-project-filter span");
      if (button) button.textContent = projectFilterLabel(state);
      await loadStorage(root, state);
    });
  });
  await loadStorage(root, state);
}

async function loadStorage(root: HTMLElement, state: AppState): Promise<void> {
  const loading = root.querySelector<HTMLElement>("#storage-loading")!;
  const content = root.querySelector<HTMLElement>("#storage-content")!;
  loading.hidden = false;
  try {
    const query = new URLSearchParams();
    for (const key of state.selectedProjectKeys) query.append("project_key", key);
    const suffix = query.size ? `?${query}` : "";
    const snapshot = await agentRequest<StorageSnapshot>({ method: "GET", path: `/v1/storage/snapshot${suffix}` });
    content.innerHTML = renderSnapshot(snapshot);
    bindAnalysis(content, root, state);
    refreshIcons(content);
  } catch (error) {
    content.innerHTML = `<div class="empty-state"><i data-lucide="hard-drive"></i><h2>Storage inventory unavailable</h2><p>${escapeHtml(errorMessage(error))}</p></div>`;
    refreshIcons(content);
  } finally {
    loading.hidden = true;
  }
}

function renderSnapshot(snapshot: StorageSnapshot): string {
  const totals = snapshot.totals;
  return `<section class="metric-strip" aria-label="Task storage totals"><div><span>Total corpus</span><strong>${formatBytes(totals.total_bytes)}</strong></div><div><span>Root tasks</span><strong>${formatBytes(totals.root_bytes)}</strong></div><div><span>Descendants</span><strong>${formatBytes(totals.descendant_bytes)}</strong></div><div><span>Task trees</span><strong>${totals.task_tree_count.toLocaleString()}</strong></div><div><span>Files</span><strong>${totals.physical_file_count.toLocaleString()}</strong></div></section>${snapshot.diagnostics.map((message) => `<div class="inline-notice warning"><i data-lucide="triangle-alert"></i><span>${escapeHtml(message)}</span></div>`).join("")}<section class="table-section"><header><div><h2>Largest Task Trees</h2><p>Analyze a selected tree to inspect history and inline-media amplification.</p></div></header>${snapshot.task_trees.length ? `<div class="table-scroll"><table><thead><tr><th>Task</th><th>Project</th><th>Total</th><th>Root</th><th>Descendants</th><th>Analysis</th><th aria-label="Actions"></th></tr></thead><tbody>${snapshot.task_trees.map(renderTree).join("")}</tbody></table></div>` : `<div class="empty-state compact"><p>No task storage was found.</p></div>`}</section>`;
}

function renderTree(tree: StorageTree): string {
  const flags = [
    tree.has_history_amplification ? "History" : "",
    tree.has_media_amplification ? "Inline media" : "",
    tree.has_active_root_history_risk ? "Active root" : "",
    tree.has_missing_root ? "Root missing" : "",
  ].filter(Boolean);
  const analysis = tree.analysis_status === "complete"
    ? `${Math.round(tree.analysis_coverage * 100)}% · ${flags.join(", ") || "No amplification flag"}`
    : "Not analyzed";
  const title = escapeHtml(tree.title || tree.root_task_id);
  return `<tr><td><strong>${title}</strong><small>${escapeHtml(tree.root_task_id)}</small></td><td>${escapeHtml(tree.project_label || "Unassigned")}</td><td>${formatBytes(tree.total_bytes)}</td><td>${formatBytes(tree.root_bytes)}</td><td>${formatBytes(tree.descendant_bytes)}<small>${tree.descendant_count.toLocaleString()} tasks</small></td><td>${escapeHtml(analysis)}</td><td><button class="icon-button analyze-button" data-tree-id="${escapeHtml(tree.root_task_id)}" title="Analyze task tree" aria-label="Analyze ${title}"><i data-lucide="scan-search"></i></button></td></tr>`;
}

function bindAnalysis(content: HTMLElement, root: HTMLElement, state: AppState): void {
  content.querySelectorAll<HTMLButtonElement>(".analyze-button").forEach((button) => {
    button.addEventListener("click", async () => {
      const treeId = button.dataset.treeId;
      if (!treeId) return;
      button.disabled = true;
      try {
        const job = await agentRequest<AnalysisJob>({ method: "POST", path: "/v1/storage/jobs", body: { tree_id: treeId } });
        await monitorAnalysis(job.operation_id, root, state);
      } catch (error) {
        showToast(`Analysis failed: ${errorMessage(error)}`, "error");
      } finally {
        button.disabled = false;
      }
    });
  });
}

async function monitorAnalysis(operationId: string, root: HTMLElement, state: AppState): Promise<void> {
  const notice = document.createElement("div");
  notice.className = "analysis-progress inline-notice";
  notice.innerHTML = `<i data-lucide="scan-search"></i><div><strong>Analyzing task storage</strong><span>Waiting for the I/O lane</span></div><button class="button-quiet">Cancel</button>`;
  root.querySelector("#storage-content")?.prepend(notice);
  refreshIcons(notice);
  let cancelled = false;
  notice.querySelector<HTMLButtonElement>("button")!.addEventListener("click", async () => {
    cancelled = true;
    await agentRequest({ method: "POST", path: `/v1/jobs/${operationId}/cancel`, body: {} });
    notice.querySelector("span")!.textContent = "Cancelling after the active worker batch";
  });
  try {
    while (true) {
      const job = await agentRequest<AnalysisJob>({ method: "GET", path: `/v1/jobs/${operationId}` });
      const completed = Number(job.progress.completed_files ?? 0);
      const total = Number(job.progress.total_files ?? 0);
      notice.querySelector("span")!.textContent = total ? `${completed.toLocaleString()} of ${total.toLocaleString()} files` : job.state === "queued" ? "Waiting for the I/O lane" : "Inspecting selected files";
      if (job.state === "completed") {
        showToast("Task tree analysis completed.", "success");
        await loadStorage(root, state);
        return;
      }
      if (job.state === "failed") throw new Error(job.error || "Task Storage analysis failed");
      if (job.state === "cancelled") {
        showToast("Task Storage analysis cancelled.", "info");
        return;
      }
      await new Promise((resolve) => window.setTimeout(resolve, cancelled ? 250 : 700));
    }
  } finally {
    notice.remove();
  }
}
