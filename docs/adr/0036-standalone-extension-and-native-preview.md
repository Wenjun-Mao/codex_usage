# ADR 0036: Standalone Extension And Native Preview

## Status

Accepted for version 2.0.0 on 2026-09-04

## Context

ADR 0034 made the native application the required runtime owner and limited the
VS Code package to a thin universal client. That would force users who primarily
work in VS Code to install a second product. Its signed-only publication plan
also depends on paid Apple Developer and eligible Azure Artifact Signing
accounts that are not available for this project.

The durable ledger and single-writer collector remain useful in both products.
The distribution boundary should let either UI use that same architecture
without creating separate parsers, ledgers, or accounting behavior.

## Decision

Publish separate macOS Apple Silicon and Windows x64 VSIX packages. Each package
bundles the matching Python collector executable and can initialize its own
`CODEX_HOME`, migrate legacy data, capture usage, and run every dashboard,
storage, and Task Transfer workflow without the native application. Its
collector is parent-bound and stops when the final owning VS Code extension
host exits.

Keep the Tauri application as an optional UI and background-service owner. A
healthy collector discovered through the owner-local descriptor is shared; the
ledger remains single-writer regardless of which client starts first. Only an
explicit native-app consent flow may install a LaunchAgent or Scheduled Task.

Marketplace publication depends on both platform VSIX builds, not on native
packaging. CI also builds unsigned macOS DMG and Windows NSIS preview artifacts,
with SHA-256 integrity metadata, for evaluation. These previews are not
notarized, Authenticode signed, uploaded to GitHub Releases, or served through a
Tauri update channel. They may trigger operating-system warnings. No Apple,
Azure, or Tauri signing secret is required by the 2.0.0 release workflow.

## Rejected Alternatives

- Requiring the native app preserves one installation owner but recreates the
  original editor-friction problem for users who only want the VS Code UI.
- Keeping one universal VSIX cannot carry the platform-specific collector
  executable without shipping both binaries to every user.
- Returning to an extension-private cache would create divergent histories and
  competing writers whenever the native app is also used.
- Publishing unsigned native installers as stable GitHub Releases would imply a
  support and update contract that the current preview channel does not provide.

## Consequences And Guardrails

The Marketplace extension is a complete product on supported platforms. Its
scheduled capture runs only while VS Code is open, so users who need unattended
capture can opt into the native preview's background collector. Both clients
must use the same authenticated API and durable ledger; neither may write
SQLite directly or fall back to a private parser cache.

Release tests must prove that both VSIX packages contain exactly one matching
collector, work without the native app, and publish only after both package jobs
succeed. Native preview jobs remain non-publishing validation and must emit
integrity metadata without paid-signing dependencies. Public documentation must
distinguish the stable Marketplace extension from the unsigned native preview.
