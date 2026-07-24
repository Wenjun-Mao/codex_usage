"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const repositoryRoot = path.resolve(__dirname, "..");
const { registerCodexTasks } = require(path.join(
  repositoryRoot,
  "extensions/vscode/out/codexAppServer",
));

async function main() {
  const workingDirectory = fs.mkdtempSync(path.join(os.tmpdir(), "codex-registration-smoke-"));
  const originalWorkingDirectory = process.cwd();
  try {
    fs.copyFileSync(path.join(__dirname, "fake-codex-app-server"), path.join(workingDirectory, "app-server"));
    process.chdir(workingDirectory);
    const result = await registerCodexTasks({
      candidates: [{ executablePath: process.execPath, source: "cli-override" }],
      threadIds: ["packaged-task-a", "packaged-task-b"],
      extensionVersion: "registration-smoke",
      startupTimeoutMs: 2_000,
      requestTimeoutMs: 2_000,
      batchTimeoutMs: 4_000,
    });
    assert.deepEqual(result.registeredThreadIds, ["packaged-task-a", "packaged-task-b"]);
    assert.deepEqual(result.failures, []);
    assert.equal(result.executable?.executablePath, process.execPath);
    console.log(`Codex registration smoke passed: registered=${result.registeredThreadIds.join(",")}`);
  } finally {
    process.chdir(originalWorkingDirectory);
    fs.rmSync(workingDirectory, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error instanceof Error ? error.stack : String(error));
  process.exitCode = 1;
});
