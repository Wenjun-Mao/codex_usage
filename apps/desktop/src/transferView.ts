import { escapeHtml, formatBytes, formatDate } from "./format";
import { agentRequest, chooseDirectory, revealPath } from "./host";
import type { AppState } from "./state";
import type { TransferInventory, TransferProject, TransferTask } from "./types";
import { confirmDialog, errorMessage, refreshIcons, setBusy, showToast } from "./ui";

type TransferMode = "import" | "export";

interface TransferState {
  mode: TransferMode;
  inventory: TransferInventory | null;
  project: TransferProject | null;
  selectedTaskIds: Set<string>;
  destinationPath: string;
  search: string;
}

const transferState: TransferState = {
  mode: "export",
  inventory: null,
  project: null,
  selectedTaskIds: new Set(),
  destinationPath: "",
  search: "",
};

export async function renderTransferView(root: HTMLElement, appState: AppState): Promise<void> {
  root.innerHTML = `<section class="view-heading"><div><p class="eyebrow">Cross-computer workflow</p><h1>Task Transfer</h1></div><div class="segmented" role="group" aria-label="Transfer direction"><button data-mode="export" class="${transferState.mode === "export" ? "active" : ""}"><i data-lucide="cloud-upload"></i>Export</button><button data-mode="import" class="${transferState.mode === "import" ? "active" : ""}"><i data-lucide="cloud-download"></i>Import</button></div></section><section class="transfer-folder"><div><span>Transfer folder</span><strong id="transfer-folder-label">${escapeHtml(appState.settings.transfer_folder || "Not selected")}</strong></div><div class="button-row"><button class="icon-button" id="open-transfer-folder" title="Open transfer folder" aria-label="Open transfer folder"${appState.settings.transfer_folder ? "" : " disabled"}><i data-lucide="folder-open"></i></button><button class="button-secondary" id="choose-transfer-folder"><i data-lucide="folder-cog"></i>Choose Folder</button></div></section><div id="transfer-workspace"></div>`;
  refreshIcons(root);
  root.querySelectorAll<HTMLButtonElement>("[data-mode]").forEach((button) => button.addEventListener("click", async () => {
    transferState.mode = button.dataset.mode as TransferMode;
    resetTransferSelection();
    await renderTransferView(root, appState);
  }));
  root.querySelector<HTMLButtonElement>("#choose-transfer-folder")!.addEventListener("click", async () => {
    const path = await chooseDirectory("Choose a Task Transfer folder");
    if (!path) return;
    const settings = await agentRequest<AppState["settings"]>({ method: "POST", path: "/v1/settings", body: { transfer_folder: path } });
    appState.settings = settings;
    resetTransferSelection();
    await renderTransferView(root, appState);
  });
  root.querySelector<HTMLButtonElement>("#open-transfer-folder")!.addEventListener("click", () => revealPath(appState.settings.transfer_folder));
  if (!appState.settings.transfer_folder) {
    renderNoFolder(root.querySelector<HTMLElement>("#transfer-workspace")!);
    return;
  }
  await loadInventory(root, appState);
}

async function loadInventory(root: HTMLElement, appState: AppState): Promise<void> {
  const workspace = root.querySelector<HTMLElement>("#transfer-workspace")!;
  workspace.innerHTML = `<div class="view-loading"><span class="spinner"></span>Checking projects and tasks</div>`;
  try {
    transferState.inventory = await agentRequest<TransferInventory>({
      method: "POST",
      path: "/v1/transfer/inventory",
      body: { sync_dir: appState.settings.transfer_folder, candidate_roots: [] },
    });
    if (transferState.project) {
      const current = transferState.inventory.projects.find((project) => project.project_key === transferState.project?.project_key);
      transferState.project = current ?? null;
    }
    renderTransferWorkspace(workspace, root, appState);
  } catch (error) {
    workspace.innerHTML = `<div class="empty-state"><i data-lucide="cloud-off"></i><h2>Transfer inventory unavailable</h2><p>${escapeHtml(errorMessage(error))}</p><button class="button-secondary" id="retry-transfer"><i data-lucide="refresh-cw"></i>Try Again</button></div>`;
    workspace.querySelector<HTMLButtonElement>("#retry-transfer")!.addEventListener("click", () => loadInventory(root, appState));
    refreshIcons(workspace);
  }
}

function renderTransferWorkspace(workspace: HTMLElement, root: HTMLElement, appState: AppState): void {
  if (!transferState.project) {
    renderProjects(workspace, root, appState);
  } else {
    renderTasks(workspace, root, appState);
  }
}

function renderProjects(workspace: HTMLElement, root: HTMLElement, appState: AppState): void {
  const projects = (transferState.inventory?.projects ?? []).map((project) => ({
    project,
    count: eligibleTasks(project).length,
  })).filter(({ count }) => count > 0);
  workspace.innerHTML = `<section class="selection-stage"><header><div><span class="step-label">Step 1 of 2</span><h2>Choose One Project</h2><p>${transferState.mode === "export" ? "Export local tasks from one project." : "Import remote tasks into one local project."}</p></div></header>${renderIssues()}<div class="project-list">${projects.map(({ project, count }) => `<button class="project-row" data-project-key="${escapeHtml(project.project_key)}"><i data-lucide="folder"></i><span><strong>${escapeHtml(project.project_label)}</strong><small>${count.toLocaleString()} ${count === 1 ? "task" : "tasks"} available</small></span><i data-lucide="chevron-right"></i></button>`).join("")}</div>${projects.length ? "" : `<div class="empty-state compact"><p>No ${transferState.mode === "export" ? "local" : "remote"} tasks are available.</p></div>`}</section>`;
  workspace.querySelectorAll<HTMLButtonElement>("[data-project-key]").forEach((button) => button.addEventListener("click", () => {
    transferState.project = transferState.inventory?.projects.find((project) => project.project_key === button.dataset.projectKey) ?? null;
    transferState.destinationPath = transferState.mode === "import" && transferState.project?.candidate_roots.length === 1 ? transferState.project.candidate_roots[0] ?? "" : "";
    transferState.selectedTaskIds.clear();
    transferState.search = "";
    renderTransferWorkspace(workspace, root, appState);
  }));
  refreshIcons(workspace);
}

function renderTasks(workspace: HTMLElement, root: HTMLElement, appState: AppState): void {
  const project = transferState.project!;
  const tasks = filteredTasks(project);
  workspace.innerHTML = `<section class="selection-stage"><header class="task-stage-header"><div><button class="button-quiet back-button" id="transfer-back"><i data-lucide="arrow-left"></i>Projects</button><span class="step-label">Step 2 of 2</span><h2>${escapeHtml(project.project_label)}</h2><p>Select the exact tasks to ${transferState.mode}. Nothing is selected by default.</p></div><div class="selection-count"><strong id="selected-task-count">${transferState.selectedTaskIds.size}</strong><span>selected</span></div></header>${transferState.mode === "import" ? renderDestination() : ""}<div class="task-toolbar"><label class="search-control"><i data-lucide="search"></i><input id="task-search" type="search" value="${escapeHtml(transferState.search)}" placeholder="Search tasks in ${escapeHtml(project.project_label)}" /></label><button class="button-quiet" id="clear-task-selection"${transferState.selectedTaskIds.size ? "" : " disabled"}>Clear</button></div><div class="task-list" id="task-list">${tasks.map(renderTask).join("") || `<div class="empty-state compact"><p>No matching tasks.</p></div>`}</div><footer class="stage-actions"><button class="button-secondary" id="review-transfer-status"${transferState.selectedTaskIds.size ? "" : " disabled"}><i data-lucide="list-checks"></i>Review Status</button><button class="button-primary" id="execute-transfer"${canExecute() ? "" : " disabled"}><i data-lucide="${transferState.mode === "export" ? "cloud-upload" : "cloud-download"}"></i><span data-button-label>${transferState.mode === "export" ? "Export" : "Import"} Selected</span></button></footer></section>`;
  bindTaskStage(workspace, root, appState);
  refreshIcons(workspace);
}

function bindTaskStage(workspace: HTMLElement, root: HTMLElement, appState: AppState): void {
  workspace.querySelector<HTMLButtonElement>("#transfer-back")!.addEventListener("click", () => {
    resetTransferSelection();
    renderTransferWorkspace(workspace, root, appState);
  });
  workspace.querySelector<HTMLInputElement>("#task-search")!.addEventListener("input", (event) => {
    transferState.search = (event.currentTarget as HTMLInputElement).value;
    renderTasks(workspace, root, appState);
    const input = workspace.querySelector<HTMLInputElement>("#task-search");
    input?.focus();
    input?.setSelectionRange(input.value.length, input.value.length);
  });
  workspace.querySelectorAll<HTMLInputElement>("[data-task-id]").forEach((input) => input.addEventListener("change", () => {
    if (input.checked) transferState.selectedTaskIds.add(input.dataset.taskId!);
    else transferState.selectedTaskIds.delete(input.dataset.taskId!);
    renderTasks(workspace, root, appState);
  }));
  workspace.querySelector<HTMLButtonElement>("#clear-task-selection")!.addEventListener("click", () => {
    transferState.selectedTaskIds.clear();
    renderTasks(workspace, root, appState);
  });
  workspace.querySelector<HTMLButtonElement>("#choose-destination")?.addEventListener("click", async () => {
    const path = await chooseDirectory(`Choose the local ${transferState.project?.project_label ?? "project"} folder`);
    if (path) {
      transferState.destinationPath = path;
      renderTasks(workspace, root, appState);
    }
  });
  workspace.querySelector<HTMLButtonElement>("#review-transfer-status")!.addEventListener("click", (event) => executeTransfer(event.currentTarget as HTMLButtonElement, "status", root, appState));
  workspace.querySelector<HTMLButtonElement>("#execute-transfer")!.addEventListener("click", (event) => executeTransfer(event.currentTarget as HTMLButtonElement, transferState.mode, root, appState));
}

async function executeTransfer(button: HTMLButtonElement, operation: TransferMode | "status", root: HTMLElement, appState: AppState): Promise<void> {
  const project = transferState.project;
  if (!project) return;
  const confirmUnverifiedProject = operation === "import"
    && project.identity_kind === "path"
    && await confirmDialog({
      title: `Import into ${project.project_label}?`,
      message: `Git cannot verify this project identity. Assign the selected tasks to ${transferState.destinationPath}?`,
      confirmLabel: "Use Project Folder",
    });
  if (operation === "import" && project.identity_kind === "path" && !confirmUnverifiedProject) return;
  setBusy(button, true, operation === "status" ? "Checking" : operation === "import" ? "Importing" : "Exporting");
  try {
    const result = await agentRequest<Record<string, unknown>>({
      method: "POST",
      path: "/v1/transfer/execute",
      body: {
        operation,
        sync_dir: appState.settings.transfer_folder,
        project_key: project.project_key,
        task_ids: [...transferState.selectedTaskIds],
        destination_path: transferState.destinationPath,
        candidate_roots: project.candidate_roots,
        confirm_unverified_project: confirmUnverifiedProject,
      },
    });
    showTransferResult(result, operation);
    if (operation !== "status") {
      resetTransferSelection();
      await loadInventory(root, appState);
    }
  } catch (error) {
    showToast(`${operation === "status" ? "Status check" : `${capitalize(operation)} operation`} failed: ${errorMessage(error)}`, "error");
  } finally {
    setBusy(button, false);
  }
}

function showTransferResult(result: Record<string, unknown>, operation: TransferMode | "status"): void {
  const payload = result.result && typeof result.result === "object" ? result.result as Record<string, unknown> : {};
  const outcome = String(payload.outcome ?? "completed");
  const label = operation === "status"
    ? "Transfer status is ready."
    : operation === "import" && outcome === "completed"
      ? "Import completed and tasks were assigned. Start Codex Desktop, or reload VS Code, to refresh its task list."
      : `${capitalize(operation)} ${outcome}.`;
  showToast(label, outcome === "completed" || operation === "status" ? "success" : "info");
}

function renderTask(task: TransferTask): string {
  const selected = transferState.selectedTaskIds.has(task.thread_id);
  return `<label class="task-row"><input type="checkbox" data-task-id="${escapeHtml(task.thread_id)}"${selected ? " checked" : ""}><span class="task-copy"><strong>${escapeHtml(task.title || task.thread_id)}</strong><small>${escapeHtml(formatDate(task.updated_at))} · ${formatBytes(task.estimated_sync_bytes)} · ${availabilityLabel(task.availability)}</small><code>${escapeHtml(task.thread_id)}</code></span></label>`;
}

function renderDestination(): string {
  return `<section class="destination-row"><div><span>Local project folder</span><strong>${escapeHtml(transferState.destinationPath || "Choose the cloned project before importing")}</strong></div><button class="button-secondary" id="choose-destination"><i data-lucide="folder-search"></i>Choose Project Folder</button></section>`;
}

function renderIssues(): string {
  return (transferState.inventory?.issues ?? []).map((issue) => `<div class="inline-notice warning"><i data-lucide="triangle-alert"></i><span>${escapeHtml(issue.message)}</span></div>`).join("");
}

function filteredTasks(project: TransferProject): TransferTask[] {
  const query = transferState.search.trim().toLocaleLowerCase();
  return eligibleTasks(project).filter((task) => !query || `${task.title} ${task.thread_id}`.toLocaleLowerCase().includes(query));
}

function eligibleTasks(project: TransferProject): TransferTask[] {
  return project.tasks.filter((task) => transferState.mode === "export" ? task.availability !== "remote" : task.availability !== "local");
}

function canExecute(): boolean {
  return transferState.selectedTaskIds.size > 0 && (transferState.mode === "export" || Boolean(transferState.destinationPath));
}

function availabilityLabel(value: TransferTask["availability"]): string {
  if (value === "both") return "On this computer and transfer folder";
  return value === "local" ? "On this computer" : "In transfer folder";
}

function renderNoFolder(workspace: HTMLElement): void {
  workspace.innerHTML = `<div class="empty-state"><i data-lucide="folder-plus"></i><h2>Choose a transfer folder</h2><p>Use a folder provided by OneDrive, Dropbox, iCloud Drive, or another file-sync service.</p></div>`;
  refreshIcons(workspace);
}

export function resetTransferSelection(): void {
  transferState.project = null;
  transferState.selectedTaskIds.clear();
  transferState.destinationPath = "";
  transferState.search = "";
}

function capitalize(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}
