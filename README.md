# Codex Usage Analyzer

Local Python CLI for reading Codex session JSONL files and estimating API-equivalent token cost.

## Usage

```powershell
uv sync
uv run codex-usage summary --range 7d --by project
uv run codex-usage summary --range all --by hour --json
uv run codex-usage summary --range month --by model --csv output/monthly-models.csv
uv run codex-usage report --range 30d --output output/report.html
```

By default, the tool looks for Codex sessions at:

- `CODEX_USAGE_SESSIONS_DIR`
- `CODEX_HOME/sessions`
- `%USERPROFILE%\.codex\sessions`
- `~/.codex/sessions`

You can override discovery with `--sessions-dir`.

## Accounting

The parser reads cumulative `total_token_usage` records and charges only the positive delta between token-count events. This avoids double-counting repeated records while still allowing daily and hourly reports for long sessions.

Project grouping uses `git.repository_url` when present, then normalized `cwd`, then the session id.

## Dashboard Report

`codex-usage report` writes a self-contained HTML dashboard with inline SVG charts:

- KPI strip for total tokens, API-equivalent cost, cache hit share, and unpriced tokens
- daily API-equivalent cost trend
- hourly cost heatmap
- top project breakdown
- model mix

The report uses no remote assets, JavaScript, or Python chart libraries. That keeps it easy to open locally now and easier to reuse later inside a VS Code webview.

## VS Code Extension Prototype

A local VS Code wrapper lives in `extensions/vscode`. It stays intentionally thin: TypeScript owns commands, settings, the status bar item, process spawning, and the webview lifecycle while Python continues to own parsing, aggregation, pricing, and HTML/SVG rendering.

```powershell
cd extensions/vscode
npm install
npm run build
npm test
```

Run it from an Extension Development Host and use `Codex Usage: Open Dashboard`. The extension invokes:

```powershell
uv run codex-usage report --range <range> --output <globalStorage>/report.html
```

For local development, `uv` must be available on `PATH`. Marketplace publishing should wait until the Python runtime and dependency distribution strategy is settled.
