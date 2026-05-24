# Codex Usage Dashboard

Windows x64 beta VS Code extension for viewing local Codex token usage, project rollups, Codex credits, and API-equivalent cost estimates.

![Synthetic Codex Usage Dashboard screenshot](https://raw.githubusercontent.com/Wenjun-Mao/codex_usage/main/docs/marketplace/dashboard-synthetic.png)

## Features

- Opens a local dashboard from Codex session JSONL logs.
- Auto-discovers the default Codex sessions directory.
- Supports quick range switching: today, yesterday, 7d, 30d, month, all.
- Supports multi-project filtering from detected project keys.
- Supports auto/day/night dashboard theme switching.
- Detects high-confidence project transitions and can split dashboard usage after verified local repository changes.
- Adds experimental selected-thread sync through a user-provided local sync folder.
- Shows total tokens, API-equivalent USD, Codex credits, cache hit share, daily/hourly views, project breakdown, and model mix.
- Uses checked-in effective-dated pricing tables. No live pricing fetch is performed.

## Commands

- `Codex Usage: Open Dashboard`
- `Codex Usage: Refresh Dashboard`
- `Codex Usage: Select Range`
- `Codex Usage: Select Projects`
- `Codex Usage: Select Theme`
- `Codex Usage: Review Project Transitions`
- `Codex Usage: Select Sync Threads`
- `Codex Usage: Sync Now`
- `Codex Usage: Sync Status`
- `Codex Usage: Open Sync Folder`
- `Codex Usage: Open Settings`

## Settings

- `codexUsage.range`: dashboard range, default `30d`.
- `codexUsage.sessionsDir`: optional explicit Codex sessions directory.
- `codexUsage.subscriptionUsd`: optional monthly subscription amount for comparison.
- `codexUsage.projectKeys`: selected project filters. Leave empty to show all projects.
- `codexUsage.projectAliases`: optional old-to-new project key map for renamed or moved repositories.
- `codexUsage.theme`: `auto`, `day`, or `night`. Auto follows your active VS Code theme.
- `codexUsage.projectTransitions.autoDetect`: automatically split usage after high-confidence local repository transitions.
- `codexUsage.sync.enabled`: enable experimental selected-thread sync.
- `codexUsage.sync.dir`: bring-your-own local sync folder.
- `codexUsage.sync.threadIds`: selected Codex thread ids.
- `codexUsage.sync.autoPull` / `codexUsage.sync.autoPush`: automatic sync behavior.

## Experimental Sync

Sync uses a local folder that you synchronize with your own tool, such as OneDrive, Dropbox, Syncthing, or a network drive. The extension only copies selected Codex session JSONL files and matching session index entries. It does not upload data itself and does not sync Codex auth, settings, caches, logs, or SQLite databases.

## Project Aliases

For renamed repositories, set `codexUsage.projectAliases` so historical logs and new logs group together:

```json
{
  "https://github.com/example/old-name": "https://github.com/example/new-name.git",
  "d:/old/local/path/old-name": "https://github.com/example/new-name.git"
}
```

Both the old keys and the canonical key continue to work for project filtering.

## Project Transitions

Automatic project transition detection uses read-only evidence from local Codex session JSONL files and, when present, the local Codex `state_5.sqlite` `threads` field `cwd` plus thread timestamps. The extension does not upload this data, make network calls for transition detection, mutate SQLite, or sync SQLite databases.

The dashboard transition table shows source, target, effective timestamp, and confidence. Use `Codex Usage: Review Project Transitions` for detailed evidence and thread ids.

## Windows Beta Install

This beta package is Windows x64 only. The installed VSIX bundles `codex-usage.exe` and does not require Python, `uv`, or this repository at runtime.

From the repository root after packaging:

```powershell
code --install-extension output\codex-usage-dashboard-win32-x64.vsix --force
```

After installation, run `Codex Usage: Open Dashboard` from the command palette.

## Privacy

The extension reads local Codex session JSONL files and writes local HTML reports under VS Code extension storage. Automatic project transition detection can also read local `state_5.sqlite` thread `cwd` and timestamps as read-only evidence. It does not upload session logs, does not include telemetry, does not fetch live pricing, and does not sync or mutate SQLite databases.

Codex session logs can include project paths, repository URLs, branch names, model names, timestamps, and usage counts. See the repository `PRIVACY.md` for details.

## Troubleshooting

- If no usage appears, confirm Codex session files exist under `%USERPROFILE%\.codex\sessions` or set `codexUsage.sessionsDir`.
- If project filtering shows no choices, switch the range to `all` and run `Codex Usage: Select Projects` again.
- If a project split looks surprising, run `Codex Usage: Review Project Transitions` to inspect the evidence, or disable `codexUsage.projectTransitions.autoDetect`.
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
