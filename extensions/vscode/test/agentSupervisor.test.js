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

function childForAgent(pid = 9876) {
  const child = new EventEmitter();
  child.stderr = new EventEmitter();
  child.pid = pid;
  child.unref = () => {};
  return child;
}

function collector({ identity, pid, parentPid, owner = "transient", post = async () => ({ stopping: true }) }) {
  return {
    identity,
    processId: pid,
    post,
    isSameAgent(other) {
      return this.identity === other.identity;
    },
    isTransientOwnedBy(expectedParentPid, expectedPid) {
      return owner === "transient" && parentPid === expectedParentPid && pid === expectedPid;
    },
  };
}

test("a stale descriptor starts one parent-bound collector and waits for its authenticated health check", async () => {
  let discoveryAttempts = 0;
  const calls = [];
  const client = collector({ identity: "owned", pid: 9876, parentPid: 4321 });
  const supervisor = new AgentSupervisor({
    settingsFile: "/tmp/codex-usage-agent-settings.json",
    getCodexHome: async () => "/tmp/codex-home",
    resolveExecutable: async () => "/tmp/codex-usage-agent",
    parentPid: 4321,
    discover: async () => {
      discoveryAttempts += 1;
      if (discoveryAttempts < 3) throw new AgentUnavailableError("stale descriptor");
      return client;
    },
    spawn: (_command, args) => {
      calls.push([...args]);
      return args.includes("--set-codex-home") ? childForControl() : childForAgent(9876);
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
  const client = collector({ identity: "background", pid: 2000, owner: "background" });
  let discoveries = 0;
  const supervisor = new AgentSupervisor({
    settingsFile: "/tmp/codex-usage-agent-settings.json",
    getCodexHome: async () => storedHome,
    resolveExecutable: async () => "/tmp/codex-usage-agent",
    discover: async () => {
      discoveries += 1;
      if (discoveries === 1) throw new AgentUnavailableError("missing descriptor");
      return client;
    },
    spawn: (_command, args) => {
      controlCalls.push([...args]);
      if (args.includes("--set-codex-home")) storedHome = args.at(-1);
      return childForControl();
    },
    sleep: async () => {},
  });

  await supervisor.configureCodexHome("/tmp/new-codex-home");
  assert.equal(storedHome, "/tmp/new-codex-home");
  assert.ok(controlCalls.some((args) => args.includes("/tmp/new-codex-home")));
});

test("a foreign collector blocks a home switch without receiving shutdown", async () => {
  let shutdowns = 0;
  const foreign = collector({
    identity: "native-background",
    pid: 3000,
    owner: "background",
    post: async () => { shutdowns += 1; return { stopping: true }; },
  });
  const controlCalls = [];
  const supervisor = new AgentSupervisor({
    settingsFile: "/tmp/codex-usage-agent-settings.json",
    getCodexHome: async () => "/tmp/old-codex-home",
    resolveExecutable: async () => "/tmp/codex-usage-agent",
    discover: async () => foreign,
    spawn: (_command, args) => {
      controlCalls.push([...args]);
      return childForControl();
    },
    sleep: async () => {},
  });

  await assert.rejects(
    supervisor.configureCodexHome("/tmp/new-codex-home"),
    /Another client owns the active collector/,
  );
  assert.equal(shutdowns, 0);
  assert.equal(controlCalls.length, 0);
});

test("a replacement collector at the same home is never treated as the spawned transient", async () => {
  let discoveryAttempts = 0;
  let shutdowns = 0;
  const spawned = collector({ identity: "spawned", pid: 4000, parentPid: 4321 });
  const replacement = collector({
    identity: "replacement",
    pid: 4001,
    owner: "background",
    post: async () => { shutdowns += 1; return { stopping: true }; },
  });
  let active = spawned;
  const supervisor = new AgentSupervisor({
    settingsFile: "/tmp/codex-usage-agent-settings.json",
    getCodexHome: async () => "/tmp/codex-home",
    resolveExecutable: async () => "/tmp/codex-usage-agent",
    parentPid: 4321,
    discover: async () => {
      discoveryAttempts += 1;
      if (discoveryAttempts === 1) throw new AgentUnavailableError("stale descriptor");
      return active;
    },
    spawn: (_command, args) => args.includes("--set-codex-home") ? childForControl() : childForAgent(4000),
    sleep: async () => {},
  });

  await supervisor.acquire();
  active = replacement;
  await assert.rejects(
    supervisor.configureCodexHome("/tmp/new-codex-home"),
    /Another client owns the active collector/,
  );
  assert.equal(shutdowns, 0);
});
