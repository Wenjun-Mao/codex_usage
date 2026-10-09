# Usage And Allowance Breakdown

Status: Approved product direction, 2026-10-08. Separate feature release after
the observed-speed chart usability patch. Not implemented or shipped.

## Goal

Explain when captured usage happened, which models/projects contributed, and
how account-wide included allowance changed within the current reset window.
Complement the compact Hourly Heatmap rather than replacing its overview.

## Experience

- Two selectors: Hour / Project and Tokens / API cost.
- Hour: stacked hourly bars with Model / Project stack grouping; default to
  API-equivalent cost stacked by model for the current reset window.
- Project: ranked horizontal totals stacked by model for the selected interval.
- Selecting an hour reveals project-by-model detail with tokens and cost.
  Selecting a project reveals its hourly pattern.
- An aligned percentage chart below Hour view shows captured allowance remaining
  on the same time domain, not a dollar/percentage dual-axis overlay.
- Retain full-range context, readable axes and responsive bounded detail windows.
  Do not reproduce the speed chart's hidden-axis or misleading-range defects.

## Evidence Contract

Reuse trusted, already-valued event summaries; do not introduce another pricing
pipeline or infer quota from raw token totals. Tokens include cached input and
free included reviews. API-equivalent dollars are not subscription charges.

Actual allowance is account-wide and must remain so under project/model filters.
Clearly distinguish captured meter readings from cost-calibrated estimates.
Reuse compatible current/previous allowance references and established full-meter,
reset, plan, coverage and unknown-cost boundaries. Credit-funded usage must not
reduce the included-allowance estimate. Unknown/excluded monetary values are not
zero. Missing local usage or snapshots must not imply complete account coverage.

Prefer composition bars over a waterfall: empirical quota attribution does not
form an exact additive bridge to the captured balance. Estimated contributions
may be useful, but cannot be labeled exact per-project/model quota spending.

## Implementation Planning Before Coding

1. Bind reset-window bounds to verified allowance history and define behavior
   when the actual opening timestamp or readings are unavailable.
2. Define the indexed hour/project/model aggregation and cache identities;
   preserve monetary parity and warm ledger-only reports.
3. Specify filter scope, drill-down/navigation commands, empty/partial coverage,
   unknown-price and credit-funded states under the existing script-free host.
4. Validate the primary flow with representative synthetic fixtures before
   expanding it; test additive totals, DST, reset crossings, saturation, credits,
   keyboard navigation and wide/narrow rendering.

Open decisions: top-project grouping with an inspectable Other category,
hourly window pagination, how much estimated quota attribution belongs in
drill-down, and treatment of partially observed reset boundaries. Settle these
in the feature implementation plan rather than widening the usability patch.
