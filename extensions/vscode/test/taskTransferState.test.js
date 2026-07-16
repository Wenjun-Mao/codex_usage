const assert = require("node:assert/strict");
const test = require("node:test");

const {
  OBSOLETE_TRANSFER_STATE_KEYS,
  TRANSFER_FOLDER_STATE_KEY,
  migrateTaskTransferState,
} = require("../out/taskTransferState");

function fakeStore(options = {}) {
  let folder = options.folder ?? "";
  const writes = options.writes ?? [];
  const removedState = options.removedState ?? [];
  const removedScopes = options.removedScopes ?? [];
  return {
    readFolder: () => folder,
    readLegacyFolder() {
      if (options.failLegacyRead) {
        throw new Error("legacy configuration is unavailable");
      }
      return options.legacyFolder ?? "";
    },
    async writeFolder(value) {
      writes.push(value);
      folder = value ?? "";
    },
    async removeGlobalState(key) {
      removedState.push(key);
      if (key === options.failStateKey) {
        throw new Error(`cannot remove ${key}`);
      }
    },
    obsoleteConfigurationScopes: () => options.scopes ?? ["global", "workspace", "folder:/repo"],
    async removeEnabledConfiguration(scope) {
      removedScopes.push(scope);
      if (scope === options.failScope) {
        throw new Error(`cannot remove ${scope}`);
      }
    },
  };
}

test("folder state keeps the stable syncDir key and names every obsolete global key", () => {
  assert.equal(TRANSFER_FOLDER_STATE_KEY, "syncDir");
  assert.deepEqual([...OBSOLETE_TRANSFER_STATE_KEYS], ["syncThreadIds", "syncSelectionVersion"]);
});

test("migration preserves the folder and removes obsolete state and enabled scopes", async () => {
  const removedState = [];
  const removedScopes = [];
  const writes = [];
  const errors = [];
  const store = fakeStore({
    folder: "/transfer",
    legacyFolder: "/legacy",
    writes,
    removedState,
    removedScopes,
  });

  await migrateTaskTransferState(store, (message) => errors.push(message));

  assert.deepEqual(writes, []);
  assert.deepEqual(removedState, ["syncThreadIds", "syncSelectionVersion"]);
  assert.deepEqual(removedScopes, ["global", "workspace", "folder:/repo"]);
  assert.deepEqual(errors, []);
});

test("migration adopts a trimmed legacy folder only when the stable folder is empty", async () => {
  const writes = [];
  const store = fakeStore({ folder: "", legacyFolder: "  /legacy  ", writes });

  await migrateTaskTransferState(store, () => undefined);

  assert.deepEqual(writes, ["/legacy"]);
});

test("migration does not consult legacy configuration when the stable folder exists", async () => {
  const store = fakeStore({ folder: "/transfer", failLegacyRead: true });

  await assert.doesNotReject(migrateTaskTransferState(store, () => undefined));
});

test("migration is idempotent after adopting the legacy folder", async () => {
  const writes = [];
  const store = fakeStore({ folder: "", legacyFolder: "/legacy", writes });

  await migrateTaskTransferState(store, () => undefined);
  await migrateTaskTransferState(store, () => undefined);

  assert.deepEqual(writes, ["/legacy"]);
});

test("cleanup failures are logged independently and do not reject activation", async () => {
  const errors = [];
  const store = fakeStore({
    failStateKey: "syncThreadIds",
    failScope: "workspace",
  });

  await assert.doesNotReject(
    migrateTaskTransferState(store, (message) => errors.push(message)),
  );
  assert.equal(errors.length, 2);
  assert.match(errors[0], /syncThreadIds/);
  assert.match(errors[1], /workspace/);
});
