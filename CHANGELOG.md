# Changelog

## 0.1.5 - Canonical Project Identity

- Resolve missing project git metadata from local `.git/config` when `cwd` points inside a repository.
- Canonicalize common HTTPS and SSH git remotes so path-only fork sessions combine with repo-keyed sessions.
- Keep path aliases for project filtering compatibility with previously saved selections.

## 0.1.4 - Fork Accounting Fix

- Fixed forked Codex session files so imported parent transcript replay is not counted as fresh usage.
- Treat the first root token snapshot in a forked session file as inherited context when no prior baseline exists.

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
