const assert = require('node:assert/strict');
const test = require('node:test');
const { digest, targets, root } = require('../scripts/release/marketplace.cjs');
const path = require('node:path');
const { runPublisher } = require('../scripts/publish_qualified_vsix.cjs');

function fixture(withTiming = false) {
  const directory = '/synthetic';
  const packages = Object.fromEntries(targets.map(target => [target, Buffer.from(target)]));
  const qualified = { schema: 1, status: 'validated-for-publication', tag: 'v2.12.3',
    source: { version: '2.12.3', sha: 'a'.repeat(40), probe: false }, qualification_run: 77, qualification_attempt: 2,
    manifest_sha256: 'f'.repeat(64), manifest: { packages: Object.fromEntries(targets.map(target =>
      [target, { sha256: digest(packages[target]), bytes: packages[target].length }])) },
    promotion: { run: 99, attempt: 1, sha: 'a'.repeat(40), ref: 'refs/tags/v2.12.3', publisher_sha: 'd'.repeat(40) } };
  if (withTiming) qualified.latency_binding = { schema: 1, domain: 'production',
    ref: 'refs/heads/codex/publication-receipts', genesis: 'e'.repeat(40), commit: 'b'.repeat(40),
    sequence: 1, invocation: 'f983a06b-d378-4aeb-a909-a6cfbd6e8ce8', binding_sha256: 'c'.repeat(64) };
  const documents = new Map();
  const put = (name, value) => documents.set(`${directory}/${name}`, Buffer.from(JSON.stringify(value) + '\n'));
  put('qualified.json', qualified);
  put('prior-intents.json', {});
  documents.set(path.join(root, 'scripts/release/journal-origins.json'), Buffer.from(JSON.stringify({ domains: {
    production: { ref: 'refs/heads/codex/publication-receipts', genesis: 'e'.repeat(40) } } })));
  for (const target of targets) documents.set(`${directory}/codex-usage-companion-${target}.vsix`, packages[target]);
  const uploads = [], saved = [], logs = [];
  const options = { environment: { GITHUB_RUN_ID: '99', GITHUB_RUN_ATTEMPT: '1', GITHUB_SHA: qualified.source.sha,
    GITHUB_REF: qualified.promotion.ref }, checkFiles: () => {}, lookup: async () => null, log: line => logs.push(line),
    upload: async (dir, target) => uploads.push(target), files: {
      readFile: async (name, encoding) => { if (!documents.has(name)) throw Object.assign(Error(`Missing ${name}`), { code: 'ENOENT' });
        return encoding ? documents.get(name).toString() : documents.get(name); },
      writeFile: async (name, value) => { documents.set(name, Buffer.from(value));
        if (name.endsWith('/publication.json')) saved.push(JSON.parse(value)); },
    } };
  const recordIntent = target => {
    put(`intent-${target}/intent.json`, { schema: 1, kind: 'publication-intent', source: qualified.source,
      tag: qualified.tag, qualification_run: 77, qualification_attempt: 2, manifest_sha256: qualified.manifest_sha256,
      publisher_sha: qualified.promotion.publisher_sha, target, package: qualified.manifest.packages[target],
      origin: { run: 99, attempt: 1, job: 'publish' },
      ...(withTiming ? { latency_binding: qualified.latency_binding } : {}) });
    const intent_sha256 = digest(documents.get(`${directory}/intent-${target}/intent.json`));
    const journal = { schema: 1, domain: 'production', ref: 'refs/heads/codex/publication-receipts',
      genesis: 'e'.repeat(40), commit: 'f'.repeat(40), sequence: 1,
      invocation: 'f983a06b-d378-4aeb-a909-a6cfbd6e8ce8', intent_sha256 };
    put(`intent-${target}-ack.json`, { target, artifact_id: '123', artifact_digest: 'b'.repeat(64),
      run: 99, attempt: 1, intent_sha256, journal });
    put(`intent-${target}-authority.json`, { schema: 1, source: qualified.source, tag: qualified.tag,
      promotion: qualified.promotion, qualification_run: 77, qualification_attempt: 2,
      manifest_sha256: qualified.manifest_sha256, target, package_sha256: qualified.manifest.packages[target].sha256,
      intent_sha256, journal, ...(withTiming ? { latency_binding: qualified.latency_binding } : {}) });
  };
  return { directory, qualified, documents, options, uploads, saved, logs, put, recordIntent };
}

test('candidate-bound timing reference survives intent, outcome and completion', async () => {
  const f = fixture(true);
  await runPublisher(f.directory, 'prepare', f.options);
  f.options.environment.VSCE_PAT = 'synthetic-test-value';
  for (const target of targets) {
    f.recordIntent(target);
    await runPublisher(f.directory, target, f.options);
  }
  delete f.options.environment.VSCE_PAT;
  const result = await runPublisher(f.directory, 'complete', f.options);
  assert.deepEqual(result.latency_binding, f.qualified.latency_binding);
  const complete = JSON.parse(f.logs.find(line => line.startsWith('CODEX_PROMOTION_COMPLETE ')).slice('CODEX_PROMOTION_COMPLETE '.length));
  assert.deepEqual(complete.latency_binding, f.qualified.latency_binding);
});

test('a matching intent digest cannot hide a missing or changed timing binding', async () => {
  for (const fault of ['missing', 'changed']) {
    const f = fixture(true), target = targets[0];
    await runPublisher(f.directory, 'prepare', f.options);
    f.recordIntent(target);
    const body = JSON.parse(f.documents.get(`${f.directory}/intent-${target}/intent.json`));
    if (fault === 'missing') delete body.latency_binding;
    else body.latency_binding.commit = '0'.repeat(40);
    f.put(`intent-${target}/intent.json`, body);
    const sha = digest(f.documents.get(`${f.directory}/intent-${target}/intent.json`));
    for (const suffix of ['ack', 'authority']) {
      const value = JSON.parse(f.documents.get(`${f.directory}/intent-${target}-${suffix}.json`));
      value.intent_sha256 = value.journal.intent_sha256 = sha;
      f.put(`intent-${target}-${suffix}.json`, value);
    }
    f.options.environment.VSCE_PAT = 'synthetic-test-value';
    await assert.rejects(runPublisher(f.directory, target, f.options));
    assert.deepEqual(f.uploads, []);
  }
});

test('actual per-target entrypoint requires durable intent and binds every outcome', async () => {
  const f = fixture();
  await runPublisher(f.directory, 'prepare', f.options);
  f.options.environment.VSCE_PAT = 'synthetic-test-value';
  await assert.rejects(runPublisher(f.directory, targets[0], f.options), /Missing .*ack/);
  assert.deepEqual(f.uploads, []);
  for (const target of targets) {
    f.recordIntent(target);
    await runPublisher(f.directory, target, f.options);
  }
  delete f.options.environment.VSCE_PAT;
  const result = await runPublisher(f.directory, 'complete', f.options);
  assert.deepEqual(f.uploads, targets);
  assert.equal(result.manifest_sha256, f.qualified.manifest_sha256);
  assert.deepEqual(Object.keys(result.intents).sort(), [...targets].sort());
});

test('actual preflight rejects second-target conflicts before any publication', async () => {
  const f = fixture();
  f.options.lookup = async (version, target) => target === targets[1] ? { sha256: '0'.repeat(64) } : null;
  await assert.rejects(runPublisher(f.directory, 'prepare', f.options));
  assert.deepEqual(f.uploads, []);
  assert(!f.documents.has(`${f.directory}/publication-plan.json`));
});

test('actual entrypoint preserves uncertainty after accepted upload reports failure', async () => {
  const f = fixture();
  await runPublisher(f.directory, 'prepare', f.options);
  f.recordIntent(targets[0]);
  f.options.environment.VSCE_PAT = 'synthetic-test-value';
  f.options.upload = async (dir, target) => { f.uploads.push(target); throw Error('accepted then CLI disconnected'); };
  await assert.rejects(runPublisher(f.directory, targets[0], f.options), /disconnected/);
  assert.equal(f.saved.at(-1).targets[targets[0]], 'possibly-uploaded');
  await assert.rejects(runPublisher(f.directory, targets[0], f.options), /already attempted/);
  assert.deepEqual(f.uploads, [targets[0]]);
  delete f.options.environment.VSCE_PAT;
  await assert.rejects(runPublisher(f.directory, 'complete', f.options));
  await assert.rejects(runPublisher(f.directory, 'prepare', f.options), /do not reset/);
  const retry = fixture();
  retry.put('prior-intents.json', { [targets[0]]: true });
  await assert.rejects(runPublisher(retry.directory, 'prepare', retry.options), /invisible/);
  assert.deepEqual(retry.uploads, []);
});

test('dispatch, intent, acknowledgment and saved outcome drift never upload', async () => {
  for (const fault of ['dispatch', 'ack', 'body', 'outcome', 'qualification', 'authority', 'pilot-journal']) {
    const f = fixture();
    await runPublisher(f.directory, 'prepare', f.options);
    f.recordIntent(targets[0]);
    f.options.environment.VSCE_PAT = 'synthetic-test-value';
    if (fault === 'dispatch') f.options.environment.GITHUB_SHA = 'c'.repeat(40);
    if (fault === 'ack') f.put(`intent-${targets[0]}-ack.json`, { target: targets[0] });
    if (fault === 'body') f.put(`intent-${targets[0]}/intent.json`, { foreign: true });
    if (fault === 'outcome') f.put('publication.json', { schema: 1 });
    if (fault === 'authority') f.put(`intent-${targets[0]}-authority.json`, { schema: 1 });
    if (fault === 'pilot-journal') {
      const key = `${f.directory}/intent-${targets[0]}-ack.json`;
      const ack = JSON.parse(f.documents.get(key));
      ack.journal.domain = 'pilot';
      f.put(`intent-${targets[0]}-ack.json`, ack);
    }
    if (fault === 'qualification') {
      f.qualified.qualification_attempt = 3;
      f.put('qualified.json', f.qualified);
    }
    await assert.rejects(runPublisher(f.directory, targets[0], f.options));
    assert.deepEqual(f.uploads, []);
  }
});

test('nonpublishing modes reject publisher credentials', async () => {
  const f = fixture();
  f.options.environment.VSCE_PAT = 'synthetic-test-value';
  for (const mode of ['prepare', 'complete']) await assert.rejects(runPublisher(f.directory, mode, f.options), /credentials/);
  assert.deepEqual(f.uploads, []);
});

test('rejected file validation prevents every read, lookup, upload and outcome write', async () => {
  for (const mode of ['prepare', targets[0], 'complete']) {
    const f = fixture(true), calls = [];
    f.options.checkFiles = () => { calls.push('check-files'); throw Error('Rejected package authority'); };
    f.options.files.readFile = async () => { calls.push('read'); throw Error('Unexpected file read'); };
    f.options.lookup = async () => { calls.push('lookup'); throw Error('Unexpected catalog lookup'); };
    f.options.upload = async () => { calls.push('upload'); throw Error('Unexpected upload'); };
    await assert.rejects(runPublisher(f.directory, mode, f.options), /Rejected package authority/);
    assert.deepEqual(calls, ['check-files']);
    assert.deepEqual(f.uploads, []);
    assert.deepEqual(f.saved, []);
    assert.deepEqual(f.logs, []);
  }
});
