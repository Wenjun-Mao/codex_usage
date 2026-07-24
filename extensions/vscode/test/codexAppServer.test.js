const assert = require("node:assert/strict");
const test = require("node:test");

const { registerCodexTasks } = require("../out/codexAppServer");
const {
  assertCleanedUp,
  baseOptions,
  createFakeChild,
  createSuccessChild,
  officialCandidate,
  pathCandidate,
  spawnRecorder,
} = require("./codexAppServerHarness");

test("registers exact unique ids through one direct app-server process", async () => {
  const requested = [];
  const child = createFakeChild((message, process) => {
    if (message.method === "initialize") {
      const notice = Buffer.from('{"method":"server/notice","params":{"text":"café"}}\n');
      const split = notice.indexOf(Buffer.from("é")) + 1;
      queueMicrotask(() => {
        process.sendStdout(notice.subarray(0, split), notice.subarray(split));
        process.sendStdout('{"id":1,"res', 'ult":{"serverInfo":{"name":"fake"}}}\n');
      });
      return;
    }
    if (message.method !== "thread/read") {
      return;
    }
    requested.push(message);
    if (requested.length === 2) {
      queueMicrotask(() => {
        process.sendStdout('{"method":"thread/status","params":{"threadId":"task-a"}}\n');
        process.sendStdout('{"id":3,"result":{"thread":{"id":"task-b"}}}\n');
        process.sendStdout('{"id":2,"result":{"thread":', '{"id":"task-a"}}}\n');
      });
    }
  });
  const recorder = spawnRecorder(() => child);

  const result = await registerCodexTasks(
    baseOptions({
      threadIds: ["task-a", "task-a", "", " padded ", "task-b"],
      spawnProcess: recorder.spawnProcess,
    }),
  );

  assert.deepEqual(recorder.calls[0], {
    executablePath: "/official/codex",
    args: ["app-server", "--stdio"],
    options: { shell: false, stdio: ["pipe", "pipe", "pipe"] },
  });
  assert.equal(recorder.calls.length, 1);
  assert.deepEqual(child.messages, [
    {
      id: 1,
      method: "initialize",
      params: { clientInfo: { name: "codex-usage", version: "0.1.37" }, capabilities: {} },
    },
    { method: "initialized", params: {} },
    { id: 2, method: "thread/read", params: { threadId: "task-a", includeTurns: false } },
    { id: 3, method: "thread/read", params: { threadId: "task-b", includeTurns: false } },
  ]);
  assert.deepEqual(result, {
    attemptedThreadIds: ["task-a", "task-b"],
    registeredThreadIds: ["task-a", "task-b"],
    failures: [
      { threadId: "", message: "Thread id must be nonempty and contain no surrounding whitespace" },
      { threadId: " padded ", message: "Thread id must be nonempty and contain no surrounding whitespace" },
    ],
    executable: officialCandidate,
  });
  assert.equal(
    child.messages.some(({ method = "" }) => /turn|prompt|model|message\/send|thread\/list/i.test(method)),
    false,
  );
  assertCleanedUp(child);
});

test("reports invalid ids without spawning or altering their values", async () => {
  const recorder = spawnRecorder(() => {
    throw new Error("must not spawn");
  });

  const result = await registerCodexTasks(
    baseOptions({ threadIds: ["", " task-a", "task-a ", ""], spawnProcess: recorder.spawnProcess }),
  );

  assert.deepEqual(result.attemptedThreadIds, []);
  assert.deepEqual(
    result.failures.map(({ threadId }) => threadId),
    ["", " task-a", "task-a "],
  );
  assert.equal(recorder.calls.length, 0);
});

test("falls back to the next candidate after a synchronous spawn failure", async () => {
  const child = createSuccessChild();
  const recorder = spawnRecorder((_path, index) => {
    if (index === 0) {
      throw new Error("spawn denied");
    }
    return child;
  });

  const result = await registerCodexTasks(
    baseOptions({ candidates: [officialCandidate, pathCandidate], spawnProcess: recorder.spawnProcess }),
  );

  assert.equal(recorder.calls.length, 2);
  assert.deepEqual(result.registeredThreadIds, ["task-a"]);
  assert.deepEqual(result.executable, pathCandidate);
  assertCleanedUp(child);
});

test("falls back after initialization errors and startup timeouts", async () => {
  const errorChild = createFakeChild((message, child) => {
    if (message.method === "initialize") {
      queueMicrotask(() => child.sendStdout('{"id":1,"error":{"code":-32000,"message":"unsupported"}}\n'));
    }
  });
  const timeoutChild = createFakeChild();
  const successChild = createSuccessChild();
  const candidates = [
    officialCandidate,
    { executablePath: "/desktop/codex", source: "desktop-app" },
    pathCandidate,
  ];
  const children = [errorChild, timeoutChild, successChild];
  const recorder = spawnRecorder((_path, index) => children[index]);

  const result = await registerCodexTasks(
    baseOptions({ candidates, spawnProcess: recorder.spawnProcess, startupTimeoutMs: 10 }),
  );

  assert.equal(recorder.calls.length, 3);
  assert.deepEqual(result.registeredThreadIds, ["task-a"]);
  assert.deepEqual(result.executable, pathCandidate);
  for (const child of children) {
    assertCleanedUp(child);
  }
});

test("does not fall back after task requests and reports explicit errors and mismatches", async () => {
  const child = createFakeChild((message, process) => {
    if (message.method === "initialize") {
      queueMicrotask(() => process.sendStdout('{"id":1,"result":{}}\n'));
    } else if (message.method === "thread/read" && message.params.threadId === "task-a") {
      queueMicrotask(() => process.sendStdout('{"id":2,"error":{"code":-32001,"message":"not found"}}\n'));
    } else if (message.method === "thread/read") {
      queueMicrotask(() => process.sendStdout('{"id":3,"result":{"thread":{"id":"other-task"}}}\n'));
    }
  });
  const recorder = spawnRecorder(() => child);

  const result = await registerCodexTasks(
    baseOptions({
      candidates: [officialCandidate, pathCandidate],
      threadIds: ["task-a", "task-b"],
      spawnProcess: recorder.spawnProcess,
    }),
  );

  assert.equal(recorder.calls.length, 1);
  assert.deepEqual(result.registeredThreadIds, []);
  assert.match(result.failures[0].message, /not found/);
  assert.match(result.failures[1].message, /other-task/);
  assert.deepEqual(result.executable, officialCandidate);
  assertCleanedUp(child);
});

test("treats malformed stdout after dispatch as terminal without exposing its contents", async () => {
  const secret = "ROLLOUT-CONTENT-MUST-NOT-LEAK";
  const child = createFakeChild((message, process) => {
    if (message.method === "initialize") {
      queueMicrotask(() => process.sendStdout('{"id":1,"result":{}}\n'));
    } else if (message.method === "thread/read") {
      queueMicrotask(() => process.sendStdout(`{"id":2,"result":{"rollout":"${secret}"\n`));
    }
  });
  const recorder = spawnRecorder(() => child);

  const result = await registerCodexTasks(
    baseOptions({ candidates: [officialCandidate, pathCandidate], spawnProcess: recorder.spawnProcess }),
  );

  assert.equal(recorder.calls.length, 1);
  assert.match(result.failures[0].message, /malformed/i);
  assert.doesNotMatch(JSON.stringify(result), new RegExp(secret));
  assertCleanedUp(child);
});

test("caps stderr diagnostics separately when the child exits early", async () => {
  const child = createFakeChild((message, process) => {
    if (message.method === "initialize") {
      queueMicrotask(() => process.sendStdout('{"id":1,"result":{}}\n'));
    } else if (message.method === "thread/read") {
      queueMicrotask(() => {
        process.sendStdout('{"method":"server/notice","params":{"rollout":"stdout-secret"}}\n');
        process.sendStderr("abcdefghijklmnop");
        process.exit(7);
      });
    }
  });
  const recorder = spawnRecorder(() => child);

  const result = await registerCodexTasks(
    baseOptions({ spawnProcess: recorder.spawnProcess, retainedDiagnosticBytes: 8 }),
  );

  assert.match(result.failures[0].message, /exited.*7/i);
  assert.match(result.failures[0].message, /stderr: ijklmnop/);
  assert.doesNotMatch(JSON.stringify(result), /stdout-secret/);
  assertCleanedUp(child);
});

test("fails only unresolved requests when a per-task timer expires", async () => {
  const child = createFakeChild((message, process) => {
    if (message.method === "initialize") {
      queueMicrotask(() => process.sendStdout('{"id":1,"result":{}}\n'));
    } else if (message.method === "thread/read" && message.params.threadId === "task-a") {
      queueMicrotask(() => process.sendStdout('{"id":2,"result":{"thread":{"id":"task-a"}}}\n'));
    }
  });
  const recorder = spawnRecorder(() => child);

  const result = await registerCodexTasks(
    baseOptions({
      threadIds: ["task-a", "task-b"],
      spawnProcess: recorder.spawnProcess,
      requestTimeoutMs: 10,
      batchTimeoutMs: 80,
    }),
  );

  assert.deepEqual(result.registeredThreadIds, ["task-a"]);
  assert.deepEqual(result.failures.map(({ threadId }) => threadId), ["task-b"]);
  assert.match(result.failures[0].message, /request timed out/i);
  assertCleanedUp(child);
});

test("fails all unresolved requests at the whole-batch timeout", async () => {
  const child = createFakeChild((message, process) => {
    if (message.method === "initialize") {
      queueMicrotask(() => process.sendStdout('{"id":1,"result":{}}\n'));
    }
  });
  const recorder = spawnRecorder(() => child);

  const result = await registerCodexTasks(
    baseOptions({
      threadIds: ["task-a", "task-b"],
      spawnProcess: recorder.spawnProcess,
      requestTimeoutMs: 80,
      batchTimeoutMs: 10,
    }),
  );

  assert.deepEqual(result.registeredThreadIds, []);
  assert.deepEqual(result.failures.map(({ threadId }) => threadId), ["task-a", "task-b"]);
  assert.ok(result.failures.every(({ message }) => /batch timed out/i.test(message)));
  assertCleanedUp(child);
});

test("falls back after an asynchronous pre-dispatch process error", async () => {
  const errorChild = createFakeChild();
  const successChild = createSuccessChild();
  const recorder = spawnRecorder((_path, index) => {
    const child = index === 0 ? errorChild : successChild;
    if (index === 0) {
      queueMicrotask(() => child.emit("error", new Error("ENOENT")));
    }
    return child;
  });

  const result = await registerCodexTasks(
    baseOptions({ candidates: [officialCandidate, pathCandidate], spawnProcess: recorder.spawnProcess }),
  );

  assert.equal(recorder.calls.length, 2);
  assert.deepEqual(result.registeredThreadIds, ["task-a"]);
  assertCleanedUp(errorChild);
  assertCleanedUp(successChild);
});

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
  const originalSetTimeout = global.setTimeout;
  const originalClearTimeout = global.clearTimeout;
  const timers = [];
  global.setTimeout = (callback, delay) => {
    const timer = { callback, cleared: false, delay };
    timers.push(timer);
    return timer;
  };
  global.clearTimeout = (timer) => {
    timer.cleared = true;
  };

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
    const requestTimers = timers.filter(({ cleared, delay }) => !cleared && delay === 10);
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
    global.setTimeout = originalSetTimeout;
    global.clearTimeout = originalClearTimeout;
  }
});
