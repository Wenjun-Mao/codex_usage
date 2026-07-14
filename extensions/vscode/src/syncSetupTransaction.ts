export const VALID_SYNC_SELECTION_VERSION = 2;

export type SyncSetupState = {
  folder: string | undefined;
  threadIds: string[] | undefined;
  enabled: boolean;
  version: number;
};

export type CommittedSyncSetup = Pick<SyncSetupState, "folder" | "threadIds"> & {
  enabled?: boolean;
};

export interface AsyncSyncSetupStore {
  read(): Promise<SyncSetupState>;
  writeVersion(value: number): Promise<void>;
  writeFolder(value: string | undefined): Promise<void>;
  writeThreadIds(value: string[] | undefined): Promise<void>;
  writeEnabled(value: boolean): Promise<void>;
}

export class SyncSetupMutationError extends Error {
  readonly originalError: Error;
  readonly rollbackErrors: Error[];

  constructor(originalError: Error, rollbackErrors: Error[]) {
    const rollbackContext = rollbackErrors.length > 0
      ? ` Rollback failed: ${rollbackErrors.map((error) => error.message).join("; ")}`
      : " Previous sync setup was restored.";
    super(`Sync setup mutation failed: ${originalError.message}.${rollbackContext}`);
    this.name = "SyncSetupMutationError";
    this.originalError = originalError;
    this.rollbackErrors = rollbackErrors;
  }
}

export class SyncSetupMutationCoordinator {
  private tail: Promise<void> = Promise.resolve();
  private pendingCount = 0;

  get isMutating(): boolean {
    return this.pendingCount > 0;
  }

  commit(store: AsyncSyncSetupStore, next: CommittedSyncSetup): Promise<void> {
    return this.enqueue(async () => {
      const previous = cloneState(await store.read());
      await applyMutation(store, previous, {
        folder: next.folder,
        threadIds: cloneThreadIds(next.threadIds),
        enabled: next.enabled ?? previous.enabled,
        version: VALID_SYNC_SELECTION_VERSION,
      });
    });
  }

  clear(store: AsyncSyncSetupStore): Promise<void> {
    return this.enqueue(async () => {
      const previous = cloneState(await store.read());
      await applyMutation(store, previous, {
        folder: undefined,
        threadIds: undefined,
        enabled: false,
        version: 0,
      });
    });
  }

  setEnabled(store: AsyncSyncSetupStore, enabled: boolean): Promise<boolean> {
    return this.enqueue(async () => {
      const previous = cloneState(await store.read());
      if (enabled && !isValidSelection(previous)) {
        return false;
      }
      await applyMutation(store, previous, {
        ...previous,
        enabled,
        version: previous.version === VALID_SYNC_SELECTION_VERSION
          ? VALID_SYNC_SELECTION_VERSION
          : 0,
      });
      return true;
    });
  }

  whenIdle(): Promise<void> {
    return this.tail;
  }

  private enqueue<T>(operation: () => Promise<T>): Promise<T> {
    this.pendingCount += 1;
    const result = this.tail.then(operation);
    this.tail = result.then(
      () => undefined,
      () => undefined,
    );
    void result.then(
      () => {
        this.pendingCount -= 1;
      },
      () => {
        this.pendingCount -= 1;
      },
    );
    return result;
  }
}

async function applyMutation(
  store: AsyncSyncSetupStore,
  previous: SyncSetupState,
  next: SyncSetupState,
): Promise<void> {
  try {
    await store.writeVersion(0);
    await store.writeFolder(next.folder);
    await store.writeThreadIds(cloneThreadIds(next.threadIds));
    await store.writeEnabled(next.enabled);
    if (next.version === VALID_SYNC_SELECTION_VERSION) {
      await store.writeVersion(VALID_SYNC_SELECTION_VERSION);
    }
  } catch (error) {
    const originalError = asError(error);
    const rollbackErrors = await rollbackMutation(store, previous);
    throw new SyncSetupMutationError(originalError, rollbackErrors);
  }
}

async function rollbackMutation(
  store: AsyncSyncSetupStore,
  previous: SyncSetupState,
): Promise<Error[]> {
  const rollbackErrors: Error[] = [];
  await captureRollbackError(rollbackErrors, () => store.writeVersion(0));
  await captureRollbackError(rollbackErrors, () => store.writeFolder(previous.folder));
  await captureRollbackError(
    rollbackErrors,
    () => store.writeThreadIds(cloneThreadIds(previous.threadIds)),
  );
  await captureRollbackError(rollbackErrors, () => store.writeEnabled(previous.enabled));

  if (rollbackErrors.length === 0 && previous.version === VALID_SYNC_SELECTION_VERSION) {
    await captureRollbackError(
      rollbackErrors,
      () => store.writeVersion(VALID_SYNC_SELECTION_VERSION),
    );
  }

  if (rollbackErrors.length > 0) {
    await captureRollbackError(rollbackErrors, () => store.writeVersion(0));
  }
  return rollbackErrors;
}

async function captureRollbackError(
  rollbackErrors: Error[],
  operation: () => Promise<void>,
): Promise<void> {
  try {
    await operation();
  } catch (error) {
    rollbackErrors.push(asError(error));
  }
}

function cloneState(state: SyncSetupState): SyncSetupState {
  return {
    folder: state.folder,
    threadIds: cloneThreadIds(state.threadIds),
    enabled: state.enabled,
    version: state.version,
  };
}

function cloneThreadIds(threadIds: string[] | undefined): string[] | undefined {
  return threadIds === undefined ? undefined : [...threadIds];
}

function isValidSelection(state: SyncSetupState): boolean {
  return Boolean(
    state.version === VALID_SYNC_SELECTION_VERSION &&
    state.folder?.trim() &&
    state.threadIds &&
    state.threadIds.length > 0,
  );
}

function asError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error));
}
