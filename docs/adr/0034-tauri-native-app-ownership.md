# ADR 0034: Tauri Native App Ownership

## Status

Partially superseded by ADR 0036 for version 2.0.0 on 2026-09-04

## Context

Users increasingly opened VS Code only to reach Codex Usage. Persistent capture
also needs an installation and lifecycle owner outside any editor. The product
must still reuse the mature Python parser, Task Transfer safeguards, and local
reporting logic while shipping a focused desktop experience on macOS Apple
Silicon and Windows x64.

## Decision

Use Tauri 2 with vanilla TypeScript and Vite for the native application. Keep
Rust as a narrow trusted host for windows, folder dialogs, sidecar launch,
service installation, authenticated API proxying, secure updates, and process
lifecycle. Package the Python core as an independent PyInstaller sidecar; keep
parsing, ledger, reporting, storage, Task Transfer, Desktop binding, and Codex
registration in Python.

Webviews never receive the collector bearer token. The Rust host reads the
owner-local descriptor and proxies only bounded `/v1/` requests. Closing the
window stops a transient collector but leaves an explicitly registered
background collector running. The VS Code package becomes an optional universal
companion and never bundles a parser or falls back to a private cache.

Publish only signed builds: notarized Developer ID DMGs on macOS and Azure
Artifact Signing per-user NSIS installers on Windows. Tauri updater artifacts
use a separately retained signing key and require confirmation before install.
There is no unsigned release fallback.

## Rejected Alternatives

- Electron has a mature ecosystem but would add a substantially larger runtime
  to a local dashboard whose privileged surface is small.
- Wails offers a compact Go host, but adding Go would not remove the Python core
  and would create a third product-logic path with less reuse of the existing
  TypeScript UI work.
- Qt/PySide could keep one language for product logic, but produces a heavier UI
  distribution and a less natural boundary for the existing web report and VS
  Code companion.
- A tray-only daemon would make capture persistent but would not replace the
  editor-dependent product UI. Version 2.0 intentionally adds no tray process.

## Consequences And Guardrails

The native app owns onboarding, capture controls, Usage, Task Storage, Task
Transfer, settings, and updates. Python remains authoritative for product and
data contracts; Rust must not reimplement accounting or transfer policy.
Service registration occurs only after explicit onboarding consent. Update
checks are opt-in and at most daily, and installation quiesces and repairs the
collector lifecycle.

Version 2.0 supports only macOS ARM64 and Windows x64. Linux, Intel macOS,
Windows ARM64, multiple simultaneous Codex homes, and automatic task lifecycle
management remain follow-ups. CI must exercise both native platforms, packaged
sidecars, the thin companion, installer lifecycle, signatures, updater metadata,
and clean-install behavior before publication.

## Supersession

ADR 0036 replaces the mandatory thin-companion boundary and signed-only native
publication contract. Tauri remains the native host, but the VS Code extension
is independently usable and the native application is currently distributed
only as an unsigned CI preview.
