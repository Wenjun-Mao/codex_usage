import type { SyncInventory, SyncTaskAvailability } from "./syncInventory";

export type TaskPickerItem = {
  id: string;
  kind: "project" | "task" | "unavailable" | "separator";
  label: string;
  description: string;
  detail: string;
  projectKey?: string;
  threadId?: string;
  childThreadIds: string[];
};

const AVAILABILITY_LABELS: Record<SyncTaskAvailability, string> = {
  local: "This device",
  remote: "Sync folder",
  both: "Both",
};

export function buildTaskPickerItems(inventory: SyncInventory, storedThreadIds: unknown): TaskPickerItem[] {
  const items: TaskPickerItem[] = [];
  const availableThreadIds = new Set<string>();

  for (const project of inventory.projects) {
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
      availableThreadIds.add(task.threadId);
      items.push({
        id: `task:${task.threadId}`,
        kind: "task",
        label: task.title,
        description: AVAILABILITY_LABELS[task.availability],
        detail: `Thread ID: ${task.threadId} | ${formatBytes(task.estimatedSyncBytes)} estimated sync size`,
        projectKey: project.projectKey,
        threadId: task.threadId,
        childThreadIds: [],
      });
    }
  }

  const unavailableThreadIds = normalizeThreadIds(storedThreadIds)
    .filter((threadId) => !availableThreadIds.has(threadId))
    .sort();
  if (unavailableThreadIds.length === 0) {
    return items;
  }

  items.push({
    id: "separator:unavailable",
    kind: "separator",
    label: "Unavailable selected tasks",
    description: "",
    detail: "",
    childThreadIds: [],
  });
  for (const threadId of unavailableThreadIds) {
    items.push({
      id: `unavailable:${threadId}`,
      kind: "unavailable",
      label: threadId,
      description: "Unavailable",
      detail: `Thread ID: ${threadId}`,
      threadId,
      childThreadIds: [],
    });
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
    if ((item.kind === "task" || item.kind === "unavailable") && item.threadId !== undefined) {
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
