# ADR 0006: Bundled Windows VSIX Runtime

Status: Accepted

Date: 2026-06-16

## Context

The local prototype ran `uv run codex-usage` from the source repo. That failed the portability requirement because Marketplace users should not need Python, uv, or this repository.

## Decision

For the Windows x64 preview, bundle a PyInstaller-built `codex-usage.exe` inside the VSIX and spawn it directly from the extension.

## Alternatives Considered

- Require users to install Python and uv. Easier for us, worse for normal users.
- Port the core to TypeScript. Removes Python packaging, but duplicates mature Python logic.
- Download the runtime on first use. Adds network behavior and supply-chain complexity.

## Consequences

The VSIX is larger but self-contained on Windows x64. Linux and macOS need separate runtime decisions.

## Guardrails

The extension should report a clear unsupported-platform error when the bundled executable is unavailable.

