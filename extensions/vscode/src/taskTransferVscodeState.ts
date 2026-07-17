import {
  TRANSFER_FOLDER_STATE_KEY,
  type TaskTransferStateStore,
} from "./taskTransferState";

export interface VscodeGlobalStateLike {
  get<T>(key: string, defaultValue: T): T;
  update(key: string, value: unknown): PromiseLike<void>;
}

export interface VscodeConfigurationInspection {
  globalValue?: unknown;
  workspaceValue?: unknown;
  workspaceFolderValue?: unknown;
}

export interface VscodeConfigurationLike<TTarget> {
  get<T>(key: string, defaultValue: T): T;
  inspect<T>(key: string): VscodeConfigurationInspection | undefined;
  update(key: string, value: unknown, target: TTarget): PromiseLike<void>;
}

export interface VscodeWorkspaceFolderLike<TResource extends { fsPath: string }> {
  uri: TResource;
}

export interface TaskTransferVscodeStateAdapter<
  TTarget,
  TResource extends { fsPath: string },
> {
  globalState: VscodeGlobalStateLike;
  configuration(resource?: TResource): VscodeConfigurationLike<TTarget>;
  workspaceFolders(): readonly VscodeWorkspaceFolderLike<TResource>[];
  targets: {
    global: TTarget;
    workspace: TTarget;
    workspaceFolder: TTarget;
  };
}

export function readTaskTransferFolder(globalState: VscodeGlobalStateLike): string {
  const value = globalState.get<unknown>(TRANSFER_FOLDER_STATE_KEY, "");
  return typeof value === "string" ? value.trim() : "";
}

export function createTaskTransferVscodeStateStore<
  TTarget,
  TResource extends { fsPath: string },
>(adapter: TaskTransferVscodeStateAdapter<TTarget, TResource>): TaskTransferStateStore {
  const baseConfiguration = adapter.configuration();
  return {
    readFolder: () => readTaskTransferFolder(adapter.globalState),
    readLegacyFolder: () => baseConfiguration.get<string>("sync.dir", ""),
    async writeFolder(value) {
      await adapter.globalState.update(TRANSFER_FOLDER_STATE_KEY, value);
    },
    async removeGlobalState(key) {
      await adapter.globalState.update(key, undefined);
    },
    obsoleteConfigurationScopes() {
      const scopes: string[] = [];
      const base = baseConfiguration.inspect<boolean>("sync.enabled");
      if (base?.globalValue !== undefined) {
        scopes.push("global");
      }
      if (base?.workspaceValue !== undefined) {
        scopes.push("workspace");
      }
      for (const folder of adapter.workspaceFolders()) {
        const inspected = adapter.configuration(folder.uri).inspect<boolean>("sync.enabled");
        if (inspected?.workspaceFolderValue !== undefined) {
          scopes.push(folderScope(folder.uri.fsPath));
        }
      }
      return scopes;
    },
    async removeEnabledConfiguration(scope) {
      if (scope === "global") {
        await baseConfiguration.update("sync.enabled", undefined, adapter.targets.global);
        return;
      }
      if (scope === "workspace") {
        await baseConfiguration.update("sync.enabled", undefined, adapter.targets.workspace);
        return;
      }
      const folderPath = scope.slice("folder:".length);
      const folder = adapter.workspaceFolders().find((item) => item.uri.fsPath === folderPath);
      if (!folder) {
        throw new Error(`Workspace folder is no longer available: ${folderPath}`);
      }
      await adapter.configuration(folder.uri).update(
        "sync.enabled",
        undefined,
        adapter.targets.workspaceFolder,
      );
    },
  };
}

function folderScope(folderPath: string): string {
  return `folder:${folderPath}`;
}
