# Support

Codex Usage Dashboard supports Windows x64 and macOS Apple Silicon. Please use GitHub Issues for bug reports, feature requests, and support:

https://github.com/Wenjun-Mao/codex_usage/issues

When reporting a problem, include:

- VS Code version.
- Codex Usage Dashboard version.
- Operating system and CPU architecture, for example Windows x64 or macOS Apple Silicon.
- Whether Codex session files exist under `CODEX_HOME/sessions`, `CODEX_HOME/archived_sessions`, `%USERPROFILE%\.codex\sessions`, `%USERPROFILE%\.codex\archived_sessions`, `~/.codex/sessions`, or `~/.codex/archived_sessions`.
- The error text from the `Codex Usage` output channel, with private paths or project names redacted if needed.
- Whether the issue happens after running `Codex Usage: Refresh Dashboard`.

Please do not attach raw Codex JSONL session logs publicly. They can contain local paths, repository URLs, prompts, and other private project context.

For Task Transfer issues, include the operation you ran, the transfer-folder provider, both computers' operating systems, and the relevant `Codex Usage` output-channel error.
