# Changelog

## Unreleased

- 2026-07-23: Made Import and Export one-project operations with all eligible tasks initially selected, while keeping Review Transfer Status cross-project and read-only.
- 2026-07-23: Added defensive one-project enforcement in the Task Transfer CLI and core.
- 2026-07-23: Registered certified imported tasks deterministically through an installed official Codex `app-server` using targeted reads.
- 2026-07-23: Kept certified imported files safe after registration failures and made a repeated Import retry registration.
- 2026-07-23: Documented cached-task-list refresh guidance and the no-model, no-direct-SQLite, and no-private-registry-write guarantees.

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
