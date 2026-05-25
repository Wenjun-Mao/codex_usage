# Persistent Usage Cache And Responsive UX Design

## Purpose

Make the Codex Usage VS Code dashboard feel responsive without adding a background daemon or service. Range switching, project selection, and sync setup currently feel slow because each action can launch the bundled Python executable, scan Codex session files, parse JSONL, infer project transitions, aggregate usage, render HTML, and then update the webview.

The goal is to keep the extension architecture simple while making repeated interactions fast. The Python CLI should persist parsed session data in a local cache and reuse it across commands. The VS Code wrapper should make long-running first-load and refresh states visible in the dashboard and status bar.

## Current Behavior

Dashboard refresh runs:

1. `codex-usage report --range <range> --output <report.html>`.
2. Python discovers sessions.
3. Python scans all JSONL files.
4. Python parses token usage and metadata.
5. Python infers project transitions.
6. Python aggregates and renders the full HTML report.
7. VS Code reads the HTML and replaces the webview contents.

Project selection and sync setup have similar costs:

- `Codex Usage: Select Projects` runs a project summary command before showing the picker.
- `Codex Usage: Configure Sync` can run a folder picker, a threads command for project choices, another threads command for conversation choices, and dashboard refreshes between steps.
- Some operations use VS Code progress, but the dashboard itself often looks idle, so delays feel like hangs.

## Desired Behavior

After the first cache build, common interactions should be fast:

- Switching ranges should usually complete in under about one second for unchanged session files.
- Project pickers should reuse cached parsed records and avoid full reparses.
- Sync project/conversation selection should show clear progress and refresh the dashboard only once after setup.
- The first run may still take several seconds, but the UI should say what is happening.

First-run dashboard copy:

```text
Initializing Codex usage cache. This can take a few seconds the first time.
```

Normal refresh copy:

```text
Refreshing Codex usage...
```

Incremental cache update copy:

```text
Updating changed sessions...
```

## Architecture

Use a persistent Python-side cache. Do not add a daemon, background service, long-running process, HTTP server, or Node-side parser.

The VS Code extension still invokes the bundled CLI. The CLI becomes smarter:

1. Discover session directories.
2. Open the local cache.
3. Check discovered JSONL files against cached file fingerprints.
4. Parse only new or changed files.
5. Delete cache rows for removed files.
6. Run range, project, transition, thread, and report operations from cached normalized records.

The cache is an implementation detail of the Python CLI. Public commands stay the same.

## Cache Storage

Use SQLite from the Python standard library. This avoids a new runtime dependency and gives durable indexed queries for summaries and thread pickers.

Default cache locations:

- When VS Code launches the CLI: pass an internal cache directory under `context.globalStorageUri`.
- When the CLI runs outside VS Code: use a cache directory under Codex home, for example `<codex_home>/.codex-usage-cache`.

The VS Code cache path should be passed through an internal CLI option or environment variable that is not exposed as a user setting. A suitable name is:

- `CODEX_USAGE_CACHE_DIR`

This is not a manual user knob in the Settings UI. It is an extension-to-CLI implementation detail.

## Cache Schema

Suggested tables:

### `schema_meta`

- `key text primary key`
- `value text not null`

Required keys:

- `schema_version`
- `parser_version`
- `project_transition_version`

If any version changes incompatibly, rebuild the cache.

### `files`

- `path text primary key`
- `session_dir text not null`
- `size_bytes integer not null`
- `mtime_ns integer not null`
- `sha256 text`
- `parsed_at text not null`
- `session_id text`
- `error text`

Use path, size, and mtime as the fast fingerprint. Hash can stay optional and be used when needed for diagnostics or suspicious cases.

### `usage_records`

One row per parsed token-usage delta.

- `file_path text not null`
- `record_index integer not null`
- `timestamp text not null`
- `session_id text not null`
- `turn_id text`
- `model text not null`
- `effort text`
- `collaboration_mode text`
- `project_key text not null`
- `project_label text not null`
- `project_aliases_json text not null`
- `cwd text`
- `git_repository_url text`
- `git_branch text`
- `parent_thread_id text`
- `input_tokens integer not null`
- `cached_input_tokens integer not null`
- `output_tokens integer not null`
- `reasoning_output_tokens integer not null`
- `total_tokens integer not null`

Primary key can be `(file_path, record_index)`.

### `session_metadata`

One row per parsed session file.

- `file_path text primary key`
- `session_id text not null`
- `title text`
- `updated_at text`
- `cwd text`
- `project_key text`
- `project_label text`
- `project_aliases_json text`
- `git_repository_url text`
- `git_branch text`
- `memory_mode text`
- `has_base_instructions integer not null`
- `session_bytes integer not null`
- `estimated_sync_bytes integer not null`

This powers thread and sync pickers without reparsing.

### `project_transitions`

Store inferred transition rows for the current cache build:

- `source_key text`
- `source_label text`
- `target_key text`
- `target_label text`
- `effective_from text`
- `confidence integer`
- `evidence_json text`
- `thread_ids_json text`

Project transitions depend on parsed records plus local path observations. They can be recomputed when changed files are detected or when the transition inference version changes.

## Cache Refresh Policy

On every CLI command that reads sessions:

1. Discover JSONL files.
2. Load `files` rows.
3. Mark files unchanged when path, size, and mtime match.
4. For changed or new files:
   - parse the file
   - delete old rows for that path
   - insert fresh `usage_records`
   - insert fresh `session_metadata`
   - update the `files` row
5. For removed files:
   - delete `files`, `usage_records`, and `session_metadata` rows for that path
6. Recompute project transitions if any file changed, disappeared, or the transition version changed.

This conservative policy means stale reports are unlikely. It also preserves correctness when Codex appends to active JSONL files.

## Query Flow

The existing CLI command behavior stays the same:

- `summary`
- `report`
- `threads`
- `sync status/import/export`
- `transitions suggest`

Internally:

- `summary` and `report` load records from cache, then apply range/project filters and aggregate.
- `threads` loads session metadata and token totals from cache.
- `sync` can keep using `list_threads`, but `list_threads` should read from cache rather than parsing all files.
- `transitions suggest` can read cached transition rows.

Keep pricing outside the parsed cache. Pricing is effective-dated and can change independently of parsed token rows, so costs should still be computed during aggregation/reporting.

## VS Code Responsive UX

### Dashboard Refresh

Before starting `codex-usage report`, replace the webview with loading HTML that includes the command strip and one of:

- `Initializing Codex usage cache. This can take a few seconds the first time.`
- `Refreshing Codex usage...`
- `Updating changed sessions...`

Use a simple heuristic for first run:

- If the cache database does not exist at the extension cache path, show initializing.
- Otherwise show refreshing.

The status bar should show:

- `Codex Usage: Initializing`
- `Codex Usage: Loading`
- then return to the normal range/sync state.

If refresh fails, keep the existing script-free error HTML and include a short note to check the Codex Usage output channel for details.

### Range Switching

When a user selects a new range:

1. Persist the range.
2. Immediately show loading HTML in the existing dashboard if it is open.
3. Run the report command.
4. Replace loading HTML with the rendered report.

Do not leave the old range visible without indication. That makes the UI feel stale.

### Project Selection

When loading projects:

- Keep the VS Code progress window.
- Set status bar to `Codex Usage: Loading Projects`.
- Reuse cached records via Python.
- Refresh the dashboard only after the project selection is saved.

### Sync Setup

`Codex Usage: Configure Sync` should be a guided flow with explicit progress:

1. Select or keep sync folder.
2. Show `Loading sync projects...`.
3. Select projects.
4. Show `Loading conversations...`.
5. Select all conversations in projects or individual conversations.
6. Refresh dashboard once at the end.

Do not refresh the dashboard between project and conversation selection. That double refresh is expensive and visually noisy.

If a step takes time, use both VS Code progress and a short status bar label. The user should never wonder whether the extension is stuck.

## Error Handling

Cache errors should not make the extension unusable.

If opening or migrating the cache fails:

1. Log the detailed error to the output channel.
2. Fall back to the current no-cache parse path for that command if practical.
3. Show a concise warning only when the user action cannot complete.

If an individual JSONL file cannot be parsed:

- Store the parse error in `files.error`.
- Skip that file's usage rows.
- Continue processing other files.
- Surface aggregate parse-error count in output or future diagnostics, not as repeated popups.

If the cache schema version is unsupported:

- Rebuild automatically by deleting/recreating cache tables.
- Show the first-run initializing message because a rebuild can take time.

## Testing

Python tests should cover:

- first cache build parses all files and stores records
- unchanged file is reused without reparsing
- changed size or mtime causes a reparse
- removed file deletes cached rows
- schema version mismatch rebuilds cache
- range summaries from cache match direct parsing
- thread listing from cache matches current `list_threads`
- project transitions are recomputed when relevant files change
- corrupt file records an error and does not block other files

TypeScript tests should cover:

- loading HTML is script-free and includes first-run copy
- dashboard refresh uses initializing copy when cache db is missing
- dashboard refresh uses refreshing copy when cache db exists
- range switch shows loading state before replacing the report
- sync setup refreshes dashboard once at the end
- status bar labels include loading states

Smoke tests should cover:

- first dashboard open with no cache
- second dashboard open using cache
- switching `7d`, `30d`, `all`, `today`
- selecting projects
- configuring sync folder/projects/conversations
- editing or appending a JSONL file and seeing updated totals

## Non-Goals

- Do not add a daemon, service, HTTP server, or long-running Python process.
- Do not add cache settings to VS Code Settings.
- Do not move parsing into TypeScript.
- Do not change public CLI command names.
- Do not change pricing semantics.
- Do not change sync conflict behavior in this slice.
