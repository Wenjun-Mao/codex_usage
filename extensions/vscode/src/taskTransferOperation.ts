import type { TaskPickerItem, TaskPickerSelection } from "./syncTaskPicker";
import type { TransferOperation } from "./transferPresentation";

export interface TaskTransferSelectionPort {
  loadRows(folder: string): Promise<TaskPickerItem[]>;
  chooseTasks(
    operation: TransferOperation,
    rows: TaskPickerItem[],
  ): Promise<TaskPickerSelection | undefined>;
}

export async function selectTaskTransferOperation(
  operation: TransferOperation,
  folder: string,
  port: TaskTransferSelectionPort,
): Promise<TaskPickerSelection | undefined> {
  const rows = await port.loadRows(folder);
  return chooseFreshTaskTransferSelection(operation, rows, port);
}

export function chooseFreshTaskTransferSelection(
  operation: TransferOperation,
  rows: TaskPickerItem[],
  port: Pick<TaskTransferSelectionPort, "chooseTasks">,
): Promise<TaskPickerSelection | undefined> {
  return port.chooseTasks(operation, rows);
}
