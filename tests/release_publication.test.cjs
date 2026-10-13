const assert = require('node:assert/strict');
const test = require('node:test');
const { digest, targets, publishPackages, targetEntry } = require('../scripts/release/marketplace.cjs');

function fixture() {
  const packages = Object.fromEntries(targets.map(target => [target, Buffer.from(target)]));
  const qualified = { schema: 1, status: 'validated-for-publication', tag: 'v2.12.2',
    source: { version: '2.12.2', probe: false }, qualification_run: 1, qualification_attempt: 1,
    manifest_sha256: 'a'.repeat(64), manifest: { packages: Object.fromEntries(targets.map(target =>
      [target, { sha256: digest(packages[target]), bytes: packages[target].length }])) } };
  const uploads = [], saved = [];
  return { qualified, packages, uploads, saved, lookup: async () => null,
    upload: async target => uploads.push(target), save: async result => saved.push(structuredClone(result)) };
}

test('unqualified, probe and wrong bytes never upload', async () => {
  for (const fault of ['unqualified', 'probe', 'bytes']) {
    const args = fixture();
    if (fault === 'unqualified') args.qualified.status = 'qualified-not-published';
    else if (fault === 'probe') args.qualified.source.probe = true;
    else args.packages['win32-x64'] = Buffer.from('changed');
    await assert.rejects(publishPackages(args));
    assert.deepEqual(args.uploads, []);
  }
});

test('matching occupied target resumes only missing target', async () => {
  const args = fixture();
  args.lookup = async (version, target) => target === 'darwin-arm64' ? { sha256: args.qualified.manifest.packages[target].sha256 } : null;
  const result = await publishPackages(args);
  assert.deepEqual(args.uploads, ['win32-x64']);
  assert.equal(result.targets[0].status, 'already-public-hash-matched');
  assert.equal(result.status, 'uploaded-awaiting-public-validation');
});

test('mismatching occupied version fails closed', async () => {
  const args = fixture();
  args.lookup = async () => ({ sha256: 'b'.repeat(64) });
  await assert.rejects(publishPackages(args), /Occupied version/);
  assert.deepEqual(args.uploads, []);
  assert.equal(args.saved.at(-1).status, 'failed-or-partial');
});

test('second-target conflict or pending cannot create a first-target partial upload', async () => {
  for (const fault of ['conflict', 'pending']) {
    const args = fixture();
    args.lookup = async (version, target) => {
      if (target === 'darwin-arm64') return null;
      if (fault === 'pending') throw Error('pending catalog validation');
      return { sha256: 'b'.repeat(64) };
    };
    await assert.rejects(publishPackages(args));
    assert.deepEqual(args.uploads, []);
  }
});

test('prior possibly accepted upload invisible in catalog is never re-uploaded', async () => {
  const args = fixture();
  args.priorIntents = { 'darwin-arm64': true };
  await assert.rejects(publishPackages(args), /invisible/);
  assert.deepEqual(args.uploads, []);
});

test('partial upload is retained, never silently called complete', async () => {
  const args = fixture();
  args.upload = async target => {
    if (target === 'win32-x64') throw Error('upload failed');
    args.uploads.push(target);
  };
  await assert.rejects(publishPackages(args), /upload failed/);
  const result = args.saved.at(-1);
  assert.equal(result.status, 'failed-or-partial');
  assert.equal(result.targets.length, 2);
  assert.equal(result.targets[1].status, 'possibly-uploaded');
});

test('unvalidated catalog is pending, not a reason to upload', async () => {
  const catalog = { versions: [{ version: '2.12.2', targetPlatform: 'darwin-arm64', flags: 0 }] };
  await assert.rejects(targetEntry(catalog, '2.12.2', 'darwin-arm64'), /pending validation/);
});

test('official download must match catalog hash and trusted HTTPS host', async () => {
  const contents = Buffer.from('official package');
  const entry = { version: '2.12.2', targetPlatform: 'darwin-arm64', flags: 1,
    files: [{ assetType: 'Microsoft.VisualStudio.Services.VSIXPackage', source: 'https://example.gallerycdn.vsassets.io/package' }],
    properties: [{ key: 'Microsoft.VisualStudio.Services.VsixSha256', value: digest(contents) }] };
  const fetcher = async () => ({ ok: true, arrayBuffer: async () => contents });
  const result = await targetEntry({ versions: [entry] }, '2.12.2', 'darwin-arm64', fetcher);
  assert.equal(result.sha256, digest(contents));
  entry.properties[0].value = 'b'.repeat(64);
  await assert.rejects(targetEntry({ versions: [entry] }, '2.12.2', 'darwin-arm64', fetcher));
  entry.files[0].source = 'http://untrusted.example/package';
  await assert.rejects(targetEntry({ versions: [entry] }, '2.12.2', 'darwin-arm64', fetcher));
});
