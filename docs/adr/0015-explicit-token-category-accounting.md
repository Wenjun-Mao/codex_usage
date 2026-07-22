# ADR 0015: Explicit Token Category Accounting

Status: Accepted

Date: 2026-07-21

## Context

Codex token events can expose distinct categories that overlap broader totals. GPT-5.6 cache writes are included in non-cached input but have a separate API rate. Dropping that field caused API-equivalent USD to miss the cache-write premium.

## Decision

Preserve every explicit upstream token category through parsing, cumulative deltas, persistence, aggregation, serialization, and reporting. Never reconstruct a missing category from another total.

API USD and Codex credits may intentionally classify the same token differently when their official rate cards differ. Cache writes use the published cache-write API rate but remain ordinary input for Codex credits until an official credit rate says otherwise.

## Alternatives Considered

- Infer cache writes from non-cached input. Rejected because ordinary uncached input can coexist with writes.
- Keep only broad totals. Rejected because it discards billable evidence.
- Fetch live billing data. Rejected because reporting remains local and deterministic.

## Consequences

Usage schema changes require a parser-cache rebuild. Missing source files cannot gain categories introduced after they were cached, so reports disclose that evidence limitation.

## Guardrails

- Keep upstream field names at ingestion boundaries.
- Use checked-in, effective-dated rates.
- Do not add a Codex-credit category without an official rate card.
- Default absent optional fields to zero; do not infer values.
- Preserve last-successful usage and metadata through cache rebuilds; replace that fallback only after an active file reparses successfully.
- Never reuse an errored cache row by fingerprint; retry it on later loads even when no prior parse succeeded.
