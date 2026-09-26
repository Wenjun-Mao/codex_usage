// Exercise the post-confirmation handoff against real OS registration APIs on CI runners.
const assert = require("node:assert/strict");
const childProcess = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { AgentSupervisor } = require("../extensions/vscode/out/agentSupervisor");

const LABEL = "com.wenjunmao.codex-usage-agent";
const TASK = "Codex Usage Agent";
const DESCRIPTION = "Captures local Codex usage into the Codex Usage ledger.";

function run(command, args, options = {}) {
  const result = childProcess.spawnSync(command, args, { encoding: "utf8", ...options });
  if (result.error) throw result.error;
  return result;
}

function requireSuccess(result, action) {
  if (result.status !== 0) {
    throw new Error(`${action} failed (${result.status}): ${(result.stderr || result.stdout).trim()}`);
  }
}

function xmlEscape(value) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function registration(executable) {
  if (process.platform === "darwin") {
    const domain = `gui/${process.getuid()}`;
    requireSuccess(run("launchctl", ["print", domain]), `inspect ${domain}`);
    const target = path.join(os.homedir(), "Library", "LaunchAgents", `${LABEL}.plist`);
    assert.equal(fs.existsSync(target), false, `runner already has ${target}`);
    const service = run("launchctl", ["print", `${domain}/${LABEL}`]);
    assert.notEqual(service.status, 0, `runner already has loaded ${LABEL}`);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, `<?xml version="1.0" encoding="UTF-8"?>\n` +
      `<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n` +
      `<plist version="1.0"><dict><key>Label</key><string>${LABEL}</string>` +
      `<key>ProgramArguments</key><array><string>${xmlEscape(executable)}</string>` +
      `<string>--background</string></array></dict></plist>\n`);
    return {
      present: () => fs.existsSync(target),
      cleanup: () => fs.rmSync(target, { force: true }),
    };
  }
  if (process.platform === "win32") {
    assert.notEqual(run("schtasks.exe", ["/Query", "/TN", TASK]).status, 0,
      `runner already has Scheduled Task ${TASK}`);
    const script = `$ErrorActionPreference = 'Stop'; ` +
      `$action = New-ScheduledTaskAction -Execute $env:CODEX_USAGE_FIXTURE_AGENT -Argument '--background'; ` +
      `$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddDays(2); ` +
      `Register-ScheduledTask -TaskName '${TASK}' -Action $action -Trigger $trigger ` +
      `-Description '${DESCRIPTION}' | Out-Null`;
    requireSuccess(run("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], {
      env: { ...process.env, CODEX_USAGE_FIXTURE_AGENT: executable },
    }), "register disposable Scheduled Task");
    return {
      present: () => run("schtasks.exe", ["/Query", "/TN", TASK]).status === 0,
      cleanup: () => run("schtasks.exe", ["/Delete", "/TN", TASK, "/F"]),
    };
  }
  throw new Error(`Unsupported acceptance platform: ${process.platform}`);
}

function writeSession(home, taskId, totalTokens) {
  const directory = path.join(home, "sessions", "2026", "09", "02");
  fs.mkdirSync(directory, { recursive: true });
  const rows = [
    { timestamp: "2026-09-02T10:00:00Z", type: "session_meta", payload: { id: taskId, cwd: path.join(home, "project") } },
    { timestamp: "2026-09-02T10:00:01Z", type: "turn_context", payload: { model: "gpt-5.6-sol" } },
    { timestamp: "2026-09-02T10:00:02Z", type: "event_msg", payload: { type: "token_count", info: { total_token_usage: { input_tokens: totalTokens, total_tokens: totalTokens } } } },
  ];
  fs.writeFileSync(path.join(directory, `rollout-${taskId}.jsonl`), rows.map(JSON.stringify).join("\n") + "\n");
}

async function main() {
  assert.equal(process.env.GITHUB_ACTIONS, "true", "run only on an isolated GitHub Actions runner");
  assert.ok(process.env.RUNNER_TEMP, "RUNNER_TEMP is required");
  const target = process.platform === "darwin" ? "darwin-arm64" : "win32-x64";
  const executable = path.resolve("extensions", "vscode", "bin", target,
    process.platform === "darwin" ? "codex-usage-agent" : "codex-usage-agent.exe");
  assert.ok(fs.existsSync(executable), `missing packaged collector: ${executable}`);
  const root = fs.mkdtempSync(path.join(process.env.RUNNER_TEMP, "codex-usage-handoff-"));
  const home = path.join(root, "codex-home");
  const settingsFile = path.join(root, "settings.json");
  writeSession(home, "first", 100);
  const supervisor = new AgentSupervisor({
    settingsFile,
    getCodexHome: async () => home,
    resolveExecutable: async () => executable,
  });
  let service;
  try {
    const owned = await supervisor.acquire();
    const initialCapture = await owned.post("/v1/capture");
    assert.equal(initialCapture.outcome, "success");
    const before = await owned.get("/v1/status");
    assert.equal(before.codex_home, home);
    assert.equal(before.coverage.captured_sources, 1);
    const ledgerPath = path.join(home, ".codex-usage", "usage-ledger.sqlite3");
    assert.ok(fs.existsSync(ledgerPath));

    service = registration(executable);
    assert.equal(service.present(), true);
    const status = await supervisor.legacyServiceStatus();
    assert.equal(status.supported, true);
    assert.equal(status.installed, true);
    assert.equal(status.recognized, true);
    writeSession(home, "second", 200);
    const handoff = await supervisor.handoffLegacyService();
    const after = await owned.get("/v1/status");
    const stillOwned = await supervisor.acquire();
    assert.ok(owned.isSameAgent(stillOwned), "handoff replaced the VS Code-owned collector");
    assert.equal(after.agent_pid, before.agent_pid);
    assert.equal(after.codex_home, home);
    assert.equal(handoff.codexHome, home);
    assert.equal(handoff.ledgerRevision, after.ledger_revision);
    assert.ok(after.ledger_revision >= before.ledger_revision);
    assert.equal(after.coverage.captured_sources, 2);
    assert.ok(fs.existsSync(ledgerPath), "handoff removed the ledger");
    assert.equal(service.present(), false, "legacy registration survived handoff");
    console.log(JSON.stringify({ platform: process.platform, home, agent_pid: after.agent_pid,
      before_revision: before.ledger_revision, after_revision: after.ledger_revision,
      captured_sources: after.coverage.captured_sources, registration_removed: true }));
  } finally {
    if (service?.present()) service.cleanup();
    await supervisor.stopManagedAgent();
    fs.rmSync(root, { recursive: true, force: true });
  }
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
