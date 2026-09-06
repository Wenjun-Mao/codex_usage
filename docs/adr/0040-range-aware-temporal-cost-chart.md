# ADR 0040: Range-Aware Temporal Cost Chart

## Status

Accepted for version 2.4.0 on 2026-09-06

## Context

The ledger correctly returns exact daily cost rows for every date range. Passing
an unbounded history directly to the fixed-width bar chart compresses x-axis
labels into unreadable placeholders, while centred tooltips can extend beyond a
chart's visible edge. Changing the ledger query would unnecessarily discard
the detail table's daily precision and duplicate presentation concerns in each
client.

## Decision

The report view model owns temporal presentation aggregation after it receives
priced daily rows. Bounded ranges, and all-history spans shorter than 31 days,
remain daily. Longer all-history spans aggregate into Monday-start calendar
weeks until the displayed range exceeds 26 weeks; then they aggregate into
calendar months. The Daily Details table always receives the original rows.

The renderer supplies a readable minimum bar-label width and uses period-aware
titles and tooltip labels. First and last temporal bars anchor their tooltips
inward; Model Mix tooltips anchor at the start of their tracks. These rules are
declarative CSS, so they require no additional ledger query or script.

## Consequences And Guardrails

All token, cost, unpriced-token, credit, and record totals remain ledger-owned;
only the chart's displayed groups are summed in the view model. Tests cover
weekly and monthly boundaries, conservation of chart values, preservation of
daily details, readable CSS sizing, and contained tooltip anchors. Any future
range-specific aggregation belongs in this presentation contract rather than
in SQLite or source parsing.
