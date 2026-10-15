# ADR 0067: Bounded Accounting Upgrades And Capture-Scoped Retries

Status: Implemented; release and live-repair qualification pending.

## Problem

Older checkpoints lack explicit history semantics but still satisfy the unchanged
file reuse test. An inherited page can therefore retain its overcount forever;
ownership promotion can also replace its old logical slot before discovery.
Separately, incomplete rebuilds were immediately requeued even with no committed
progress, while an exception stopped unrelated queued sources.

## Decision

Before replica selection or ownership promotion, inspect checkpoints that lack
the explicit history-field contract. Read at most 32 frozen headers and 1 MiB per
capture, sharing the established 8 MiB extra-history ceiling with replica proof
and baseline resolution. Reuse the established metadata parser. Use unbuffered
bounded reads and stable device/inode/size/mtime/ctime checks; account for failed
reads as well as successful ones. Inspect unattempted recent sources first, then
rotate actual attempts so failed sources cannot starve unexamined history.

Persist typed, versioned discovery decisions bound to the observed source and
capture guards. Physical pages, inherited prefixes and explicit fork cutoffs
require staged rebuild. An unchanged header without inherited-prefix semantics
does not require immediate replay of a large unrelated history. That decision
does not certify old financial facts, repair historical null-counter overcounts,
or grant append authority. A checkpoint without the new history contract cannot
resume; active legacy sources fall back to bounded staging instead of treating a
lost counter baseline as zero.

Reserve affected captured keys, logical slots and physical families, including
absent old paths. New or unclassified claimants cannot replace their checkpoints.
Gate both preflight promotion and successful parse commits. Dependencies remain
explicitly pending until the slot is released; absent captures are retained, not
silently rebound to a newly found copy. Already superseded normalized captures
do not create fresh missing-source obligations.

Only unattempted budget-pending discovery schedules automatic baseline capture
continuations. Unavailable, changed or invalid evidence is a named gap, not an
invitation to full reparse. Preserve a failed discovery classification when the
next budget defers its retry. These receipts are workflow hints, not parser or
accounting proof. Qualified accounting and authority still follow ADRs 0064-0066.

## Rebuild Scheduling

Slices report complete, committed progress or blocked/no-progress separately;
bytes read alone are not progress. Track record/candidate and drain advancement
as well as byte offsets. Requeue only progress, at the tail, on the existing
priority I/O lane. Blocked work and failed jobs yield to unrelated sources.

Allow one retry of blocked or recoverable I/O work per successful non-baseline
capture run. Baseline continuations and rebuild callbacks do not reset that
allowance. Authority/invariant failures require changed relevant source evidence,
not an unrelated ledger revision. Sample the attempt's evidence and capture epoch
when the lane starts execution, not when it queues the slice. A capture ahead of
that slice must not accidentally grant another immediate attempt. Bind completion
to its submitted source and actual attempt evidence. Isolate fingerprint failures
per source; do not probe a failed fingerprint repeatedly within the same capture.
Preserve authority-failure suppression across probe errors. Classify extended
SQLite busy/locked errors by their primary code. Add no timers, threads, services
or speculative retries.

## Guardrails And Remaining Work

Regressions cover unchanged retrospective discovery, unchanged checkpoint
retention, absent paths/new claimants, cold replicas and slot dependencies,
budget/failure scheduling, weak null-counter append refusal, warm history-free
capture, fair retries, failures not starving other jobs, and UI/capture priority.
They include weak and qualified claimants with misleading recognized filenames,
capture-before-execution ordering, both fingerprint failure paths, and primary/
extended SQLite retry classification.
Discovery does not itself rebind a missing path, repair unresolved replica
families, invalidate dependent lineage, authorize live writes or qualify release.
Those remain explicit repair and validation work in the implementation plan.
