# Changelog

## Unreleased

- Repositioned the feature as deliberate Task Transfer with explicit Import Tasks, Export Tasks, and Review Transfer Status operations.
- Added fresh per-operation selection, extension-only destination mapping, automatic version-3 folder migration, and retained transfer files.
- Documented Windows x64 and macOS Apple Silicon as the current package targets; Linux packaging remains follow-up work.

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
