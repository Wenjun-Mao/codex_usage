const childProcess = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { expectedAgentPath } = require("./packageContent");

const target = process.argv[2];
const agentPath = expectedAgentPath(target);
const extensionRoot = path.resolve(__dirname, "..");
const releaseDirectory = path.resolve(extensionRoot, "..", "..", "output", "releases");
const outputPath = path.join(releaseDirectory, `codex-usage-companion-${target}.vsix`);

if (!fs.existsSync(path.join(extensionRoot, agentPath))) {
  throw new Error(`Build the ${target} collector before packaging this VSIX.`);
}
fs.mkdirSync(releaseDirectory, { recursive: true });
childProcess.execFileSync(process.platform === "win32" ? "npm.cmd" : "npm", ["run", "build"], {
  cwd: extensionRoot,
  stdio: "inherit",
});
childProcess.execFileSync(process.execPath, [path.join(__dirname, "verify-package.js"), "--target", target], {
  cwd: extensionRoot,
  stdio: "inherit",
});
childProcess.execFileSync(process.platform === "win32" ? "npx.cmd" : "npx", [
  "vsce", "package", "--target", target, "--out", outputPath,
], { cwd: extensionRoot, stdio: "inherit" });
