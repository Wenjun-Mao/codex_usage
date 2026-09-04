# ADR 0037: Unified Dashboard Interaction And Theme

## Status

Accepted for version 2.1.0 on 2026-09-04

## Context

Usage HTML is rendered by the Python reporting core, while Task Storage and the
native application shell are rendered in TypeScript. Those host boundaries are
useful, but independent controls and CSS made Capture and Reload appear
equivalent, allowed explicit themes to diverge, and gave Usage and Storage
different visual structures.

## Decision

Use one product-level interaction and presentation contract with host-local
adapters. **Capture Usage** reads changed Codex task files into the durable
ledger. A contextual **Reload** action only re-queries the active Usage or Task
Storage view. Usage and Storage are primary navigation; range is Usage-only,
while project and theme controls are shared.

Use the native application's semantic palette and compact operational layout as
the visual authority. Every host implements the same semantic color tokens,
page heading, metric strip, section, table, notice, focus, and responsive
behavior. Explicit Day and Night choices override the host preference; Auto
follows it. Analytical model colors remain independent from the product accent.

Keep the existing Python and TypeScript renderer ownership instead of creating
a cross-language UI runtime. Contract and visual tests guard the host adapters.
Rendered usage-report cache keys include an explicit renderer revision so HTML
from an older presentation contract is never reused after an upgrade.

## Rejected Alternatives

- Renaming both actions without changing their hierarchy leaves the underlying
  ambiguity in place.
- Fixing only Task Storage's background color leaves loading, error, table, and
  native-app states free to diverge again.
- Moving every report into a new shared TypeScript renderer would create a much
  larger data-interface migration without improving accounting or collection.

## Consequences And Guardrails

Visible command names may change, but existing command IDs and settings remain
compatible. Theme, accessibility, responsive-layout, and renderer-cache tests
must cover both report views. Future report styling changes must bump the
renderer revision whenever cached HTML would otherwise remain visually stale.
