# ADR 0039: Shared Usage Comparison Scale

## Status

Accepted for version 2.3.0 on 2026-09-05

## Context

Project Breakdown owned the Tokens/API cost radio state. Its CSS scope could
not reach Model Mix, which therefore remained token-scaled even though both
charts present the same report-level comparison.

## Decision

The Usage view owns one script-free **Compare by** radio group immediately
before the two comparison charts. Project and model bars receive precomputed
token and API-cost width variables during report rendering. CSS applies the
selected measure to both charts; changing it performs no ledger query, source
file read, or report regeneration.

Unpriced models retain their token width and receive an explicit zero API-cost
width. Exact tables and tooltip disclosures remain available in either mode.

## Consequences

This supersedes the Project Breakdown-only control in ADR 0038. Tests cover
one accessible selector, both width variables, zero-cost unpriced models,
theme-safe declarative styles, and ledger-only report rendering.
