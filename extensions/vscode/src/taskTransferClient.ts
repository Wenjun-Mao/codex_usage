import * as vscode from "vscode";
import { AgentClient } from "./agentClient";
import {
  eligibleTransferProjects,
  type TransferOperation,
} from "./taskTransferContract";
import type { AgentSettings, TransferInventory, TransferProject, TransferTask } from "./types";

export class TaskTransferClient {
  private inFlight = false;

  constructor(
    private readonly acquireClient: () => Promise<AgentClient | undefined>,
    private readonly output: vscode.OutputChannel,
  ) {}

  async menu(): Promise<void> {
    const client = await this.acquireClient();
    if (!client) return;
    const settings = await client.get<AgentSettings>("/v1/settings");
    const selected = await vscode.window.showQuickPick([
      { label: "$(cloud-download) Import Tasks", description: "Bring selected remote tasks into one local project", operation: "import" as const },
      { label: "$(cloud-upload) Export Tasks", description: "Publish selected local tasks from one project", operation: "export" as const },
      { label: "$(list-selection) Review Status", description: "Compare selected local and remote tasks", operation: "status" as const },
      { label: "$(folder) Change Transfer Folder", description: settings.transfer_folder || "Not selected", operation: "folder" as const },
      { label: "$(folder-opened) Open Transfer Folder", description: settings.transfer_folder || "Not selected", operation: "open" as const },
    ], { placeHolder: "Choose a Task Transfer action" });
    if (!selected) return;
    if (selected.operation === "folder") await this.chooseFolder(client);
    else if (selected.operation === "open") await this.openFolder(settings.transfer_folder);
    else await this.run(selected.operation, client);
  }

  async run(operation: TransferOperation, existingClient?: AgentClient): Promise<void> {
    if (this.inFlight) {
      void vscode.window.showInformationMessage("A Task Transfer operation is already running.");
      return;
    }
    this.inFlight = true;
    try {
      const client = existingClient ?? await this.acquireClient();
      if (!client) return;
      const folder = await this.requireFolder(client);
      if (!folder) return;
      const roots = (vscode.workspace.workspaceFolders ?? []).map((item) => item.uri.fsPath);
      const inventory = await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Window, title: "Checking Task Transfer projects" },
        () => client.post<TransferInventory>("/v1/transfer/inventory", { sync_dir: folder, candidate_roots: roots }),
      );
      for (const issue of inventory.issues) this.output.appendLine(`[task transfer] ${issue.code}: ${issue.message}`);
      const selection = await chooseProjectAndTasks(inventory, operation);
      if (!selection) return;
      const destination = operation === "import" ? await chooseDestination(selection.project) : undefined;
      if (operation === "import" && !destination) return;
      const confirmed = operation === "import" && selection.project.identity_kind === "path"
        ? await confirmPathIdentity(selection.project, destination!)
        : false;
      if (operation === "import" && selection.project.identity_kind === "path" && !confirmed) return;
      const title = operation === "status" ? "Reviewing Task Transfer status" : `${operation === "import" ? "Importing" : "Exporting"} ${selection.tasks.length} ${selection.tasks.length === 1 ? "task" : "tasks"}`;
      const response = await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title },
        () => client.post<Record<string, unknown>>("/v1/transfer/execute", {
          operation,
          sync_dir: folder,
          project_key: selection.project.project_key,
          task_ids: selection.tasks.map((task) => task.thread_id),
          destination_path: destination,
          candidate_roots: [...new Set([...roots, ...selection.project.candidate_roots])],
          confirm_unverified_project: confirmed,
        }),
      );
      this.output.appendLine(`[task transfer] ${JSON.stringify(response)}`);
      void vscode.window.showInformationMessage(formatTransferResult(operation, response));
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      this.output.appendLine(`[task transfer error] ${message}`);
      void vscode.window.showErrorMessage(`Task Transfer failed: ${message}`);
    } finally {
      this.inFlight = false;
    }
  }

  async chooseFolder(existingClient?: AgentClient): Promise<string | undefined> {
    const client = existingClient ?? await this.acquireClient();
    if (!client) return undefined;
    const selected = await vscode.window.showOpenDialog({
      title: "Choose Task Transfer Folder",
      openLabel: "Use Transfer Folder",
      canSelectFiles: false,
      canSelectFolders: true,
      canSelectMany: false,
    });
    const folder = selected?.[0]?.fsPath;
    if (!folder) return undefined;
    await client.post("/v1/settings", { transfer_folder: folder });
    return folder;
  }

  private async requireFolder(client: AgentClient): Promise<string | undefined> {
    const settings = await client.get<AgentSettings>("/v1/settings");
    if (settings.transfer_folder && await pathExists(settings.transfer_folder)) return settings.transfer_folder;
    if (settings.transfer_folder) {
      void vscode.window.showWarningMessage("The configured Task Transfer folder is unavailable. Choose it again.");
    }
    return this.chooseFolder(client);
  }

  private async openFolder(folder: string): Promise<void> {
    if (!folder || !await pathExists(folder)) {
      void vscode.window.showWarningMessage("Choose an available Task Transfer folder first.");
      return;
    }
    await vscode.env.openExternal(vscode.Uri.file(folder));
  }
}

async function chooseProjectAndTasks(
  inventory: TransferInventory,
  operation: TransferOperation,
): Promise<{ project: TransferProject; tasks: TransferTask[] } | undefined> {
  const available = eligibleTransferProjects(inventory, operation);
  if (!available.length) {
    void vscode.window.showInformationMessage(`No tasks are available to ${operation === "status" ? "review" : operation}.`);
    return undefined;
  }
  const projectChoice = await vscode.window.showQuickPick(available.map(({ project, tasks }) => ({
    label: `$(folder) ${project.project_label}`,
    description: `${tasks.length} ${tasks.length === 1 ? "task" : "tasks"}`,
    project,
    tasks,
  })), { title: `${titleCase(operation)} Tasks: Choose One Project`, placeHolder: "Only one project can be processed at a time" });
  if (!projectChoice) return undefined;
  const picked = await vscode.window.showQuickPick(projectChoice.tasks.map((task) => ({
    label: task.title || task.thread_id,
    description: availabilityLabel(task.availability),
    detail: `Task ID: ${task.thread_id} | Estimated transfer: ${formatBytes(task.estimated_sync_bytes)}`,
    task,
    picked: false,
  })), {
    title: `${titleCase(operation)} Tasks: ${projectChoice.project.project_label}`,
    placeHolder: "Select exact tasks; search applies only within this project",
    canPickMany: true,
  });
  if (!picked?.length) return undefined;
  return { project: projectChoice.project, tasks: picked.map((item) => item.task) };
}

async function chooseDestination(project: TransferProject): Promise<string | undefined> {
  if (project.candidate_roots.length) {
    const browse = "__browse__";
    const selected = await vscode.window.showQuickPick([
      ...project.candidate_roots.map((candidate) => ({ label: candidate, value: candidate })),
      { label: "$(folder-opened) Choose Another Folder...", value: browse },
    ], { title: `Choose Local Project Folder for ${project.project_label}` });
    if (!selected) return undefined;
    if (selected.value !== browse) return selected.value;
  }
  const selected = await vscode.window.showOpenDialog({
    title: `Choose Local Project Folder for ${project.project_label}`,
    openLabel: "Use Project Folder",
    canSelectFiles: false,
    canSelectFolders: true,
    canSelectMany: false,
  });
  return selected?.[0]?.fsPath;
}

async function confirmPathIdentity(project: TransferProject, destination: string): Promise<boolean> {
  const selected = await vscode.window.showWarningMessage(
    `Git cannot verify the identity of ${project.project_label}. Import its selected tasks into ${destination}?`,
    { modal: true },
    "Use Folder",
  );
  return selected === "Use Folder";
}

function availabilityLabel(value: TransferTask["availability"]): string {
  if (value === "both") return "On this computer and transfer folder";
  return value === "local" ? "On this computer" : "In transfer folder";
}

function formatTransferResult(operation: TransferOperation, response: Record<string, unknown>): string {
  const result = isRecord(response.result) ? response.result : {};
  const outcome = typeof result.outcome === "string" ? result.outcome : "completed";
  return operation === "status" ? "Task Transfer status is ready in the Codex Usage output." : `${titleCase(operation)} ${outcome}.`;
}

function titleCase(value: string): string {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) return "0 B";
  const units = ["B", "KiB", "MiB", "GiB"];
  const index = Math.min(Math.floor(Math.log(value) / Math.log(1024)), units.length - 1);
  return `${(value / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

async function pathExists(value: string): Promise<boolean> {
  try {
    await vscode.workspace.fs.stat(vscode.Uri.file(value));
    return true;
  } catch {
    return false;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
