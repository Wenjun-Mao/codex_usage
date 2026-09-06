# ADR 0040: Range-Aware Temporal Cost Chart

## Status

Accepted for version 2.4.0 on 2026-09-06

## Context

The ledger correctly returns exact local-calendar daily cost rows for every date
range. The old chart created one grid track per day with a 5 px minimum and then
clipped the date text inside each track. A long history therefore reduced dates
to overlapping or numeric-looking fragments rather than meaningful temporal
labels. Its centred tooltip rule also placed half of the first or last tooltip
outside the visible chart edge. Changing the ledger query would unnecessarily
discard the detail table's daily precision and duplicate presentation concerns
in each client.

## Decision

The report view model owns temporal presentation aggregation after it receives
priced daily rows. For `all`, it derives both Monday-through-Sunday weeks and
calendar months from those already-local day keys, including the first and last
partial periods. The report pre-renders both series and exposes one native radio
group, **Week | Month**, defaulting to Week. CSS switches the visible series, so
the desktop sandbox and VS Code webview need no script, ledger query, JSONL read,
or report regeneration. Every shorter range remains on the existing daily chart.
The Daily Details table always receives the original rows.

The all-history section is titled **Cost Trend**. The renderer supplies readable
minimum widths and bounded desktop, medium, and narrow tick subsets, always
including the first and last periods. Tooltips show the exact calendar period,
API-equivalent cost, and token total. First and last temporal bars anchor their
tooltips inward, and tooltip width is capped against the report viewport.

## Consequences And Guardrails

All token, cost, unpriced-token, credit, and record totals remain ledger-owned;
only the chart's displayed groups are summed in the view model. Tests cover
Monday, month/year, timezone, and partial-period boundaries; exact conservation;
all-range-only control visibility; daily shorter ranges; keyboard state; local
zero-I/O switching; responsive ticks; both themes; and contained edge tooltips.
Any future range-specific aggregation belongs in this presentation contract
rather than in SQLite or source parsing.
