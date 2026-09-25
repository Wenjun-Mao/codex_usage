# ADR 0045: Guard-Verified Ledger Generations

## Status

Accepted for the 2.8.7 corrective candidate on 2026-09-25. The 2.8.6
occurrence-key fix prevented reuse of a historical unique key, but still used
OS device/inode identity to decide generation continuity. It did not satisfy
this content-continuity contract.

## Context

A source's OS device value can change and later return while its inode and
content history remain continuous. The prior ledger equated the device/inode
digest with generation identity, so a returning pair collided with a superseded
row. The parser checkpoint already records a head digest and a 64 KiB digest
ending at its processed byte offset. The trusted ledger generation records
those same guards and its processed size.

The observed failure followed a macOS upgrade, but that timing does not prove
the upgrade caused the device transition. A read-only check of the affected
source showed that both saved trusted guards still match the current file.

## Decision

A ledger generation is a durable occurrence identified by a per-source
monotonic number. New generation keys use `occurrence:<number>`; existing keys
remain readable. Device and inode are diagnostic change signals, never the
permanent uniqueness key.

Before advancing a trusted generation, ledger sync opens the source and checks
both the parser checkpoint's current head and boundary guards and the trusted
generation's saved head and prior processed-boundary guards. The file must be
at least as large as the checkpoint, the parser's inode must still match the
opened file, and the path must still refer to the same open file after the
bounded reads. This verification reads at most four 64 KiB guard windows. If
the trusted guards match, size and record count do not regress, and the inode
is unchanged, the generation continues; only new parser records are appended.
A device value may change or revert under this verified continuity.

An inode change, failed prior guard, truncation, or lower record count creates
a distinct occurrence after the parser reconstructs a complete workset. The
old trusted generation and its events remain in the ledger until the new
occurrence, events, and source metadata promote in one transaction. A current
parser guard mismatch aborts sync instead of promoting an unverified workset.
The parser allows device-only transitions through its existing guarded append
check, including a zero-tail guard validation when size is unchanged. Inode
changes still trigger staged reconstruction.

## Rejected Alternatives

- Reusing a superseded generation would overwrite historical event evidence.
- Ignoring the unique-key error or removing the constraint would conceal an
  incomplete capture.
- Using unchanged path, inode, prefix, size, or mtime alone would miss a changed
  processed boundary.
- Rehashing the full prefix on every append would defeat bounded capture on
  multi-gigabyte sources.

## Consequences And Guardrails

The normal append path reads only guard windows plus the tail; unchanged cycles
open no JSONLs. As in ADR 0022, a middle-prefix edit that preserves file
identity and both guard regions is outside the bounded append contract. Tests
cover device change and reversion, zero-tail validation, same path/inode/head
with changed boundary, atomic replacement, repeated capture, event conservation,
and rollback. A disposable SQLite backup of the affected ledger verifies the
recovery without changing the live ledger or its source JSONLs.
