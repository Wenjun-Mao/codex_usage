const AGENT_BY_TARGET = {
  "darwin-arm64": "bin/darwin-arm64/codex-usage-agent",
  "win32-x64": "bin/win32-x64/codex-usage-agent.exe",
};

function expectedAgentPath(target) {
  const agent = AGENT_BY_TARGET[target];
  if (!agent) throw new Error(`Unsupported VSIX target: ${target}`);
  return agent;
}

function verifyPackageFiles(files, target) {
  const expectedAgent = expectedAgentPath(target);
  const present = new Set(files);
  const forbidden = files.filter((file) =>
    /(^|\/)(src|test|apps)(\/|$)|\.py$|usage-cache|src-tauri/iu.test(file)
      || (file.startsWith("bin/") && file !== expectedAgent),
  );
  if (forbidden.length) {
    throw new Error(`VSIX contains unsupported runtime files:\n${forbidden.join("\n")}`);
  }
  for (const required of ["out/extension.js", "package.json", "README.md", expectedAgent]) {
    if (!present.has(required)) throw new Error(`VSIX is missing ${required}`);
  }
  const collectors = files.filter((file) => file.startsWith("bin/") && /codex-usage-agent(?:\.exe)?$/u.test(file));
  if (collectors.length !== 1) throw new Error(`VSIX must contain exactly one collector; found ${collectors.length}.`);
}

module.exports = { expectedAgentPath, verifyPackageFiles };
