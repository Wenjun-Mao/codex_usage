const assert = require("node:assert/strict");
const test = require("node:test");

let transactionModule;
let transactionModuleError;
try {
  transactionModule = require("../out/syncSetupTransaction");
} catch (error) {
  transactionModuleError = error;
}

const VALID_VERSION = 2;

function transactionApi() {
  assert.ifError(transactionModuleError);
  return transactionModule;
}

function deferred() {
  let resolve;
  const promise = new Promise((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function cloneState(state) {
  return {
    folder: state.folder,
    threadIds: state.threadIds === undefined ? undefined : [...state.threadIds],
    enabled: state.enabled,
    version: state.version,
  };
}

function validForSpawn(state) {
  return Boolean(
    state.version === VALID_VERSION &&
      state.folder &&
      Array.isArray(state.threadIds) &&
      state.threadIds.length > 0,
  );
}

class FakeAsyncSyncSetupStore {
  constructor(initial) {
    this.state = cloneState(initial);
    this.reads = [];
    this.writes = [];
    this.afterWriteStates = [];
    this.failures = new Map();
    this.blocks = new Map();
    this.callsByField = new Map();
  }

  fail(field, occurrence, message = `${field} write failed`) {
    this.failures.set(`${field}:${occurrence}`, new Error(message));
  }

  block(field, occurrence) {
    const entered = deferred();
    const release = deferred();
    this.blocks.set(`${field}:${occurrence}`, { entered, release });
    return { entered: entered.promise, release: release.resolve };
  }

  async read() {
    const snapshot = cloneState(this.state);
    this.reads.push(snapshot);
    return snapshot;
  }

  async writeVersion(value) {
    await this.#write("version", value);
  }

  async writeFolder(value) {
    await this.#write("folder", value);
  }

  async writeThreadIds(value) {
    await this.#write("threadIds", value === undefined ? undefined : [...value]);
  }

  async writeEnabled(value) {
    await this.#write("enabled", value);
  }

  async #write(field, value) {
    const occurrence = (this.callsByField.get(field) || 0) + 1;
    this.callsByField.set(field, occurrence);
    const key = `${field}:${occurrence}`;
    this.writes.push({ field, value });

    const block = this.blocks.get(key);
    if (block) {
      block.entered.resolve();
      await block.release.promise;
    }

    const failure = this.failures.get(key);
    if (failure) {
      throw failure;
    }

    this.state[field] = Array.isArray(value) ? [...value] : value;
    this.afterWriteStates.push(cloneState(this.state));
  }
}

function validState(name = "old", enabled = true) {
  return {
    folder: `/${name}`,
    threadIds: [`${name}-1`, `${name}-2`],
    enabled,
    version: VALID_VERSION,
  };
}

function nextSetup(name = "next", enabled = true) {
  return {
    folder: `/${name}`,
    threadIds: [`${name}-1`, `${name}-2`],
    enabled,
  };
}

test("setup exposes invalid version while a tuple write is suspended", async () => {
  const { SyncSetupMutationCoordinator } = transactionApi();
  const store = new FakeAsyncSyncSetupStore(validState());
  const folderWrite = store.block("folder", 1);
  const coordinator = new SyncSetupMutationCoordinator();

  const mutation = coordinator.commit(store, nextSetup());
  await folderWrite.entered;

  assert.equal(store.state.version, 0);
  assert.equal(validForSpawn(store.state), false);

  folderWrite.release();
  await mutation;
});

test("setup keeps the spawn gate closed between every forward write", async () => {
  const { SyncSetupMutationCoordinator } = transactionApi();
  const store = new FakeAsyncSyncSetupStore(validState());

  await new SyncSetupMutationCoordinator().commit(store, nextSetup());

  assert.deepEqual(
    store.writes.slice(0, 5).map(({ field, value }) => [field, value]),
    [
      ["version", 0],
      ["folder", "/next"],
      ["threadIds", ["next-1", "next-2"]],
      ["enabled", true],
      ["version", VALID_VERSION],
    ],
  );
  assert.deepEqual(store.afterWriteStates.map(validForSpawn), [false, false, false, false, true]);
  assert.deepEqual(store.state, { ...nextSetup(), version: VALID_VERSION });
});

for (const [name, field, occurrence] of [
  ["version invalidation", "version", 1],
  ["folder", "folder", 1],
  ["thread IDs", "threadIds", 1],
  ["enabled state", "enabled", 1],
  ["commit marker", "version", 2],
]) {
  test(`setup restores the complete previous tuple after ${name} rejection`, async () => {
    const { SyncSetupMutationCoordinator, SyncSetupMutationError } = transactionApi();
    const previous = validState();
    const store = new FakeAsyncSyncSetupStore(previous);
    store.fail(field, occurrence, `forward ${name} failed`);

    await assert.rejects(
      new SyncSetupMutationCoordinator().commit(store, nextSetup()),
      (error) => {
        assert.ok(error instanceof SyncSetupMutationError);
        assert.match(error.message, new RegExp(`forward ${name} failed`));
        assert.equal(error.rollbackErrors.length, 0);
        return true;
      },
    );

    assert.deepEqual(store.state, previous);
    assert.deepEqual(store.writes.slice(-5).map(({ field }) => field), [
      "version",
      "folder",
      "threadIds",
      "enabled",
      "version",
    ]);
  });
}

test("rollback failure preserves both errors and leaves selection invalid", async () => {
  const { SyncSetupMutationCoordinator, SyncSetupMutationError } = transactionApi();
  const store = new FakeAsyncSyncSetupStore(validState());
  store.fail("folder", 1, "forward folder failed");
  store.fail("threadIds", 1, "rollback IDs failed");

  await assert.rejects(
    new SyncSetupMutationCoordinator().commit(store, nextSetup()),
    (error) => {
      assert.ok(error instanceof SyncSetupMutationError);
      assert.match(error.message, /forward folder failed/);
      assert.match(error.message, /rollback IDs failed/);
      assert.equal(error.originalError.message, "forward folder failed");
      assert.deepEqual(error.rollbackErrors.map((rollbackError) => rollbackError.message), [
        "rollback IDs failed",
      ]);
      return true;
    },
  );

  assert.equal(store.state.version, 0);
  assert.equal(validForSpawn(store.state), false);
  assert.deepEqual(store.writes.at(-1), { field: "version", value: 0 });
});

test("failed final version restoration leaves the rolled-back tuple invalid", async () => {
  const { SyncSetupMutationCoordinator, SyncSetupMutationError } = transactionApi();
  const previous = validState();
  const store = new FakeAsyncSyncSetupStore(previous);
  store.fail("enabled", 1, "forward enabled failed");
  store.fail("version", 3, "rollback marker failed");

  await assert.rejects(
    new SyncSetupMutationCoordinator().commit(store, nextSetup()),
    (error) => {
      assert.ok(error instanceof SyncSetupMutationError);
      assert.match(error.message, /forward enabled failed/);
      assert.match(error.message, /rollback marker failed/);
      return true;
    },
  );

  assert.deepEqual(
    { folder: store.state.folder, threadIds: store.state.threadIds, enabled: store.state.enabled },
    { folder: previous.folder, threadIds: previous.threadIds, enabled: previous.enabled },
  );
  assert.equal(store.state.version, 0);
});

test("concurrent setup commits serialize without mixed tuples", async () => {
  const { SyncSetupMutationCoordinator } = transactionApi();
  const store = new FakeAsyncSyncSetupStore(validState());
  const firstFolderWrite = store.block("folder", 1);
  const coordinator = new SyncSetupMutationCoordinator();

  const first = coordinator.commit(store, nextSetup("first"));
  await firstFolderWrite.entered;
  const second = coordinator.commit(store, nextSetup("second", false));
  await Promise.resolve();

  assert.equal(store.reads.length, 1);
  assert.equal(coordinator.isMutating, true);

  firstFolderWrite.release();
  await Promise.all([first, second]);

  assert.deepEqual(store.reads, [validState(), { ...nextSetup("first"), version: VALID_VERSION }]);
  assert.deepEqual(store.state, { ...nextSetup("second", false), version: VALID_VERSION });
  assert.deepEqual(store.writes.map(({ field }) => field), [
    "version", "folder", "threadIds", "enabled", "version",
    "version", "folder", "threadIds", "enabled", "version",
  ]);
  assert.equal(coordinator.isMutating, false);
});

test("clear queued after setup starts only after setup commits and ends invalid", async () => {
  const { SyncSetupMutationCoordinator } = transactionApi();
  const store = new FakeAsyncSyncSetupStore(validState());
  const firstFolderWrite = store.block("folder", 1);
  const coordinator = new SyncSetupMutationCoordinator();

  const setup = coordinator.commit(store, nextSetup());
  await firstFolderWrite.entered;
  const clear = coordinator.clear(store);
  firstFolderWrite.release();
  await Promise.all([setup, clear]);

  assert.deepEqual(store.reads, [validState(), { ...nextSetup(), version: VALID_VERSION }]);
  assert.deepEqual(store.writes.slice(5).map(({ field, value }) => [field, value]), [
    ["version", 0],
    ["folder", undefined],
    ["threadIds", undefined],
    ["enabled", false],
  ]);
  assert.deepEqual(store.state, {
    folder: undefined,
    threadIds: undefined,
    enabled: false,
    version: 0,
  });
});

test("setup queued after clear reads the cleared tuple and publishes the new tuple", async () => {
  const { SyncSetupMutationCoordinator } = transactionApi();
  const store = new FakeAsyncSyncSetupStore(validState());
  const clearFolderWrite = store.block("folder", 1);
  const coordinator = new SyncSetupMutationCoordinator();

  const clear = coordinator.clear(store);
  await clearFolderWrite.entered;
  const setup = coordinator.commit(store, nextSetup());
  clearFolderWrite.release();
  await Promise.all([clear, setup]);

  assert.deepEqual(store.reads[1], {
    folder: undefined,
    threadIds: undefined,
    enabled: false,
    version: 0,
  });
  assert.deepEqual(store.state, { ...nextSetup(), version: VALID_VERSION });
});

test("enabled mutations share setup ordering and republish validity last", async () => {
  const { SyncSetupMutationCoordinator } = transactionApi();
  const store = new FakeAsyncSyncSetupStore(validState());
  const setupFolderWrite = store.block("folder", 1);
  const coordinator = new SyncSetupMutationCoordinator();

  const setup = coordinator.commit(store, nextSetup());
  await setupFolderWrite.entered;
  const pause = coordinator.setEnabled(store, false);
  setupFolderWrite.release();

  assert.equal(await pause, true);
  await setup;
  assert.deepEqual(store.state, { ...nextSetup(), enabled: false, version: VALID_VERSION });
  assert.deepEqual(store.writes.slice(-5).map(({ field }) => field), [
    "version",
    "folder",
    "threadIds",
    "enabled",
    "version",
  ]);
});

test("reconfiguration preserves enabled state from its queued previous tuple", async () => {
  const { SyncSetupMutationCoordinator } = transactionApi();
  const store = new FakeAsyncSyncSetupStore(validState());
  const coordinator = new SyncSetupMutationCoordinator();

  const pause = coordinator.setEnabled(store, false);
  const reconfigure = coordinator.commit(store, {
    folder: "/reconfigured",
    threadIds: ["reconfigured-1"],
  });
  await Promise.all([pause, reconfigure]);

  assert.deepEqual(store.reads[1], { ...validState(), enabled: false });
  assert.deepEqual(store.state, {
    folder: "/reconfigured",
    threadIds: ["reconfigured-1"],
    enabled: false,
    version: VALID_VERSION,
  });
});

test("whenIdle waits for every operation already queued", async () => {
  const { SyncSetupMutationCoordinator } = transactionApi();
  const store = new FakeAsyncSyncSetupStore(validState());
  const setupFolderWrite = store.block("folder", 1);
  const coordinator = new SyncSetupMutationCoordinator();

  const setup = coordinator.commit(store, nextSetup());
  await setupFolderWrite.entered;
  const clear = coordinator.clear(store);
  let idle = false;
  const queueIdle = coordinator.whenIdle().then(() => {
    idle = true;
  });
  await Promise.resolve();

  assert.equal(idle, false);
  setupFolderWrite.release();
  await Promise.all([setup, clear, queueIdle]);
  assert.equal(idle, true);
  assert.equal(store.state.version, 0);
});

test("resume queued after clear refuses to revalidate an empty tuple", async () => {
  const { SyncSetupMutationCoordinator } = transactionApi();
  const store = new FakeAsyncSyncSetupStore(validState());
  const coordinator = new SyncSetupMutationCoordinator();

  await coordinator.clear(store);
  const writesAfterClear = store.writes.length;

  assert.equal(await coordinator.setEnabled(store, true), false);
  assert.equal(store.writes.length, writesAfterClear);
  assert.equal(store.state.version, 0);
});
