# Support

Use [GitHub Issues](https://github.com/Wenjun-Mao/codex_usage/issues) for Codex
Usage bug reports and feature requests.

Include:

- Installed VS Code Companion version and whether a legacy background service
  remains registered.
- Operating system and architecture: macOS Apple Silicon or Windows x64.
- Configured capture interval and whether VS Code remained open.
- Last capture, pending files/bytes, baseline coverage, and stale-source state.
- Plan Allowance reading label and local observation time if the displayed
  percentage differs from the Codex app.
- The affected workflow: Usage, Task Storage, onboarding, or
  background capture.
- Relevant redacted collector/extension output and reproducible steps.

Task Transfer was retired in 2.13.0. Existing chats and transfer files remain
untouched. For ongoing chat mobility use Codex native handoff between connected
hosts with matching saved Git projects; offline recovery is not covered.

Never attach raw Codex JSONLs, the usage ledger, `agent.json`, Desktop state,
Task Transfer content, or unredacted logs publicly. They may contain prompts,
responses, local paths, repository URLs, task identifiers, and credentials.
