# Changelog

## Unreleased

## 2.2.0 - 2026-09-04 - Comparative Usage Charts

- Ordered model charts and details by GPT generation and product tier, and assigned stable, more distinguishable colors to current named models.
- Added Root task and Subagent API-equivalent dollar totals plus a Tokens/API cost scale switch to Project Breakdown.
- Made Model Mix use one shared chart grid so every neutral bar track has identical geometry.

## 2.1.1 - 2026-09-04 - GPT-6 Astra Pricing

- Added exact `gpt-6-astra` API-equivalent and standard Codex credit pricing from the first verified availability date, including cache-write and long-context API rates.
- Updated the GPT-5.6 Sol, Terra, and Luna standard credit schedules from the newly published rate table while preserving earlier usage at its historical rates.
- Kept plan-specific and Fast-mode multipliers out of estimates because local task records do not identify those billing contexts reliably.

## 2.1.0 - 2026-09-04 - Unified Dashboard UI

- Renamed the visible collection action to **Capture Usage** and replaced the ambiguous toolbar **Refresh** action with a view-specific reload icon, while preserving existing command IDs.
- Made Usage and Task Storage share explicit Day, Night, and Auto themes, one compact metric-strip treatment, and consistent headers, notices, tables, spacing, and responsive behavior.
- Added last-capture and source metadata to the toolbar, hid the Usage range outside Usage, and invalidated stale rendered HTML through a dedicated renderer revision.

## 2.0.1 - 2026-09-04 - Live Baseline Progress

- Refreshed an open Usage dashboard automatically when the collector advances the ledger or baseline coverage, replacing stale partial-baseline notices without requiring **Refresh**.
- Kept the 30-second automatic refresh quiet and ledger-only, and retained the last good dashboard if a background refresh fails.

## 2.0.0 - 2026-09-04 - Standalone Durable Ledger

- Rebuilt the extension as standalone macOS Apple Silicon and Windows x64 packages, each bundling its matching parent-bound local collector; the native app, Python, `uv`, and a source checkout are not required.
- Added collector setup, 15-minute default or custom scheduling, Manual Only, Capture Now, Codex-home selection, project-transition settings, and legacy-cache migration directly inside VS Code.
- Added persistent ledger-backed Usage, Task Storage, Task Transfer, project-transition review, and collector status through the authenticated loopback client.
- Kept scheduled capture alive while VS Code is open even when the dashboard is closed, with the optional unsigned native preview available only for capture that must continue outside VS Code.
- Split Marketplace packaging by platform and made publication depend on both VSIX jobs while native app builds remain separate unsigned CI previews.
- Removed the public Python CLI; the extension communicates only with the bundled or already-running authenticated collector.
- Added guarded onboarding migration for legacy schema-8 caches, including retained deleted-task history and an explicit source choice for genuinely divergent task records.

## 1.8.2 - 2026-08-29 - Release Gate Hardening

- Refactored internal cache result validation so native release-tag builds satisfy the focused-module guard on detached Git checkouts.
- Includes the multi-window cache coordination and archive-relocation recovery from 1.8.1 with no dashboard or workflow changes.

## 1.8.1 - 2026-08-29 - Cross-Process Cache Recovery

- Coordinated reports from separate VS Code windows through one shared cache lock instead of allowing duplicate append commits.
- Captured a fresh source inventory after any lock wait and rejected stale append checkpoints atomically before they can create duplicate rows.
- Kept reports working when Codex archives a task during direct fallback by finding and parsing the same task at its new path exactly once.

## 1.8.0 - 2026-08-27 - Codex-Owned Task Lifecycle

- Removed **Back Up Task** and **Prepare Task Rollover**, leaving **Analyze** as the only Task Storage row operation.
- Simplified the Task Storage protocol to schema 4 and removed backup- and rollover-readiness fields without changing inventory or amplification diagnostics.
- Documented manual **Fork in Codex** for continuity and a fresh task with a concise handoff for meaningful inherited-context reduction.
- Existing `.codex-task-backup` files remain untouched but can no longer be created, verified, or restored by Codex Usage.

## 1.7.8 - 2026-08-23 - Project Role Column Matrix

- Replaced repeated Root tasks and Subagents labels with one shared pair of comparison columns.
- Kept exact role totals and project shares visible while making smaller subagent differences easier to compare.
- Stacked the two labeled role cells cleanly on narrow dashboards and retained model colors and tooltips.

## 1.7.7 - 2026-08-22 - Sol Promotional Pricing

- Updated GPT-5.6 Sol API-equivalent estimates to the promotional rates announced for August 22, 2026.
- Kept earlier Sol usage on its original rates and applied the reduced rates to short- and long-context usage from the exact effective-date boundary.
- Kept Codex credit estimates unchanged because no new credit rate was announced.

## 1.7.6 - 2026-08-15 - Desktop Project Binding

- Added a guarded Desktop project-assignment preflight that blocks Import before file transfer when Desktop is running, the destination project is missing or ambiguous, or an assignment conflicts.
- Bound only certified, successfully registered tasks through an atomic global-state update with source rechecks, a sibling backup, post-write verification, and rollback.
- Kept VS Code-only imports on the supported app-server registration path and made unchanged re-imports repair missing Desktop assignments without rewriting task files or Codex SQLite.

## 1.7.5 - 2026-08-12 - Project Breakdown Layout

- Kept every Project Breakdown background track the same length across projects.
- Prevented Root tasks and Subagents headings from being cut off when a project or role has a small token share.
- Kept model tooltips inside the visible chart at both role boundaries.

## 1.7.4 - 2026-08-12 - Subagent Replay Accounting

- Corrected Usage reports that counted inherited parent-history replay inside newer structured subagent forks, which inflated totals and appeared under `unknown`.
- Kept the inherited cumulative history only as a token baseline, then attributed the subagent's actual work to the model recorded at its inter-agent boundary.
- Rebuilds the disposable parser cache once after upgrade; subsequent refreshes retain guarded append-aware performance.

## 1.7.3 - 2026-08-09 - Marketplace Product Guide

- Reframed the Marketplace README around installing and using the extension without cloning its source repository.
- Replaced repository-relative VSIX commands with Marketplace installation steps, removed development and CI internals, and rewrote cache behavior in user-facing terms.
- Clarified that Task Transfer requires the user's own destination project folder and added regression coverage to keep contributor instructions out of Marketplace copy.

## 1.7.2 - 2026-08-09 - Marketplace Workflow Guide

- Removed developer-specific corpus measurements from the Marketplace README and replaced them with a general explanation of storage amplification.
- Added a Quick Start, command-purpose table, and step-by-step Task Transfer, storage analysis, backup, and rollover workflows.
- Clarified recovery-ready versus salvage results, sensitive archive handling, and that the current extension verifies backups but cannot restore them.

## 1.7.1 - 2026-08-08 - Documentation Accuracy

- Clarified that corpus-size measurements are dated audit snapshots rather than expected installation sizes.
- Documented the complete native packaged release gates, including report/cache, Task Transfer, verified-backup, and storage-analysis smoke checks.
- Disclosed disposable SQLite caches and user-requested Task Transfer and verified-backup outputs in Marketplace privacy copy.

## 1.7.0 - 2026-08-08 - Storage Amplification And Rollover

- Added per-tree **Analyze** actions for repeated compacted-history bytes, inline-media markers, large descendants, and active-root history risk, with cancellable selected-tree progress and no model calls.
- Added conservative complete, partial, and not-analyzed states so the dashboard never presents missing evidence as a negative amplification result.
- Added **Prepare Rollover** for eligible recovery-ready trees. It creates a new verified backup, copies a text-only starter prompt, and provides a checklist without creating, archiving, restoring, or deleting Codex tasks.
- Upgraded the local disposable cache to schema 8 so ordinary usage parsing and explicit storage analysis reuse the same guarded append-aware evidence.

## 1.6.1 - 2026-08-07 - Guardian Approval Ownership

- Folded Codex guardian approval logs into their explicit owning task trees instead of listing them as `Root missing`, while retaining `codex-auto-review` under Subagents in Usage.
- Included guardian files in verified backups of their owning task and preserved genuine missing-parent and cycle diagnostics.
- Refreshed the storage ownership metadata once through bounded prefix reads without discarding or reparsing the schema 7 usage cache.
- Validated the corrected grouping on the live corpus: 409 false missing roots became zero and physical-byte accounting remained complete.

## 1.6.0 - 2026-08-07 - Focused Dashboard Views

- Split the dashboard into top-level **Usage** and **Task Storage** views, with Usage remaining the default and Task Storage retaining its full inventory and per-tree backup actions.
- Kept project and theme controls shared, hid the usage-only date control from Task Storage, and made view switching instant without regenerating the report.
- Remembered the selected view for the current extension session and reapplied it safely when an in-flight dashboard refresh publishes.
- Kept the webview script-free under strict CSP and added focused Usage and Task Storage Marketplace screenshots.

## 1.5.0 - 2026-08-07 - Verified Task Backups

- Added a **Back Up** action to each Task Storage row and the global **Codex Usage: Back Up Task** command, with project-first selection of exactly one task tree.
- Added strict `.codex-task-backup` format v1 using one-frame streaming PAX/zstd compression, canonical TAR termination, bounded session-index metadata, per-file and index hashes, whole-archive verification, and atomic verify-before-publish safety.
- Preserved structured descendants, active and archived copies, duplicates, and embedded side-chat content; transient metadata reads retry, while missing roots, relationship cycles, and unresolved corpus metadata produce warning-bearing salvage archives that are not recovery-ready.
- Added Maximum (zstd 19) and Balanced (zstd 9) presets plus the local-only, compressed-but-not-encrypted privacy disclosure. Backup does not restore, delete, or free storage.

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

- Repositioned the feature as deliberate Task Transfer with explicit Import Tasks, Export Tasks, and Review Transfer Status operations.
- Added a fresh, empty selection for every operation, persisted only the transfer-folder path, and removed saved task selections and project mappings.
- Kept persistent status usage-only while limiting transfer progress and failure text to active operations.
- Added extension-only destination project resolution through active VS Code workspaces and validated local folders without requiring desktop-app state.
- Added automatic migration to the version-3 `tasks/` transfer layout while retaining transfer files and local version-2 paired baselines.
- Added all-or-nothing directional preflight for Import and Export so a conflict, issue, or opposite-direction action blocks the selected batch.
- Aligned extension UI, Marketplace, README, and troubleshooting wording, and documented Windows x64 and macOS Apple Silicon as the current package targets; Linux packaging remains follow-up work.

## 0.1.35 - 2026-07-14 - Manual Cross-Platform Task Transfer

- Replaced Sync Now with separate Pull Tasks and Push Tasks commands.
- Removed automatic activation, focus, timer, and file-change sync triggers.
- Added safe canonical project matching and selective multi-record cwd rebinding for tasks pulled between Windows and macOS.
- Preserve remote task JSONLs while tracking intentional local/remote hash differences with paired baselines.
- Report tasks that still need the opposite direction after a successful manual transfer.

## 0.1.34 - 2026-07-14 - Exact Task Sync Selection

- Replaced project/conversation setup with one project-grouped task picker that stores exact selected task thread ids.
- Made project rows shortcuts for the tasks currently shown, so future tasks stay excluded until explicitly selected.
- Added remote-only task discovery so a task can be selected and pulled on another computer before it exists locally.
- Changed the selection schema to exact task thread ids; this invalidates previous project/conversation selectors, does not migrate them, and shows one-time **Setup required** after upgrading.
- Kept the version-2 remote layout unchanged, so no remote cleanup or republish is required. Version-1 folders still require a clean resync before use as version 2.
- Use task in user-facing sync copy while retaining thread id for the technical CLI and storage contract.
- macOS Apple Silicon packaged inventory/push/pull verified locally; Windows x64 is a CI-only release gate.
- Documented full-JSONL task sync as an option when built-in Codex handoff cannot complete for a very large task.

## 0.1.33 - 2026-07-14

- Store each synced conversation as one flat JSONL file and run each sync in one process for lower startup and scan overhead.
- Continue the same long-running Codex conversation on another computer when normal handoff cannot complete because the conversation is too large.
- Require an explicit clean resync when upgrading a version-1 sync folder to the version-2 layout.
- Preserve append-only prefix fast-forwards, transactional conflict detection, and conflict backup safety.

## 0.1.32 - 2026-07-09

- Added API-equivalent USD rates for GPT-5.6 Sol, Terra, and Luna from June 26, 2026, plus Codex credit estimates from July 9, 2026.
- Added GPT-5.6 request-level long-context API-only pricing for retained events over 272,000 input tokens: Sol $10/$1/$45, Terra $5/$0.50/$22.50, and Luna $2/$0.20/$9 per 1M uncached input, cached input, and output tokens. Codex credits remain flat.
- Mapped the official `gpt-5.6` alias to Sol while preserving partial-pricing warnings for unpublished variants.
- Documented that retained positive deltas are priced as request-level events, so cumulative session totals cannot trigger long-context pricing.
- Documented the local cache-write accounting limitation.

## 0.1.31 - 2026-07-03

- Added macOS Apple Silicon preview packaging with a bundled `codex-usage` executable.
- Kept Windows x64 packaging unchanged.

## 0.1.30 - 2026-06-24

- Hardened future-model pricing behavior so newly released Codex models show usage immediately while cost estimates stay partial until official rates are checked in.
- Refreshed the synthetic dashboard screenshot.

## 0.1.29 - 2026-06-15 - Marketplace Preview

- Prepared the extension package for Windows x64 Marketplace preview publishing.
- Added Marketplace support documentation.
- Kept Codex usage accounting local-only, with checked-in pricing and no telemetry.
- Documented that Codex fast mode is counted through recorded token usage but cannot currently be labeled separately because Codex does not write a per-turn fast-mode marker to session JSONL.

## 0.1.28 - 2026-06-12 - Compact Centered Heatmap

- Kept the hourly heatmap centered while restoring compact cell sizing so it no longer feels oversized.

## 0.1.27 - 2026-06-11 - Heatmap Legend Cleanup

- Removed the hourly heatmap legend line now that hover and keyboard-focus tooltips provide exact values.

## 0.1.26 - 2026-06-11 - Heatmap Palette Cleanup

- Removed the amber max bucket from the hourly heatmap so day and night modes use a calmer blue-only intensity scale.
