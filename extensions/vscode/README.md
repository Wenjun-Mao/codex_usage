# Codex Usage Dashboard

Windows x64 beta VS Code extension for viewing local Codex token usage, project rollups, Codex credits, and API-equivalent cost estimates.

![Synthetic Codex Usage Dashboard screenshot](https://raw.githubusercontent.com/Wenjun-Mao/codex_usage/main/docs/marketplace/dashboard-synthetic.png)

## Features

- Opens a local dashboard from Codex session JSONL logs.
- Auto-discovers the default Codex sessions directory.
- Supports quick range switching: today, yesterday, 7d, 30d, month, all.
- Supports multi-project filtering from detected project keys.
- Supports auto/day/night dashboard theme switching.
- Shows total tokens, API-equivalent USD, Codex credits, cache hit share, daily/hourly views, project breakdown, and model mix.
- Uses checked-in effective-dated pricing tables. No live pricing fetch is performed.

## Commands

- `Codex Usage: Open Dashboard`
- `Codex Usage: Refresh Dashboard`
- `Codex Usage: Select Range`
- `Codex Usage: Select Projects`
- `Codex Usage: Select Theme`
- `Codex Usage: Open Settings`

## Settings

- `codexUsage.range`: dashboard range, default `30d`.
- `codexUsage.sessionsDir`: optional explicit Codex sessions directory.
- `codexUsage.subscriptionUsd`: optional monthly subscription amount for comparison.
- `codexUsage.projectKeys`: selected project filters. Leave empty to show all projects.
- `codexUsage.theme`: `auto`, `day`, or `night`. Auto follows your active VS Code theme.

## Windows Beta Install

This beta package is Windows x64 only. The installed VSIX bundles `codex-usage.exe` and does not require Python, `uv`, or this repository at runtime.

From the repository root after packaging:

```powershell
code --install-extension output\codex-usage-dashboard-win32-x64.vsix --force
```

After installation, run `Codex Usage: Open Dashboard` from the command palette.

## Privacy

The extension reads local Codex session JSONL files and writes local HTML reports under VS Code extension storage. It does not upload session logs, does not include telemetry, and does not fetch live pricing.

Codex session logs can include project paths, repository URLs, branch names, model names, timestamps, and usage counts. See the repository `PRIVACY.md` for details.

## Troubleshooting

- If no usage appears, confirm Codex session files exist under `%USERPROFILE%\.codex\sessions` or set `codexUsage.sessionsDir`.
- If project filtering shows no choices, switch the range to `all` and run `Codex Usage: Select Projects` again.
- If the dashboard theme is not what you expect, run `Codex Usage: Select Theme` and choose `auto`, `day`, or `night`.
- If the dashboard says no sessions were found, check the configured sessions path and file permissions.
- If pricing looks stale, check the report header for the checked-in pricing table date.

## Development

From `extensions/vscode`:

```powershell
npm install
npm run build
npm test
npm run package:vsix:win
```

For the shortest loop, open this folder as the VS Code workspace and press F5. The included launch configuration starts an Extension Development Host.
