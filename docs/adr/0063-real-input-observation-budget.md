# ADR 0063: Real Input Observation Budget

Status: implementation candidate, 2026-10-13; fresh full qualification required.

## Context

Two hosted WebKit focus waits timed out at 250ms; the second wait's own log resolved
the tooltip as visible. Later DOM does not establish deadline compliance. The
existing fixture also followed real Tab with corrective programmatic target focus,
then timed a selector visibility/adoption operation rather than the user input.
There is no evidence justifying a product CSS change or a relaxed deadline.

The actual predecessor of the first usage target is the focusable allowance legend,
not the SVG account glyphs. A bounded three-engine probe rejected the glyph-origin
assumption. This is fixture input authority, not an engine-specific exception.

## Decision

Define one strict `<250ms` real-input-to-computed-style observation budget for
hover, hide and keyboard focus. Resolve the stable tooltip handle before timing,
then start before the real input. Observe visibility, opacity and nonzero geometry
directly without asking a selector wait to resolve/adopt an element afterward.
Every observation, including a late visible result, is checked against the same
absolute elapsed budget. No timing subtraction, timeout increase or passing retry.

Keyboard setup focuses the known preceding allowance-legend/usage target; real
Tab must reach the expected target with `:focus-visible` and no hover masking.
Do not apply corrective focus after Tab. Hide requires both hover and active focus
triggers absent. Keep the same behavior in Chromium, WebKit and Firefox, product
scripts disabled, and all existing containment, text, input, hit-test and geometry
assertions. Test-side style evaluation is already an established fixture mechanism;
it does not enable product scripts or change the CSP.

## Guards

Tests reject exactly 250ms and later visible results, missing keyboard modality,
hover masking and hidden results with lingering input triggers. Complete 72-case
three-engine qualification and fresh hosted normal/failure-retry/dry-run pilots
remain required. Earlier failed evidence is preserved; renderer root cause and
general hosted reliability are not inferred from a passing sample.
