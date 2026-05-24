# Changelog

## 0.1.10 - Version Label

- Added the installed extension version to the dashboard action strip so beta installs are easier to confirm.

## 0.1.9 - Settings Cleanup

- Removed manual VS Code settings for project aliases, project keys, sessions directory, and subscription comparison.
- Removed CLI/config support for manual sessions-dir, subscription, and project-alias overrides.
- Moved selected dashboard projects into VS Code extension state while keeping `--project-key` filtering for reports, threads, and sync.
- Simplified discovery to automatic Codex home locations and made `CODEX_HOME` authoritative for testing and sync import.
- Kept automatic project identity and transition detection as the default path for renamed or moved repositories.

## 0.1.8 - Auto Project Transitions

- Added automatic high-confidence project splits when timestamped Codex events reference verified local repository paths.
- Added `codex-usage transitions suggest --json` for reviewing inferred transitions from the CLI.
- Added `Codex Usage: Review Project Transitions` and the `codexUsage.projectTransitions.autoDetect` setting.
- Added report transition metadata for source, target, effective timestamp, and confidence; detailed evidence and thread ids are available through the CLI and VS Code review command.
- Updated sync and thread project awareness so selected threads use transition-aware project identity.

## 0.1.6 - Experimental Selected-Thread Sync

- Added dependency-light Codex thread sync commands backed by a user-provided local sync folder.
- Added VS Code commands and settings for selecting threads, syncing now, checking status, and opening the sync folder.
- Syncs selected session JSONL files and matching session index entries only; SQLite memory rows are detected but not synced.

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
