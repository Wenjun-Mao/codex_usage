const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

function lineCount(filePath) {
  return fs.readFileSync(filePath, "utf8").split(/\r?\n/).length - 1;
}

test("extension TypeScript and Node tests stay under 500 lines", () => {
  const extensionRoot = path.resolve(__dirname, "..");
  const files = [
    ...fs.readdirSync(path.join(extensionRoot, "src"))
      .filter((name) => name.endsWith(".ts"))
      .map((name) => path.join(extensionRoot, "src", name)),
    ...fs.readdirSync(path.join(extensionRoot, "test"))
      .filter((name) => name.endsWith(".test.js"))
      .map((name) => path.join(extensionRoot, "test", name)),
  ];
  const oversized = files
    .map((filePath) => [path.relative(extensionRoot, filePath), lineCount(filePath)])
    .filter(([, count]) => count >= 500);

  assert.deepEqual(oversized, []);
});
