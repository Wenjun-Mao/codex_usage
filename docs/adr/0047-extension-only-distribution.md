# ADR 0047: Extension-Only Distribution

## Status

Accepted for version 2.9.0 on 2026-09-25. Supersedes the active native ownership
and distribution/lifecycle portions of ADRs 0034 and 0036.

## Context

The VS Code Companion already includes a platform-specific collector and the
complete Usage, Task Storage, and Task Transfer experience. Maintaining the
second Tauri frontend, Rust host, preview installers, fixtures, and release
surface adds work without serving the primary VS Code use case. A previously
registered native background collector may still own the shared ledger, so
removing service compatibility abruptly could strand an existing user.

## Decision

Ship only macOS Apple Silicon and Windows x64 VSIX packages. Build PyInstaller
collectors in a neutral build location and put exactly one matching executable
in each VSIX. The extension and shared Python report renderer are the visual
authority, continuing ADR 0037's interaction and theme contract. Keep the
existing local SQLite ledger and authenticated single-writer collector API.

Run scheduled capture while VS Code is open, including when its dashboard is
closed. The bundled collector is parent-bound and exits with the final owning
extension host. The extension does not install a replacement unattended daemon.
Missed quota observations while VS Code is closed are a coverage gap that later
capture cannot always fill.

Provide a Command Palette handoff for the known legacy Codex Usage LaunchAgent
or Windows Scheduled Task. Detection and removal require explicit confirmation;
normal activation and updates never unregister a service. Handoff retains the
same `CODEX_HOME` and ledger, waits for the old writer to exit, then starts the
bundled collector. Failure stays visible and recoverable without data reset.

## Rejected Alternatives

- Freeze native preview builds while retaining source and release jobs: this
  keeps two product surfaces and their maintenance burden.
- Remove all legacy service handling: an active registered collector could keep
  ledger ownership or be orphaned after native app removal.
- Install a new extension-managed OS daemon: this changes the intended VS Code
  lifecycle and creates another persistent service contract.

## Consequences And Guardrails

The product no longer captures quota snapshots while all VS Code extension hosts
are closed. Documentation and report copy must avoid claiming continuous quota
coverage across that gap. Historical ledger data and task files remain intact.

CI validates Python, Ruff, extension tests, packaged collector smoke checks,
archive contents, and extension visual gates on supported platforms. Marketplace
publication waits for both VSIX jobs. Native DMG/NSIS, Tauri, Cargo, and signing
checks leave the release workflow. Handoff acceptance uses disposable data and
known-service registrations; no release test touches a live ledger or service.
