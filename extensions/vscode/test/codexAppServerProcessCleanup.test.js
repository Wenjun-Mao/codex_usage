const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");

const { registerCodexTasks } = require("../out/codexAppServer");

test(
  "waits for forced cleanup of a real app-server process tree",
  { skip: process.platform === "win32" ? "POSIX signal escalation contract" : false },
  async () => {
    const fixtureDir = fs.mkdtempSync(path.join(os.tmpdir(), "codex-app-server-cleanup-"));
    const pidFile = path.join(fixtureDir, "processes.json");
    const fixture = path.join(fixtureDir, "app-server");
    const originalCwd = process.cwd();
    const originalPidFile = process.env.CODEX_USAGE_TEST_PID_FILE;
    let processIds;
    fs.writeFileSync(fixture, ignoringAppServerSource(), "utf8");
    process.env.CODEX_USAGE_TEST_PID_FILE = pidFile;

    try {
      process.chdir(fixtureDir);
      const startedAt = Date.now();
      const result = await registerCodexTasks({
        candidates: [{ executablePath: process.execPath, source: "path" }],
        threadIds: ["task-a"],
        extensionVersion: "0.1.37",
        startupTimeoutMs: 500,
        requestTimeoutMs: 500,
        batchTimeoutMs: 1_000,
        cleanupGraceTimeoutMs: 50,
        cleanupForceTimeoutMs: 500,
      });
      processIds = JSON.parse(fs.readFileSync(pidFile, "utf8"));

      assert.deepEqual(result.registeredThreadIds, ["task-a"]);
      assert(Date.now() - startedAt < 1_500, "cleanup must remain bounded");
      assert.equal(processExists(processIds.parent), false, "app-server parent survived");
      assert.equal(processExists(processIds.child), false, "app-server descendant survived");
    } finally {
      process.chdir(originalCwd);
      restoreEnvironment("CODEX_USAGE_TEST_PID_FILE", originalPidFile);
      if (processIds) {
        forceKill(processIds.child);
        forceKill(processIds.parent);
        await wait(25);
      }
      fs.rmSync(fixtureDir, { recursive: true, force: true });
    }
  },
);

function ignoringAppServerSource() {
  return `
const fs = require("node:fs");
const { spawn } = require("node:child_process");

process.on("SIGTERM", () => {});
setInterval(() => {}, 1_000);
const child = spawn(
  process.execPath,
  ["-e", "process.on('SIGTERM', () => {}); setInterval(() => {}, 1000)"],
  { stdio: "ignore" },
);
fs.writeFileSync(
  process.env.CODEX_USAGE_TEST_PID_FILE,
  JSON.stringify({ parent: process.pid, child: child.pid }),
);

let buffer = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  let newline;
  while ((newline = buffer.indexOf("\\n")) >= 0) {
    const line = buffer.slice(0, newline);
    buffer = buffer.slice(newline + 1);
    if (!line) continue;
    const message = JSON.parse(line);
    if (message.method === "initialize") {
      process.stdout.write(JSON.stringify({ id: message.id, result: {} }) + "\\n");
    } else if (message.method === "thread/read") {
      process.stdout.write(
        JSON.stringify({
          id: message.id,
          result: { thread: { id: message.params.threadId } },
        }) + "\\n",
      );
    }
  }
});
`;
}

function processExists(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    if (error && error.code === "ESRCH") {
      return false;
    }
    throw error;
  }
}

function forceKill(pid) {
  try {
    process.kill(pid, "SIGKILL");
  } catch (error) {
    if (!error || error.code !== "ESRCH") {
      throw error;
    }
  }
}

function restoreEnvironment(name, value) {
  if (value === undefined) {
    delete process.env[name];
  } else {
    process.env[name] = value;
  }
}

function wait(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}
