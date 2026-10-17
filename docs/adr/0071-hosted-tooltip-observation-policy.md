# ADR 0071: Hosted Tooltip Observation Policy

Status: Owner-approved October 16, 2026; implemented, qualification pending.

## Problem

The 250 ms tooltip guard was chosen to catch the return of browser-native
two-second tooltip delays, not derived from a user-mandated service level.
Hosted WebKit input-through-style observations also include automation and
engine scheduling. Their 300-600 ms delays have no established product cause.
Treating every such observation as a release failure has become disproportionate.

ADR 0070's source-bound exception correctly protected one release, but the
qualification code made that exception mandatory for every hosted candidate.
The published 2.12.3 slot is immutable; it is not a reusable approval mechanism.

## Decision

For verified source versions 2.12.4 and later, normal hosted qualification uses
`hosted-webkit-observed`. The owner approved this policy after reviewing the
original guard's purpose and measurement limitations. It is a declared test
environment distinction, not a claim that the unresolved timing issue is fixed.

- Retain all 72 cases, 648 real-input observations, hidden/matched baselines,
  original sequence, script-disabled rendering and all functional assertions.
- Hosted WebKit hover, hide and keyboard observations must complete in strictly
  less than two seconds. Record raw times, per-phase maxima and the count at or
  above 250 ms. A threshold exceedance is visible, not relabelled a strict pass.
- Chromium, Firefox, local browser checks and exact-package native VS Code
  retain the strict 250 ms limit. The owned suite remains bounded to 600 seconds.
- Use observation schema 3 for the normal hosted policy. Retain schema 2 and
  exact journal validation for legacy exception evidence. Select policy from
  independently verified source identity, never missing bindings or a caller flag.
- Carry the policy from raw producer evidence through freeze, independent
  inspection and pre-upload validation. Reject borrowed/null legacy bindings,
  wrong policy/schema, missing or altered observations and inconsistent summaries.

Leave the publication journal, origin/genesis pins, old approvals, same-version
conflict rules, possible-upload fences and atomic non-forced append unchanged.
Later-version publication intents omit the obsolete latency binding; they still
need the full package/native/source/tag/publisher and retained-upload checks.
Qualification does not grant permission to tag, publish or install a candidate.

## Alternatives And Guardrails

Rejected reusing or rewriting 2.12.3's published exception, new per-release
approval slots for this known measurement limitation, removing timing evidence,
loosening native response checks, and rerunning until a strict hosted sample passes.
Two seconds is a finite functional ceiling, not the desired interaction speed.
The original input/transport timing remains intact; no subtraction or retries.

Tests preserve legacy validation, enforce exact numeric limits and state/modality,
reject policy substitution at each proof boundary, revalidate raw artifacts, and
append synthetic new-version intents after frozen old publication records while
rejecting duplicate targets. Native numeric proof rejects booleans and nonfinite
values rather than interpreting `false` as a fast response.

Revisit the hosted observation measurement separately when evidence can isolate
product latency from automation scheduling. No new tracing campaign is authorized
by this decision, and no dashboard, accounting or runtime default changes.
