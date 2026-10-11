/* Verify the exact preflight, tag artifacts and public Marketplace packages. */
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const fs = require('node:fs/promises');
const path = require('node:path');
const root = path.resolve(__dirname, '..');
const { getPublicGalleryAPI, getMarketplaceUrl } = require(path.join(root, 'extensions/vscode/node_modules/@vscode/vsce/out/util'));
const { ExtensionQueryFlags: F } = require(path.join(root, 'extensions/vscode/node_modules/azure-devops-node-api/interfaces/GalleryInterfaces'));
const version = require(path.join(root, 'extensions/vscode/package.json')).version;
const targets = ['darwin-arm64', 'win32-x64'];
const digest = bytes => createHash('sha256').update(bytes).digest('hex');

async function main() {
  const [commit, preflightRun, publicationRun, artifactDirectory, outputDirectory] = process.argv.slice(2);
  assert(commit && preflightRun && publicationRun && artifactDirectory && outputDirectory,
    'Usage: node scripts/verify_marketplace_release.cjs COMMIT PREFLIGHT TAG_RUN ARTIFACT_DIR OUTPUT_DIR');
  const output = path.resolve(outputDirectory);
  await fs.mkdir(output, { recursive: true });
  assert.equal(getMarketplaceUrl(), 'https://marketplace.visualstudio.com');
  const run = id => JSON.parse(execFileSync('gh', ['run', 'view', id,
    '--json', 'headSha,headBranch,event,conclusion,url,jobs'], { cwd: root, encoding: 'utf8' }));
  const preflight = run(preflightRun), publication = run(publicationRun);
  for (const workflow of [preflight, publication]) {
    assert.equal(workflow.headSha, commit);
    assert.equal(workflow.conclusion, 'success');
  }
  assert.equal(preflight.event, 'workflow_dispatch');
  assert(preflight.jobs.filter(job => job.name !== 'Publish platform VSIX packages').every(job => job.conclusion === 'success'));
  assert.equal(preflight.jobs.find(job => job.name === 'Publish platform VSIX packages').conclusion, 'skipped');
  assert(publication.jobs.every(job => job.conclusion === 'success'));
  assert.equal(publication.headBranch, `v${version}`);
  assert.equal(publication.event, 'push');
  assert.equal(execFileSync('git', ['rev-parse', `v${version}`], { cwd: root, encoding: 'utf8' }).trim(), commit);
  await fs.writeFile(path.join(output, 'preflight-workflow.json'), JSON.stringify(preflight, null, 2) + '\n');
  await fs.writeFile(path.join(output, 'publication-workflow.json'), JSON.stringify(publication, null, 2) + '\n');
  const deadline = Date.now() + 30 * 60 * 1000;
  let catalog;
  while (Date.now() < deadline) {
    catalog = await getPublicGalleryAPI().getExtension('wenjun-mao.codex-usage-dashboard',
      [F.IncludeVersions, F.IncludeFiles, F.IncludeVersionProperties]);
    await fs.writeFile(path.join(output, 'catalog.json'), JSON.stringify(catalog, null, 2) + '\n');
    if (targets.every(target => catalog.versions.some(row => row.version === version && row.targetPlatform === target && (row.flags & 1)))) break;
    console.log('Awaiting validated public entries for both targets');
    await new Promise(resolve => setTimeout(resolve, 30000));
  }
  const evidence = { version, tag: `v${version}`, commit, verifiedAt: new Date().toISOString(),
    nonpublishingWorkflow: preflight.url, publicationWorkflow: publication.url,
    publicCatalog: 'https://marketplace.visualstudio.com/items?itemName=wenjun-mao.codex-usage-dashboard', targets: [] };
  for (const target of targets) {
    const entries = catalog.versions.filter(row => row.version === version && row.targetPlatform === target);
    assert.equal(entries.length, 1, `Missing or duplicate target ${target}`);
    const entry = entries[0];
    assert(entry.flags & 1, `Unvalidated public target ${target}`);
    const asset = entry.files.find(file => file.assetType === 'Microsoft.VisualStudio.Services.VSIXPackage');
    assert(asset);
    const url = new URL(asset.source);
    assert.equal(url.protocol, 'https:');
    assert(url.hostname.endsWith('.gallerycdn.vsassets.io') || url.hostname.endsWith('.gallery.vsassets.io'));
    const response = await fetch(url, { signal: AbortSignal.timeout(60000) });
    assert(response.ok);
    const bytes = Buffer.from(await response.arrayBuffer());
    assert(bytes.length > 0 && bytes.length < 100 * 1024 * 1024);
    const expected = await fs.readFile(path.join(artifactDirectory, `codex-usage-companion-${target}`, `codex-usage-companion-${target}.vsix`));
    const sha256 = digest(bytes);
    assert.equal(sha256, digest(expected), `Public/tag artifact mismatch ${target}`);
    const declared = entry.properties.find(property => property.key === 'Microsoft.VisualStudio.Services.VsixSha256');
    assert(declared);
    assert.equal(sha256, declared.value.toLowerCase());
    await fs.writeFile(path.join(output, `official-${target}.vsix`), bytes);
    evidence.targets.push({ target, version, sha256, bytes: bytes.length,
      officialDownload: asset.source, tagArtifactEqual: true, catalogHashEqual: true });
    console.log(`${target} ${version}: ${sha256} (public = tag artifact = catalog hash)`);
  }
  await fs.writeFile(path.join(output, 'verification.json'), JSON.stringify(evidence, null, 2) + '\n');
}
main().catch(error => { console.error(error); process.exitCode = 1; });
