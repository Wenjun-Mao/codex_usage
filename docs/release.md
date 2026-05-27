# Beta Release Checklist

This project is prepared for Windows x64 beta distribution. Do not publish to the Marketplace from this checklist.

## Build And Test

Run from the repository root:

```powershell
uv run pytest
```

Run from the VS Code extension folder:

```powershell
cd extensions/vscode
npm test
npm run package:vsix:win
```

Expected VSIX output:

```text
output/codex-usage-dashboard-win32-x64.vsix
```

## Inspect The VSIX

Run from the repository root:

```powershell
tar -tf output\codex-usage-dashboard-win32-x64.vsix
```

The archive should include:

- `extension/LICENSE.txt`
- `extension/media/icon.png`
- `extension/bin/win32-x64/codex-usage.exe`
- `extension/out/core.js`
- `extension/out/extension.js`
- `extension/package.json`
- `extension/readme.md`

The archive should not include:

- TypeScript source files
- tests
- `node_modules`
- `.vscode`
- source maps

## Local Install Smoke

Install into normal VS Code:

```powershell
code --install-extension output\codex-usage-dashboard-win32-x64.vsix --force
```

Manual smoke checklist:

- Run `Codex Usage: Open Dashboard`.
- Run `Codex Usage: Refresh Dashboard`.
- Run `Codex Usage: Select Range`.
- Run `Codex Usage: Select Projects`.
- Run `Codex Usage: Open Settings`.
- Confirm readable behavior when no session files are found.
- Confirm the dashboard says pricing uses rates effective at each usage event.

## Archive/Delete Accounting Checks

Archived Codex conversations should remain in usage totals through `archived_sessions`. Deleted conversations should remain in historical totals after the local cache has parsed them once, but the real delete behavior must be observed on an expendable conversation instead of assumed.

Before any manual delete experiment, capture:

```powershell
uv run codex-usage storage snapshot --json > output\storage-snapshot-before-delete-experiment.json
uv run codex-usage summary --range all --by session --json > output\delete-experiment-before-summary.json
```

Then delete one nonessential Codex conversation in the Codex app and capture:

```powershell
uv run codex-usage storage snapshot --json > output\storage-snapshot-after-delete-experiment.json
uv run codex-usage summary --range all --by session --json > output\delete-experiment-after-summary.json
```

Do not use a conversation needed for sync or resume testing. This beta preserves parsed historical usage but cannot restore a deleted Codex conversation.

## Codex Delete Behavior Observation

Observed on Windows with Codex app build current as of 2026-05-27:

- Archive moves session JSONL files from `sessions` to `archived_sessions`.
- Delete removed the archived session JSONL from local Codex storage; Codex Usage retained historical usage from cache.

## Beta Notes

- First beta target is Windows x64 only.
- The VSIX is self-contained and does not require Python, `uv`, or this repository at runtime.
- The extension reads local Codex session files and writes local reports only.
- Marketplace publisher identity is intentionally not finalized in this beta slice.
