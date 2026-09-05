# ADR 0038: Semantic Model Presentation And Cost Scale

## Status

Accepted for version 2.2.0 on 2026-09-04

## Context

Project Breakdown and Model Mix assigned order and color from descending token
volume. A model therefore changed position and color across report ranges, and
newer model generations could appear below older ones. Model Mix also gave each
row an independent CSS grid, so different value-label widths produced unequal
track lengths.

Project Breakdown exposed role-level token totals and project shares even
though its already-valued aggregation also contains API-equivalent cost. Users
could not compare projects by that cost without mentally reconciling the exact
tables.

## Decision

Keep visual-model membership bounded to the seven highest-token exact models,
then present those models by descending GPT generation and product tier. Known
tiers use the order Astra, Sol, Terra, and Luna where applicable; recognized GPT
models precede unrecognized labels, and `Other` remains last. Assign stable
slots to current named models and use a multi-hue categorical palette so model
identity does not depend on usage rank.

Model Mix rows participate in one shared grid, giving every neutral track the
same start and end positions.

Project Breakdown displays token and API-equivalent dollar totals in each role
cell. A script-free segmented control selects Tokens or API cost as the bar
scale, with Tokens as the default. Each role column remains independently
scaled across projects. Model segments use the same selected measure as their
containing role bar, and the displayed project share follows the selected
measure.

This decision partially supersedes the presentation order in ADR 0021 and the
token-only role metric and scale in ADR 0030. Their aggregation, conservation,
role-classification, and independent-column contracts remain authoritative.

## Rejected Alternatives

- Sorting every model only by generation would let negligible models displace
  high-volume models from the bounded visual set.
- Keeping rank-derived colors would continue changing model identity between
  ranges.
- Scaling the outer role by cost while retaining token-scaled model segments
  would encode two incompatible measures in one bar.
- JavaScript state is unnecessary for a local visual preference and would
  weaken the report's script-free rendering contract.

## Consequences And Guardrails

API-cost mode can show zero-width bars for models without a verified USD rate;
token mode and exact disclosure tables continue to expose that usage. Tests
cover generation/tier order, stable color assignment, shared Model Mix tracks,
role cost conservation, both width variables, keyboard-operable scale controls,
and script-free output. Cached rendered reports must increment their renderer
revision when this contract changes.
