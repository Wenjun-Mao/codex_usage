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
- Adds experimental selected-conversation sync through a user-provided local sync folder.
- Shows total tokens, API-equivalent USD, Codex credits, cache hit share, daily/hourly views, project breakdown, and model mix.
- Uses checked-in effective-dated pricing tables. No live pricing fetch is performed.

## Commands

- `Codex Usage: Open Dashboard`
- `Codex Usage: Refresh Dashboard`
- `Codex Usage: Select Range`
- `Codex Usage: Select Projects`
- `Codex Usage: Select Theme`
- `Codex Usage: Review Project Transitions`
- `Codex Usage: Configure Sync`
- `Codex Usage: Select Sync Projects`
- `Codex Usage: Select Sync Conversations`
- `Codex Usage: Sync Now`
- `Codex Usage: Sync Status`
- `Codex Usage: Open Sync Folder`
- `Codex Usage: Open Settings`

## Settings

- `codexUsage.range`: dashboard range, default `30d`.
- `codexUsage.theme`: `auto`, `day`, or `night`. Auto follows your active VS Code theme.
- `codexUsage.projectTransitions.autoDetect`: automatically split usage after high-confidence local repository transitions.
- `codexUsage.sync.enabled`: enable experimental selected-conversation sync.
- `codexUsage.sync.autoPull` / `codexUsage.sync.autoPush`: automatic sync behavior.

Project filtering is managed with `Codex Usage: Select Projects` and is stored as extension UI state, not as a user setting.
Sync folder, sync project, and sync conversation selections are managed with `Codex Usage: Configure Sync` and stored as extension UI state, not as user settings.

## Experimental Sync

Sync uses a local folder that you synchronize with your own tool, such as OneDrive, Dropbox, Syncthing, or a network drive. The extension only copies selected Codex session JSONL files and matching session index entries. It does not upload data itself and does not sync Codex auth, settings, caches, logs, or SQLite databases.

The setup flow is project-first: choose the sync folder, choose projects with rough sync-size estimates, then choose all conversations in those projects or specific conversations. The command id for selecting conversations remains `codexUsage.selectSyncThreads` internally for compatibility, but the command palette shows `Codex Usage: Select Sync Conversations`.

The status bar is the primary background sync indicator. Automatic sync uses a focus cooldown, a file-change debounce, and failure backoff to avoid noisy repeated runs. Normal automatic success/failure details go to the Codex Usage output channel; popups are reserved for manual sync and action-needed failures such as conflicts.

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

- If no usage appears, confirm Codex session files exist under `CODEX_HOME\sessions`, `%USERPROFILE%\.codex\sessions`, or `~\.codex\sessions`.
- If project filtering shows no choices, switch the range to `all` and run `Codex Usage: Select Projects` again.
- If a project split looks surprising, run `Codex Usage: Review Project Transitions` to inspect the evidence, or disable `codexUsage.projectTransitions.autoDetect`.
- If the dashboard theme is not what you expect, run `Codex Usage: Select Theme` and choose `auto`, `day`, or `night`.
- If the dashboard says no sessions were found, check the detected sessions path and file permissions.
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
