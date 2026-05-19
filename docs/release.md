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

## Beta Notes

- First beta target is Windows x64 only.
- The VSIX is self-contained and does not require Python, `uv`, or this repository at runtime.
- The extension reads local Codex session files and writes local reports only.
- Marketplace publisher identity is intentionally not finalized in this beta slice.
