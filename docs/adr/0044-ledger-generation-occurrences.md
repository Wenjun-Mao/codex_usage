# ADR 0044: Distinct Ledger Generation Occurrences

## Status

Accepted for 2.8.6 on 2026-09-25.

## Context

The durable ledger previously used the OS device and inode digest as both the
file identity and the unique generation key. A device value can change and later
return while the inode and source head remain the same. On a return, a new parser
checkpoint can refer to a key already owned by a superseded generation. The
ledger sync then fails its uniqueness constraint. Its transaction rolls back,
leaving the previous trusted generation intact, but capture cannot advance.

An observed local case had a current parser device value matching generation 2,
while generation 5 remained trusted. The device transition followed a macOS
upgrade; the upgrade's causal role was not established. The parser correctly
treated the identity mismatch as a guarded append failure and rebuilt its
workset. The conflict was in the ledger's generation identity contract.

## Decision

Separate the stable OS identity digest from each durable occurrence of that
identity. Existing bare digest keys remain readable. New generation keys append
the monotonically increasing per-source generation number to the digest. Ledger
sync compares the digest portion for ordinary append continuity; a changed
identity, a rebuilt stale source, truncation, a lower record count, or a changed
head or boundary at a fixed size creates a new occurrence. A head digest change
during growth of a file smaller than the digest window remains an ordinary
append, because that digest necessarily changes as the window fills.

Every new occurrence receives its own event rows. Historical rows and the unique
constraints remain in place. The source update, trusted-status switch, generation
insert, event insertion, and revision increment remain in one transaction.

## Rejected Alternatives

- Reusing a superseded row would overwrite its historical event snapshot and
  break the monotonic generation timeline.
- Ignoring a duplicate insert would leave the parser workset ahead of the
  trusted ledger and falsely report a successful capture.
- Removing old generations or the uniqueness constraint would hide the invalid
  identity model and discard useful history.
- A schema migration to add another identity column would rewrite durable
  metadata without being required for this backward-compatible key format.

## Consequences And Guardrails

The same device/inode pair may now appear in multiple generation occurrences.
The newest trusted occurrence owns reports; superseded event rows remain
available for audit. A retry after a committed transition compares the digest
prefix and does not insert another occurrence. Tests cover identity changes and
reversion, stable append behavior, fixed-size head and boundary replacement,
and transactional rollback.
The affected local ledger was also synchronized twice on a disposable SQLite
backup: the first pass advanced its trusted record count from 12,438 to 12,464
without removing prior events, and the second pass made no change.
