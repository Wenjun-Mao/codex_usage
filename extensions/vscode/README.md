# Codex Usage Dashboard

Windows x64 and macOS Apple Silicon Preview VS Code extension for viewing local Codex token usage, project rollups, Codex credits, and API-equivalent cost estimates.

![Synthetic Codex Usage Dashboard screenshot](https://raw.githubusercontent.com/Wenjun-Mao/codex_usage/main/docs/marketplace/dashboard-synthetic.png)

## Features

- Opens a local dashboard from Codex session JSONL logs.
- Auto-discovers the default active and archived Codex session directories.
- Supports quick range switching: today, yesterday, 7d, 30d, month, all.
- Supports multi-project filtering from detected project keys.
- Supports auto/day/night dashboard theme switching.
- Detects high-confidence project transitions and can split dashboard usage after verified local repository changes.
- Adds experimental exact-task sync through a user-provided local sync folder.
- Shows total tokens, API-equivalent USD, Codex credits, cache hit share, daily/hourly views, project breakdown, and model mix.
- Uses checked-in effective-dated pricing tables. No live pricing fetch is performed.

## Preview Status

This Marketplace preview supports Windows x64 and macOS Apple Silicon. The installed extension bundles `codex-usage.exe` on Windows and `codex-usage` on macOS, and does not require Python, `uv`, or this repository at runtime. Intel macOS is not supported. Release status: macOS Apple Silicon packaged inventory/push/pull verified locally; Windows x64 packaging is CI-only and remains a release gate. The GitHub Actions packaged smoke test must pass before publication.

## Commands

- `Codex Usage: Open Dashboard`
- `Codex Usage: Refresh Dashboard`
- `Codex Usage: Select Range`
- `Codex Usage: Select Projects`
- `Codex Usage: Select Theme`
- `Codex Usage: Review Project Transitions`
- `Codex Usage: Sync Menu`
- `Codex Usage: Configure Sync`
- `Codex Usage: Select Sync Tasks`
- `Codex Usage: Pull Tasks`
- `Codex Usage: Push Tasks`
- `Codex Usage: Sync Status`
- `Codex Usage: Open Sync Folder`
- `Codex Usage: Open Settings`

## Settings

- `codexUsage.range`: dashboard range, default `30d`.
- `codexUsage.theme`: `auto`, `day`, or `night`. Auto follows your active VS Code theme.
- `codexUsage.projectTransitions.autoDetect`: automatically split usage after high-confidence local repository transitions.
- `codexUsage.sync.enabled`: enable experimental selected-task sync.

Project filtering is managed with `Codex Usage: Select Projects` and is stored as extension UI state, not as a user setting.
The sync folder and exact task selections are managed with `Codex Usage: Configure Sync` and stored as extension UI state, not as user settings.

## Experimental Sync

Sync uses a local folder that you synchronize with your own tool, such as OneDrive, Dropbox, Syncthing, or a network drive. The extension only copies selected active Codex task JSONLs and stores matching session-index metadata in a central catalog. It does not upload data itself and does not sync Codex auth, settings, caches, logs, archived tasks, or SQLite databases.

A built-in Codex handoff can fail on a very large task. Task sync is designed for that usage scenario: it preserves the task as a full JSONL without summarizing or repackaging its context, so the same long-running task can continue on another computer.

Setup uses one project-grouped `Select Tasks` picker after the sync folder is chosen. Project rows are current-task shortcuts: each row selects or deselects only the tasks currently shown beneath it. Remote-only tasks are discovered from the sync folder, including on a device where they have not been pulled. Future tasks under an already represented project remain excluded until explicitly selected. Deselecting a task never deletes its remote JSONL or catalog entry.

In user-facing UI and documentation, each selectable Codex sidebar item is a **task**. The CLI and storage contracts use its technical thread id through fields such as `thread_id` and the `--thread-id` option.

Version 2 writes this sync-folder layout:

```text
<sync-folder>/
  conversations/
    <portable-thread-filename>.jsonl
  sync-index.json
```

Version `0.1.34` changes the selection schema to exact task thread ids. It intentionally invalidates the previous project/conversation selection state and does not migrate those selectors. After upgrading, sync shows **Setup required** once so you can choose exact tasks. The version-2 remote layout is unchanged, with no remote cleanup or republish required; existing remote task JSONLs remain available to the picker. The older version-1 layout still requires its previously documented clean resync before it can be used as version 2.

Version `0.1.35` replaces bidirectional Sync Now and all automatic triggers with explicit `Pull Tasks` and `Push Tasks` commands. Both directions share conflict preflight and snapshot validation, but each mutates only its named side. The result reports selected tasks that still need the opposite direction.

For a cross-platform pull, open or save the destination checkout in Codex first. Sync requires one canonical Git identity match, leaves the remote JSONL unchanged, and rewrites `session_meta.payload.cwd` in every local metadata record for that project. Unrelated metadata and every non-metadata record remain byte-identical. Missing, ambiguous, or locally modified foreign-path tasks block safely.

If a task was already imported under another computer's path before this rebind, quit and reopen Codex after Pull so its local task index is rebuilt from the corrected JSONL. The extension never patches Codex's SQLite database.

Click the dashboard `Sync: ... ▾` control or run `Codex Usage: Sync Menu` to manage sync. The menu supports pull, push, status, pause/resume, changing the sync folder or selected tasks, clearing the setup, and opening the sync folder. Clearing setup only forgets extension selections; it does not delete Codex logs or sync-folder files.

The status bar shows explicit transfer states including `Sync:Scanning`, `Sync:Pulling`, and `Sync:Pushing`. Sync never runs on extension activation, window focus, a timer, or a Codex session file change. Transfer details go to the Codex Usage output channel, with visible completion and action-needed messages.

Leave `codexUsage.sync.enabled` on and run `Codex Usage: Pull Tasks` or `Codex Usage: Push Tasks` when you want to transfer. Use `Codex Usage: Sync Status` to inspect selected tasks without transferring files.

Task sync is prefix-aware. Normal append-only progress on one computer is transferred by the matching manual direction; true divergent edits on two computers are reported as conflicts and neither side is overwritten.

Sync copies only selected active task JSONLs and preserves matching session-index metadata in its repairable catalog. Archived tasks can appear in usage totals but are not sync candidates.

### Archive/Delete Accounting

Archived Codex conversations are included in usage totals. Deleted or otherwise missing conversations are retained in historical totals after the local cache has parsed them once. The dashboard header shows archived and retained missing file counts when applicable.

## Project Transitions

Automatic project transition detection uses read-only evidence from local Codex session JSONL files and, when present, the local Codex `state_5.sqlite` `threads` field `cwd` plus thread timestamps. The extension does not upload this data, make network calls for transition detection, mutate SQLite, or sync SQLite databases.

The dashboard transition table shows source, target, effective timestamp, and confidence. Use `Codex Usage: Review Project Transitions` for detailed evidence and thread ids.

## Preview Install

Windows x64:

```powershell
code --install-extension output\releases\codex-usage-dashboard-win32-x64.vsix --force
```

macOS Apple Silicon:

```bash
code --install-extension output/releases/codex-usage-dashboard-darwin-arm64.vsix --force
```

After installation, run `Codex Usage: Open Dashboard` from the command palette.

## First Run And Cache

On first open, the dashboard may show "Initializing Codex usage cache. This can take a few seconds the first time." The extension passes an internal cache folder to the bundled Python CLI and stores parsed usage rows in local SQLite under VS Code global extension storage. No cache setting is exposed in VS Code Settings; deleting the extension storage folder simply causes the cache to rebuild.

## Privacy

The extension reads local Codex session JSONL files and writes local HTML reports under VS Code extension storage. Automatic project transition detection can also read local `state_5.sqlite` thread `cwd` and timestamps as read-only evidence. It does not upload session logs, does not include telemetry, does not fetch live pricing, and does not sync or mutate SQLite databases.

Codex session logs can include project paths, repository URLs, branch names, model names, timestamps, and usage counts. See the repository `PRIVACY.md` for details.

## Pricing And Fast Mode Notes

API-equivalent USD and Codex credit estimates are calculated from checked-in effective-dated pricing tables. The extension does not fetch live pricing, does not know your subscription price, and does not convert Codex credits to dollars. If a newly released Codex model appears before checked-in rates are added, the dashboard keeps its tokens visible and marks cost/credits as partial rather than guessing from another model.

GPT-5.6 Sol, Terra, and Luna use official API rates for usage recorded from June 26, 2026 onward. Their Codex credit estimates start July 9, 2026 and remain flat across context length. Reasoning effort such as `ultra` remains separate metadata and does not change the per-token model rate.

The official `gpt-5.6` model alias is priced as GPT-5.6 Sol. Other variants such as `gpt-5.6-pro`, `gpt-5.6-mini`, and wrapper names remain visible but unpriced unless they exactly match a checked-in model id or explicit alias.

For GPT-5.6 API USD, exactly 272,000 input tokens is short-context pricing. More than 272,000 input tokens, including 272,001, prices the full retained request event at long-context API rates. Long rates per 1M tokens are: Sol $10 uncached input, $1 cached input, $45 output; Terra $5 uncached input, $0.50 cached input, $22.50 output; Luna $2 uncached input, $0.20 cached input, $9 output. The long-context multiplier does not apply to Codex credits.

The parser reads cumulative token records but reports only retained positive deltas. A local audit of GPT-5.6 Sol sessions found retained positive deltas matched request-level `last_token_usage`, so pricing is per retained event and cumulative session totals cannot trigger long-context pricing.

For GPT-5.6 and later API models, explicit cache writes can have a separate 1.25x input charge. Local Codex logs expose no distinct cache-write token count, so the API-equivalent estimate cannot include that unobservable uplift.

Codex fast mode is counted through the token usage that Codex records. At the moment, Codex session JSONL files do not expose a durable per-turn fast-mode marker or exact charged-credit field, so the dashboard cannot label GPT-5.5 fast-mode turns separately from regular GPT-5.5 turns.

## Troubleshooting

- If no usage appears, confirm Codex session files exist under `CODEX_HOME/sessions`, `CODEX_HOME/archived_sessions`, `%USERPROFILE%\.codex\sessions`, `%USERPROFILE%\.codex\archived_sessions`, `~/.codex/sessions`, or `~/.codex/archived_sessions`.
- If project filtering shows no choices, switch the range to `all` and run `Codex Usage: Select Projects` again.
- If a project split looks surprising, run `Codex Usage: Review Project Transitions` to inspect the evidence, or disable `codexUsage.projectTransitions.autoDetect`.
- If the dashboard theme is not what you expect, run `Codex Usage: Select Theme` and choose `auto`, `day`, or `night`.
- If the dashboard says no sessions were found, check the detected sessions path and file permissions.
- If pricing looks stale, check the report header for the checked-in pricing table date.

## Development

Windows x64 packaging is CI-only. The GitHub Actions Windows job runs the extension tests, builds `codex-usage.exe`, packages the VSIX, and exercises inventory plus exact-task push/pull through the packaged executable.

macOS Apple Silicon on macOS/bash from `extensions/vscode`:

```bash
npm install
npm run build
npm test
npm run package:vsix:mac
```

For the shortest loop, open this folder as the VS Code workspace and press F5. The included launch configuration starts an Extension Development Host.
