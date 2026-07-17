export const TRANSFER_FOLDER_STATE_KEY = "syncDir";
export const OBSOLETE_TRANSFER_STATE_KEYS = ["syncThreadIds", "syncSelectionVersion"] as const;

export interface TaskTransferStateStore {
  readFolder(): string;
  readLegacyFolder(): string;
  writeFolder(value: string | undefined): Promise<void>;
  removeGlobalState(key: string): Promise<void>;
  obsoleteConfigurationScopes(): readonly string[];
  removeEnabledConfiguration(scope: string): Promise<void>;
}

export async function migrateTaskTransferState(
  store: TaskTransferStateStore,
  logError: (message: string) => void,
): Promise<void> {
  const folder = store.readFolder().trim();
  if (!folder) {
    const legacyFolder = store.readLegacyFolder().trim();
    if (legacyFolder) {
      try {
        await store.writeFolder(legacyFolder);
      } catch (error) {
        logError(cleanupError("transfer folder", error));
      }
    }
  }

  for (const key of OBSOLETE_TRANSFER_STATE_KEYS) {
    try {
      await store.removeGlobalState(key);
    } catch (error) {
      logError(cleanupError(`global state ${key}`, error));
    }
  }

  let scopes: readonly string[] = [];
  try {
    scopes = store.obsoleteConfigurationScopes();
  } catch (error) {
    logError(cleanupError("sync.enabled configuration scopes", error));
  }
  for (const scope of scopes) {
    try {
      await store.removeEnabledConfiguration(scope);
    } catch (error) {
      logError(cleanupError(`sync.enabled configuration at ${scope}`, error));
    }
  }
}

function cleanupError(target: string, error: unknown): string {
  const detail = error instanceof Error ? error.message : String(error);
  return `Could not remove obsolete Task Transfer ${target}: ${detail}`;
}
