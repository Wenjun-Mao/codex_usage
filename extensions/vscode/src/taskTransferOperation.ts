import type { TaskPickerItem } from "./syncTaskPicker";
import type { TransferOperation } from "./transferPresentation";

export interface TaskTransferSelectionPort {
  loadRows(folder: string): Promise<TaskPickerItem[]>;
  chooseTasks(
    operation: TransferOperation,
    rows: TaskPickerItem[],
    initialThreadIds: readonly string[],
  ): Promise<string[] | undefined>;
}

export async function selectTaskTransferOperation(
  operation: TransferOperation,
  folder: string,
  port: TaskTransferSelectionPort,
): Promise<string[] | undefined> {
  const rows = await port.loadRows(folder);
  return chooseFreshTaskTransferSelection(operation, rows, port);
}

export function chooseFreshTaskTransferSelection(
  operation: TransferOperation,
  rows: TaskPickerItem[],
  port: Pick<TaskTransferSelectionPort, "chooseTasks">,
): Promise<string[] | undefined> {
  return port.chooseTasks(operation, rows, []);
}
