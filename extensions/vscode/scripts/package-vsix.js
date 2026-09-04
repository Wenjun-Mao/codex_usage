const childProcess = require("node:child_process");
const fs = require("node:fs");
const path = require("node:path");
const { npmCliPath, vsceCliPath } = require("./cliEntrypoints");
const { expectedAgentPath } = require("./packageContent");

function packageVsix(target, {
  extensionRoot = path.resolve(__dirname, ".."),
  releaseDirectory = path.resolve(extensionRoot, "..", "..", "output", "releases"),
  fileSystem = fs,
  run = childProcess.execFileSync,
  nodePath = process.execPath,
  npmPath = npmCliPath(),
  vscePath = vsceCliPath(),
} = {}) {
  const agentPath = expectedAgentPath(target);
  const outputPath = path.join(releaseDirectory, `codex-usage-companion-${target}.vsix`);

  if (!fileSystem.existsSync(path.join(extensionRoot, agentPath))) {
    throw new Error(`Build the ${target} collector before packaging this VSIX.`);
  }
  fileSystem.mkdirSync(releaseDirectory, { recursive: true });
  run(nodePath, [npmPath, "run", "build"], {
    cwd: extensionRoot,
    stdio: "inherit",
  });
  run(nodePath, [path.join(__dirname, "verify-package.js"), "--target", target], {
    cwd: extensionRoot,
    stdio: "inherit",
  });
  run(nodePath, [
    vscePath, "package", "--target", target, "--out", outputPath,
  ], { cwd: extensionRoot, stdio: "inherit" });
}

if (require.main === module) packageVsix(process.argv[2]);

module.exports = { packageVsix };
