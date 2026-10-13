/* Verify qualification, explicit promotion and official public package bytes. */
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const { parseArgs } = require('node:util');
const { root, targets, digest, publicClient, targetEntry } = require('./release/marketplace.cjs');

async function main() {
  const { values } = parseArgs({ options: Object.fromEntries([
    'qualification-run', 'qualification-attempt', 'promotion-run', 'promotion-attempt', 'output'
  ].map(key => [key, { type: 'string' }])) });
  for (const key of ['qualification-run', 'qualification-attempt', 'promotion-run', 'promotion-attempt'])
    assert(/^[1-9][0-9]{0,19}$/.test(values[key] || ''), `Missing or invalid --${key}`);
  assert(values.output, 'Missing --output');
  const directory = path.resolve(values.output);
  await fs.mkdir(directory, { recursive: true });
  const api = endpoint => JSON.parse(execFileSync('gh', ['api', '--hostname', 'github.com',
    `repos/Wenjun-Mao/codex_usage/${endpoint}`], { cwd: root, encoding: 'utf8' }));
  const publication = api(`actions/runs/${values['promotion-run']}`);
  assert.equal(publication.event, 'workflow_dispatch');
  assert.equal(publication.path, '.github/workflows/promote-vsix.yml');
  assert.equal(publication.repository.full_name, 'Wenjun-Mao/codex_usage');
  assert.equal(publication.head_repository.id, publication.repository.id);
  assert.equal(publication.status, 'completed');
  assert.equal(publication.conclusion, 'success');
  assert.equal(String(publication.run_attempt), values['promotion-attempt']);
  const jobs = api(`actions/runs/${values['promotion-run']}/attempts/${values['promotion-attempt']}/jobs`).jobs;
  const required = name => {
    const matches = jobs.filter(job => job.name === name);
    assert.equal(matches.length, 1, `Missing or duplicate job ${name}`);
    assert.equal(matches[0].conclusion, 'success');
    return matches[0];
  };
  required('Validate qualification');
  required('Publish qualified packages');
  execFileSync('uv', ['run', 'python', 'scripts/qualification.py', 'validate-publication',
    '--run', values['qualification-run'], '--attempt', values['qualification-attempt'],
    '--promotion-run', values['promotion-run'], '--promotion-attempt', values['promotion-attempt'],
    '--ref', `refs/tags/${publication.head_branch}`, '--output', directory], { cwd: root, stdio: 'inherit' });
  const qualified = JSON.parse(await fs.readFile(path.join(directory, 'qualified.json'), 'utf8'));
  assert.equal(publication.head_sha, qualified.source.sha);
  execFileSync('uv', ['run', 'python', 'scripts/publication_intent.py', 'verify-complete', '--directory', directory],
    { cwd: root, stdio: 'inherit' });
  const catalog = publicClient();
  const deadline = Date.now() + 30 * 60 * 1000;
  let current;
  while (Date.now() < deadline) {
    current = await catalog();
    await fs.writeFile(path.join(directory, 'catalog.json'), JSON.stringify(current, null, 2) + '\n');
    if (targets.every(target => current.versions.some(row => row.version === qualified.source.version &&
      row.targetPlatform === target && (row.flags & 1)))) break;
    console.log('Awaiting validated official entries; no re-upload');
    await new Promise(resolve => setTimeout(resolve, 30000));
  }
  const evidence = { schema: 1, version: qualified.source.version, tag: qualified.tag,
    commit: qualified.source.sha, verifiedAt: new Date().toISOString(),
    qualificationRun: qualified.qualification_run, qualificationAttempt: qualified.qualification_attempt,
    promotionRun: publication.id, promotionAttempt: publication.run_attempt, targets: [] };
  for (const target of targets) {
    const entry = await targetEntry(current, qualified.source.version, target);
    assert(entry, `Missing public ${target}`);
    assert.equal(entry.sha256, qualified.manifest.packages[target].sha256, `Public/qualified mismatch ${target}`);
    const local = await fs.readFile(path.join(directory, `codex-usage-companion-${target}.vsix`));
    assert.equal(entry.sha256, digest(local));
    await fs.writeFile(path.join(directory, `official-${target}.vsix`), entry.contents);
    const { contents, ...metadata } = entry;
    evidence.targets.push({ ...metadata, qualifiedArtifactEqual: true, catalogHashEqual: true });
    console.log(`${target}: public = qualified package = catalog hash`);
  }
  await fs.writeFile(path.join(directory, 'verification.json'), JSON.stringify(evidence, null, 2) + '\n');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
