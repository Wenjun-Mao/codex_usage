const assert = require("node:assert/strict");
const test = require("node:test");

const { inspectCodexDesktopProcess } = require("../out/codexDesktopProcess");

test("macOS process inspection recognizes only the Desktop main executable", async () => {
  const running = await inspectCodexDesktopProcess({
    platform: "darwin",
    async executeFile(file, args) {
      assert.equal(file, "/bin/ps");
      assert.deepEqual(args, ["-axo", "pid=,args="]);
      return {
        stdout:
          " 101 /Applications/ChatGPT.app/Contents/MacOS/ChatGPT\n" +
          " 102 /Applications/ChatGPT.app/Contents/Resources/codex app-server\n",
      };
    },
  });
  assert.deepEqual(running, { status: "running" });

  const closed = await inspectCodexDesktopProcess({
    platform: "darwin",
    async executeFile() {
      return { stdout: " 102 /Applications/ChatGPT.app/Contents/Resources/codex app-server\n" };
    },
  });
  assert.deepEqual(closed, { status: "closed" });
});

test("Windows process inspection handles running closed invalid and failed probes", async () => {
  for (const [stdout, status] of [["2\r\n", "running"], ["0\r\n", "closed"]]) {
    const result = await inspectCodexDesktopProcess({
      platform: "win32",
      async executeFile(file, args) {
        assert.equal(file, "powershell.exe");
        assert.match(args.join(" "), /Get-Process/);
        return { stdout };
      },
    });
    assert.equal(result.status, status);
  }

  const invalid = await inspectCodexDesktopProcess({
    platform: "win32",
    async executeFile() { return { stdout: "not-a-count" }; },
  });
  assert.equal(invalid.status, "unknown");

  const failed = await inspectCodexDesktopProcess({
    platform: "darwin",
    async executeFile() { throw new Error("private process detail"); },
  });
  assert.deepEqual(failed, {
    status: "unknown",
    reason: "Codex Desktop process inspection failed",
  });
});
