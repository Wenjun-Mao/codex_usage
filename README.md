# Codex Usage Dashboard

Local tooling for understanding Codex token usage, project activity, Codex credits, and API-equivalent cost from Codex session JSONL logs.

![Synthetic Codex Usage Dashboard screenshot](docs/marketplace/dashboard-synthetic.png)

This repository contains:

- A Python CLI, `codex-usage`, for parsing local Codex session logs.
- A Windows x64 VS Code extension beta that bundles the Python CLI as `codex-usage.exe`.
- A dependency-light dashboard report rendered with local HTML, CSS, and inline SVG.

## Windows VS Code Beta

The current beta package is Windows x64 only. It is self-contained at runtime and does not require Python, `uv`, or this repository after installation.

Build and install the local VSIX:

```powershell
cd extensions/vscode
npm run package:vsix:win
code --install-extension ..\..\output\codex-usage-dashboard-win32-x64.vsix --force
```

Available commands:

- `Codex Usage: Open Dashboard`
- `Codex Usage: Refresh Dashboard`
- `Codex Usage: Select Range`
- `Codex Usage: Select Projects`
- `Codex Usage: Review Project Transitions`
- `Codex Usage: Select Theme`
- `Codex Usage: Configure Sync`
- `Codex Usage: Select Sync Projects`
- `Codex Usage: Select Sync Conversations`
- `Codex Usage: Sync Now`
- `Codex Usage: Sync Status`
- `Codex Usage: Open Sync Folder`
- `Codex Usage: Open Settings`

## CLI Usage

```powershell
uv sync
uv run codex-usage summary --range 7d --by project
uv run codex-usage summary --range all --by hour --json
uv run codex-usage summary --range month --by model --csv output/monthly-models.csv
uv run codex-usage report --range 30d --output output/report.html
uv run codex-usage report --range all --theme night --output output/night-report.html
uv run codex-usage transitions suggest --json
uv run codex-usage threads --project-key https://github.com/example/demo --json
uv run codex-usage sync export --sync-dir D:\CodexSync --thread-id <thread-id>
uv run codex-usage sync status --sync-dir D:\CodexSync --thread-id <thread-id> --json
```

By default, the tool looks for Codex sessions at:

- `CODEX_HOME/sessions`
- `%USERPROFILE%\.codex\sessions`
- `~/.codex/sessions`

Discovery uses the first existing location in that order. Set `CODEX_HOME` when you need to point the CLI at a different Codex home for testing or migration.

Dashboard theme defaults to `auto`. In standalone HTML, auto follows the browser/system color-scheme preference. In VS Code, auto follows the active VS Code theme. You can force a report with `--theme day` or `--theme night`, or set `CODEX_USAGE_THEME`.

## What The Dashboard Shows

- Total tokens and usage event counts
- API-equivalent USD using checked-in effective-dated pricing
- Codex credit estimates
- Cache hit share
- Daily and hourly usage patterns
- Project, model, and session rollups

The report uses no remote assets, JavaScript, or Python chart libraries. It is safe to open locally and is designed to fit inside a VS Code webview.
The dashboard uses the same tokenized day/night design system as the VS Code extension, including dark-mode-friendly charts and tables.

## Experimental Conversation Sync

The Windows VS Code beta can sync selected Codex conversations through a bring-your-own local sync folder such as OneDrive, Dropbox, Syncthing, or a network drive. Sync is off by default. Run `Codex Usage: Configure Sync` to choose a sync folder, select one or more projects, see a rough sync-size estimate for each project, then choose whether to sync all conversations in those projects or only specific conversations.

Projects match the repo/workspace identities shown in Project Breakdown. Conversations are individual Codex sessions inside those projects. Size estimates are based on local session JSONL file sizes plus a small manifest/index/metadata allowance, so they are useful for cloud-storage planning but not exact billing or provider overhead. The extension stores the sync folder, selected sync projects, and selected conversations as local VS Code extension UI state, not as raw settings you need to edit by hand.

Background sync is intentionally quiet. The VS Code status bar shows the current sync state, such as `Sync:Off`, `Sync:Idle`, `Sync:Waiting`, `Sync:Pulling`, `Sync:Pushing`, `Sync:Conflict`, or `Sync:Issue`. Automatic sync logs details to the Codex Usage output channel; visible notifications are reserved for manual sync and action-needed failures.

Manual-only sync is supported: keep Sync Enabled on, turn Auto Pull and Auto Push off, then use `Codex Usage: Sync Now` from the command palette or the dashboard action strip. Use `Sync Status` to inspect selected conversation state without running a full sync.

Sync uses three-way state per conversation. If one side only appends new Codex JSONL events, the beta treats it as a fast-forward and pulls or pushes automatically. If both computers append different tails to the same conversation, sync stops and preserves both sides for review.

The sync MVP copies only selected session JSONL files and matching `session_index.jsonl` entries. It does not sync `auth.json`, settings, caches, logs, or SQLite databases. If local memory database rows are detected for a selected conversation, sync status reports that they are not synced by this beta.

## Accounting And Pricing

The parser reads cumulative `total_token_usage` records and counts only positive deltas between token-count events. This avoids double-counting repeated records while still allowing daily and hourly reports for long sessions.

Project grouping uses `git.repository_url` when present, local `.git/config` origin remotes resolved from `cwd` when needed, then normalized `cwd`, then the session id. Automatic project transition detection handles high-confidence repository switches within a thread without manual alias configuration.

Pricing uses checked-in effective-dated rate schedules. Each usage event is priced with the API USD and Codex credit rates active at that event's timestamp, so future price changes can be added without rewriting historical reports.

The tool does not fetch live pricing. Cost and credit values are estimates based on the checked-in pricing table version shown in each report.

## Project Transitions

Codex can continue one thread after you ask it to work in another local repository. By default, reports apply automatic high-confidence transition detection when a timestamped Codex event references an existing local path, that path resolves to a repository with a `.git/config` origin remote, and the thread already has usage under a different source project. Usage before the transition timestamp stays with the source project; usage after the timestamp moves to the detected target project.

The detector uses read-only evidence from local Codex session JSONL files and, when present, the local Codex `state_5.sqlite` `threads` field `cwd` plus thread timestamps. It does not upload this data, make network calls, mutate SQLite, or include SQLite databases in experimental sync.

Casual repository name mentions do not split usage because the detector requires verified local path evidence. Dashboard reports show transition source, target, effective timestamp, and confidence. Detailed evidence text and thread ids are available through `codex-usage transitions suggest --json` and `Codex Usage: Review Project Transitions`.

Use `uv run codex-usage transitions suggest --json` to review inferred transitions directly. Pass `--no-auto-transitions` to summary, report, or threads commands when you want the original project grouping without automatic splits.

## Privacy

Codex Usage Dashboard is local-first:

- It reads local Codex session JSONL files.
- Project transition detection can also read local `state_5.sqlite` thread `cwd` and timestamps as read-only evidence.
- It writes local reports.
- It does not upload session logs.
- It does not include telemetry.
- It does not fetch live pricing.

See [PRIVACY.md](PRIVACY.md) for details. The screenshot above uses synthetic data.

## Development

Python:

```powershell
uv run pytest
```

VS Code extension:

```powershell
cd extensions/vscode
npm install
npm test
```

Release checklist: [docs/release.md](docs/release.md).
