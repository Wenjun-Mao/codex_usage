# ADR 0069: Alternate Replay Inputs Do Not Move Retained Checkpoints

Status: Released in 2.12.3; targeted disposable/live repair and restore pass for
available bases. Missing bases remain explicit gaps; [receipt](../release/2026-10-15-2.12.3-published.md).

## Problem

Bounded upgrade discovery matched the captured path only. A missing legacy
capture therefore reserved its ownership slot forever, even when an owned copy
of the same physical rollout was available. Reassigning its weak checkpoint to
that copy would grant resume authority under the old accounting semantics.

## Decision

Keep captured paths, checkpoints and financial facts unchanged. Discovery may
record a separate alternate replay-input receipt only for a recognized matching
physical filename family, a validated header with the captured logical identity,
and compatible byte-prefix guards at every retained checkpoint/normalized extent.
All available same-physical candidates participate: the longest must cover the
retained extents and the shorter candidates. Conflicts remain gaps, not reasons
to choose the preferred token total or ignore a sibling. This retains ADR 0064's
bounded head/tail proof, not a claim to have read every historical interior byte.

Charge these reads to the existing discovery file/byte limits and shared history
budget. Present and missing-source attempts share one fair order; failed attempts
rotate behind unseen work. Eligible budget-deferred copies trigger continuation.
Families exceeding a whole configured batch remain named gaps, not retry loops.
Unchanged receipts reuse
capture and inventory/stat bindings without reopening raw sources. The receipt
is not evidence that any financial correction has already occurred.

Only the isolated staged-replay path consumes this alternate input. Bind its
original capture, normalized extents, candidate snapshots and selected path to
the authority fingerprint and stage filename. Recheck the retained capture and
every recorded source snapshot before installation, including ctime. Changed inputs
require ordinary discovery qualification again and a distinct stage; do not
silently adopt a partially parsed stage bound to different evidence.

Install the completed replacement workset, canonical source identity, normalized
generation, descendant invalidation and receipt retirement in one transaction.
Invalidate dependents of both the captured and replacement physical path. Retain
superseded normalized facts and failed-install stages. A populated identity
target remains a refusal, not permission to overwrite another captured history.
Normal parsing, stored-fact containment and quota observations retain their
separate authority contracts.

## Repair Maintenance And Guardrails

Retain obsolete, unknown and failed stages through repair qualification and its
rollback window; introduce no age-based or background garbage collection. Before
live maintenance, inventory stage groups and their storage, reserve capacity for
the selected replay and backups, and preserve the pre-repair groups as part of
the rollback procedure. A ledger-only snapshot is not a stage backup. Release
qualification must demonstrate this retention/restore policy; selective stage
reclamation is a separate maintenance change, not a prerequisite to immediate
automatic deletion. Busy maintenance ownership still refuses boundedly.

Regressions cover complete financial/context and pricing parity, absent paths,
short/conflicting/foreign copies, sibling obligations, bounded/fair discovery,
no-read warm reuse, changed inputs/receipts, distinct stages and atomic rollback.
Private snapshot validation, fresh backup/CAS and owner UI/release gates remain
required. This decision authorizes no new service controls or publication.

## Qualification Checkpoint

Frozen-prefix disposable replay used the production discovery and staged-install
paths without widening budgets. Available-base targets matched independent full
parses and normalized/cache facts; unavailable bases remained named gaps. Other
retained financial projections and official quota evidence were unchanged.
The indexed allowance oracle and an independent pre-upgrade restore passed.
Failed private stages were preserved and restored separately. These checks do
not establish a fresh live backup or admit migration under an active old writer;
compatible runtime cutover and the live maintenance checks remain required.
