const assert = require("node:assert/strict");
const { PassThrough } = require("node:stream");
const EventEmitter = require("node:events");
const test = require("node:test");

const {
  StorageOperationCancelledError,
  runStorageOperation,
} = require("../out/storageOperationProcess");

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

const parseProgressLine = (line) => {
  const value = JSON.parse(line);
  return value.phase === "analyzing" ? value : undefined;
};

test("storage operation streams stderr progress and parses final stdout", async () => {
  const child = fakeChild();
  const progress = [];
  const output = [];
  const result = runStorageOperation({
    executablePath: "codex-usage", args: [], env: {}, cancellationToken: token(),
    parseProgressLine,
    parseResult: JSON.parse,
    onProgress: (event) => progress.push(event), onOutput: (text) => output.push(text),
    spawnProcess: () => child,
  });
  child.stderr.write('{"phase":"analyzing","completed_bytes":5}\n');
  child.stdout.end('{"source_bytes_read":5}');
  child.stderr.end();
  child.emit("close", 0);

  assert.equal((await result).source_bytes_read, 5);
  assert.equal(progress[0].phase, "analyzing");
  assert.doesNotMatch(output.join(""), /completed_bytes/);
});

test("storage operation cancellation terminates the complete process tree", async () => {
  const child = fakeChild();
  const cancellation = token();
  const result = runStorageOperation({
    executablePath: "codex-usage", args: [], env: {}, cancellationToken: cancellation,
    parseProgressLine, parseResult: JSON.parse,
    onProgress: () => undefined, onOutput: () => undefined, spawnProcess: () => child,
  });
  cancellation.cancel();
  await assert.rejects(result, StorageOperationCancelledError);
  assert.equal(child.killCalls, 1);
});
