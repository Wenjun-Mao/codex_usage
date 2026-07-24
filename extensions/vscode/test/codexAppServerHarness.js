const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const { PassThrough } = require("node:stream");

const officialCandidate = {
  executablePath: "/official/codex",
  source: "official-vscode-extension",
};
const pathCandidate = { executablePath: "codex", source: "path" };

function createFakeChild(onMessage = () => {}) {
  const stdin = new PassThrough();
  const stdout = new PassThrough();
  const stderr = new PassThrough();
  const child = new EventEmitter();
  const messages = [];
  let stdinBuffer = "";

  child.stdin = stdin;
  child.stdout = stdout;
  child.stderr = stderr;
  child.exitCode = null;
  child.signalCode = null;
  child.killCalls = 0;
  child.stdinEndCalls = 0;
  child.kill = (signal = "SIGTERM") => {
    child.killCalls += 1;
    child.signalCode = signal;
    queueMicrotask(() => {
      child.emit("exit", null, signal);
      child.emit("close", null, signal);
    });
    return true;
  };
  child.sendStdout = (...chunks) => {
    for (const chunk of chunks) {
      stdout.write(chunk);
    }
  };
  child.emitStdoutSynchronously = (chunk) => {
    stdout.emit("data", Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  };
  child.sendStderr = (...chunks) => {
    for (const chunk of chunks) {
      stderr.write(chunk);
    }
  };
  child.exit = (code = 1, signal = null) => {
    child.exitCode = code;
    child.signalCode = signal;
    child.emit("exit", code, signal);
    queueMicrotask(() => child.emit("close", code, signal));
  };

  const transportWrite = stdin.write.bind(stdin);
  const originalEnd = stdin.end.bind(stdin);
  stdin.end = (...args) => {
    child.stdinEndCalls += 1;
    return originalEnd(...args);
  };
  child.interceptStdinWrite = (interceptor) => {
    stdin.write = (chunk, ...args) =>
      interceptor({
        child,
        chunk,
        message: JSON.parse(Buffer.from(chunk).toString("utf8")),
        write: () => transportWrite(chunk, ...args),
      });
  };
  stdin.on("data", (chunk) => {
    stdinBuffer += chunk.toString("utf8");
    let newlineIndex;
    while ((newlineIndex = stdinBuffer.indexOf("\n")) >= 0) {
      const line = stdinBuffer.slice(0, newlineIndex);
      stdinBuffer = stdinBuffer.slice(newlineIndex + 1);
      if (!line) {
        continue;
      }
      const message = JSON.parse(line);
      messages.push(message);
      onMessage(message, child);
    }
  });
  child.messages = messages;
  return child;
}

function createSuccessChild(expectedThreadIds = ["task-a"]) {
  const pending = new Set(expectedThreadIds);
  return createFakeChild((message, child) => {
    if (message.method === "initialize") {
      queueMicrotask(() => child.sendStdout('{"id":1,"result":{"serverInfo":{"name":"fake"}}}\n'));
      return;
    }
    if (message.method === "thread/read" && pending.delete(message.params.threadId)) {
      queueMicrotask(() =>
        child.sendStdout(`${JSON.stringify({ id: message.id, result: { thread: { id: message.params.threadId } } })}\n`),
      );
    }
  });
}

function spawnRecorder(factory) {
  const calls = [];
  const spawnProcess = (executablePath, args, options) => {
    calls.push({ executablePath, args, options });
    return factory(executablePath, calls.length - 1);
  };
  return { calls, spawnProcess };
}

function baseOptions(overrides = {}) {
  return {
    candidates: [officialCandidate],
    threadIds: ["task-a"],
    extensionVersion: "0.1.37",
    startupTimeoutMs: 40,
    requestTimeoutMs: 40,
    batchTimeoutMs: 80,
    ...overrides,
  };
}

function assertCleanedUp(child) {
  assert.equal(child.stdinEndCalls, 1);
  assert.equal(child.killCalls, 1);
  assert.equal(child.listenerCount("error"), 0);
  assert.equal(child.listenerCount("exit"), 0);
  assert.equal(child.listenerCount("close"), 0);
  assert.equal(child.stdout.listenerCount("data"), 0);
  assert.equal(child.stderr.listenerCount("data"), 0);
  assert.equal(child.stdin.listenerCount("error"), 0);
}

function installControllableTimers() {
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
  return {
    timers,
    restore() {
      global.setTimeout = originalSetTimeout;
      global.clearTimeout = originalClearTimeout;
    },
  };
}

module.exports = {
  assertCleanedUp,
  baseOptions,
  createFakeChild,
  createSuccessChild,
  officialCandidate,
  pathCandidate,
  installControllableTimers,
  spawnRecorder,
};
