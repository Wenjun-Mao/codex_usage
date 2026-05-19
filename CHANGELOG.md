# Changelog

## 0.1.3 - Theme Beta

- Added auto, day, and night dashboard themes.
- Added `Codex Usage: Select Theme` and the `codexUsage.theme` setting.
- Added CLI report theme output with `codex-usage report --theme auto|day|night`.
- Updated report charts and heatmap cells to use themeable CSS tokens.

## 0.1.0 - Windows Beta

- Added a self-contained Windows x64 VSIX with a bundled `codex-usage.exe`.
- Added a VS Code dashboard command surface for opening, refreshing, range switching, project filtering, and settings.
- Added local HTML/SVG dashboard reporting with daily cost trend, hourly heatmap, project breakdown, model mix, and exact tables.
- Added effective-dated checked-in pricing so each usage event is priced with the rate active at that timestamp.
- Added Codex credit estimates alongside API-equivalent USD.
- Added local session discovery for `%USERPROFILE%\.codex\sessions`, `CODEX_HOME/sessions`, and explicit session overrides.
- Added MIT licensing and beta publishing metadata.

## Notes

- This is a Windows x64 beta package for local testing.
- The extension does not upload session logs, does not include telemetry, and does not fetch live pricing.
