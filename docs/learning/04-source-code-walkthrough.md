# Source Code Walkthrough

This walkthrough is the map I wanted before touching the code.

## CLI Entry

Start with [src/codex_usage/cli.py](../../src/codex_usage/cli.py). It defines public commands:

- `summary`
- `report`
- `threads`
- `transitions`
- `sync export`
- `sync import`
- `sync status`

The CLI should remain boring. Its main job is to parse arguments, load session data, call domain modules, and write output.

## Models

[src/codex_usage/models.py](../../src/codex_usage/models.py) defines the core shapes:

- `TokenUsage`
- `SessionMetadata`
- `UsageRecord`

`TokenUsage.positive_delta()` is one of the most important pieces of the project. Codex records cumulative totals, so new usage is the positive delta from the previous total.

## Discovery And Inventory

[src/codex_usage/discovery.py](../../src/codex_usage/discovery.py), [src/codex_usage/session_files.py](../../src/codex_usage/session_files.py), and [src/codex_usage/session_inventory.py](../../src/codex_usage/session_inventory.py) locate session files and distinguish active, archived, and missing-retained storage states.

This layer is why users do not need to type a sessions directory in settings.

## Parser

[src/codex_usage/parser.py](../../src/codex_usage/parser.py) reads JSONL line by line and emits `UsageRecord` rows.

Notable behavior:

- ignores malformed JSON lines;
- ignores `token_count` events with missing or null info;
- tracks current model from `turn_context`;
- calculates positive deltas from cumulative totals;
- avoids counting replayed parent history in fork files;
- inherits parent project identity for subagent/fork records when appropriate.

Future me: parser code is defensive because the input is not our schema. That is good. The goal is not to fail loudly on every unknown event; the goal is to preserve trustworthy usage records.

## Project Identity And Transitions

[src/codex_usage/project_identity.py](../../src/codex_usage/project_identity.py) turns git metadata or `cwd` into a canonical project key.

[src/codex_usage/project_transition_evidence.py](../../src/codex_usage/project_transition_evidence.py) and [src/codex_usage/project_transitions.py](../../src/codex_usage/project_transitions.py) detect high-confidence project switches, such as a repo rename where the same conversation continues from a new path or remote.

Labels can collide. Project keys should not.

## Cache

[src/codex_usage/session_cache.py](../../src/codex_usage/session_cache.py) stores parsed usage records in SQLite. It is responsible for:

- reusing unchanged files;
- reparsing changed files;
- retaining already-parsed missing files;
- caching project transition results;
- exposing file summaries for thread and sync pickers.

The cache is a performance feature and a historical-retention feature. It should not change usage math.

## Aggregation And Pricing

[src/codex_usage/aggregation.py](../../src/codex_usage/aggregation.py) filters by range and project keys, then groups records by day, hour, project, model, or session.

[src/codex_usage/pricing.py](../../src/codex_usage/pricing.py) contains effective-dated API USD and Codex credit rate schedules. Aggregation passes each record timestamp into pricing, so historical usage is priced using the rate active at the event time.

API USD and Codex credits are intentionally separate.

## Reporting

[src/codex_usage/report_view.py](../../src/codex_usage/report_view.py) prepares chart-ready data.

[src/codex_usage/charts.py](../../src/codex_usage/charts.py) generates inline SVG.

[src/codex_usage/report_theme.py](../../src/codex_usage/report_theme.py) defines theme values.

[src/codex_usage/reporting.py](../../src/codex_usage/reporting.py) renders terminal, CSV, JSON, and HTML outputs.

The report is script-free and self-contained so it can run as a standalone HTML file and inside a VS Code webview.

## VS Code Extension

[extensions/vscode/src/core.ts](../../extensions/vscode/src/core.ts) contains pure, testable TypeScript helpers:

- argument builders;
- settings normalization;
- webview CSP/control injection;
- QuickPick item parsing;
- sync status labeling.

[extensions/vscode/src/extension.ts](../../extensions/vscode/src/extension.ts) owns VS Code side effects:

- commands;
- output channel;
- status bar;
- webview panels;
- global state;
- file watchers;
- child process spawning.

Future me: this split is why the TypeScript tests are useful. Most extension behavior can be tested without launching VS Code.

## Sync

[src/codex_usage/sync.py](../../src/codex_usage/sync.py) is the selected-conversation sync engine.

[src/codex_usage/sync_io.py](../../src/codex_usage/sync_io.py) owns safer file I/O helpers.

Sync is conservative because the files are user data. It copies selected session JSONL files and matching index entries. It does not sync Codex auth, settings, caches, logs, or SQLite databases.

