const assert = require("node:assert/strict");
const { EventEmitter } = require("node:events");
const path = require("node:path");
const test = require("node:test");
const { AgentIncompatibleError, AgentUnavailableError } = require("../out/agentClient");
const { AgentSupervisor } = require("../out/agentSupervisor");

function supervisorWith(discover) {
  const calls = [];
  let sleeps = 0;
  const supervisor = new AgentSupervisor({
    settingsFile: "/tmp/accounting-settings.json",
    getCodexHome: async () => "/tmp/accounting-home",
    resolveExecutable: async () => "/tmp/accounting-agent",
    discover,
    sleep: async () => { sleeps += 1; },
    spawn: (_command, args) => {
      calls.push([...args]);
      const child = new EventEmitter();
      child.stdout = new EventEmitter();
      child.stderr = new EventEmitter();
      child.unref = () => {};
      if (!args.includes("--parent-pid")) process.nextTick(() => child.emit("close", 0));
      return child;
    },
  });
  return { supervisor, calls, sleepCount: () => sleeps };
}

for (const operation of ["acquire", "change home", "handoff"]) {
  test(`incompatible collector refuses ${operation} without writer or settings controls`, async () => {
    let discoveries = 0;
    const { supervisor, calls, sleepCount } = supervisorWith(async () => {
      discoveries += 1;
      throw new AgentIncompatibleError();
    });
    // Service registration inspection is read-only; mutation is forbidden.
    supervisor.legacyServiceStatus = async () => ({
      supported: true, installed: true, recognized: true, detail: "fixture",
    });
    const action = operation === "acquire" ? () => supervisor.acquire()
      : operation === "change home" ? () => supervisor.configureCodexHome("/tmp/other-home")
        : () => supervisor.handoffLegacyService();
    await assert.rejects(action(), AgentIncompatibleError);
    assert.equal(discoveries, 1);
    assert.equal(sleepCount(), 0);
    assert.deepEqual(calls, []);
    assert.equal(supervisor.managedClient, undefined);
  });
}

test("incompatibility during startup propagates immediately instead of retrying or claiming ownership", async () => {
  let discoveries = 0;
  const { supervisor, calls, sleepCount } = supervisorWith(async () => {
    discoveries += 1;
    if (discoveries === 1) throw new AgentUnavailableError("not running yet");
    throw new AgentIncompatibleError();
  });
  await assert.rejects(supervisor.acquire(), AgentIncompatibleError);
  assert.equal(discoveries, 2);
  assert.equal(sleepCount(), 0);
  assert.equal(calls.length, 2);
  assert(calls[0].includes("--set-codex-home"));
  assert(calls[1].includes("--parent-pid"));
  assert.equal(supervisor.managedClient, undefined);
  assert.equal(supervisor.starting, undefined);
});

test("incompatible destination is checked before stopping an owned collector or persisting the new home", async () => {
  const target = path.resolve("/tmp/destination-home");
  let shutdowns = 0;
  const owned = {
    post: async () => { shutdowns += 1; },
    isSameAgent: () => true,
    isTransientOwnedBy: () => true,
  };
  const discoveries = [];
  const { supervisor, calls } = supervisorWith(async home => {
    discoveries.push(home);
    if (home === target) throw new AgentIncompatibleError();
    return owned;
  });
  supervisor.managedClient = owned;
  supervisor.managedHome = path.resolve("/tmp/accounting-home");
  supervisor.managedLaunchId = "a".repeat(48);
  await assert.rejects(supervisor.configureCodexHome(target), AgentIncompatibleError);
  assert.deepEqual(discoveries, [target]);
  assert.equal(shutdowns, 0);
  assert.deepEqual(calls, []);
  assert.equal(supervisor.managedClient, owned);
});

test("incompatible replacement never receives the previously managed collector's shutdown", async () => {
  let rejectDiscovery = false;
  let shutdowns = 0;
  const managed = {
    post: async () => { shutdowns += 1; },
    isSameAgent: () => true,
    isTransientOwnedBy: () => true,
  };
  const { supervisor, calls } = supervisorWith(async () => {
    if (rejectDiscovery) throw new AgentIncompatibleError();
    return managed;
  });
  await supervisor.acquire();
  supervisor.managedClient = managed;
  supervisor.managedHome = "/tmp/accounting-home";
  supervisor.managedLaunchId = "a".repeat(48);
  rejectDiscovery = true;
  await assert.rejects(supervisor.stopManagedAgent(), AgentIncompatibleError);
  assert.equal(shutdowns, 0);
  assert.deepEqual(calls, []);
});
