# Changelog

## Unreleased

## 2.2.0 - 2026-09-04 - Comparative Usage Charts

- Ordered visual and exact model breakdowns by GPT generation and product tier, with stable multi-hue colors for current named models.
- Added role-level API-equivalent dollars and a script-free Tokens/API cost scale to Project Breakdown.
- Made every Model Mix row share one grid so neutral bar tracks have identical geometry.

## 2.1.1 - 2026-09-04 - GPT-6 Astra Pricing

- Added exact `gpt-6-astra` API-equivalent and standard Codex credit pricing from the first verified availability date, including cache-write and long-context API rates.
- Updated the GPT-5.6 Sol, Terra, and Luna standard credit schedules from the newly published rate table while preserving earlier usage at its historical rates.
- Kept plan-specific and Fast-mode multipliers out of estimates because local task records do not identify those billing contexts reliably.

## 2.1.0 - 2026-09-04 - Unified Dashboard UI

- Distinguished **Capture Usage**, which scans changed Codex task data into the durable ledger, from each view's compact reload action, which only re-queries that view's existing data.
- Unified Usage and Task Storage around the same explicit Day, Night, and Auto themes, compact metric strip, typography, spacing, status treatment, and responsive layout in both the standalone extension and optional native app.
- Added last-capture and data-source context to the dashboard toolbar, kept Usage range controls out of Task Storage, and added a renderer revision to invalidate persistent HTML when presentation code changes.
- Regenerated the Marketplace images from the unified native fixture and added wide/narrow Day and Night layout checks.

## 2.0.1 - 2026-09-04 - Live Baseline Progress

- Refreshed open Usage views automatically as the durable ledger revision or baseline coverage advances, so partial-baseline notices and totals no longer remain frozen until a manual refresh.
- Kept automatic report refreshes ledger-only, quiet, and bounded to a 30-second cadence while preserving the last good report after transient background failures.
- Used the native client's lightweight status poll to trigger coherent report-and-baseline updates without reopening Codex JSONL files.

## 2.0.0 - 2026-09-04 - Durable Ledger And Standalone Clients

- Added a forward-migrated durable SQLite ledger for persistent history and one authenticated local collector with 15-minute default capture, configurable 1-1,440 minute or Manual Only scheduling, Capture Now coalescing, watcher reconciliation, bounded append reads, and resumable stale-source reconstruction.
- Made Usage reports ledger-only and shared Usage, Task Storage, Task Transfer, Desktop binding, registration, onboarding, and settings through one Python agent contract.
- Rebuilt the Marketplace extension as standalone macOS Apple Silicon and Windows x64 packages, each with its matching parent-bound collector and no native-app, Python, `uv`, or source-checkout requirement.
- Added an optional Tauri 2 native UI whose explicitly enabled LaunchAgent or Scheduled Task can retain usage while Codex, VS Code, and the native window are closed.
- Published the VSIX packages independently of unsigned native DMG and NSIS preview artifacts, which carry SHA-256 integrity metadata but no paid signing or automatic-update contract.
- Removed the public Python CLI and its `codex-usage` console script; Python entry points are private agent and packaging interfaces.
- Made baseline coverage account for every inventoried source before bounded parsing, so unscheduled files and bytes remain visibly incomplete instead of producing prematurely complete totals.
- Added resumable, audited schema-8 cache migration that retains deleted-source history, deduplicates complete semantic overlap, and asks for one explicit source when a task's usage context, metadata, or transition evidence diverges.
- Kept guarded Task Transfer imports compatible with Codex Desktop's compact two-field project assignments while retaining legacy assignment support and fail-closed validation for unknown state shapes.
- Preserved one project identity when a verified local checkout changes from an upstream Git remote to a fork in the same canonical path, preventing duplicate Project Breakdown rows without merging unrelated repositories by label.

## 1.8.2 - 2026-08-29 - Release Gate Hardening

- Split parser-batch result validation from the cache refresh coordinator so detached release-tag builds enforce the repository's focused-module size guard without changing cache behavior.
- Retained the complete cross-process cache serialization, stale-checkpoint rollback, and active-to-archive fallback recovery introduced in 1.8.1.

## 1.8.1 - 2026-08-29 - Cross-Process Cache Recovery

- Serialized shared usage-cache refreshes across independent VS Code extension hosts, capturing source inventory only after the reporter owns the cache lock.
- Rechecked append checkpoints inside the SQLite write transaction and rolled back stale commit groups before any duplicate record indexes can be inserted.
- Recovered direct fallback when Codex moves an intact rollout from active to archived storage during a report, retrying only the exact relocated task and keeping genuine disappearance explicit.

## 1.8.0 - 2026-08-27 - Codex-Owned Task Lifecycle

- Removed custom compressed task backup, verification, and rollover workflows from the CLI and VS Code extension; Task Storage now exposes only read-only inventory and selected-tree analysis.
- Replaced the storage snapshot payload with schema 4 and removed backup- and rollover-readiness fields while preserving topology diagnostics, analysis coverage, and amplification metrics.
- Removed the zstandard runtime dependency and replaced the packaged backup gate with cross-platform Task Storage snapshot-and-analysis coverage.
- Documented manual **Fork in Codex** for continuity and a fresh task with a concise handoff for meaningful inherited-context reduction. Existing `.codex-task-backup` files remain untouched but can no longer be created, verified, or restored by Codex Usage.

## 1.7.8 - 2026-08-23 - Project Role Column Matrix

- Replaced repeated per-project Root tasks and Subagents headings with one shared pair of role columns.
- Scaled each role column independently across projects while keeping exact token totals and project shares visible in every cell.
- Added stable equal-width role tracks, explicit zero-usage cells, and a stacked narrow layout with local role labels.

## 1.7.7 - 2026-08-22 - Sol Promotional Pricing

- Added GPT-5.6 Sol's promotional API rates from August 22, 2026: $4 input, $0.40 cached input, $5 cache write, and $20 output per million tokens.
- Applied the existing long-context contract to the reduced rates while preserving the original Sol rates for earlier usage.
- Left Codex credit estimates unchanged because OpenAI's announcement changes API pricing only.

## 1.7.6 - 2026-08-15 - Desktop Project Binding

- Added a guarded Desktop project-assignment preflight that blocks Import before file transfer when Desktop is running, the destination project is missing or ambiguous, or an assignment conflicts.
- Bound only certified, successfully registered tasks through an atomic global-state update with source rechecks, a sibling backup, post-write verification, and rollback.
- Kept VS Code-only imports on the supported app-server registration path and made unchanged re-imports repair missing Desktop assignments without rewriting task files or Codex SQLite.

## 1.7.5 - 2026-08-12 - Project Breakdown Layout

- Made every Project Breakdown row share one chart grid so gray tracks keep identical lengths regardless of value-label width.
- Moved Root tasks and Subagents headings onto the full shared track while keeping only the colored role bars proportional, preventing labels from being clipped for small projects or role shares.
- Anchored edge-segment tooltips inside the chart and added browser geometry checks for equal tracks and complete role labels.

## 1.7.4 - 2026-08-12 - Subagent Replay Accounting

- Stopped counting inherited parent-history replay as fresh usage in newer structured subagent fork files, removing duplicated totals and the resulting oversized `unknown` model bucket.
- Preserved replayed cumulative snapshots as the baseline for the subagent's actual token deltas, with model attribution beginning at the explicit inter-agent own-work boundary.
- Bumped the disposable parser cache to version 6 for one corrective rebuild and added full, append-checkpoint, and relevance-gate regression coverage plus live-corpus verification.

## 1.7.3 - 2026-08-09 - Marketplace Product Guide

- Reframed the Marketplace README for users who install the extension directly, removing source-build commands, CI gate details, and low-level parser internals.
- Replaced clone-relative VSIX commands with Visual Studio Marketplace installation steps and clarified that Task Transfer needs the user's own destination project folder, not the Codex Usage source repository.
- Kept observable cache behavior and troubleshooting guidance while adding regression coverage that preserves the boundary between product and contributor documentation.

## 1.7.2 - 2026-08-09 - Marketplace Workflow Guide

- Removed developer-specific corpus measurements from the public READMEs and kept the product explanation focused on general storage-amplification behavior.
- Added practical workflows for opening the report, analyzing one task tree, transferring tasks between computers, creating a verified backup, and preparing a rollover.
- Clarified recovery-ready versus salvage results, sensitive archive handling, and the current boundary that backups can be created and verified but not restored by the extension.

## 1.7.1 - 2026-08-08 - Documentation Accuracy

- Reframed live-corpus sizes as dated audit snapshots and recorded the 2026-08-08 follow-up without implying that either measurement is an expected installation size.
- Updated release documentation to cover the packaged report/cache, Task Transfer, verified-backup, and storage-analysis smoke gates on both supported platforms.
- Expanded privacy wording to disclose local SQLite caches and user-requested Task Transfer and verified-backup artifacts.

## 1.7.0 - 2026-08-08 - Storage Amplification And Rollover

- Added opt-in, selected-tree content analysis that measures repeated compacted-history bytes, inline-media markers, large descendants, and active-root history risk without invoking a model or scanning unrelated task trees.
- Rebuilt the disposable cache as schema 8 so the usage parser and explicit analyzer share guarded append-aware diagnostics; incomplete evidence remains visibly unknown and cannot produce positive amplification claims.
- Added **Analyze** and **Prepare Rollover** Task Storage actions plus `storage analyze` and `storage rollover` CLI commands. Rollover creates a new recovery-ready verified backup before emitting a text-only starter prompt and checklist, and never creates or deletes Codex tasks.
- Documented the observed repeated-history storage mechanism, conservative 1 GiB and 50% amplification thresholds, and the operational boundary between diagnosis, backup, and user-owned Codex task lifecycle changes.

## 1.6.1 - 2026-08-07 - Guardian Approval Ownership

- Recognized Codex guardian approval logs as structured descendants of their explicit immediate parent or owning task instead of reporting them as `Root missing` trees.
- Preserved guardian bytes, `codex-auto-review` subagent usage, and complete per-tree backups while keeping genuine missing parents and cycles visible.
- Added an atomic storage-metadata contract refresh that rereads only bounded metadata prefixes and leaves the schema 7 usage cache intact.
- Verified the fix against the live corpus: 409 false missing-root groups collapsed into their nine owning task families, leaving 32 task trees, zero missing roots, and unchanged physical-byte accounting.

## 1.6.0 - 2026-08-07 - Focused Dashboard Views

- Split the dashboard into top-level **Usage** and **Task Storage** views so date-filtered token analysis no longer shares one long page with current disk inventory and backup controls.
- Kept project filtering and theme shared while limiting the date-range context to Usage; both datasets are still generated together and view switching never reruns the CLI.
- Preserved the script-free CSP with local fragment navigation in standalone reports and allowlisted, session-remembered view commands in VS Code.
- Added independent desktop and narrow-layout visual gates plus focused Usage and Task Storage Marketplace screenshots.

## 1.5.0 - 2026-08-07 - Verified Task Backups

- Added read-only Task Storage backup for exactly one selected task tree, preserving every current physical JSONL, including structured descendants, active and archived copies, duplicates, and embedded side-chat content.
- Added strict `.codex-task-backup` format v1 with one-frame streaming PAX/zstd compression, canonical TAR termination, bounded session-index metadata, per-file and index SHA-256 values, final whole-archive verification, Maximum and Balanced presets, and atomic verify-before-publish safety.
- Added transient metadata retries and conservative salvage warnings for missing roots, relationship cycles, and unresolved corpus metadata, while distinguishing integrity-verified salvage from recovery-ready archives.
- Added `storage backup` and `storage verify` CLI commands plus the VS Code **Back Up Task** action and global command. Backup is local-only, compressed but not encrypted, and does not restore, delete, or free storage.

## 1.4.0 - 2026-08-07 - Task Storage Insights

- Added a read-only Task Storage dashboard section and expanded `codex-usage storage snapshot` to show current local bytes by user-visible root task tree, separating root files from nested structured descendants and including active plus archived files.
- Added project-filtered, date-independent storage reporting with logical-byte totals, complete task-tree inventory, 1 GiB root and 10 GiB tree visibility badges, and disposable cache schema 7 rebuild behavior.
- Documented the release-validation corpus of 196.08 GiB across 2,525 files, including 187.63 GiB of structured descendants, as the reason task-tree visibility precedes future backup or restore workflows; 1.4.0 does not delete, back up, restore, or compress data.
- Counted side-chat bytes and token usage under Root task because local evidence stores them in the parent JSONL without a durable discriminator; the report discloses this rather than inventing a third role.

## 1.3.0 - 2026-08-07 - Guarded Append Performance

- Added disposable cache schema 6 with guarded active-file parser checkpoints, tail-only ordinary append refreshes, and atomic fallback to the prior complete generation.
- Shared one buffered byte-oriented parser across full and append work, skipped JSON decoding for large known-irrelevant payloads after a bounded 4 KiB classification, and scheduled eight-file groups by unread bytes.
- Made Task Transfer metadata discovery stop after valid `session_meta`, compiled effective-dated pricing indexes, and valued each usage record once per report.
- Added timing-sidecar and VS Code Output diagnostics for full parses, append parses, append fallbacks, and source bytes read.

## 1.2.0 - 2026-08-04 - Project Role And Model Insights

- Split each Project Breakdown row into user-visible root-task and structured-subagent groups, then stacked both groups by model with shared Model Mix colors.
- Kept exact model details while grouping chart models after the largest seven into visual-only Other, with complete accessible tooltips and project role totals.
- Added explicit usage-role persistence through disposable cache schema 5 and rebuilt prior local caches once without rescanning source files for each report view.
- Added a reproducible Playwright-generated Marketplace screenshot and release review gate.

## 1.1.0 - 2026-08-03 - Incremental Usage Cache

- Rebuilt the disposable schema 4 cache once after upgrade, then refreshed only changed complete files in one pass for usage and transition candidates.
- Kept candidate verification and SQLite in the parent process, refreshed transitions per task, and used range-aware UTC-microsecond cache queries with parent identity lookup.
- Serialized dashboard refreshes to the latest request and added the `Loaded in X.X seconds` toolbar value without promising a fixed load time.

## 1.0.0 - 2026-08-03 - Stable Marketplace Release

- Promoted the Windows x64 and macOS Apple Silicon Marketplace packages from Preview to stable `1.0.0` after both native packaged Task Transfer gates passed.
- Prevented multiline Project Breakdown and Model Mix tooltips from being clipped at the top edge of horizontally scrollable charts.

## 0.1.42 - 2026-07-31 - Faster Root-Task Transfer And Usage Refresh

- Listed only active user-visible root tasks in Task Transfer while keeping subagent usage in dashboard totals.
- Deferred complete task hashing and conflict planning until after selection by replacing browse-time usage parsing and all-task hashing with metadata-only inventory.
- Skipped JSON decoding for irrelevant Codex events without changing usage totals, pricing, cache schema, or aggregation behavior.
- Refreshed invalidated usage caches with at most four whole-file worker processes and parent-only eight-file atomic commits, retaining complete prior generations on failure without adding offsets, range pruning, or schema changes.

## 0.1.41 - 2026-07-30 - Reduced Terra And Luna API Pricing

- Applied OpenAI's reduced Standard API rates for GPT-5.6 Terra and Luna from July 31, 2026.
- Preserved historical estimates by retaining the original rates for earlier usage.
- Kept GPT-5.6 Sol API pricing and Terra, Luna, and Sol Codex credit rates unchanged.

## 0.1.40 - 2026-07-29 - Two-Stage Task Transfer Selection

- Split Import and Export into a project-only screen followed by a task-only screen.
- Started every task screen with zero selected tasks and removed projects from the selected count.
- Added Back navigation that clears task choices before returning to project selection.
- Limited task search to the chosen project while preserving cross-project Review Transfer Status.

## 0.1.39 - 2026-07-29 - Stable Windows Task Selection

- Fixed the Windows Task Transfer picker so VS Code's delayed selection refresh cannot undo task choices or make the selected count oscillate.

## 0.1.38 - 2026-07-23 - Deterministic Task Import Registration

- Made Import and Export one-project operations with all eligible tasks initially selected, while keeping Review Transfer Status cross-project and read-only.
- Added defensive one-project enforcement in the Task Transfer CLI and core.
- Registered certified imported tasks deterministically through an installed official Codex `app-server` using targeted reads.
- Kept certified imported files safe after registration failures and made a repeated Import retry registration.
- Documented cached-task-list refresh guidance and the no-model, no-direct-SQLite, and no-private-registry-write guarantees.

## 0.1.37 - 2026-07-21 - GPT-5.6 Cache-Write Accounting

- Preserved Codex cache-write token counts through parsing, local caching, aggregation, JSON, CSV, terminal, and HTML reports.
- Applied the published GPT-5.6 cache-write API rates, including long-context multipliers, while keeping Codex credits on their published input rate.
- Rebuilt available cached source data and disclosed the evidence limitation for retained records whose source JSONL is missing.

## 0.1.36 - 2026-07-16 - Task Transfer UX And Storage V3

- Repositioned the former selected-task feature as deliberate Task Transfer with explicit Import Tasks, Export Tasks, and Review Transfer Status operations.
- Added a fresh, empty task selection for every operation, persisted only the transfer-folder path, and removed saved task selections and project mappings.
- Kept the persistent status bar usage-only while showing transfer progress and failures only during an active operation.
- Removed the desktop-app prerequisite; extension-only imports now resolve existing destination projects from active VS Code workspaces and validated local folders without writing private Codex state.
- Added automatic migration to the version-3 `tasks/` transfer layout while keeping local paired-baseline state at version 2.
- Added all-or-nothing directional preflight for Import and Export while retaining source files in the transfer folder.
- Aligned extension UI, README, Marketplace, and troubleshooting wording with Task Transfer, and documented Windows x64 and macOS Apple Silicon as the current package targets.

## 0.1.35 - 2026-07-14 - Manual Cross-Platform Task Transfer

- Replaced bidirectional Sync Now with explicit Pull Tasks and Push Tasks commands.
- Removed activation, focus, timer, and Codex-session file watcher sync triggers; transfers now run only on direct user action.
- Rebind pulled tasks to exactly one matching local Codex project through canonical Git identity, rewriting every matching-project local session metadata cwd while leaving remote JSONLs and unrelated records unchanged.
- Added paired local/remote sync baselines so intentional cross-platform cwd materialization is not mistaken for a conversation edit.
- Block missing or ambiguous project matches and locally modified foreign-path tasks instead of guessing, overwriting, or publishing unsafe state.
- Kept shared three-way planning, conflict preflight, atomic replacement, backups, and concurrent-change validation in both directions.

## 0.1.34 - 2026-07-14 - Exact Task Sync Selection

- Replaced project/conversation setup with one project-grouped task picker that stores exact selected task thread ids.
- Made project rows shortcuts for the tasks currently shown, so future tasks stay excluded until explicitly selected.
- Added remote-only task discovery so a task can be selected and pulled on another computer before it exists locally.
- Changed the selection schema to exact task thread ids; this invalidates previous project/conversation selectors, does not migrate them, and shows one-time **Setup required** after upgrading.
- Kept the version-2 remote layout unchanged, so no remote cleanup or republish is required. Version-1 folders still require a clean resync before use as version 2.
- Use task in user-facing sync copy while retaining thread id for the technical CLI and storage contract.
- macOS Apple Silicon packaged inventory/push/pull verified locally; Windows x64 is a CI-only release gate.
- Documented full-JSONL task sync as an option when built-in Codex handoff cannot complete for a very large task.

## 0.1.33 - 2026-07-14 - Flat Single-Process Sync

- Store each synced conversation as one flat JSONL file and run each sync in one process for lower startup and scan overhead.
- Continue the same long-running Codex conversation on another computer when normal handoff cannot complete because the conversation is too large.
- Require an explicit clean resync when upgrading a version-1 sync folder to the version-2 layout.
- Preserve append-only prefix fast-forwards, transactional conflict detection, and conflict backup safety.

## 0.1.32 - 2026-07-09 - GPT-5.6 Pricing Support

- Added effective-dated API-equivalent USD rates for GPT-5.6 Sol, Terra, and Luna from June 26, 2026, and Codex credit rates from July 9, 2026.
- Added request-level long-context API-only pricing for GPT-5.6 retained events over 272,000 input tokens: Sol $10/$1/$45, Terra $5/$0.50/$22.50, and Luna $2/$0.20/$9 per 1M uncached input, cached input, and output tokens. Codex credits remain flat.
- Mapped the official `gpt-5.6` alias to Sol while keeping unpublished variants such as `gpt-5.6-pro`, `gpt-5.6-mini`, and wrapper names unpriced through exact model matching.
- Documented that audited retained positive deltas matched request-level `last_token_usage`, so cumulative session totals cannot trigger long-context pricing.
- Documented that local Codex logs cannot identify the API's distinct cache-write token category.

## 0.1.31 - 2026-07-03 - macOS Apple Silicon Preview

- Added macOS Apple Silicon VS Code packaging with a bundled `codex-usage` executable.
- Added POSIX path evidence for automatic project transition detection on macOS.
- Kept Windows x64 packaging unchanged and documented Intel macOS as unsupported.

## 0.1.30 - 2026-06-24 - Future Model Pricing Hardening

- Hardened checked-in pricing lookup so unknown future model variants remain visible but unpriced instead of inheriting rates by substring.
- Documented the exact-model pricing guardrail for future model launches such as GPT-5.6.
- Refreshed the synthetic dashboard screenshot used in README and Marketplace materials.

## 0.1.29 - 2026-06-15 - Marketplace Preview Polish

- Updated VS Code extension metadata for Marketplace preview publishing under the `wenjun-mao` publisher id.
- Added extension-local changelog and support documents for Marketplace packaging.
- Documented the current Codex fast-mode accounting limitation: usage is counted from recorded tokens, but Codex does not expose a durable per-turn fast-mode marker in JSONL.

## 0.1.28 - 2026-06-12 - Compact Centered Heatmap

- Kept the hourly heatmap centered while restoring compact cell sizing so it no longer feels oversized.

## 0.1.27 - 2026-06-11 - Heatmap Legend Cleanup

- Removed the hourly heatmap legend line now that hover and keyboard-focus tooltips provide exact values.
- Centered the hourly heatmap and let its cells scale up on wider dashboards so it better matches surrounding chart/table widths.

## 0.1.26 - 2026-06-11 - Heatmap Palette Cleanup

- Removed the amber max bucket from the hourly heatmap so day and night modes use a calmer blue-only intensity scale.
- Updated the heatmap legend wording to describe the day/night scale accurately.

## 0.1.25 - 2026-06-11 - Sync Menu Controls

- Added explicit Sync menu actions for pause/resume, changing folder, changing projects, changing conversations, clearing sync setup, opening the sync folder, status, and manual sync.
- Updated the dashboard Sync control label to read like a menu control.

## 0.1.24 - 2026-05-30 - Fast Bar Chart Tooltips

- Replaced populated daily, project, and model SVG bars with script-free HTML/CSS bars so hover and keyboard-focus tooltips feel immediate across the dashboard.

## 0.1.23 - 2026-05-30 - Heatmap Tooltip Clipping Fix

- Reserved top-row hover space for the hourly heatmap so two-line tooltips are not clipped by the horizontal scroll container.

## 0.1.22 - 2026-05-30 - Heatmap Tooltip Polish

- Split hourly heatmap tooltip content into two lines: timestamp first, then cost and token usage.

## 0.1.21 - 2026-05-30 - Fast Heatmap Tooltips

- Replaced populated hourly heatmap SVG cells with a script-free HTML/CSS grid for immediate hover and keyboard-focus tooltips.
- Kept heatmap colors themeable across day, night, auto, and VS Code high-contrast modes.

## 0.1.20 - 2026-05-30 - Publishing Hardening

- Preserved previous cached usage when a changed session file hits a transient parse/read failure.
- Preserved retained missing-file usage across compatible cache schema rebuilds.
- Stored sync conversations with filesystem-safe folder names when thread ids contain slashes or invalid Windows path characters.
- Included archived Codex session folders in VS Code auto-sync watcher discovery.

## 0.1.19 - 2026-05-27 - Archive/Delete Resilient Usage

- Included Codex `archived_sessions` in usage totals.
- Preserved cached historical usage when previously parsed session files disappear locally.
- Added `codex-usage storage snapshot --json` to support before/after delete behavior experiments.
- Avoided double-counting session files moved between active and archived storage.
- Kept sync conversation selection limited to currently available local JSONL files.

## 0.1.18 - 2026-05-25 - Dashboard Action Strip Cleanup

- Collapsed dashboard sync actions into one Sync menu to reduce top-bar crowding.
- Removed project transition review from the dashboard action strip; it remains available through the Command Palette.
- Kept Sync Now, Sync Status, Configure Sync, and Open Sync Folder available from the Sync menu.

## 0.1.17 - 2026-05-25 - Persistent Usage Cache

- Added a persistent local SQLite usage cache for faster dashboard refreshes, project pickers, and sync setup.
- Added clearer first-run and refresh loading messages in the dashboard and status bar.
- Reduced sync setup churn by refreshing the dashboard once after folder/project/conversation selection finishes.

## 0.1.16 - 2026-05-25 - Three-Way Sync State

- Added local sync-state tracking so Codex conversation sync can distinguish local-only, remote-only, and true divergent changes.
- Added prefix-aware fast-forward handling for append-only Codex JSONL session files.
- Improved sync status summaries for local changes, remote changes, fast-forwards, and true conflicts.

## 0.1.15 - 2026-05-25 - Manual Sync UX

- Added `Sync Now` and `Sync Status` to the dashboard action strip.
- Clarified that Sync Enabled allows manual sync, while Auto Pull and Auto Push are optional automation.
- Updated sync setting descriptions to use conversation wording and explain manual-only mode.

## 0.1.14 - 2026-05-25 - Sync Scheduler Hardening

- Added single-flight sync scheduling so background triggers do not start overlapping sync runs.
- Added calmer auto sync timing with focus cooldown, file-change debounce, and failure backoff.
- Moved normal background sync feedback into the VS Code status bar and output channel.
- Kept visible notifications for manual sync and action-needed failures such as conflicts.
- Clearing Sync Off now cancels pending file-change sync timers and prevents new auto sync runs.

## 0.1.13 - 2026-05-25 - Sync Import Stability

- Fixed sync import so already-identical local session files are not rewritten, avoiding Windows access-denied errors when Codex still has a session file open.

## 0.1.12 - 2026-05-25 - Project-First Sync UX

- Changed the sync setup flow to select projects before conversations.
- Renamed user-facing sync thread wording to conversations while keeping thread ids as the internal sync unit.
- Added an all-conversations-in-selected-projects mode that resolves current conversations at sync time.
- Added rough per-project sync-size estimates based on local session JSONL files plus metadata overhead.
- Added a direct `Codex Usage: Select Sync Projects` command.

## 0.1.11 - 2026-05-24 - Sync Setup UX

- Added `Codex Usage: Configure Sync` with a VS Code folder picker for the sync folder and the existing thread picker for selected threads.
- Removed raw `sync.dir` and `sync.threadIds` settings from the Settings UI.
- Moved sync folder and thread selections into local VS Code extension state, with migration from previous beta settings.
- Added a dashboard sync control showing whether sync is off, missing a folder, missing threads, or configured.

## 0.1.10 - 2026-05-24 - Version Label

- Added the installed extension version to the dashboard action strip so beta installs are easier to confirm.

## 0.1.9 - 2026-05-24 - Settings Cleanup

- Removed manual VS Code settings for project aliases, project keys, sessions directory, and subscription comparison.
- Removed CLI/config support for manual sessions-dir, subscription, and project-alias overrides.
- Moved selected dashboard projects into VS Code extension state while keeping `--project-key` filtering for reports, threads, and sync.
- Simplified discovery to automatic Codex home locations and made `CODEX_HOME` authoritative for testing and sync import.
- Kept automatic project identity and transition detection as the default path for renamed or moved repositories.

## 0.1.8 - 2026-05-24 - Auto Project Transitions

- Added automatic high-confidence project splits when timestamped Codex events reference verified local repository paths.
- Added `codex-usage transitions suggest --json` for reviewing inferred transitions from the CLI.
- Added `Codex Usage: Review Project Transitions` and the `codexUsage.projectTransitions.autoDetect` setting.
- Added report transition metadata for source, target, effective timestamp, and confidence; detailed evidence and thread ids are available through the CLI and VS Code review command.
- Updated sync and thread project awareness so selected threads use transition-aware project identity.

## 0.1.6 - 2026-05-24 - Experimental Selected-Thread Sync

- Added dependency-light Codex thread sync commands backed by a user-provided local sync folder.
- Added VS Code commands and settings for selecting threads, syncing now, checking status, and opening the sync folder.
- Syncs selected session JSONL files and matching session index entries only; SQLite memory rows are detected but not synced.

## 0.1.5 - 2026-05-21 - Canonical Project Identity

- Resolve missing project git metadata from local `.git/config` when `cwd` points inside a repository.
- Canonicalize common HTTPS and SSH git remotes so path-only fork sessions combine with repo-keyed sessions.
- Keep path aliases for project filtering compatibility with previously saved selections.

## 0.1.4 - 2026-05-21 - Fork Accounting Fix

- Fixed forked Codex session files so imported parent transcript replay is not counted as fresh usage.
- Treat the first root token snapshot in a forked session file as inherited context when no prior baseline exists.

## 0.1.3 - 2026-05-19 - Theme Beta

- Added auto, day, and night dashboard themes.
- Added `Codex Usage: Select Theme` and the `codexUsage.theme` setting.
- Added CLI report theme output with `codex-usage report --theme auto|day|night`.
- Updated report charts and heatmap cells to use themeable CSS tokens.

## 0.1.0 - 2026-05-19 - Windows Beta

- Added a self-contained Windows x64 VSIX with a bundled `codex-usage.exe`.
- Added a VS Code dashboard command surface for opening, refreshing, range switching, project filtering, and settings.
- Added local HTML/SVG dashboard reporting with daily cost trend, hourly heatmap, project breakdown, model mix, and exact tables.
- Added effective-dated checked-in pricing so each usage event is priced with the rate active at that timestamp.
- Added Codex credit estimates alongside API-equivalent USD.
- Added local session discovery for `%USERPROFILE%\.codex\sessions`, `CODEX_HOME/sessions`, and explicit session overrides.
- Added MIT licensing and beta publishing metadata.

## Notes

- The initial 0.1.0 beta package targeted Windows x64 for local testing.
- The extension does not upload session logs, does not include telemetry, and does not fetch live pricing.
