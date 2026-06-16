# ADR 0001: Python Core With Thin VS Code Wrapper

Status: Accepted

Date: 2026-06-16

## Context

The project started as Python code for parsing local Codex JSONL files. VS Code extensions run in a Node.js extension host, so a Python-only VS Code extension is not the right runtime model.

## Decision

Keep parsing, aggregation, pricing, reporting, caching, and sync in the Python CLI. Keep the VS Code extension as a thin TypeScript wrapper that owns VS Code commands, webviews, global state, status bar behavior, and process spawning.

## Alternatives Considered

- Port all logic to TypeScript. This would simplify extension runtime but duplicate or discard the working Python core.
- Build a Python-first extension with a wrapper from the start. This still requires Node.js extension code and adds packaging risk early.
- Keep only a CLI. This would miss the intended VS Code dashboard workflow.

## Consequences

The Python CLI remains reusable outside VS Code. The extension stays small and testable. Packaging must solve Python runtime distribution for Marketplace users.

## Guardrails

TypeScript should not reimplement token accounting, pricing, project identity, or sync decisions.

