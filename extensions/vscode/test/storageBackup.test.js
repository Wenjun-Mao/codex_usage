const assert = require("node:assert/strict");
const test = require("node:test");

const { StorageBackupController } = require("../out/storageBackup");
const { BackupCancelledError } = require("../out/storageBackupProcess");

const tree = {
  rootTaskId: "root-1234567890abcdef", title: "Important Task", projectKey: "repo-a", projectLabel: "Repo A",
  totalBytes: 4096, rootBytes: 3072, descendantBytes: 1024, descendantCount: 1, physicalFileCount: 2,
  hasMissingRoot: false, hasRelationshipCycle: false, duplicateFileCount: 0, metadataDiagnostics: [],
  recoveryReady: true,
};

function port(overrides = {}) {
  const calls = { execute: [], notify: [], logs: [] };
  return {
    calls,
    loadSnapshot: async () => ({ projects: [{ projectKey: "repo-a", projectLabel: "Repo A", trees: [tree] }], trees: [tree] }),
    chooseTree: async () => tree,
    chooseCompression: async () => "maximum",
    confirmSensitiveData: async () => true,
    chooseOutput: async () => "/tmp/important.codex-task-backup",
    outputExists: async () => false,
    confirmReplace: async () => true,
    execute: async (request) => {
      calls.execute.push(request);
      request.onProgress({ event: "progress", phase: "compressing", completedBytes: 1, totalBytes: 2 });
      return {
        archivePath: request.outputPath, sourceBytes: 4096, archiveBytes: 1024, fileCount: 2,
        recoveryReady: true, warnings: [], archiveSha256: "abc", compression: request.compression,
      };
    },
    reportProgress: () => undefined,
    log: (message) => calls.logs.push(message),
    notify: (kind, message) => calls.notify.push({ kind, message }),
    ...overrides,
  };
}

test("row invocation validates against a fresh snapshot then backs up with replace false", async () => {
  const fake = port();
  await new StorageBackupController(fake).backup(tree.rootTaskId);
  assert.equal(fake.calls.execute.length, 1);
  assert.equal(fake.calls.execute[0].treeId, tree.rootTaskId);
  assert.equal(fake.calls.execute[0].replace, false);
  assert.match(fake.calls.notify.at(-1).message, /Verified backup created/);
});

test("global invocation picks a tree and only passes replace after confirmation", async () => {
  const fake = port({ outputExists: async () => true });
  await new StorageBackupController(fake).backup();
  assert.equal(fake.calls.execute[0].replace, true);
});

test("stale row IDs do not open backup prompts and salvage is clearly distinguished", async () => {
  const fake = port({
    execute: async (request) => ({
      archivePath: request.outputPath, sourceBytes: 4096, archiveBytes: 1024, fileCount: 2,
      recoveryReady: false, warnings: ["cycle"], archiveSha256: "abc", compression: request.compression,
    }),
  });
  const controller = new StorageBackupController(fake);
  await controller.backup("missing");
  assert.equal(fake.calls.execute.length, 0);
  assert.match(fake.calls.notify.at(-1).message, /no longer available/);
  await controller.backup(tree.rootTaskId);
  assert.equal(fake.calls.notify.at(-1).kind, "warning");
  assert.match(fake.calls.notify.at(-1).message, /salvage backup/);
});

test("malformed row arguments never fall through to the global picker", async () => {
  const fake = port();
  await new StorageBackupController(fake).backup([tree.rootTaskId]);
  assert.equal(fake.calls.execute.length, 0);
  assert.match(fake.calls.notify.at(-1).message, /Invalid Task Storage backup action/);
});

test("cancellation reports no final archive rather than a failed or successful backup", async () => {
  const fake = port({ execute: async () => { throw new BackupCancelledError(); } });
  await new StorageBackupController(fake).backup(tree.rootTaskId);
  assert.equal(fake.calls.notify.at(-1).kind, "info");
  assert.match(fake.calls.notify.at(-1).message, /cancelled/);
  assert.doesNotMatch(fake.calls.notify.at(-1).message, /failed/i);
});
