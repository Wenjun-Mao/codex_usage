# Marketplace Preview Release Checklist

This project is prepared for Windows x64 and macOS Apple Silicon Marketplace preview distribution. Linux packaging is a follow-up and is not a supported or hidden publication target for this release. Confirm the Marketplace publisher id `wenjun-mao` exists before publishing.

## Build And Test

Run from the repository root:

```powershell
uv run pytest
```

For Windows x64 packaging, run from Windows/PowerShell:

```powershell
cd extensions\vscode
npm test
npm run package:vsix:win
```

For macOS Apple Silicon packaging, run from macOS/bash:

```bash
cd extensions/vscode
npm test
npm run package:vsix:mac
```

Expected VSIX output:

```text
output/releases/codex-usage-dashboard-win32-x64.vsix
output/releases/codex-usage-dashboard-darwin-arm64.vsix
```

## GitHub Actions Release

The repository has a `Package and Publish VSIX` workflow that builds both platform packages on native GitHub-hosted runners.

Use the manual workflow trigger with `publish=false` to build and inspect artifacts without publishing. Run the manual workflow on the `main` ref with `publish=true` to publish both generated VSIX files to the VS Code Marketplace. Pushing a release tag that matches the extension version and points at a commit contained in `origin/main`, such as `v0.1.32`, also builds and publishes both packages.

Publishing requires the repository Actions secret `VSCE_PAT`. The token must have Marketplace `Manage` permission for publisher `wenjun-mao`.

## Inspect The VSIX

Run from the repository root:

```powershell
tar -tf output\releases\codex-usage-dashboard-win32-x64.vsix
```

On macOS, inspect the macOS package:

```bash
tar -tf output/releases/codex-usage-dashboard-darwin-arm64.vsix
```

Each archive should include:

- `extension/LICENSE.txt`
- `extension/CHANGELOG.md`
- `extension/SUPPORT.md`
- `extension/media/icon.png`
- `extension/out/core.js`
- `extension/out/extension.js`
- `extension/package.json`
- `extension/readme.md`

The Windows archive should include:

- `extension/bin/win32-x64/codex-usage.exe`

The macOS Apple Silicon archive should include:

- `extension/bin/darwin-arm64/codex-usage`

The archive should not include:

- TypeScript source files
- tests
- `node_modules`
- `.vscode`
- source maps

## Marketplace Preflight

Before publishing:

- Confirm the Visual Studio Marketplace publisher id is `wenjun-mao`.
- Confirm `extensions/vscode/package.json` has `"preview": true`.
- Confirm `extensions/vscode/package.json` does not have `"private": true`.
- Confirm the package targets are Windows x64 and macOS Apple Silicon.
- Confirm no Linux package or Marketplace target is included; Linux remains follow-up work.
- Confirm the extension README clearly says Windows x64 and macOS Apple Silicon Preview.
- Confirm `PRIVACY.md`, `LICENSE`, `CHANGELOG.md`, and `SUPPORT.md` are current.
- Confirm pricing notes say pricing is checked-in and effective-dated, with no live fetch.
- Confirm Codex fast mode is documented as counted through recorded tokens but not separately labeled because Codex does not expose a durable per-turn fast-mode marker in JSONL.
- Confirm the version in `extensions/vscode/package.json` has not already been published. Marketplace versions are immutable.

## Manual Marketplace Upload

Use this path when you want to upload the VSIX through the browser instead of publishing from the terminal.

1. Open <https://marketplace.visualstudio.com/manage/publishers/>.
2. Sign in with the Microsoft account that owns the publisher.
3. Select publisher `wenjun-mao`.
4. Open the existing `Codex Usage Dashboard` extension entry.
5. Choose the update/upload action for a new extension version.
6. Upload the target VSIX from the repository root, such as `output\releases\codex-usage-dashboard-win32-x64.vsix` or `output/releases/codex-usage-dashboard-darwin-arm64.vsix`.
7. Wait for Marketplace verification to finish.
8. Confirm the listing shows the new version, then search/install it from VS Code after indexing catches up.

## CLI Marketplace Publish

Publish Windows x64 from Windows/PowerShell after the checks pass:

```powershell
cd extensions\vscode
npx vsce login wenjun-mao
npm run package:vsix:win
npx vsce publish --packagePath ..\..\output\releases\codex-usage-dashboard-win32-x64.vsix
```

Publish macOS Apple Silicon from macOS/bash after the checks pass:

```bash
cd extensions/vscode
npx vsce login wenjun-mao
npm run package:vsix:mac
npx vsce publish --packagePath ../../output/releases/codex-usage-dashboard-darwin-arm64.vsix
```

## Local Install Smoke

Install into normal VS Code:

```powershell
code --install-extension output\releases\codex-usage-dashboard-win32-x64.vsix --force
```

On macOS Apple Silicon:

```bash
code --install-extension output/releases/codex-usage-dashboard-darwin-arm64.vsix --force
```

Manual smoke checklist:

- Run `Codex Usage: Open Dashboard`.
- Run `Codex Usage: Refresh Dashboard`.
- Run `Codex Usage: Select Range`.
- Run `Codex Usage: Select Projects`.
- Run `Codex Usage: Task Transfer`.
- Run `Codex Usage: Import Tasks`, `Codex Usage: Export Tasks`, and `Codex Usage: Review Transfer Status`.
- Run `Codex Usage: Open Settings`.
- Confirm readable behavior when no session files are found.
- Confirm the dashboard says pricing uses rates effective at each usage event.
- Confirm token reporting works with no transfer folder remembered.

## Task Transfer Acceptance

- Confirm Import, Export, and Review each open with a fresh empty selection.
- Export selected active tasks and confirm unselected and archived tasks are not copied.
- Confirm the filesystem provider has converged before testing on the destination computer.
- Confirm the corresponding destination project checkout already exists; Task Transfer must not clone it.
- Confirm a matching Git origin maps automatically and a mismatched Git origin is rejected.
- Confirm a non-Git destination requires explicit unverified-mapping confirmation.
- Import a task and confirm its JSONL remains in the transfer folder.
- Confirm conflicts, opposite-direction work, and invalid mappings block the complete selected batch without partial copies.
- Confirm a valid version-2 transfer folder migrates automatically to the version-3 `tasks/` layout.

Extension-only manual gate:

- Quit the Codex desktop app.
- Open an existing matching checkout in VS Code.
- Import a remote-only task using the packaged extension.
- Reload VS Code.
- Confirm the official Codex extension lists and opens the task under that workspace.

## Archive/Delete Accounting Checks

Archived Codex tasks should remain in usage totals through `archived_sessions`. Deleted tasks should remain in historical totals after the local cache has parsed them once, but the real delete behavior must be observed on an expendable task instead of assumed.

Before any manual delete experiment, capture:

```powershell
uv run codex-usage storage snapshot --json > output\storage-snapshot-before-delete-experiment.json
uv run codex-usage summary --range all --by session --json > output\delete-experiment-before-summary.json
```

Then delete one nonessential Codex task in the Codex app and capture:

```powershell
uv run codex-usage storage snapshot --json > output\storage-snapshot-after-delete-experiment.json
uv run codex-usage summary --range all --by session --json > output\delete-experiment-after-summary.json
```

Do not use a task needed for Task Transfer testing. This beta preserves parsed historical usage but cannot restore a deleted Codex task.

## Codex Delete Behavior Observation

Observed on Windows with Codex app build current as of 2026-05-27:

- Archive moves session JSONL files from `sessions` to `archived_sessions`.
- Delete removed the archived session JSONL from local Codex storage; Codex Usage retained historical usage from cache.

## Preview Notes

- Preview targets are Windows x64 and macOS Apple Silicon.
- Linux packaging is follow-up work and is not supported in this release.
- The VSIX is self-contained and does not require Python, `uv`, or this repository at runtime.
- Intel macOS is not supported.
- The extension reads local Codex session files and writes local reports only.
- Marketplace publisher identity is `wenjun-mao`.
