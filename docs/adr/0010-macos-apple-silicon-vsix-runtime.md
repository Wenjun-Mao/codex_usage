# ADR 0010: macOS Apple Silicon VSIX Runtime

Status: Accepted

Date: 2026-07-04

## Context

The first Marketplace preview bundled a Windows x64 PyInstaller executable. macOS users need the same self-contained VS Code extension experience without requiring Python, uv, or this repository at runtime.

This preview limits macOS support to Apple Silicon to reduce release and test surface. This project does not plan to support Intel macOS packages.

## Decision

Bundle a PyInstaller-built `codex-usage` executable for `darwin-arm64` at `extensions/vscode/bin/darwin-arm64/codex-usage` and package it with `vsce --target darwin-arm64`.

Keep Windows x64 packaging unchanged. Do not add `darwin-x64`.

## Alternatives Considered

- Require macOS users to install Python and uv. This keeps packaging simple, but gives Marketplace users a worse runtime story than Windows users.
- Build both Apple Silicon and Intel macOS packages. Intel support adds release and test surface outside the current preview scope.
- Port the Python core to TypeScript. This duplicates mature accounting, cache, pricing, transition, and sync logic.

## Consequences

macOS Apple Silicon users get a self-contained VSIX. The release process now has separate Windows and macOS package commands. Intel Mac users receive a clear unsupported-platform error.

## Guardrails

Do not download a runtime on first use. Do not support Intel Mac unless a future ADR reverses this decision. Keep TypeScript responsible only for VS Code orchestration and platform executable selection.
