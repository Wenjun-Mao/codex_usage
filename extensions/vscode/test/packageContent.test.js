const assert = require("node:assert/strict");
const test = require("node:test");

const { expectedAgentPath, verifyPackageFiles } = require("../scripts/packageContent");

test("each platform VSIX contains exactly its matching bundled collector", () => {
  const sharedFiles = ["out/extension.js", "package.json", "README.md"];
  const macAgent = expectedAgentPath("darwin-arm64");
  const windowsAgent = expectedAgentPath("win32-x64");

  verifyPackageFiles([...sharedFiles, macAgent], "darwin-arm64");
  verifyPackageFiles([...sharedFiles, windowsAgent], "win32-x64");
  assert.throws(() => verifyPackageFiles(sharedFiles, "darwin-arm64"), /is missing/);
  assert.throws(() => verifyPackageFiles(sharedFiles, "win32-x64"), /is missing/);
  assert.throws(
    () => verifyPackageFiles([...sharedFiles, macAgent, windowsAgent], "darwin-arm64"),
    /unsupported runtime files/,
  );
  assert.throws(() => expectedAgentPath("linux-x64"), /Unsupported VSIX target/);
});
