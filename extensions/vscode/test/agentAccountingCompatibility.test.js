const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const http = require("node:http");
const os = require("node:os");
const path = require("node:path");
const test = require("node:test");
const { AgentClient, AgentIncompatibleError, AgentUnavailableError } = require("../out/agentClient");
const { AgentSupervisor } = require("../out/agentSupervisor");

const capability = "physical-lineage-accounting-v2";
const health = { ok: true, api_version: 1, capabilities: [capability] };

async function fixture(context, payload) {
  const home = await fs.mkdtemp(path.join(os.tmpdir(), "accounting-compatibility-"));
  const descriptorPath = path.join(home, ".codex-usage", "agent.json");
  await fs.mkdir(path.dirname(descriptorPath));
  const calls = [];
  const server = http.createServer((request, response) => {
    calls.push({ method: request.method, path: request.url, token: request.headers.authorization });
    response.setHeader("Content-Type", "application/json");
    response.end(JSON.stringify(request.url === "/v1/health" ? payload : { ready: true }));
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  const descriptor = {
    pid: process.pid, api_version: 1, port: server.address().port,
    token: "f".repeat(40), codex_home: home,
    // Descriptor metadata must never substitute for runtime health.
    capabilities: [capability],
  };
  await fs.writeFile(descriptorPath, JSON.stringify(descriptor));
  const close = async () => {
    if (server.listening) await new Promise(resolve => server.close(resolve));
  };
  context.after(async () => {
    await close();
    await fs.rm(home, { recursive: true, force: true });
  });
  return { home, descriptorPath, descriptor, calls, close };
}

test("Python background descriptors accept a null parent without granting transient ownership", async context => {
  const instance = await fixture(context, health);
  await fs.writeFile(instance.descriptorPath, JSON.stringify({
    ...instance.descriptor, process_owner: "background", parent_pid: null, launch_id: null,
  }));
  const supervisor = new AgentSupervisor({
    settingsFile: path.join(instance.home, "settings.json"),
    getCodexHome: async () => instance.home,
    resolveExecutable: async () => assert.fail("must not resolve a fallback executable"),
    spawn: () => assert.fail("must not spawn collector or settings controls"),
  });
  const client = await supervisor.acquire();
  assert.equal(client.processOwner, "background");
  assert.equal(client.isTransientOwnedBy(process.pid, "a".repeat(48)), false);
  assert.equal(await supervisor.stopManagedAgent(), false);
  assert.deepEqual(instance.calls.map(call => call.path), ["/v1/health"]);
});

for (const [name, ownership] of [
  ["null transient parent", { process_owner: "transient", parent_pid: null }],
  ["omitted transient parent", { process_owner: "transient" }],
  ["string background parent", { process_owner: "background", parent_pid: "123" }],
  ["boolean background parent", { process_owner: "background", parent_pid: false }],
  ["nonpositive transient parent", { process_owner: "transient", parent_pid: 0 }],
  ["fractional transient parent", { process_owner: "transient", parent_pid: 1.5 }],
  ["nonempty background parent", { process_owner: "background", parent_pid: process.pid }],
]) {
  test(`discovery rejects ${name} before health or ownership adoption`, async context => {
    const instance = await fixture(context, health);
    await fs.writeFile(instance.descriptorPath, JSON.stringify({ ...instance.descriptor, ...ownership }));
    await assert.rejects(AgentClient.discoverAt(instance.home), AgentUnavailableError);
    assert.deepEqual(instance.calls, []);
  });
}

for (const [name, capabilities] of [
  ["missing", undefined], ["null", null], ["empty", []],
  ["wrong version", ["physical-lineage-accounting-v0"]],
  ["pre-fence preview", ["physical-lineage-accounting-v1"]],
  ["string", capability], ["object", { [capability]: true }],
  ["mixed types", [capability, 1]],
]) {
  test(`discovery refuses ${name} accounting capability without treating it as unavailable`, async context => {
    const { home, calls } = await fixture(context, { ...health, capabilities });
    await assert.rejects(AgentClient.discoverAt(home), error => {
      assert(error instanceof AgentIncompatibleError);
      assert(!(error instanceof AgentUnavailableError));
      assert.match(error.message, /accounting/i);
      return true;
    });
    assert.deepEqual(calls.map(call => call.path), ["/v1/health"]);
  });
}

test("a healthy different API is incompatible, not a reason to start another writer", async context => {
  const { home } = await fixture(context, { ...health, api_version: 2 });
  await assert.rejects(AgentClient.discoverAt(home), error => error instanceof AgentIncompatibleError);
});

for (const mismatch of ["capability", "descriptor API"]) {
  test(`real discovery propagates ${mismatch} incompatibility through supervisor without controls`, async context => {
    const instance = await fixture(context, mismatch === "capability" ? { ok: true, api_version: 1 } : health);
    if (mismatch === "descriptor API") {
      await fs.writeFile(instance.descriptorPath, JSON.stringify({ ...instance.descriptor, api_version: 2 }));
    }
    const supervisor = new AgentSupervisor({
      settingsFile: path.join(instance.home, "settings.json"),
      getCodexHome: async () => instance.home,
      resolveExecutable: async () => assert.fail("must not resolve executable"),
      spawn: () => assert.fail("must not spawn settings or collector controls"),
    });
    await assert.rejects(supervisor.acquire(), AgentIncompatibleError);
    assert.deepEqual(instance.calls.map(call => call.path), mismatch === "capability" ? ["/v1/health"] : []);
  });
}

test("health readiness must be the boolean true", async context => {
  const { home } = await fixture(context, { ...health, ok: "true" });
  await assert.rejects(AgentClient.discoverAt(home), AgentUnavailableError);
});

test("failed descriptor refresh never adopts the incompatible collector for later writes", async context => {
  const current = await fixture(context, health);
  const replacement = await fixture(context, { ok: true, api_version: 1 });
  const client = await AgentClient.discoverAt(current.home);
  await current.close();
  await fs.writeFile(current.descriptorPath, JSON.stringify({
    ...replacement.descriptor, codex_home: current.home, pid: process.pid + 1,
  }));

  await assert.rejects(client.get("/v1/status"), error => error instanceof AgentIncompatibleError);
  assert.equal(client.processId, process.pid);
  await assert.rejects(client.post("/v1/capture"), AgentUnavailableError);
  assert.deepEqual(replacement.calls.map(call => call.path), ["/v1/health"]);
  assert.equal(replacement.calls[0].token, `Bearer ${replacement.descriptor.token}`);
  assert.equal(client.descriptor.port, current.descriptor.port);
});

for (const failure of ["transport", "malformed health", "malformed descriptor", "descriptor API"]) {
  test(`failed refresh with ${failure} preserves the last verified descriptor`, async context => {
    const current = await fixture(context, health);
    const replacement = await fixture(context, failure === "malformed health" ? null : health);
    const client = await AgentClient.discoverAt(current.home);
    await current.close();
    if (failure === "transport") await replacement.close();
    await fs.writeFile(current.descriptorPath, JSON.stringify({
      ...replacement.descriptor, codex_home: current.home,
      pid: failure === "malformed descriptor" ? -1 : process.pid + 1,
      api_version: failure === "descriptor API" ? 2 : 1,
    }));
    const ErrorType = failure === "descriptor API" ? AgentIncompatibleError : AgentUnavailableError;
    await assert.rejects(client.get("/v1/status"), ErrorType);
    assert.equal(client.processId, process.pid);
    assert.equal(client.descriptor.port, current.descriptor.port);
    await assert.rejects(client.post("/v1/capture"), AgentUnavailableError);
    assert(replacement.calls.every(call => call.path === "/v1/health"));
  });
}
