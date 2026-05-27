# Privacy

Codex Usage Dashboard is designed as a local-first tool.

## What It Reads

- Local Codex session JSONL files from the detected Codex sessions directory.
- Local archived Codex session JSONL files from detected `archived_sessions` directories.
- Read-only local Codex `state_5.sqlite` thread evidence for automatic project transition detection, limited to thread id/timestamps and the `threads` field `cwd` when present.
- Local Codex `session_index.jsonl` entries when experimental selected-thread sync is used.
- Read-only local Codex SQLite memory diagnostics when sync status is requested.
- User settings for dashboard range, theme, transition detection, and experimental sync behavior toggles.
- Extension UI state for selected dashboard projects, the selected sync folder, selected sync projects, sync conversation mode, and selected sync conversation ids.

## What It Writes

- Local HTML reports under VS Code extension storage.
- Optional local CLI outputs such as JSON, CSV, and HTML reports when you run `codex-usage` directly.
- Optional selected-thread sync files under a user-provided local sync folder.
- Local sync backups under `.codex-sync-backups` before imported thread files overwrite existing local files.
- A local SQLite usage cache that may retain parsed token usage for session files that were later archived or deleted locally.
- It does not write to or mutate Codex SQLite databases.

## Network And Telemetry

- The extension does not upload Codex session logs.
- The extension does not include telemetry.
- The extension does not fetch live pricing data.
- Automatic project transition detection does not upload data or make network calls.
- Experimental sync writes only to the local folder you choose through the extension. Any cloud transfer is handled by your own sync tool, not by this extension.
- Experimental sync does not sync Codex SQLite databases, including `state_5.sqlite`.
- API-equivalent USD and Codex credit estimates use checked-in effective-dated pricing tables.

## Data Sensitivity

Codex session logs can include project paths, repository URLs, branch names, model names, timestamps, and usage counts. Project transition detection can also inspect local thread current working directories and timestamps from `state_5.sqlite`. Do not share raw logs, generated reports, or transition JSON unless you are comfortable sharing that metadata.

The retained cache data stays on your machine under the extension/global Codex Usage cache and is used only for historical accounting. It cannot restore a deleted Codex conversation.

The screenshot in this repository is synthetic and does not contain real session data.
