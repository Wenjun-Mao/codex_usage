const assert = require("node:assert/strict");
const test = require("node:test");

const { LatestRefreshCoordinator } = require("../out/latestRefreshCoordinator");

function deferredQueue() {
  const entries = new Map();
  return {
    next(key) {
      let resolve;
      let reject;
      const promise = new Promise((resolvePromise, rejectPromise) => {
        resolve = resolvePromise;
        reject = rejectPromise;
      });
      entries.set(key, { promise, resolve, reject });
      return entries.get(key);
    },
    resolve(key, value) {
      entries.get(key).resolve(value);
    },
    reject(key, error) {
      entries.get(key).reject(error);
    },
  };
}

function tick() {
  return new Promise((resolve) => setImmediate(resolve));
}

function deferred() {
  let resolve;
  const promise = new Promise((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

test("latest refresh coordinator runs one process and publishes only newest request", async () => {
  const gates = deferredQueue();
  const running = [];
  const published = [];
  const coordinator = new LatestRefreshCoordinator(
    async (request) => {
      running.push(request);
      return gates.next(request).promise;
    },
    async (request, result) => published.push([request, result]),
  );

  const first = coordinator.request("today");
  const second = coordinator.request("yesterday");
  const third = coordinator.request("7d");
  assert.deepEqual(running, ["today"]);

  gates.resolve("today", "old");
  await tick();
  assert.deepEqual(running, ["today", "7d"]);
  gates.resolve("7d", "new");

  assert.equal(await first, "superseded");
  assert.equal(await second, "superseded");
  assert.equal(await third, "published");
  assert.deepEqual(published, [["7d", "new"]]);
});

test("latest refresh coordinator discards a stale execution error before publishing a newer success", async () => {
  const gates = deferredQueue();
  const running = [];
  const published = [];
  const coordinator = new LatestRefreshCoordinator(
    async (request) => {
      running.push(request);
      return gates.next(request).promise;
    },
    (request, result) => published.push([request, result]),
  );

  const first = coordinator.request("today");
  const second = coordinator.request("7d");
  gates.reject("today", new Error("obsolete failure"));
  await tick();
  assert.deepEqual(running, ["today", "7d"]);
  gates.resolve("7d", "fresh report");

  assert.equal(await first, "superseded");
  assert.equal(await second, "published");
  assert.deepEqual(published, [["7d", "fresh report"]]);
});

test("latest refresh coordinator clears active state after publish failure", async () => {
  const executed = [];
  const published = [];
  let failFirstPublish = true;
  const coordinator = new LatestRefreshCoordinator(
    async (request) => {
      executed.push(request);
      return `${request} report`;
    },
    async (request, result) => {
      published.push([request, result]);
      if (failFirstPublish) {
        failFirstPublish = false;
        throw new Error("publish failed");
      }
    },
  );

  await assert.rejects(coordinator.request("today"), /publish failed/);
  assert.equal(await coordinator.request("7d"), "published");
  assert.deepEqual(executed, ["today", "7d"]);
  assert.deepEqual(published, [["today", "today report"], ["7d", "7d report"]]);
});

test("latest refresh coordinator accepts a new request after becoming idle", async () => {
  const executed = [];
  const published = [];
  const coordinator = new LatestRefreshCoordinator(
    async (request) => {
      executed.push(request);
      return `${request} report`;
    },
    (request, result) => published.push([request, result]),
  );

  assert.equal(await coordinator.request("today"), "published");
  assert.equal(await coordinator.request("month"), "published");
  assert.deepEqual(executed, ["today", "month"]);
  assert.deepEqual(published, [["today", "today report"], ["month", "month report"]]);
});

test("latest refresh coordinator prevents an async publisher from committing after replacement", async () => {
  const firstPublisherStarted = deferred();
  const allowFirstPublisher = deferred();
  const executed = [];
  const committed = [];
  const coordinator = new LatestRefreshCoordinator(
    async (request) => {
      executed.push(request);
      return `${request} report`;
    },
    async (request, result, publication) => {
      if (request === "today") {
        firstPublisherStarted.resolve();
        await allowFirstPublisher.promise;
      }
      publication.commit(() => committed.push([request, result]));
    },
  );

  const first = coordinator.request("today");
  await firstPublisherStarted.promise;
  const second = coordinator.request("7d");
  allowFirstPublisher.resolve();

  assert.equal(await first, "superseded");
  assert.equal(await second, "published");
  assert.deepEqual(executed, ["today", "7d"]);
  assert.deepEqual(committed, [["7d", "7d report"]]);
  assert.equal(await coordinator.request("month"), "published");
  assert.deepEqual(committed, [["7d", "7d report"], ["month", "month report"]]);
});
