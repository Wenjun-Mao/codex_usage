# Privacy

Codex Usage is local-first. It has no telemetry, cloud backend, Codex hooks, or
model/API calls.

## Data Read Locally

- Active and archived Codex task JSONLs under the selected `CODEX_HOME`.
- Codex task/project metadata needed for project identity, transition evidence,
  Task Transfer registration, and guarded Desktop assignment.
- Existing schema-8 Codex Usage caches selected during first-run migration.
- A user-selected Task Transfer folder during explicit Import, Export, or Review
  Status operations.
- App settings such as active Codex home, capture interval, background consent,
  theme, transition detection, update preference, and transfer folder.

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
- A per-user macOS LaunchAgent or Windows Scheduled Task only after explicit
  background-capture consent.
- Selected task files and transfer metadata only in a user-chosen Task Transfer
  folder during explicit operations.
- A temporary sibling backup of Codex Desktop project state during guarded Task
  Transfer assignment. The state is verified and restored if commit validation
  fails.

Task Transfer Import atomically installs selected task JSONLs but never edits
their content or writes Codex SQLite databases. Outside an explicit Import or
Export, Codex task JSONLs are read-only. Task Storage is read-only except for
its disposable diagnostic cache. Codex Usage does not create, fork, archive,
restore, or delete Codex tasks.

## Local Communication

The collector listens on a random `127.0.0.1` port and publishes a per-start
bearer token in an owner-local descriptor. It rejects browser origins,
non-loopback host headers, unauthenticated requests, protocol mismatches, and
oversized requests. The Tauri Rust host and VS Code extension host proxy calls;
webviews never receive the token. Reports and clients never write SQLite
directly.

## Network Activity

The native preview retains a user-controlled GitHub update-check setting, but
The 2.x release line does not publish an automatic native update channel. The
VS Code extension can open the distribution-workflow page when the user
explicitly asks to find a missing native preview. Marketplace extension updates
are handled by VS Code.

Codex Usage does not upload task files, usage rows, project metadata, reports,
or diagnostics. Pricing tables are checked into the application and are not
fetched live. A cloud-storage provider may copy Task Transfer files only because
the user chose a folder managed by that provider; Codex Usage does not connect
to the provider itself.

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
