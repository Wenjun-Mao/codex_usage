/* Trusted per-target publisher; each invocation requires a durable prior intent. */
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const { root, targets, digest, publicClient, targetEntry, preflightPackages } = require('./release/marketplace.cjs');

function checkFiles(directory, env) {
  const environment = Object.fromEntries(Object.entries(env).filter(([key]) =>
    ['PATH', 'HOME', 'TMPDIR', 'SYSTEMROOT', 'UV_CACHE_DIR'].includes(key)));
  execFileSync('uv', ['run', 'python', 'scripts/qualification.py', 'check-files', '--directory', directory],
    { cwd: root, env: environment, stdio: 'inherit' });
}

function upload(directory, target, env) {
  const { vsceCliPath } = require(path.join(root, 'extensions/vscode/scripts/cliEntrypoints'));
  execFileSync(process.execPath, [vsceCliPath(), 'publish', '--packagePath',
    path.join(directory, `codex-usage-companion-${target}.vsix`)], { cwd: root, env, stdio: 'inherit' });
}

async function runPublisher(directory, mode, options = {}) {
  assert(directory && (['prepare', 'complete'].includes(mode) || targets.includes(mode)),
    'Usage: node scripts/publish_qualified_vsix.cjs DIRECTORY prepare|complete|TARGET');
  const env = options.environment || process.env;
  if (mode === 'prepare' || mode === 'complete') assert(!env.VSCE_PAT, 'Nonpublishing step received publisher credentials');
  const files = options.files || fs;
  (options.checkFiles || checkFiles)(directory, env);
  const qualified = JSON.parse(await files.readFile(path.join(directory, 'qualified.json'), 'utf8'));
  assert.equal(qualified.status, 'validated-for-publication');
  assert.equal(qualified.source.probe, false);
  assert.equal(env.GITHUB_SHA, qualified.source.sha, 'Immutable dispatch source changed');
  assert.equal(env.GITHUB_REF, qualified.promotion.ref);
  assert.equal(qualified.promotion.sha, qualified.source.sha);
  assert.equal(String(qualified.promotion.run), env.GITHUB_RUN_ID);
  assert.equal(String(qualified.promotion.attempt), env.GITHUB_RUN_ATTEMPT);
  const packages = {};
  for (const target of targets) packages[target] = await files.readFile(path.join(directory, `codex-usage-companion-${target}.vsix`));
  const catalog = options.lookup ? null : publicClient();
  const lookup = options.lookup || (async (version, target) => targetEntry(await catalog(), version, target));
  const save = async result => files.writeFile(path.join(directory, 'publication.json'), JSON.stringify(result, null, 2) + '\n');
  const log = options.log || console.log;
  const timing = qualified.latency_binding ? { latency_binding: qualified.latency_binding } : {};
  const binding = { schema: 1, source: qualified.source, tag: qualified.tag, promotion: qualified.promotion,
    qualification_run: qualified.qualification_run, qualification_attempt: qualified.qualification_attempt,
    manifest_sha256: qualified.manifest_sha256, ...timing };
  const validateOutcome = result => { for (const [key, value] of Object.entries(binding)) assert.deepEqual(result[key], value); };
  if (mode === 'complete') {
    const result = JSON.parse(await files.readFile(path.join(directory, 'publication.json'), 'utf8'));
    validateOutcome(result);
    assert(targets.every(target => ['public-hash-matched', 'upload-returned-success-awaiting-public-validation'].includes(result.targets[target])));
    result.status = 'uploaded-awaiting-public-validation';
    await save(result);
    log('CODEX_PROMOTION_COMPLETE ' + JSON.stringify({ qualification_run: qualified.qualification_run,
      qualification_attempt: qualified.qualification_attempt, source: qualified.source, packages: qualified.manifest.packages, ...timing }));
    return result;
  }
  if (mode === 'prepare') {
    try {
      await files.readFile(path.join(directory, 'publication.json'));
      throw new Error('Publication directory already has an outcome; do not reset possible side effects');
    } catch (error) {
      if (error.code !== 'ENOENT') throw error;
    }
    const priorIntents = JSON.parse(await files.readFile(path.join(directory, 'prior-intents.json'), 'utf8'));
    const occupied = await preflightPackages({ qualified, packages, lookup, priorIntents });
    const plan = { ...binding, targets: Object.fromEntries(targets.map(target =>
      [target, occupied[target] ? 'public-hash-matched' : 'eligible-not-attempted'])) };
    await files.writeFile(path.join(directory, 'publication-plan.json'), JSON.stringify(plan) + '\n');
    await save({ ...plan, intents: {}, status: 'preflight-complete-no-upload' });
    if (env.GITHUB_OUTPUT) await files.appendFile(env.GITHUB_OUTPUT,
      `mac=${!occupied['darwin-arm64']}\nwin=${!occupied['win32-x64']}\n`);
    return plan;
  }
  assert(env.VSCE_PAT, 'Publisher credentials missing');
  const plan = JSON.parse(await files.readFile(path.join(directory, 'publication-plan.json'), 'utf8'));
  validateOutcome(plan);
  assert.equal(plan.targets[mode], 'eligible-not-attempted');
  const ack = JSON.parse(await files.readFile(path.join(directory, `intent-${mode}-ack.json`), 'utf8'));
  assert.equal(ack.target, mode);
  assert(/^[1-9][0-9]*$/.test(ack.artifact_id) && /^[0-9a-f]{64}$/.test(ack.artifact_digest));
  assert.equal(ack.run, qualified.promotion.run);
  assert.equal(ack.attempt, qualified.promotion.attempt);
  const body = await files.readFile(path.join(directory, `intent-${mode}/intent.json`));
  assert.equal(ack.intent_sha256, digest(body));
  const intent = JSON.parse(body);
  assert.deepEqual(intent, { schema: 1, kind: 'publication-intent', source: qualified.source, tag: qualified.tag,
    qualification_run: qualified.qualification_run, qualification_attempt: qualified.qualification_attempt,
    manifest_sha256: qualified.manifest_sha256, publisher_sha: qualified.promotion.publisher_sha,
    target: mode, package: qualified.manifest.packages[mode],
    origin: { run: qualified.promotion.run, attempt: qualified.promotion.attempt, job: 'publish' }, ...timing });
  const authority = JSON.parse(await files.readFile(path.join(directory, `intent-${mode}-authority.json`), 'utf8'));
  validateOutcome(authority);
  assert.equal(authority.target, mode);
  assert.equal(authority.package_sha256, qualified.manifest.packages[mode].sha256);
  assert.equal(authority.intent_sha256, digest(body));
  assert.deepEqual(authority.journal, ack.journal);
  const policy = JSON.parse(await files.readFile(path.join(root, 'scripts/release/journal-origins.json'), 'utf8')).domains.production;
  assert.equal(ack.journal.domain, 'production');
  assert.equal(ack.journal.genesis, policy.genesis);
  assert.equal(ack.journal.ref, policy.ref);
  assert.equal(ack.journal.intent_sha256, digest(body));
  assert(/^[0-9a-f]{40}$/.test(ack.journal.commit) && Number.isSafeInteger(ack.journal.sequence) && ack.journal.sequence > 0 &&
    /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/.test(ack.journal.invocation));
  const result = JSON.parse(await files.readFile(path.join(directory, 'publication.json'), 'utf8'));
  validateOutcome(result);
  assert.equal(result.targets[mode], 'eligible-not-attempted', 'Target was already attempted; remain pending');
  result.intents[mode] = ack;
  result.targets[mode] = 'possibly-uploaded';
  await save(result);
  try {
    const occupied = await lookup(qualified.source.version, mode);
    if (occupied) {
      assert.equal(occupied.sha256, qualified.manifest.packages[mode].sha256, 'Occupied target changed');
      result.targets[mode] = 'public-hash-matched';
    } else {
      await (options.upload || upload)(directory, mode, env);
      result.targets[mode] = 'upload-returned-success-awaiting-public-validation';
    }
    result.status = 'uploaded-or-partial-awaiting-public-validation';
    await save(result);
    log('CODEX_PROMOTION ' + JSON.stringify({ target: mode, qualification_run: qualified.qualification_run,
      qualification_attempt: qualified.qualification_attempt, source: qualified.source, package: qualified.manifest.packages[mode] }));
    return result;
  } catch (error) {
    result.status = 'failed-or-partial';
    result.failure = error.message;
    await save(result);
    throw error;
  }
}
if (require.main === module) runPublisher(path.resolve(process.argv[2] || ''), process.argv[3])
  .catch(error => { console.error(error); process.exitCode = 1; });
module.exports = { runPublisher, checkFiles };
