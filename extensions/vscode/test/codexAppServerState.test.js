const assert = require("node:assert/strict");
const test = require("node:test");

const { registerCodexTasks } = require("../out/codexAppServer");
const {
  assertCleanedUp,
  baseOptions,
  createFakeChild,
  createSuccessChild,
  installControllableTimers,
  officialCandidate,
  pathCandidate,
  spawnRecorder,
} = require("./codexAppServerHarness");

test("handles synchronous task responses only after the complete batch is staged", async () => {
  const child = createFakeChild((message, process) => {
    if (message.method === "initialize") {
      queueMicrotask(() => process.sendStdout('{"id":1,"result":{}}\n'));
    }
  });
  child.interceptStdinWrite(({ child: process, message, write }) => {
    if (process.stdinEndCalls > 0) {
      return true;
    }
    const written = write();
    if (message.method === "thread/read") {
      process.emitStdoutSynchronously(
        `${JSON.stringify({ id: message.id, result: { thread: { id: message.params.threadId } } })}\n`,
      );
    }
    return written;
  });
  const recorder = spawnRecorder(() => child);

  const result = await registerCodexTasks(
    baseOptions({
      threadIds: ["task-a", "task-b"],
      spawnProcess: recorder.spawnProcess,
    }),
  );

  assert.deepEqual(result.registeredThreadIds, ["task-a", "task-b"]);
  assert.deepEqual(
    child.messages.filter(({ method }) => method === "thread/read").map(({ params }) => params.threadId),
    ["task-a", "task-b"],
  );
  assertCleanedUp(child);
});

test("does not fall back when the first task write reports a synchronous process failure", async () => {
  const firstChild = createFakeChild((message, process) => {
    if (message.method === "initialize") {
      queueMicrotask(() => process.sendStdout('{"id":1,"result":{}}\n'));
    }
  });
  let failedWrite = false;
  firstChild.interceptStdinWrite(({ child, message, write }) => {
    if (child.stdinEndCalls > 0) {
      return true;
    }
    const written = write();
    if (message.method === "thread/read" && !failedWrite) {
      failedWrite = true;
      child.emit("error", new Error("write failed after send"));
    }
    return written;
  });
  const fallbackChild = createSuccessChild(["task-a", "task-b"]);
  const recorder = spawnRecorder((_path, index) => (index === 0 ? firstChild : fallbackChild));

  const result = await registerCodexTasks(
    baseOptions({
      candidates: [officialCandidate, pathCandidate],
      threadIds: ["task-a", "task-b"],
      spawnProcess: recorder.spawnProcess,
    }),
  );

  assert.equal(recorder.calls.length, 1);
  assert.deepEqual(result.registeredThreadIds, []);
  assert.deepEqual(result.failures.map(({ threadId }) => threadId), ["task-a", "task-b"]);
  assert.ok(result.failures.every(({ message }) => /write failed after send/.test(message)));
  assert.deepEqual(result.executable, officialCandidate);
  assertCleanedUp(firstChild);
});

test("falls back without dispatch when initialized writing fails synchronously", async () => {
  const firstChild = createFakeChild((message, process) => {
    if (message.method === "initialize") {
      queueMicrotask(() => process.sendStdout('{"id":1,"result":{}}\n'));
    }
  });
  const attemptedMethods = [];
  firstChild.interceptStdinWrite(({ child, message, write }) => {
    attemptedMethods.push(message.method);
    if (child.stdinEndCalls > 0) {
      return true;
    }
    const written = write();
    if (message.method === "initialized") {
      child.emit("error", new Error("initialized write failed"));
    }
    return written;
  });
  const fallbackChild = createSuccessChild(["task-a", "task-b"]);
  const recorder = spawnRecorder((_path, index) => (index === 0 ? firstChild : fallbackChild));
  const timerController = installControllableTimers();

  try {
    const result = await registerCodexTasks(
      baseOptions({
        candidates: [officialCandidate, pathCandidate],
        threadIds: ["task-a", "task-b"],
        spawnProcess: recorder.spawnProcess,
      }),
    );

    assert.deepEqual(attemptedMethods, ["initialize", "initialized"]);
    assert.equal(firstChild.messages.some(({ method }) => method === "thread/read"), false);
    assert.equal(recorder.calls.length, 2);
    assert.deepEqual(result.registeredThreadIds, ["task-a", "task-b"]);
    assert.deepEqual(result.executable, pathCandidate);
    assert.ok(timerController.timers.every(({ cleared }) => cleared));
    assertCleanedUp(firstChild);
    assertCleanedUp(fallbackChild);
  } finally {
    timerController.restore();
  }
});

test("fails an unterminated stdout frame as soon as its byte limit is exceeded", async () => {
  const secret = "x".repeat(33);
  const child = createFakeChild((message, process) => {
    if (message.method === "initialize") {
      queueMicrotask(() => process.sendStdout('{"id":1,"result":{}}\n'));
    } else if (message.method === "thread/read") {
      queueMicrotask(() => process.sendStdout(secret));
    }
  });
  const recorder = spawnRecorder(() => child);

  const result = await registerCodexTasks(
    baseOptions({
      candidates: [officialCandidate, pathCandidate],
      spawnProcess: recorder.spawnProcess,
      protocolFrameBytes: 32,
      requestTimeoutMs: 200,
      batchTimeoutMs: 300,
    }),
  );

  assert.equal(recorder.calls.length, 1);
  assert.match(result.failures[0].message, /stdout frame exceeded 32 bytes/i);
  assert.doesNotMatch(JSON.stringify(result), new RegExp(secret));
  assertCleanedUp(child);
});

test("ignores a late response for a timed-out request while another request succeeds", async () => {
  const child = createFakeChild((message, process) => {
    if (message.method === "initialize") {
      queueMicrotask(() => process.sendStdout('{"id":1,"result":{}}\n'));
    }
  });
  const recorder = spawnRecorder(() => child);
  const timerController = installControllableTimers();

  try {
    const registration = registerCodexTasks(
      baseOptions({
        threadIds: ["task-a", "task-b"],
        spawnProcess: recorder.spawnProcess,
        requestTimeoutMs: 10,
        batchTimeoutMs: 80,
      }),
    );
    await Promise.resolve();
    const requestTimers = timerController.timers.filter(({ cleared, delay }) => !cleared && delay === 10);
    assert.equal(requestTimers.length, 2);

    requestTimers[0].callback();
    child.sendStdout('{"id":2,"result":{"thread":{"id":"task-a"}}}\n');
    child.sendStdout('{"id":3,"result":{"thread":{"id":"task-b"}}}\n');
    const result = await registration;

    assert.deepEqual(result.registeredThreadIds, ["task-b"]);
    assert.deepEqual(result.failures.map(({ threadId }) => threadId), ["task-a"]);
    assert.match(result.failures[0].message, /request timed out/i);
    assertCleanedUp(child);
  } finally {
    timerController.restore();
  }
});
