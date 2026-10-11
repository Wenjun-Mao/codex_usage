# Allowance Axis Layout Review

Status: Owner selected Axis-Linked and accepted the full-dashboard preview on
2026-10-10. Source integrated for 2.12.0 release preparation. No installed
extension changes are part of preview or release verification.

## Problem

The current chart combines additive usage with account-wide captured readings.
Both captions appear above the plot, so proximity does not clearly associate a
series with its scale. A distinct neutral account color helps but does not remove
dual-axis interpretation. This is a presentation-layer issue, not an accounting
or capture defect.

## Candidates

- A: Axis-linked keys. Usage title, stacked-bar glyph and model key are left-aligned;
  account title, capture-dot glyph and latest-reading key are right-aligned. One
  plot retains left usage and right account scales.
- B: Aligned panes. Usage and account readings occupy vertically aligned panes
  with their own left scales and one shared bottom time axis. The account pane is
  compact but preserves every displayed captured reading and boundary.

Axis-Linked is now the ordinary renderer. The alternate pane implementation and
preview-only selection argument have been removed. The original comparison
artifacts remain local review evidence, not a second runtime path.

The right key shows only Allowance Remaining and the latest captured percentage
for a single series. Account scope, limit/plan and original capture timestamp
remain in tooltip/accessibility metadata and issued exact evidence. Multiple
account identities keep distinct visible keys. Bars occupy half their temporal
slot and stay centered; below-resolution nonzero components use colored ticks,
not circles that resemble extra point annotations.

## Local Review

Run `.venv/bin/python scripts/preview_breakdown_layouts.py --ledger <retained-ledger>
--now <timezone-aware-date> --range 7d --check`. Use a retained frozen ledger,
not the live Codex home. The script opens the supplied source read-only, copies it
to a disposable home, and prepares normal source-backed report inputs there.
Static links compare metrics, daily/hourly views and themes without
capture, extension installation, native command receipts or network access.

Generated files and browser evidence remain under
`output/playwright/axis-layout-comparison/`. The selected renderer preserves exact
values, captured identities, timezone and time domain. Empty/unknown values,
account conflicts, balance offsets and no-interpolation rules remain unchanged.

Pointer verification covers enlarged latest readings, including both scale
endpoints. Subpixel historical dots are not reliable individual hover targets
in every browser; exact lookup remains in the account key and issued day
inspection. The plot viewport includes marker room while preserving the UTC
transform so boundary markers do not lose their hit area to SVG clipping.
Horizontal marker room is conditional on an account overlay, where fixed axis
gutters contain it. Usage-only plots stay within the available width; vertical
marker room and tick alignment remain unchanged in both modes.
