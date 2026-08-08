# Changelog

## Unreleased

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
