# Support

Codex Usage Dashboard is a Windows x64 and macOS Apple Silicon preview extension. Please use GitHub Issues for bug reports, feature requests, and preview feedback:

https://github.com/Wenjun-Mao/codex_usage/issues

When reporting a problem, include:

- VS Code version.
- Codex Usage Dashboard version.
- Operating system and CPU architecture, for example Windows x64 or macOS Apple Silicon.
- Whether Codex session files exist under `CODEX_HOME/sessions`, `CODEX_HOME/archived_sessions`, `%USERPROFILE%\.codex\sessions`, `%USERPROFILE%\.codex\archived_sessions`, `~/.codex/sessions`, or `~/.codex/archived_sessions`.
- The error text from the `Codex Usage` output channel, with private paths or project names redacted if needed.
- Whether the issue happens after running `Codex Usage: Refresh Dashboard`.

Please do not attach raw Codex JSONL session logs publicly. They can contain local paths, repository URLs, prompts, and other private project context.

For sync issues, include whether sync is manual-only or automatic, which sync folder provider you use, and whether `Codex Usage: Sync Status` reports conflicts.
