# Codex Usage Dashboard VS Code Extension

Local development wrapper around the Python `codex-usage` CLI.

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
- `Codex Usage: Open Settings`

For the shortest loop, open this `extensions/vscode` folder as the VS Code workspace and press F5. The included launch configuration starts an Extension Development Host.

The extension expects `uv` to be on `PATH` and, by default, infers the Python project root as two directories above this extension folder.
