# Codex Usage Dashboard VS Code Extension

Portable Windows wrapper around the bundled Python `codex-usage` CLI.

## Development

From this folder:

```powershell
npm install
npm run build
npm test
```

Run the extension in a VS Code Extension Development Host and execute:

- `Codex Usage: Open Dashboard`
- `Codex Usage: Refresh Dashboard`
- `Codex Usage: Select Range`
- `Codex Usage: Select Projects`
- `Codex Usage: Open Settings`

For the shortest loop, open this `extensions/vscode` folder as the VS Code workspace and press F5. The included launch configuration starts an Extension Development Host.

Development builds can use the local TypeScript host, but packaged Windows VSIX builds include the Python CLI as `bin/win32-x64/codex-usage.exe`.

## Local VSIX

Build a self-contained Windows x64 package:

```powershell
npm run package:vsix:win
code --install-extension ..\..\output\codex-usage-dashboard-win32-x64.vsix --force
```

The installed Windows VSIX does not require Python, `uv`, or this repository at runtime. It reads Codex session files from the current machine, using automatic discovery unless `codexUsage.sessionsDir` is set.
