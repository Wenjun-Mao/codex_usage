const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const test = require("node:test");

const { AgentUnavailableError } = require("../out/agentClient");
const { AgentSupervisor } = require("../out/agentSupervisor");

function childForControl() {
  const child = new EventEmitter();
  child.stderr = new EventEmitter();
  child.unref = () => {};
  process.nextTick(() => child.emit("close", 0));
  return child;
}

function childForAgent() {
  const child = new EventEmitter();
  child.stderr = new EventEmitter();
  child.unref = () => {};
  return child;
}

test("a stale descriptor starts one parent-bound collector and waits for its authenticated health check", async () => {
  let discoveryAttempts = 0;
  const calls = [];
  const client = {};
  const supervisor = new AgentSupervisor({
    settingsFile: "/tmp/codex-usage-agent-settings.json",
    getCodexHome: async () => "/tmp/codex-home",
    setCodexHome: async () => {},
    resolveExecutable: async () => "/tmp/codex-usage-agent",
    parentPid: 4321,
    discover: async () => {
      discoveryAttempts += 1;
      if (discoveryAttempts < 3) throw new AgentUnavailableError("stale descriptor");
      return client;
    },
    spawn: (_command, args) => {
      calls.push([...args]);
      return args.includes("--set-codex-home") ? childForControl() : childForAgent();
    },
    sleep: async () => {},
  });

  assert.equal(await supervisor.acquire(), client);
  assert.equal(calls.filter((args) => args.includes("--parent-pid")).length, 1);
  assert.deepEqual(calls.at(-1), [
    "--settings-file", "/tmp/codex-usage-agent-settings.json", "--parent-pid", "4321",
  ]);
  await supervisor.acquire();
  assert.equal(calls.filter((args) => args.includes("--parent-pid")).length, 1);
});

test("changing CODEX_HOME validates before persisting the selected home", async () => {
  let storedHome = "/tmp/old-codex-home";
  const controlCalls = [];
  const client = { post: async () => ({ stopping: true }) };
  let discoveries = 0;
  const supervisor = new AgentSupervisor({
    settingsFile: "/tmp/codex-usage-agent-settings.json",
    getCodexHome: async () => storedHome,
    setCodexHome: async (home) => { storedHome = home; },
    resolveExecutable: async () => "/tmp/codex-usage-agent",
    discover: async () => {
      discoveries += 1;
      if (discoveries === 1) throw new AgentUnavailableError("missing descriptor");
      return client;
    },
    spawn: (_command, args) => {
      controlCalls.push([...args]);
      return childForControl();
    },
    sleep: async () => {},
  });

  await supervisor.configureCodexHome("/tmp/new-codex-home");
  assert.equal(storedHome, "/tmp/new-codex-home");
  assert.ok(controlCalls.some((args) => args.includes("/tmp/new-codex-home")));
});
