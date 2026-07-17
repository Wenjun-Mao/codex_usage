import * as vscode from "vscode";
import {
  reduceTaskSelection,
  selectedPickerItemIds,
  type TaskPickerItem,
} from "./syncTaskPicker";
import type { TransferOperation } from "./transferPresentation";

type TaskQuickPickItem = vscode.QuickPickItem & { task?: TaskPickerItem };

export function showTaskTransferPicker(
  operation: TransferOperation,
  rows: TaskPickerItem[],
  initialThreadIds: readonly string[],
): Promise<string[] | undefined> {
  const quickPick = vscode.window.createQuickPick<TaskQuickPickItem>();
  const pickerItems = rows.map((row): TaskQuickPickItem => {
    if (row.kind === "separator") {
      return { label: row.label, kind: vscode.QuickPickItemKind.Separator };
    }
    return {
      label: row.label,
      description: row.description,
      detail: row.detail,
      task: row,
    };
  });
  const pickerItemsById = new Map(
    pickerItems.flatMap((item) => (item.task ? [[item.task.id, item] as const] : [])),
  );
  const rowsById = new Map(rows.map((row) => [row.id, row]));
  let selectedThreadIds = [...initialThreadIds];
  let previousSelectedRowIds = new Set(selectedPickerItemIds(rows, selectedThreadIds));
  let applyingCanonicalSelection = false;
  let settled = false;

  const title = pickerTitle(operation);
  quickPick.title = title;
  quickPick.placeholder = "Select tasks or toggle a project to select all of its tasks";
  quickPick.canSelectMany = true;
  quickPick.matchOnDescription = true;
  quickPick.matchOnDetail = true;
  quickPick.items = pickerItems;
  quickPick.selectedItems = pickerItemsForIds(previousSelectedRowIds, pickerItemsById);

  return new Promise((resolve) => {
    const disposables: vscode.Disposable[] = [];
    const finish = (value: string[] | undefined): void => {
      if (settled) {
        return;
      }
      settled = true;
      for (const disposable of disposables) {
        disposable.dispose();
      }
      quickPick.dispose();
      resolve(value);
    };

    disposables.push(
      quickPick.onDidChangeSelection((selectedItems) => {
        if (applyingCanonicalSelection) {
          return;
        }
        const nextSelectedRowIds = new Set(
          selectedItems.flatMap((item) => (item.task ? [item.task.id] : [])),
        );
        const removed = [...previousSelectedRowIds].filter((id) => !nextSelectedRowIds.has(id));
        const added = [...nextSelectedRowIds].filter((id) => !previousSelectedRowIds.has(id));
        for (const rowId of removed) {
          const row = rowsById.get(rowId);
          if (row) {
            selectedThreadIds = reduceTaskSelection(selectedThreadIds, row, false);
          }
        }
        for (const rowId of added) {
          const row = rowsById.get(rowId);
          if (row) {
            selectedThreadIds = reduceTaskSelection(selectedThreadIds, row, true);
          }
        }
        previousSelectedRowIds = new Set(selectedPickerItemIds(rows, selectedThreadIds));
        applyingCanonicalSelection = true;
        quickPick.selectedItems = pickerItemsForIds(previousSelectedRowIds, pickerItemsById);
        applyingCanonicalSelection = false;
        if (selectedThreadIds.length > 0) {
          quickPick.title = title;
        }
      }),
      quickPick.onDidAccept(() => {
        if (selectedThreadIds.length === 0) {
          quickPick.title = "Select at least one Codex task";
          return;
        }
        finish([...selectedThreadIds]);
      }),
      quickPick.onDidHide(() => finish(undefined)),
    );
    quickPick.show();
  });
}

function pickerTitle(operation: TransferOperation): string {
  if (operation === "import") {
    return "Select tasks to import";
  }
  if (operation === "export") {
    return "Select tasks to export";
  }
  return "Select tasks to review";
}

function pickerItemsForIds(
  ids: ReadonlySet<string>,
  itemsById: ReadonlyMap<string, TaskQuickPickItem>,
): TaskQuickPickItem[] {
  return [...ids]
    .map((id) => itemsById.get(id))
    .filter((item): item is TaskQuickPickItem => item !== undefined);
}
