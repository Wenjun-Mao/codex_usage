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
- `Codex Usage: Select Theme`
- `Codex Usage: Open Settings`

## CLI Usage

```powershell
uv sync
uv run codex-usage summary --range 7d --by project
uv run codex-usage summary --range all --by hour --json
uv run codex-usage summary --range month --by model --csv output/monthly-models.csv
uv run codex-usage report --range 30d --output output/report.html
uv run codex-usage report --range all --theme night --output output/night-report.html
```

By default, the tool looks for Codex sessions at:

- `CODEX_USAGE_SESSIONS_DIR`
- `CODEX_HOME/sessions`
- `%USERPROFILE%\.codex\sessions`
- `~/.codex/sessions`

You can override discovery with `--sessions-dir` or the VS Code `codexUsage.sessionsDir` setting.

Dashboard theme defaults to `auto`. In standalone HTML, auto follows the browser/system color-scheme preference. In VS Code, auto follows the active VS Code theme. You can force a report with `--theme day` or `--theme night`, or set `CODEX_USAGE_THEME`.

## What The Dashboard Shows

- Total tokens and usage event counts
- API-equivalent USD using checked-in effective-dated pricing
- Codex credit estimates
- Cache hit share
- Daily and hourly usage patterns
- Project, model, and session rollups
- Optional subscription comparison when you provide a monthly subscription amount

The report uses no remote assets, JavaScript, or Python chart libraries. It is safe to open locally and is designed to fit inside a VS Code webview.
The dashboard uses the same tokenized day/night design system as the VS Code extension, including dark-mode-friendly charts and tables.

## Accounting And Pricing

The parser reads cumulative `total_token_usage` records and counts only positive deltas between token-count events. This avoids double-counting repeated records while still allowing daily and hourly reports for long sessions.

Project grouping uses `git.repository_url` when present, then normalized `cwd`, then the session id.

Pricing uses checked-in effective-dated rate schedules. Each usage event is priced with the API USD and Codex credit rates active at that event's timestamp, so future price changes can be added without rewriting historical reports.

The tool does not fetch live pricing. Cost and credit values are estimates based on the checked-in pricing table version shown in each report.

## Privacy

Codex Usage Dashboard is local-first:

- It reads local Codex session JSONL files.
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
