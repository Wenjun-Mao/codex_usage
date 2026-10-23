# Privacy

Codex Usage is local-first. It has no telemetry, cloud backend, Codex hooks, or
model/API calls.

## Data Read Locally

- Active and archived Codex task JSONLs under the selected `CODEX_HOME`.
- Codex task/project metadata needed for project identity and transition evidence.
- Existing schema-8 Codex Usage caches selected during first-run migration.
- Companion settings such as active Codex home, capture interval, theme,
  transition detection. Legacy native settings and the inert transfer-folder path remain
  in the shared settings file for compatibility.

Task content can include prompts, responses, paths, repository URLs, tool data,
branch names, timestamps, model names, and usage counts. Do not publish raw task
files or diagnostic logs without reviewing them.

## Data Written Locally

- The durable ledger at
  `CODEX_HOME/.codex-usage/usage-ledger.sqlite3`, including captured usage and
  retained history for source files that later disappear.
- A separate disposable Task Storage diagnostics database.
- The owner-local authenticated collector descriptor, lock, logs, rebuild
  staging, migration audit, and settings.
- No new OS background service. A legacy Codex Usage LaunchAgent or Windows
  Scheduled Task is removed only after explicit handoff confirmation.
Codex task JSONLs, Codex SQLite databases and Desktop project state are read-only.
Task Transfer was retired in 2.13.0; existing chats, transfer files and paired
state remain untouched, and configured transfer folders are not accessed.
Task Storage is read-only except for
its disposable diagnostic cache. Codex Usage does not create, fork, archive,
restore, or delete Codex tasks.

## Local Communication

The collector listens on a random `127.0.0.1` port and publishes a per-start
bearer token in an owner-local descriptor. It rejects browser origins,
non-loopback host headers, unauthenticated requests, protocol mismatches, and
oversized requests. The VS Code extension host proxies calls;
webviews never receive the token. Reports and clients never write SQLite
directly.

## Network Activity

Marketplace extension updates are handled by VS Code. The extension makes no
automatic update-check request of its own.

Codex Usage does not upload task files, usage rows, project metadata, reports,
or diagnostics. Pricing tables are checked into the application and are not
fetched live. Codex Usage does not access legacy transfer folders or connect to
their storage providers. Independently configured cloud-storage software may
continue synchronizing those folders.

## Retention And Removal

Captured usage is intentionally retained when a source JSONL disappears. A
manual task deletion can lose an uncaptured tail of up to the configured
interval, so run **Capture Usage** first. The ledger cannot restore deleted task
content.

**Reset Local Data** removes Codex Usage's ledger and disposable diagnostics,
not Codex task files or legacy migration sources. Windows uninstall asks whether
to remove ledger and settings and defaults to preservation. On macOS,
**Unregister Background Agent** and **Reset Local Data** are explicit settings
actions before drag-to-trash removal.

Version 1.8.0 stopped creating or verifying `.codex-task-backup` archives.
Existing archives remain user-owned and untouched.

Repository screenshots use synthetic data and contain no personal task data.
