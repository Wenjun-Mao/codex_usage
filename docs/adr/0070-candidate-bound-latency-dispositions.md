# ADR 0070: Candidate-Bound Hosted Latency Dispositions

Status: Design selected; implementation and explicit journal-append authority pending.

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
