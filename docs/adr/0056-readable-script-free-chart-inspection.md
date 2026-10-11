# ADR 0056: Readable Script-Free Chart Inspection

Status: Accepted for local implementation, 2026-10-11. Not released.

Native VS Code acceptance also checks the host's automatic command-URI anchor
titles. The hit-area child has an explicit empty title to suppress inherited
native tooltips; CSS inspection and the anchor's accessible label remain intact.

Summary precision is capped at six fractional digits. Smaller nonzero values
use a signed inequality rather than zero or an arbitrarily long decimal.
Near-empty/full allowance labels use `<0.01%`/`>99.99%`; only exact boundary
readings display 0%/100%. Source readings and meter values stay unrounded.
When bounded labels would collapse distinct balance ticks, rescale the axis
with an explicit multiplier and retain exact values in tick titles. This is an
axis-unit change, not rounding or dropping small captured balance movement.

## Context

Usage bars used SVG `title` elements for inspection. Browsers control their
hover delay, and labels interpolated Python floats directly, exposing values
such as `74.19778399999994`. Repeating date, clock and numeric offset at every
time tick also consumed three rows. These are presentation-layer failures;
neither accounting precision nor source timestamps should change to fix them.

The dashboard's webview deliberately disallows scripts. Adding JavaScript or
reducing source evidence is unnecessary for these interactions.

## Decision

Use script-free HTML hover/focus targets over unchanged SVG usage geometry.
Each target has a real layout box, a readable accessible label and the same
server-issued inspection action. CSS makes its popup visible immediately on
hover or keyboard focus, without a transition or browser-native tooltip delay.
Targets, including the minimum hit width for tiny/clipped buckets, stay within
the plot. Popups have bounded width and show a total plus a swatch/name/value row
for each series. Unknown, excluded, empty and known zero retain their meanings.

Keep account dots painted and hit-tested above the usage hit areas in the same
SVG. Native account-dot inspection remains unchanged; this decision does not
promise immediate native tooltips for every dashboard mark. SVG usage marks use
`desc` instead of duplicating native tooltips. No script or CSP exception is added.

Format derived money to two decimal places, credits with bounded display
precision and large token counts in human units. Adapt precision or use a
sub-cent summary label rather than silently turning a positive value into zero.
Shared summary helpers cover the KPI, allowance estimate/pace and credit table paths.
Do not round stored events, valuation, aggregation, chart heights or exports.
Original captured balance/allowance evidence remains available in inspection;
derived floating-point tails are not meaningful additional accounting precision.

Single-day hourly ticks show clocks only, with the local date and timezone once
below the axis. Multi-day hourly ticks use at most two rows: date and clock.
Offset-changing windows add zone abbreviations to clocks and disclose all offsets
once. Tick positions remain on the original UTC domain, and full timestamps stay
in accessible/native tick context. A closing midnight is `24:00` for the selected
local day. Daily ticks remain dates.

Report render revision 34 invalidates earlier presentation caches. Pricing and
ledger revisions do not change because of this presentation contract.

## Alternatives And Guardrails

Rejected reducing accounting precision, relying on native tooltip timing,
relaxing the script policy, and using `display:contents` on the focus target:
browser checks showed that a target without a layout box cannot reliably focus.

`test_breakdown_hover_numbers.py` checks readable floats, tiny nonzero values,
issued actions, immutable source values and DST/single-day/multi-day labels.
Existing geometry tests continue to check unmodified centers and heights.
`check_breakdown_hover_ui.py` checks immediate hover and keyboard focus, tab order,
contained popups and account-dot hit testing in Chromium, WebKit and Firefox,
at desktop and narrow widths with scripts disabled. The broader dashboard matrix
checks actual tick glyph containment, controls and exact inspection access.

Local verification: 1,795 Python tests passed with one platform-specific skip;
48 extension tests passed. The script-disabled browser checks covered 72
hover/focus views and 720 dashboard layout views across all three engines,
day/night themes and widths of 1440, 760 and 360 pixels. Exact frozen accounting
parity remained intact. No release, installation or live-ledger mutation was
part of this verification.
