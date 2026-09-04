# Support

Use [GitHub Issues](https://github.com/Wenjun-Mao/codex_usage/issues) for Codex
Usage bug reports and feature requests.

Include:

- Installation surface and version: standalone VS Code extension or native app
  preview.
- Operating system and architecture: macOS Apple Silicon or Windows x64.
- Whether background capture is enabled and the configured interval.
- Last capture, pending files/bytes, baseline coverage, and stale-source state.
- The affected workflow: Usage, Task Storage, Task Transfer, onboarding, or
  background capture.
- Relevant redacted collector/app output and reproducible steps.

For Task Transfer, also include the operation, transfer-folder provider, both
computers' operating systems, whether Codex Desktop was fully closed for Import,
and whether the destination checkout already existed.

Never attach raw Codex JSONLs, the usage ledger, `agent.json`, Desktop state,
Task Transfer content, or unredacted logs publicly. They may contain prompts,
responses, local paths, repository URLs, task identifiers, and credentials.
