const assert = require("node:assert/strict");
const path = require("node:path");
const test = require("node:test");

const { bundledAgentRelativePath, supportedAgentTarget } = require("../out/bundledAgent");

test("bundled collector selection is limited to released VSIX targets", () => {
  assert.equal(supportedAgentTarget("darwin", "arm64"), "darwin-arm64");
  assert.equal(supportedAgentTarget("win32", "x64"), "win32-x64");
  assert.equal(bundledAgentRelativePath("darwin", "arm64"), path.join("bin", "darwin-arm64", "codex-usage-agent"));
  assert.equal(bundledAgentRelativePath("win32", "x64"), path.join("bin", "win32-x64", "codex-usage-agent.exe"));
  assert.throws(() => supportedAgentTarget("linux", "x64"), /macOS Apple Silicon and Windows x64/);
});
