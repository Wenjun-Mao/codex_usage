# ADR 0070: Candidate-Bound Hosted Latency Dispositions

Status: Journal foundation implemented; observation/proof integration and explicit append authority pending.

## Problem

The owner defers the existing hosted WebKit timing investigation for one release.
A timing overrun must remain visible, while every functional check and exact
case still executes. The current observer aborts before later checks, and a
whole-suite `passed` label cannot express this distinction. Environment flags,
blanket skips and an unbound version allowlist would weaken release authority.

Committing the expected full commit SHA into that same commit is circular.
Conversely, one irrevocable approval for the first disabled candidate would
prevent the plan's mandatory source-changing enablement and requalification.

## Selected Design

Keep a fixed one-release D4 slot in the existing independently pinned production
journal, with typed append-only candidate bindings. Freeze source before adding
its binding. Include repository, reserved release version, actual source version,
full source SHA, contract fingerprint, workflow, exact hosted WebKit hover/hide/
keyboard scope, disposition and finite functional deadline. No new ref or
genesis, qualification write permission, publisher credential or tag is needed.

The slot's release version, scope and binding cap are immutable. Each successor
must name the current predecessor commit, increment its revision and carry an
explicit approval/reason. Preserve old bindings but make them ineligible for
current qualification or promotion. Purpose may advance from `nonpublishing`
to `release`, never back; release source version must equal the reserved version.
The proposed cap is four bindings: required C/E plus the two already-authorized
corrective iterations. New typed-event append authority is awaiting owner review;
no journal write is authorized merely by this design record.

Either target's anchored possible-publication intent permanently freezes the
slot, regardless of outcome, catalog visibility, acknowledgement or surviving
Actions evidence. Validate intent against the current binding in the same
verified journal parent used for its non-forced append. If a competing append
wins, stop rather than rebuild/replay the loser. Preserve all existing upload
source/package conflict and duplicate-target rules; approvals are not uploads.

## Observation And Proof

Separate functional completion from timing disposition in versioned evidence.
Retain all 72 original hover cases and 648 target/phase observations, raw elapsed
values and baseline/matched state. Approved hosted WebKit observations are
`deferred-known-latency`, never silently passed. Other engines, local runs and
exact-package native replay retain their strict timing requirements.

Use a finite independently enforceable functional execution/observation bound,
including input and transport completion. Wrong or missing state, primed inputs,
modality/content/containment failures, transport errors and incomplete inventories
remain failures. Neither late success nor swallowed exceptions proves completion
within an execution limit. This is not a root-cause fix or a timing subtraction.

Producer receipts, frozen manifests and promotion retain the anchored binding
reference. Freeze and promotion each resolve fresh canonical journal state and
revalidate raw hover payloads, not only summaries. Keep successful-job/original-
attempt markers, artifact digests, source closure, native proof and tag checks.
`PROMOTION_ENABLED` stays false during this implementation and its pilots.

Negative guards cover wrong source/version/contract/context, stale predecessor,
duplicate slot, cap overflow, purpose regression, superseded/forged proof, both
append race orders, either target's publication freeze, missing/duplicate/nonfinite
observations, false pass labels and functional/transport failures. No automatic
rebinding after a failed run and no new diagnostic batches are introduced.

## Implementation Checkpoint

The journal supports typed bindings, current-candidate resolution, immutable
release scope, bounded monotonic replacement and permanent freezing after either
target's possible-upload intent. Both race orders and lost acknowledgements are
covered with the in-memory Git transport. Approval reasons are bounded before
serialization. Candidate creation checks the complete stored record's byte and
history-count limits before any Git-object write, so a valid event cannot poison
retained history merely by exceeding a reader limit after wrapping or append.

These are foundation tests, not active release authority. No real binding has
been appended. The selected future scope retains the 250 ms strict criterion,
with 2 s functional acceptance and a 600 s owned-process execution ceiling for
the approved hosted WebKit context only. These deferred bounds are not yet wired
into the observer. Raw observation collection, independent fresh-journal proof
validation and producer/freeze/promotion integration remain unimplemented. The
current strict observer and all existing qualification checks remain unchanged.

Local verification: 2,774 passed with the one approved Windows-only skip, with
raw JUnit and collection inventory independently validated under
`output/verification/d4-journal-foundation/`. A subsequent 111-case focused run
includes the added record-count boundary guard. Ruff, frozen monetary parity and
bounded-work guards pass. Independent read-only review found and then verified
the serialized-size correction. No hosted pilot or production journal write has
been run for this foundation.
