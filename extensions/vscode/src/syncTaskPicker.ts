import { filterInventoryForOperation, type SyncInventory } from "./syncInventory";
import {
  taskAvailabilityLabel,
  taskPickerDetail,
  taskStateLabel,
  type TransferOperation,
} from "./transferPresentation";

export type TaskPickerItem = {
  id: string;
  kind: "project" | "task" | "separator";
  label: string;
  description: string;
  detail: string;
  projectKey?: string;
  threadId?: string;
  childThreadIds: string[];
};

export function buildTaskPickerItems(
  inventory: SyncInventory,
  operation: TransferOperation,
): TaskPickerItem[] {
  const items: TaskPickerItem[] = [];
  const visibleInventory = filterInventoryForOperation(inventory, operation);

  for (const project of visibleInventory.projects) {
    const childThreadIds = project.tasks.map((task) => task.threadId);
    items.push({
      id: `project:${project.projectKey}`,
      kind: "project",
      label: project.projectLabel,
      description: "",
      detail: taskCountLabel(childThreadIds.length),
      projectKey: project.projectKey,
      childThreadIds,
    });

    for (const task of project.tasks) {
      items.push({
        id: `task:${task.threadId}`,
        kind: "task",
        label: task.title,
        description: `${taskStateLabel(task.action, task.state)} | ${taskAvailabilityLabel(task.availability)}`,
        detail: taskPickerDetail(task.threadId, formatBytes(task.estimatedSyncBytes)),
        projectKey: project.projectKey,
        threadId: task.threadId,
        childThreadIds: [],
      });
    }
  }

  return items;
}

export function reduceTaskSelection(
  selectedThreadIds: unknown,
  changedItem: TaskPickerItem,
  selected: boolean,
): string[] {
  const current = normalizeThreadIds(selectedThreadIds);
  if (changedItem.kind === "separator") {
    return current;
  }

  if (changedItem.kind === "project") {
    if (selected) {
      return normalizeThreadIds([...current, ...changedItem.childThreadIds]);
    }
    const removedThreadIds = new Set(changedItem.childThreadIds);
    return current.filter((threadId) => !removedThreadIds.has(threadId));
  }

  if (changedItem.threadId === undefined) {
    return current;
  }
  if (selected) {
    return normalizeThreadIds([...current, changedItem.threadId]);
  }
  return current.filter((threadId) => threadId !== changedItem.threadId);
}

export function selectedPickerItemIds(items: TaskPickerItem[], selectedThreadIds: unknown): string[] {
  const selected = new Set(normalizeThreadIds(selectedThreadIds));
  return items.flatMap((item) => {
    if (item.kind === "project") {
      const everyChildSelected =
        item.childThreadIds.length > 0 && item.childThreadIds.every((threadId) => selected.has(threadId));
      return everyChildSelected ? [item.id] : [];
    }
    if (item.kind === "task" && item.threadId !== undefined) {
      return selected.has(item.threadId) ? [item.id] : [];
    }
    return [];
  });
}

function normalizeThreadIds(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return [...new Set(value.filter((threadId): threadId is string => typeof threadId === "string"))];
}

function taskCountLabel(taskCount: number): string {
  return `${taskCount} task${taskCount === 1 ? "" : "s"}`;
}

function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return unitIndex === 0 ? `${Math.round(size)} B` : `${size.toFixed(1)} ${units[unitIndex]}`;
}
