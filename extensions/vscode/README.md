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
- Adds optional cross-computer Codex Task Transfer through a user-provided folder.
- Shows total tokens, API-equivalent USD, Codex credits, cache hit share, daily/hourly views, project breakdown, and model mix.
- Uses checked-in effective-dated pricing tables. No live pricing fetch is performed.

## Preview Status

This Marketplace preview supports Windows x64 and macOS Apple Silicon only. The installed extension bundles `codex-usage.exe` on Windows and `codex-usage` on macOS, and does not require Python, `uv`, or this repository at runtime. The release workflow runs both native packaged version-3 Task Transfer smoke gates, Windows x64 and macOS Apple Silicon, and requires them to pass before publication. Intel macOS and Windows ARM64 are not supported targets in this release. Linux packaging is a follow-up and is not a supported target in this release.

## Commands

- `Codex Usage: Open Dashboard`
- `Codex Usage: Refresh Dashboard`
- `Codex Usage: Select Range`
- `Codex Usage: Select Projects`
- `Codex Usage: Select Theme`
- `Codex Usage: Review Project Transitions`
- `Codex Usage: Task Transfer`
- `Codex Usage: Choose Transfer Folder`
- `Codex Usage: Import Tasks`
- `Codex Usage: Export Tasks`
- `Codex Usage: Review Transfer Status`
- `Codex Usage: Open Transfer Folder`
- `Codex Usage: Open Settings`

## Settings

- `codexUsage.range`: dashboard range, default `30d`.
- `codexUsage.theme`: `auto`, `day`, or `night`. Auto follows your active VS Code theme.
- `codexUsage.projectTransitions.autoDetect`: automatically split usage after high-confidence local repository transitions.

Project filtering is managed with `Codex Usage: Select Projects` and is stored as extension UI state, not as a user setting.
Task Transfer remembers only the transfer-folder path as extension UI state. Task selections and project mappings are never saved.

## Task Transfer

Task Transfer deliberately moves selected active Codex tasks between computers through a folder managed by OneDrive, Dropbox, iCloud Drive, Syncthing, a network drive, or another filesystem provider. It is optional: token reporting works without Task Transfer, and the extension never transfers tasks in the background.

Codex's built-in handoff can fail on a very large task. Task Transfer preserves the task as a full JSONL without summarizing or repackaging its context, so the same long-running task can continue on another computer.

1. On the source computer, run **Export Tasks**, choose the project, and select the active tasks to transfer.
2. Wait for the filesystem provider to finish copying the transfer folder.
3. Clone or copy the corresponding project checkout to the destination computer if it is not already there.
4. When using only the Codex IDE extension, open that checkout in VS Code.
5. Run **Import Tasks**, choose the project, and accept an automatic project match or choose a validated local folder.
6. After successful registration, reload VS Code or open/restart Codex so the imported tasks
   appear. In the official Codex VS Code extension, reloading VS Code refreshes a cached task list.

The Codex desktop app is not required. An IDE-only workflow uses open VS Code workspace folders as destination candidates. Git-backed projects are matched and validated by normalized Git origin; a chosen checkout with the wrong origin is rejected. For a non-Git project, the extension shows the source and destination and asks for confirmation because the mapping cannot be verified automatically. Task Transfer does not clone repositories, so the destination checkout must already exist.

Each Import or Export handles one Codex project. Choose a project, then all eligible tasks in it start selected; deselect any tasks you do not want to transfer. The transfer folder can retain tasks from many projects across separate operations. Review Transfer Status remains cross-project and does not copy files. Neither task selections nor project mappings are saved. Imported tasks remain in the transfer folder, and changing or forgetting the remembered folder does not delete any task files.

The extension checks the complete selected batch before copying anything. Conflicts, malformed folder structures, changed source files, unsafe mappings, and tasks that need the opposite direction block the whole operation. Existing local tasks keep their current checkout path. Task Transfer does not copy Codex auth, settings, caches, logs, archived tasks, or SQLite databases.

After certified task files are copied during Import, Codex Usage asks an installed official Codex runtime to register the selected tasks through targeted `app-server` task-read requests. Registration sends targeted reads only: it does not invoke a model, send a prompt, or start a turn. Codex Usage never writes Codex SQLite or private project registries directly; Codex owns the resulting state repair. If registration fails, the certified imported files remain safe in place, and re-running Import retries registration for the selected tasks. After successful registration, open or restart Codex, or reload VS Code when using the official Codex VS Code extension, to refresh a cached task list.

On supported Windows x64 and macOS Apple Silicon installations, official runtime discovery checks the official Codex VS Code extension, the native Codex desktop app, and `PATH`; the desktop app is not required when another official runtime is available. The packaged Codex Usage VSIX is limited to Windows x64 and macOS Apple Silicon.

The current transfer-folder layout is:

```text
<transfer-folder>/
  sync-index.json
  tasks/
    <portable-task-filename>.jsonl
```

Valid version-2 folders migrate automatically to this version-3 layout before Import, Export, or Review. The **Task Transfer** menu lets you choose, change, open, or forget the folder. Only that folder path is remembered.

### Archive/Delete Accounting

Archived Codex tasks are included in usage totals. Deleted or otherwise missing tasks are retained in historical totals after the local cache has parsed them once. The dashboard header shows archived and retained missing file counts when applicable.

## Project Transitions

Automatic project transition detection uses read-only evidence from local Codex session JSONL files and, when present, project paths and timestamps from the local Codex database. The extension does not upload this data, make network calls for transition detection, mutate SQLite, or include SQLite databases in Task Transfer.

The dashboard transition table shows source, target, effective timestamp, and confidence. Use `Codex Usage: Review Project Transitions` for detailed evidence and Task IDs.

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

The extension reads local Codex session JSONL files and writes local HTML reports under VS Code extension storage. Automatic project transition detection can also read local Codex project paths and timestamps as read-only evidence. It does not upload session logs, does not include telemetry, does not fetch live pricing, and does not include or mutate SQLite databases in Task Transfer.

Codex session logs can include project paths, repository URLs, branch names, model names, timestamps, and usage counts. See the repository `PRIVACY.md` for details.

## Pricing And Fast Mode Notes

API-equivalent USD and Codex credit estimates are calculated from checked-in effective-dated pricing tables. The extension does not fetch live pricing, does not know your subscription price, and does not convert Codex credits to dollars. If a newly released Codex model appears before checked-in rates are added, the dashboard keeps its tokens visible and marks cost/credits as partial rather than guessing from another model.

GPT-5.6 Sol, Terra, and Luna use official API rates for usage recorded from June 26, 2026 onward. Their Codex credit estimates start July 9, 2026 and remain flat across context length. Reasoning effort such as `ultra` remains separate metadata and does not change the per-token model rate.

The official `gpt-5.6` model alias is priced as GPT-5.6 Sol. Other variants such as `gpt-5.6-pro`, `gpt-5.6-mini`, and wrapper names remain visible but unpriced unless they exactly match a checked-in model id or explicit alias.

API-equivalent USD figures are estimates, not actual API or Codex billing. For GPT-5.6, standard cache-write rates per 1M tokens are: Sol $6.25, Terra $3.125, Luna $1.25; cache read (cached input) and ordinary input remain distinct categories. Exactly 272,000 input tokens is short-context pricing. More than 272,000 input tokens, including 272,001, prices the full retained request event at long-context API rates. Long-context rates per 1M tokens are: Sol ordinary input $10, cache read (cached input) $1, cache write $12.50, output $45; Terra ordinary input $5, cache read (cached input) $0.50, cache write $6.25, output $22.50; Luna ordinary input $2, cache read (cached input) $0.20, cache write $2.50, output $9. Codex credits do not use long-context or API cache-write categories; cache writes use the ordinary input credit rate.

The parser reads cumulative token records but reports only retained positive deltas. A local audit of GPT-5.6 Sol sessions found retained positive deltas matched request-level `last_token_usage`, so pricing is per retained event and cumulative session totals cannot trigger long-context pricing.

For GPT-5.6 and later API models, local Codex logs expose `cache_write_input_tokens`. API-equivalent USD prices those explicit cache writes at 1.25 times the ordinary input rate, including the long-context multiplier when applicable; remaining ordinary input uses the standard input rate. Codex credits have no separate cache-write category, so cache writes use the published ordinary input credit rate. Cache-contract changes reparse available source JSONL files, but retained records whose source JSONL is missing cannot gain newly observed token evidence; reports disclose that limitation.

Codex fast mode is counted through the token usage that Codex records. At the moment, Codex session JSONL files do not expose a durable per-turn fast-mode marker or exact charged-credit field, so the dashboard cannot label GPT-5.5 fast-mode turns separately from regular GPT-5.5 turns.

## Troubleshooting

### Imported files exist but tasks are not visible

1. Confirm an official Codex runtime is installed on the destination computer.
2. Check the Codex Usage output for a post-import registration failure.
3. Run **Import Tasks** again for the same project and task subset to retry registration.
4. Open or restart Codex, or reload VS Code when using the official Codex VS Code extension.

- If no usage appears, confirm Codex session files exist under `CODEX_HOME/sessions`, `CODEX_HOME/archived_sessions`, `%USERPROFILE%\.codex\sessions`, `%USERPROFILE%\.codex\archived_sessions`, `~/.codex/sessions`, or `~/.codex/archived_sessions`.
- If project filtering shows no choices, switch the range to `all` and run `Codex Usage: Select Projects` again.
- If a project split looks surprising, run `Codex Usage: Review Project Transitions` to inspect the evidence, or disable `codexUsage.projectTransitions.autoDetect`.
- If the dashboard theme is not what you expect, run `Codex Usage: Select Theme` and choose `auto`, `day`, or `night`.
- If the dashboard says no sessions were found, check the detected sessions path and file permissions.
- If pricing looks stale, check the report header for the checked-in pricing table date.

## Development

Windows x64 packaging is CI-only. The GitHub Actions Windows job runs the extension tests, builds `codex-usage.exe`, executes the native version-3 packaged Task Transfer smoke, and requires it to pass before publication.

macOS Apple Silicon on macOS/bash from `extensions/vscode`:

```bash
npm install
npm run build
npm test
npm run package:vsix:mac
```

For the shortest loop, open this folder as the VS Code workspace and press F5. The included launch configuration starts an Extension Development Host.
