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

## VS Code Extension Direction

The MVP is Python-first. A future VS Code extension should stay thin: TypeScript handles commands, status bar, and webviews, then invokes this CLI with `--json`. VS Code extensions run in Node.js or a browser WebWorker, so a normal extension cannot be pure Python.
