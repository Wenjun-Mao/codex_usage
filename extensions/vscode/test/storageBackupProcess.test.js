const assert = require("node:assert/strict");
const { PassThrough } = require("node:stream");
const EventEmitter = require("node:events");
const test = require("node:test");

const { BackupCancelledError, runBackupProcess } = require("../out/storageBackupProcess");

function fakeChild() {
  const child = new EventEmitter();
  child.stdout = new PassThrough();
  child.stderr = new PassThrough();
  child.stdin = new PassThrough();
  child.pid = undefined;
  child.killCalls = 0;
  child.kill = () => {
    child.killCalls += 1;
    child.emit("close", null);
    return true;
  };
  return child;
}

function token() {
  const listeners = new Set();
  return {
    isCancellationRequested: false,
    onCancellationRequested(listener) {
      listeners.add(listener);
      return { dispose: () => listeners.delete(listener) };
    },
    cancel() {
      for (const listener of listeners) listener();
    },
  };
}

test("backup process streams stderr progress and parses one final stdout result", async () => {
  const child = fakeChild();
  const progress = [];
  const output = [];
  const result = runBackupProcess({
    executablePath: "codex-usage", args: [], env: {}, cancellationToken: token(),
    onProgress: (event) => progress.push(event), onOutput: (text) => output.push(text),
    spawnProcess: () => child,
  });
  child.stderr.write('{"event":"progress","phase":"compressing","completed_bytes":5,"total_bytes":10}\n');
  child.stdout.end(JSON.stringify({
    archive_path: "/tmp/task", source_bytes: 10, archive_bytes: 5, file_count: 1,
    recovery_ready: true, warnings: [], archive_sha256: "abc", compression: "maximum",
  }));
  child.stderr.end();
  child.emit("close", 0);
  assert.equal((await result).archiveBytes, 5);
  assert.equal(progress[0].phase, "compressing");
  assert.doesNotMatch(output.join(""), /completed_bytes/);
});

test("backup cancellation terminates the complete spawned process tree", async () => {
  const child = fakeChild();
  const cancellation = token();
  const result = runBackupProcess({
    executablePath: "codex-usage", args: [], env: {}, cancellationToken: cancellation,
    onProgress: () => undefined, onOutput: () => undefined, spawnProcess: () => child,
  });
  cancellation.cancel();
  await assert.rejects(result, BackupCancelledError);
  assert.equal(child.killCalls, 1);
});
