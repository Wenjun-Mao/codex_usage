const assert = require("node:assert/strict");
const test = require("node:test");

const { expectedAgentPath, verifyPackageFiles } = require("../scripts/packageContent");

test("each platform VSIX requires only its matching bundled collector", () => {
  const macAgent = expectedAgentPath("darwin-arm64");
  verifyPackageFiles(["out/extension.js", "package.json", "README.md", macAgent], "darwin-arm64");
  assert.throws(
    () => verifyPackageFiles([
      "out/extension.js", "package.json", "README.md", macAgent, expectedAgentPath("win32-x64"),
    ], "darwin-arm64"),
    /unsupported runtime files/,
  );
});
