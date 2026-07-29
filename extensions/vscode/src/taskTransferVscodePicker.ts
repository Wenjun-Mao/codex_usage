import * as vscode from "vscode";
import {
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

export const TRANSFER_PICKER_COPY = {
  import: {
    title: "Import Tasks: Choose One Project",
    placeholder: "One project per import. All tasks start selected.",
  },
  export: {
    title: "Export Tasks: Choose One Project",
    placeholder: "One project per export. All tasks start selected.",
  },
  review: {
    title: "Review Tasks Across Projects",
    placeholder: "Select any tasks to compare without copying files.",
  },
} as const;

export function showTaskTransferPicker(
  operation: TransferOperation,
  rows: TaskPickerItem[],
): Promise<TaskPickerSelection | undefined> {
  const quickPick = vscode.window.createQuickPick<TaskQuickPickItem>();
  let state = initialTaskPickerSelection(operation);
  let canonicalSelectionIds = new Set<string>();
  let pickerItemsById = new Map<string, TaskQuickPickItem>();
  let pendingCanonicalSelectionIds: ReadonlySet<string> | undefined;
  let settled = false;

  quickPick.title = TRANSFER_PICKER_COPY[operation].title;
  quickPick.placeholder = TRANSFER_PICKER_COPY[operation].placeholder;
  quickPick.canSelectMany = true;
  quickPick.matchOnDescription = true;
  quickPick.matchOnDetail = true;

  const render = (): void => {
    const pickerItems = visibleTaskPickerItems(rows, state, operation).map((row) => ({
      label: row.label,
      description: activeProjectDescription(row, state, operation),
      detail: row.detail,
      task: row,
    }));
    pickerItemsById = new Map(
      pickerItems.flatMap((item) => (item.task ? [[item.task.id, item] as const] : [])),
    );
    canonicalSelectionIds = new Set(selectedTaskPickerItemIds(rows, state, operation));
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
        const previousActiveProjectKey = state.activeProjectKey;
        const removed = [...canonicalSelectionIds].filter((id) => !selectedRowIds.has(id));
        const added = [...selectedRowIds].filter((id) => !canonicalSelectionIds.has(id));
        for (const rowId of removed) {
          const row = rows.find((candidate) => candidate.id === rowId);
          if (row) {
            state = reducePickerSelection(state, row, false, operation);
          }
        }
        for (const rowId of added) {
          const row = rows.find((candidate) => candidate.id === rowId);
          if (row) {
            state = reducePickerSelection(state, row, true, operation);
          }
        }
        if (state.activeProjectKey !== previousActiveProjectKey) {
          render();
          return;
        }
        canonicalSelectionIds = new Set(selectedTaskPickerItemIds(rows, state, operation));
        if (!sameItemIds(selectedRowIds, canonicalSelectionIds)) {
          pendingCanonicalSelectionIds = new Set(canonicalSelectionIds);
          quickPick.selectedItems = pickerItemsForIds(canonicalSelectionIds, pickerItemsById);
        }
      }),
      quickPick.onDidAccept(() => {
        if (!hasValidPickerSelection(state, operation)) {
          quickPick.title = "Select at least one Codex task";
          return;
        }
        finish({
          ...(operation === "review" ? {} : { projectKey: state.activeProjectKey }),
          threadIds: [...state.selectedThreadIds],
        });
      }),
      quickPick.onDidHide(() => finish(undefined)),
    );
    render();
    quickPick.show();
  });
}

function reducePickerSelection(
  state: TaskPickerSelectionState,
  row: TaskPickerItem,
  selected: boolean,
  operation: TransferOperation,
): TaskPickerSelectionState {
  if (operation !== "review") {
    return reduceTransferTaskSelection(state, row, selected);
  }
  return {
    selectedThreadIds: reduceTaskSelection(state.selectedThreadIds, row, selected),
  };
}

function activeProjectDescription(
  row: TaskPickerItem,
  state: TaskPickerSelectionState,
  operation: TransferOperation,
): string {
  return operation !== "review" && row.kind === "project" && row.projectKey === state.activeProjectKey
    ? "Selected project"
    : row.description;
}

function hasValidPickerSelection(
  state: TaskPickerSelectionState,
  operation: TransferOperation,
): boolean {
  return state.selectedThreadIds.length > 0 && (operation === "review" || state.activeProjectKey !== undefined);
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
