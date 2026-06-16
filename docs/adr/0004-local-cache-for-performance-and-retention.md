# ADR 0004: Local SQLite Cache For Performance And Retention

Status: Accepted

Date: 2026-06-16

## Context

Parsing every JSONL file on every dashboard refresh made range switching slow. Archive and delete behavior also raised a product question: should historical usage disappear when a local session file disappears?

## Decision

Use a local SQLite cache for parsed usage rows, file summaries, file errors, and project transition results. Reuse unchanged files and retain previously parsed missing files as historical usage.

## Alternatives Considered

- Parse every file every time. Simple, but slow as logs grow.
- Keep only an in-memory cache. Faster inside one session, but loses history on restart.
- Drop missing files immediately. Easy, but makes historical reports depend on current file presence.

## Consequences

First run can take a few seconds. Later range switching is faster. Deleted files remain in historical totals after the cache has parsed them once, which matches usage-as-history semantics.

## Guardrails

The cache must not change token accounting. Failed refreshes should not wipe previous good rows.

