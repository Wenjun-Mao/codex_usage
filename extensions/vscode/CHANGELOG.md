# Changelog

## 0.1.32

- Added API-equivalent USD and Codex credit estimates for GPT-5.6 Sol, Terra, and Luna.
- Preserved partial-pricing warnings for generic or unpublished GPT-5.6 variants.
- Documented the local cache-write accounting limitation.

## 0.1.31

- Added macOS Apple Silicon preview packaging with a bundled `codex-usage` executable.
- Kept Windows x64 packaging unchanged.

## 0.1.30

- Hardened future-model pricing behavior so newly released Codex models show usage immediately while cost estimates stay partial until official rates are checked in.
- Refreshed the synthetic dashboard screenshot.

## 0.1.29 - Marketplace Preview

- Prepared the extension package for Windows x64 Marketplace preview publishing.
- Added Marketplace support documentation.
- Kept Codex usage accounting local-only, with checked-in pricing and no telemetry.
- Documented that Codex fast mode is counted through recorded token usage but cannot currently be labeled separately because Codex does not write a per-turn fast-mode marker to session JSONL.

## 0.1.28 - Compact Centered Heatmap

- Kept the hourly heatmap centered while restoring compact cell sizing so it no longer feels oversized.

## 0.1.27 - Heatmap Legend Cleanup

- Removed the hourly heatmap legend line now that hover and keyboard-focus tooltips provide exact values.

## 0.1.26 - Heatmap Palette Cleanup

- Removed the amber max bucket from the hourly heatmap so day and night modes use a calmer blue-only intensity scale.
