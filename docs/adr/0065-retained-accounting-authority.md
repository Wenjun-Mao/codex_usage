# ADR 0065: Retained Accounting Authority Is Not Parser Authority

Status: Released in 2.12.3; [qualification and publication receipt](../release/2026-10-15-2.12.3-published.md).

## Problem

A physical paginated rollout can have several cached copies. If the longest raw
copy disappears, guarded parser handoff correctly refuses a shorter available
copy. That refusal did not prevent both retained normalized generations being
charged: root 100 + short page 50 + long page 100 appeared as 250 instead of 200.
Deleting a capture, selecting by token magnitude, or weakening byte-prefix proof
would either lose evidence or authorize unsafe parsing.

## Decision

Keep raw parsing under ADR 0064. Separately select one **whole stored accounting
projection** per evidenced physical rollout. A retained copy dominates another
only if all its indexed financial facts cover that copy exactly, its captured
extent is no smaller, and their explicit paginated identity, logical task, lineage,
fork/replay contract and resolved history boundary agree. Compare cache facts and
their established normalized projections; verify each existing normalized capture
against its own checkpoint guards, counts and cache projection. Require contiguous
indexes, consistent timestamp indexes, and complete non-draining checkpoints.

Financial facts include time, task/parent/role, turn, model, effort/mode, project
key/aliases, checkout/repository/branch attribution and every token component.
Storage paths and **project display labels** are not financial identity. Labels
remain mutable presentation metadata; renaming a label cannot create a different
charge or project identity. The immutable comparison is project key/context, not
the current human-readable label joined from `ledger_projects`. This contract
does not claim an immutable historical display-name timeline.

The initial proof excludes image-bearing captures. Language containment cannot
silently suppress image accounting. Different physical UUIDs remain independent
spent streams, even when their facts happen to match.

Persist a versioned, content-free accounting receipt in `schema_meta`, with actual
fact digests, capture bindings, lineage and the chosen/covered source keys. This
is distinct from a byte-prefix alias receipt. Actual facts are revalidated at
capture and normalization boundaries, including before rebuild; generation ID
alone is not an immutable capture. Range/report reads consume the qualified
selection without reopening raw history or rerunning the proof.

Malformed or missing checkpoint members remain family obligations, not reasons
to forget a copy. Persist declared paginated physical membership independently
of the replaceable checkpoint; that evidence (or a previously declared canonical
page key) can retain an unresolved family even when no checkpoint remains eligible.
Membership alone grants neither financial selection nor parser authority.
Pending inventory aliases without a checkpoint or accounting facts are not
captured histories; bounded discovery must not manufacture conflicts between them.
Incomparable families are withheld from additive totals and
reported as incomplete. A previously chosen whole capture can remain accounting
authority only if its own identity, lineage and actual facts freshly match its
qualified receipt; new unresolved siblings remain excluded and visible. Such a
fallback binds only the revalidated authority and retains the last complete proof.
Do not infer completeness or clear source errors/missing flags from that choice.

Normalize a selected, already-captured cache snapshot through a named accounting
authorization when raw data is absent. This derives ledger facts from validated
stored facts, not a new raw capture, and does not rebind parser state. Establish
selection before source synchronization so initial normalization completes in
one call. Revalidate afterward as well.

Supersede exactly covered duplicate normalized captures; stage unresolved ones.
Keep their events and all parser captures/checkpoints. Rebuild only current
trusted events, not nontrusted evidence or shared dimension identities. Exclude
fully retired missing sources from the coverage denominator; staged or unresolved
sources still block complete coverage. Accounting decisions advance ledger
revision and dependent invalidation; unchanged decisions do not.

## Boundaries And Guardrails

- Accounting containment proves stored-fact containment, not raw byte equality,
  parser-state equality at an earlier endpoint, or completeness against lost logs.
- Only subsequent byte-proven raw recovery may resume/rebind parsing or retire
  the accounting-only selection. Missing members cannot merely disappear.
- Inspect conflicts before sync/rebuild can replace evidence. Retain a prior
  authority only with a fresh proof, not because its old selection existed.
- Regressions cover full/ranged/normalized parity, malformed members, same-total
  financial differences, index and lineage errors, generation-ID mutation,
  first normalization, preservation through rebuild, raw recovery and stable
  unchanged revisions. Validate mutable labels separately from financial facts.
- A synthetic 3,002-response proof measured 0.174s median with deep-copy projection
  and 0.069s with the compact financial projection (three samples each).
  Traced peak fell from 14.73 to 10.30 MiB. These are local proof-only observations,
  not end-to-end capture/report or hosted performance claims. Revalidate facts
  at write boundaries; do not trade correct invalidation for a stale warm receipt.
- Mixed-version writers, lineage upgrades, disposable/live repair and release
  qualification remain governed by the implementation plan. This ADR authorizes
  no live mutation, installation or publication by itself.
