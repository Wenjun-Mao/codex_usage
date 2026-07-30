import * as vscode from "vscode";
import {
  activateTaskPickerProject,
  initialTaskPickerSelection,
  reduceTaskSelection,
  reduceTransferTaskSelection,
  selectedTaskPickerItemIds,
  visibleTaskPickerItems,
  type TaskPickerItem,
  type TaskPickerSelection,
  type TaskPickerSelectionState,
} from "./syncTaskPicker";
import type { TransferOperation } from "./transferPresentation";

type TaskQuickPickItem = vscode.QuickPickItem & { task?: TaskPickerItem };
type ScopedTransferOperation = Exclude<TransferOperation, "review">;

const SCOPED_TRANSFER_PICKER_COPY = {
  import: {
    projectTitle: "Import Tasks: Choose a Project",
    projectPlaceholder: "Choose one project to import tasks into.",
    taskTitle: (projectLabel: string) => `Import Tasks: Select Tasks for ${projectLabel}`,
    taskPlaceholder: (projectLabel: string) => `Search tasks in ${projectLabel}.`,
    emptyTitle: "Select at least one Codex task to import",
  },
  export: {
    projectTitle: "Export Tasks: Choose a Project",
    projectPlaceholder: "Choose one project to export tasks from.",
    taskTitle: (projectLabel: string) => `Export Tasks: Select Tasks from ${projectLabel}`,
    taskPlaceholder: (projectLabel: string) => `Search tasks in ${projectLabel}.`,
    emptyTitle: "Select at least one Codex task to export",
  },
} as const;

const REVIEW_PICKER_COPY = {
  title: "Review Tasks Across Projects",
  placeholder: "Select any tasks to compare without copying files.",
} as const;

export function showTaskTransferPicker(
  operation: TransferOperation,
  rows: TaskPickerItem[],
): Promise<TaskPickerSelection | undefined> {
  return operation === "review"
    ? showReviewTaskPicker(rows)
    : showScopedTaskTransferPicker(operation, rows);
}

function showScopedTaskTransferPicker(
  operation: ScopedTransferOperation,
  rows: TaskPickerItem[],
): Promise<TaskPickerSelection | undefined> {
  const quickPick = vscode.window.createQuickPick<TaskQuickPickItem>();
  let state = initialTaskPickerSelection(operation);
  let settled = false;

  quickPick.matchOnDescription = true;
  quickPick.matchOnDetail = true;

  const render = (): void => {
    const isTaskStep = state.activeProjectKey !== undefined;
    const activeProject = rows.find(
      (row) => row.kind === "project" && row.projectKey === state.activeProjectKey,
    );
    const copy = SCOPED_TRANSFER_PICKER_COPY[operation];

    quickPick.canSelectMany = isTaskStep;
    quickPick.buttons = isTaskStep ? [vscode.QuickInputButtons.Back] : [];
    quickPick.title = activeProject
      ? copy.taskTitle(activeProject.label)
      : copy.projectTitle;
    quickPick.placeholder = activeProject
      ? copy.taskPlaceholder(activeProject.label)
      : copy.projectPlaceholder;
    quickPick.value = "";
    quickPick.items = visibleTaskPickerItems(rows, state, operation).map(toQuickPickItem);
    quickPick.activeItems = [];
    quickPick.selectedItems = [];
  };

  return new Promise((resolve) => {
    const disposables: vscode.Disposable[] = [];
    const finish = (selection: TaskPickerSelection | undefined): void => {
      if (settled) {
        return;
      }
      settled = true;
      for (const disposable of disposables) {
        disposable.dispose();
      }
      quickPick.dispose();
      resolve(selection);
    };

    disposables.push(
      quickPick.onDidAccept(() => {
        if (state.activeProjectKey === undefined) {
          const activeRow = quickPick.activeItems[0]?.task;
          if (activeRow?.kind !== "project" || activeRow.projectKey === undefined) {
            return;
          }
          state = activateTaskPickerProject(rows, activeRow.projectKey);
          render();
          return;
        }

        let acceptedState: TaskPickerSelectionState = {
          activeProjectKey: state.activeProjectKey,
          selectedThreadIds: [],
        };
        for (const item of quickPick.selectedItems) {
          if (item.task?.kind === "task") {
            acceptedState = reduceTransferTaskSelection(acceptedState, item.task, true);
          }
        }
        if (acceptedState.selectedThreadIds.length === 0) {
          quickPick.title = SCOPED_TRANSFER_PICKER_COPY[operation].emptyTitle;
          return;
        }
        finish({
          projectKey: state.activeProjectKey,
          threadIds: [...acceptedState.selectedThreadIds],
        });
      }),
      quickPick.onDidTriggerButton((button) => {
        if (button !== vscode.QuickInputButtons.Back) {
          return;
        }
        state = initialTaskPickerSelection(operation);
        render();
      }),
      quickPick.onDidHide(() => finish(undefined)),
    );
    render();
    quickPick.show();
  });
}

function showReviewTaskPicker(
  rows: TaskPickerItem[],
): Promise<TaskPickerSelection | undefined> {
  const quickPick = vscode.window.createQuickPick<TaskQuickPickItem>();
  let state = initialTaskPickerSelection("review");
  let canonicalSelectionIds = new Set<string>();
  let pickerItemsById = new Map<string, TaskQuickPickItem>();
  let pendingCanonicalSelectionIds: ReadonlySet<string> | undefined;
  let settled = false;

  quickPick.title = REVIEW_PICKER_COPY.title;
  quickPick.placeholder = REVIEW_PICKER_COPY.placeholder;
  quickPick.canSelectMany = true;
  quickPick.matchOnDescription = true;
  quickPick.matchOnDetail = true;

  const render = (): void => {
    const pickerItems = visibleTaskPickerItems(rows, state, "review").map(toQuickPickItem);
    pickerItemsById = new Map(
      pickerItems.flatMap((item) => (item.task ? [[item.task.id, item] as const] : [])),
    );
    canonicalSelectionIds = new Set(selectedTaskPickerItemIds(rows, state, "review"));
    pendingCanonicalSelectionIds = canonicalSelectionIds.size > 0
      ? new Set(canonicalSelectionIds)
      : undefined;
    quickPick.items = pickerItems;
    if (canonicalSelectionIds.size > 0) {
      quickPick.selectedItems = pickerItemsForIds(canonicalSelectionIds, pickerItemsById);
    }
  };

  return new Promise((resolve) => {
    const disposables: vscode.Disposable[] = [];
    const finish = (selection: TaskPickerSelection | undefined): void => {
      if (settled) {
        return;
      }
      settled = true;
      for (const disposable of disposables) {
        disposable.dispose();
      }
      quickPick.dispose();
      resolve(selection);
    };

    disposables.push(
      quickPick.onDidChangeSelection((selectedItems) => {
        if (settled) {
          return;
        }
        const selectedRowIds = new Set(
          selectedItems.flatMap((item) => (item.task ? [item.task.id] : [])),
        );
        // Item replacement can echo an empty selection before VS Code applies our canonical selection.
        if (pendingCanonicalSelectionIds !== undefined) {
          if (sameItemIds(selectedRowIds, pendingCanonicalSelectionIds)) {
            pendingCanonicalSelectionIds = undefined;
          }
          return;
        }
        if (sameItemIds(selectedRowIds, canonicalSelectionIds)) {
          return;
        }
        const removed = [...canonicalSelectionIds].filter((id) => !selectedRowIds.has(id));
        const added = [...selectedRowIds].filter((id) => !canonicalSelectionIds.has(id));
        for (const rowId of removed) {
          const row = rows.find((candidate) => candidate.id === rowId);
          if (row) {
            state = {
              selectedThreadIds: reduceTaskSelection(state.selectedThreadIds, row, false),
            };
          }
        }
        for (const rowId of added) {
          const row = rows.find((candidate) => candidate.id === rowId);
          if (row) {
            state = {
              selectedThreadIds: reduceTaskSelection(state.selectedThreadIds, row, true),
            };
          }
        }
        canonicalSelectionIds = new Set(selectedTaskPickerItemIds(rows, state, "review"));
        if (!sameItemIds(selectedRowIds, canonicalSelectionIds)) {
          pendingCanonicalSelectionIds = new Set(canonicalSelectionIds);
          quickPick.selectedItems = pickerItemsForIds(canonicalSelectionIds, pickerItemsById);
        }
      }),
      quickPick.onDidAccept(() => {
        if (state.selectedThreadIds.length === 0) {
          quickPick.title = "Select at least one Codex task";
          return;
        }
        finish({ threadIds: [...state.selectedThreadIds] });
      }),
      quickPick.onDidHide(() => finish(undefined)),
    );
    render();
    quickPick.show();
  });
}

function toQuickPickItem(row: TaskPickerItem): TaskQuickPickItem {
  return {
    label: row.label,
    description: row.description,
    detail: row.detail,
    task: row,
  };
}

function pickerItemsForIds(
  ids: ReadonlySet<string>,
  itemsById: ReadonlyMap<string, TaskQuickPickItem>,
): TaskQuickPickItem[] {
  return [...ids]
    .map((id) => itemsById.get(id))
    .filter((item): item is TaskQuickPickItem => item !== undefined);
}

function sameItemIds(left: ReadonlySet<string>, right: ReadonlySet<string>): boolean {
  return left.size === right.size && [...left].every((id) => right.has(id));
}
