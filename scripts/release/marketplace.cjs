/* Exact public target hashes, shared by publishing and post-publication proof. */
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const path = require('node:path');
const root = path.resolve(__dirname, '../..');
const targets = ['darwin-arm64', 'win32-x64'];
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

function publicClient() {
  const util = require(path.join(root, 'extensions/vscode/node_modules/@vscode/vsce/out/util'));
  const { ExtensionQueryFlags: flags } = require(path.join(root, 'extensions/vscode/node_modules/azure-devops-node-api/interfaces/GalleryInterfaces'));
  assert.equal(util.getMarketplaceUrl(), 'https://marketplace.visualstudio.com');
  return () => util.getPublicGalleryAPI().getExtension('wenjun-mao.codex-usage-dashboard',
    [flags.IncludeVersions, flags.IncludeFiles, flags.IncludeVersionProperties]);
}

async function targetEntry(catalog, version, target, fetcher = fetch) {
  const entries = catalog.versions.filter(row => row.version === version && row.targetPlatform === target);
  assert(entries.length <= 1, `Duplicate public target ${target}`);
  if (!entries.length) return null;
  const entry = entries[0];
  assert(entry.flags & 1, `Public target ${target} is pending validation; do not re-upload`);
  const asset = entry.files.find(file => file.assetType === 'Microsoft.VisualStudio.Services.VSIXPackage');
  assert(asset, `Missing official package ${target}`);
  const url = new URL(asset.source);
  assert.equal(url.protocol, 'https:');
  assert(url.hostname.endsWith('.gallerycdn.vsassets.io') || url.hostname.endsWith('.gallery.vsassets.io'));
  const response = await fetcher(url, { signal: AbortSignal.timeout(60000) });
  assert(response.ok);
  const bytes = Buffer.from(await response.arrayBuffer());
  assert(bytes.length > 0 && bytes.length < 100 * 1024 * 1024);
  const sha256 = digest(bytes);
  const declared = entry.properties.find(property => property.key === 'Microsoft.VisualStudio.Services.VsixSha256');
  assert(declared && declared.value.toLowerCase() === sha256, `Catalog/download mismatch ${target}`);
  return { target, version, sha256, bytes: bytes.length, officialDownload: asset.source, contents: bytes };
}

async function preflightPackages({ qualified, packages, lookup, priorIntents = {} }) {
  assert.equal(qualified.status, 'validated-for-publication');
  assert.equal(qualified.schema, 1);
  assert.equal(qualified.tag, `v${qualified.source.version}`);
  assert.equal(qualified.source.probe, false);
  assert.deepEqual(Object.keys(packages).sort(), [...targets].sort());
  for (const target of targets) {
    const expected = qualified.manifest.packages[target];
    assert.equal(digest(packages[target]), expected.sha256, `Upload bytes differ ${target}`);
    assert.equal(packages[target].length, expected.bytes, `Upload size differs ${target}`);
  }
  const occupiedTargets = {};
  for (const target of targets) {
      const occupied = await lookup(qualified.source.version, target);
      if (occupied) {
        assert.equal(occupied.sha256, qualified.manifest.packages[target].sha256,
          `Occupied version has different ${target} bytes; stop`);
      } else {
        assert(!priorIntents[target], `Prior ${target} upload may be invisible; remain pending, do not re-upload`);
      }
    occupiedTargets[target] = occupied;
  }
  return occupiedTargets;
}

async function publishPackages({ qualified, packages, lookup, upload, save, priorIntents = {} }) {
  const result = { schema: 1, status: 'uploading', qualificationRun: qualified.qualification_run,
    qualificationAttempt: qualified.qualification_attempt, source: qualified.source,
    manifestSha256: qualified.manifest_sha256, targets: [] };
  try {
    const occupiedTargets = await preflightPackages({ qualified, packages, lookup, priorIntents });
    for (const target of targets) {
      const occupied = occupiedTargets[target];
      if (occupied) {
        result.targets.push({ target, status: 'already-public-hash-matched', sha256: occupied.sha256 });
      } else {
        result.targets.push({ target, status: 'possibly-uploaded', sha256: qualified.manifest.packages[target].sha256 });
        await save(result);
        await upload(target);
        result.targets.at(-1).status = 'uploaded-awaiting-public-validation';
      }
      await save(result);
    }
    result.status = 'uploaded-awaiting-public-validation';
    await save(result);
    return result;
  } catch (error) {
    result.status = 'failed-or-partial';
    result.failure = error.message;
    await save(result);
    throw error;
  }
}

module.exports = { root, targets, digest, publicClient, targetEntry, preflightPackages, publishPackages };
