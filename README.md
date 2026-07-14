# Codex Usage Dashboard

Local tooling for understanding Codex token usage, project activity, Codex credits, and API-equivalent cost from Codex session JSONL logs.

![Synthetic Codex Usage Dashboard screenshot](docs/marketplace/dashboard-synthetic.png)

This repository contains:

- A Python CLI, `codex-usage`, for parsing local Codex session logs.
- A Windows x64 and macOS Apple Silicon VS Code extension preview that bundles the Python CLI.
- A dependency-light dashboard report rendered with local HTML, CSS, and inline SVG.

## VS Code Preview Packages

The current preview packages support Windows x64 and macOS Apple Silicon. Each package is self-contained at runtime and does not require Python, `uv`, or this repository after installation.

Build and install the local VSIX:

```powershell
cd extensions/vscode
npm run package:vsix:win
code --install-extension ..\..\output\releases\codex-usage-dashboard-win32-x64.vsix --force
```

```bash
cd extensions/vscode
npm run package:vsix:mac
code --install-extension ../../output/releases/codex-usage-dashboard-darwin-arm64.vsix --force
```

Available commands:

- `Codex Usage: Open Dashboard`
- `Codex Usage: Refresh Dashboard`
- `Codex Usage: Select Range`
- `Codex Usage: Select Projects`
- `Codex Usage: Review Project Transitions`
- `Codex Usage: Select Theme`
- `Codex Usage: Sync Menu`
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
uv run codex-usage sync run --sync-dir D:\CodexSync --thread-id <thread-id> --json
uv run codex-usage sync status --sync-dir D:\CodexSync --thread-id <thread-id> --json
```

By default, the tool looks for Codex session storage at:

- `CODEX_HOME/sessions`
- `CODEX_HOME/archived_sessions`
- `%USERPROFILE%\.codex\sessions`
- `%USERPROFILE%\.codex\archived_sessions`
- `~/.codex/sessions`
- `~/.codex/archived_sessions`

Dashboard and usage-report discovery includes active and archived session roots when they exist. Conversation sync uses only the active `sessions` roots. Set `CODEX_HOME` when you need to point the CLI at a different Codex home for testing or migration.

Dashboard theme defaults to `auto`. In standalone HTML, auto follows the browser/system color-scheme preference. In VS Code, auto follows the active VS Code theme. You can force a report with `--theme day` or `--theme night`, or set `CODEX_USAGE_THEME`.

### Performance Cache

The VS Code preview stores a local SQLite cache under VS Code global extension storage. The first dashboard open may say "Initializing Codex usage cache" and take a few seconds while existing Codex JSONL files are parsed. Later range switches and project pickers reuse unchanged parsed rows and should usually feel much faster. The cache is local only, can be rebuilt automatically after schema changes, and does not change pricing semantics because costs are still calculated from checked-in effective-dated rates at report time.

### Codex Fast Mode

Codex fast mode is counted through the token usage that Codex records. Current Codex session JSONL files do not expose a durable per-turn fast-mode marker or exact charged-credit field, so the dashboard cannot label GPT-5.5 fast-mode turns separately from regular GPT-5.5 turns.

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

The VS Code preview can sync selected Codex conversations through a bring-your-own local sync folder such as iCloud Drive, OneDrive, Dropbox, Syncthing, or a network drive. Sync is off by default. Run `Codex Usage: Configure Sync` to choose a sync folder, select one or more projects, see a rough sync-size estimate for each project, then choose whether to sync all conversations in those projects or only specific conversations.

Continue a long-running Codex conversation on another computer when a normal handoff cannot complete because the conversation is too large. Sync transfers the original conversation JSONL without summarizing or repackaging its context.

Projects match the repo/workspace identities shown in Project Breakdown. Conversations are individual Codex sessions inside those projects. Current sync discovery includes active `sessions` conversations only, not archived conversations. Size estimates are based on local session JSONL file sizes plus a small central-index allowance, so they are useful for cloud-storage planning but not exact billing or provider overhead. The extension stores the sync folder, selected sync projects, and selected conversations as local VS Code extension UI state, not as raw settings you need to edit by hand.

Version 2 writes one byte-preserved JSONL per conversation and one repairable catalog:

```text
<sync-folder>/
  conversations/
    <portable-thread-filename>.jsonl
  sync-index.json
```

Version 2 does not migrate or automatically clean up the earlier layout. Existing sync users must empty the old sync-folder contents themselves, then run sync again.

Selection controls which active conversations participate; deselecting a project or conversation never deletes its remote JSONL or index entry. Project mode discovers newly created matching active conversations on future runs.

Sync is managed from the dashboard `Sync: ... ▾` menu, where you can pause/resume, change the folder, change projects or conversations, clear setup, run manual sync, and inspect status.

Background sync is intentionally quiet. The VS Code status bar shows the current sync state, such as `Sync:Off`, `Sync:Idle`, `Sync:Waiting`, `Sync:Scanning`, `Sync:Pulling`, `Sync:Pushing`, `Sync:Conflict`, or `Sync:Issue`. Automatic sync logs details to the Codex Usage output channel; visible notifications are reserved for manual sync and action-needed failures.

Manual-only sync is supported: keep Sync Enabled on, turn Auto Pull and Auto Push off, then use `Codex Usage: Sync Now` from the command palette or the dashboard action strip. Use `Sync Status` to inspect selected conversation state without running a full sync.

Sync uses three-way state per conversation. If one side only appends new Codex JSONL events, the beta treats it as a fast-forward and pulls or pushes automatically. If both computers append different tails to the same conversation, sync stops and preserves both sides for review.

The sync MVP copies only selected active conversation JSONLs and preserves their matching session-index metadata through the repairable catalog. It does not sync `auth.json`, settings, caches, logs, archived conversations, or SQLite databases. If local memory database rows are detected for a selected conversation, sync status reports that they are not synced by this beta.

## Archived And Deleted Conversations

The dashboard treats token usage as historical usage. Archiving a Codex conversation moves its JSONL file to `archived_sessions`, and those files are included in totals. If a conversation file disappears after the dashboard cache has seen it, its parsed usage is retained as historical usage and marked as a retained missing file.

To observe how your installed Codex build handles deletion:

```powershell
uv run codex-usage storage snapshot --json > output\before-delete.json
# delete one test conversation in Codex
uv run codex-usage storage snapshot --json > output\after-delete.json
uv run codex-usage summary --range all --by project --json > output\after-delete-summary.json
```

Do not use a conversation you still need for sync testing. The dashboard can preserve usage after it has parsed a file, but it cannot restore a deleted Codex conversation.

## Accounting And Pricing

The parser reads cumulative `total_token_usage` records and counts only positive deltas between token-count events. This avoids double-counting repeated records while still allowing daily and hourly reports for long sessions.

Project grouping uses `git.repository_url` when present, local `.git/config` origin remotes resolved from `cwd` when needed, then normalized `cwd`, then the session id. Automatic project transition detection handles high-confidence repository switches within a thread without manual alias configuration.

Pricing uses checked-in effective-dated rate schedules. Each retained usage event is priced with the API USD and Codex credit rates active at that event's timestamp, so future price changes can be added without rewriting historical reports.

GPT-5.6 Sol, Terra, and Luna use official API rates for usage recorded from June 26, 2026 onward. Their Codex credit estimates start July 9, 2026, remain flat across context length, and use the public credit rate card. Reasoning effort such as `ultra` does not change the per-token rate; any additional work is reflected in the recorded token totals.

The official `gpt-5.6` model alias is priced as GPT-5.6 Sol. Other variants such as `gpt-5.6-pro`, `gpt-5.6-mini`, and wrapper names remain visible but unpriced unless they exactly match a checked-in model id or explicit alias.

For GPT-5.6 API USD, exactly 272,000 input tokens is short-context pricing. More than 272,000 input tokens, including 272,001, prices the full retained request event at long-context API rates. Long rates per 1M tokens are: Sol $10 uncached input, $1 cached input, $45 output; Terra $5 uncached input, $0.50 cached input, $22.50 output; Luna $2 uncached input, $0.20 cached input, $9 output. The long-context multiplier does not apply to Codex credits.

The parser reads cumulative `total_token_usage` records but reports only retained positive deltas. A local audit of GPT-5.6 Sol sessions found retained positive deltas matched request-level `last_token_usage`, so pricing is per retained event and cumulative session totals cannot trigger long-context pricing.

The tool does not fetch live pricing. Cost and credit values are estimates based on the checked-in pricing table version shown in each report. New Codex models may appear in local logs before this repository has official checked-in rates for them; those models remain visible in totals and model mix, but their API USD and Codex credit estimates are excluded until exact effective-dated rates are checked in.

For GPT-5.6 and later API models, explicit cache writes can have a separate 1.25x input charge. Local Codex logs expose cached-input reads but no distinct cache-write token count, so API-equivalent USD applies the standard input rate to non-cached input and cannot include an unobservable cache-write uplift.

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
