# ADR 0022: Guarded Append Parser Checkpoints

## Status

Accepted. [ADR 0032](0032-cross-process-cache-refresh-recovery.md) extends the
atomic checkpoint contract with cross-process refresh ownership and a
transaction-time stale-checkpoint assertion.

## Context

The local performance audit on 2026-08-07 covered 2,509 JSONL files totaling
about 148 GB. Warm range changes reused SQLite rows, but a small append to an
active multi-gigabyte task still invalidated that file's complete generation.
The bounded 4 KiB event classifier reduced JSON decoding work, but it could
not remove the old-prefix I/O.

Task Transfer discovery had a related bounded-work problem: metadata can occur
on the first line, yet discovery accumulated as much as 1 MiB per task before
parsing. On the measured corpus, stopping after valid `session_meta` reduced
source bytes from about 1.414 GiB to 53 MiB and elapsed time from 1.36 seconds
to 0.153 seconds.

The usage cache is disposable derived data. Its correctness requirement is to
produce the same records, metadata, transition candidates, role attribution,
model state, fork behavior, and cumulative-token deltas as a from-zero parse,
while preserving the previous complete generation after interruption.

## Decision

Schema 6 uses `usage-cache-v6.sqlite3` and adds a parser checkpoint owned by
each cached file generation. The checkpoint stores the parsed byte offset,
next usage and candidate indexes, cumulative-token baseline, active model,
turn, effort, collaboration mode, current and root metadata, fork state,
source device and file identity, canonical task ID, a head digest, and a 64 KiB
digest ending at the old boundary. Schema 5 is discarded and rebuilt; it is not
migrated or dual-read.

Device and file identity values are opaque equality tokens. Schema 6 stores
their exact decimal representations as text because Windows can expose
unsigned 64-bit values beyond SQLite's signed integer range.

Only active JSONLs can use append parsing. The path, OS file identity, task ID,
strictly increasing size, head digest, and old-boundary digest must all match.
Missing identity, replacement, truncation, same-size modification, digest
mismatch, archived-file change, or invalid checkpoint state falls back to a
from-zero parse. Inventory captures the readable size before scheduling, and a
worker reads no later growth until the next refresh.

Full and append parsing share one buffered, byte-oriented state machine. It
inspects the first 4 KiB of normal Codex rows for event discriminators and skips
known irrelevant rows without JSON-decoding their remaining payload.
Unclassifiable or reordered prefixes use the existing full-line semantic check.
Unicode-escaped labels, function-call workdirs, forks, roles, model state, and
cumulative-token deltas retain their prior semantics. An incomplete final JSON
row keeps its starting offset for the next refresh; a complete valid row does
not require a trailing newline.

Workers remain read-only and pickle-safe. Eight-file groups are submitted in
descending estimated unread bytes, using full size for a from-zero parse and
tail size for an append, while original ordinals still determine commit order.
The parent atomically commits appended records, candidates, metadata,
fingerprint, and checkpoint in the existing SQLite transaction. Any parsing,
verification, or SQLite failure retains the prior rows and checkpoint.

Task Transfer metadata discovery reads one bounded line at a time and stops
after valid `session_meta`, retaining the 1 MiB ceiling and retry behavior.
Pricing schedules compile to normalized effective-dated model and alias
indexes. Each usage record is valued once per report and that valuation is
reused by totals, temporal rows, and Project Breakdown. Existing aggregation
entry points remain compatibility wrappers, and conservation checks use both
relative and absolute floating-point tolerance.

## Rejected Alternatives

- Hashing the complete old prefix before every append would detect every
  prefix mutation, but cryptographic verification still has to read every old
  byte. On multi-gigabyte files it would recreate the I/O cost this decision is
  intended to remove.
- Trusting size and mtime alone would miss replacements and in-place edits near
  the prior boundary.
- Persisting a rendered report or Task Transfer inventory would add broad
  invalidation and lifecycle contracts unrelated to the measured bottlenecks.
- Increasing the worker limit could increase memory and I/O contention without
  addressing repeated prefix reads.
- Unbuffered `FileIO.readline()` preserves exact logical read bounds but turns
  large JSONL line scanning into syscall-heavy work. Explicit buffering keeps
  the same captured-size semantics without that pathological cost.
- Migrating schema 5 would preserve disposable derived data while adding a
  permanent compatibility path.

## Consequences And Guardrails

The append fast path detects replacement and edits at the head or old boundary,
but it does not cryptographically re-verify an unchanged middle prefix. A
pathological middle-of-file in-place edit that preserves file identity and both
guard regions is outside the fast-path contract. This is acceptable because
Codex-owned active JSONLs are append-only during normal operation and Task
Transfer replacements receive new file identities; any failed guard performs a
safe from-zero parse.

Tests compare full, appended, and forced-fallback results with a from-zero
oracle; cover repeated and partial appends, growth, truncation, replacement,
boundary edits, archive ownership, duplicate identities, and rollback; prove
tail-bounded source reads and zero opens for unchanged files; and preserve the
four-process, parent-only SQLite contract. Diagnostics report full parses,
append parses, append fallbacks, and source bytes read. Native macOS Apple
Silicon and Windows x64 packaging remains a non-publishing pre-release gate.

Release validation used the live 2,510-file corpus at 153.23 GB. The buffered
schema 6 cold rebuild completed in 207.4 seconds with no file, cache, worker, or
fallback errors. The next refresh observed two real active-file appends, reused
2,508 generations, read 632,351 source bytes, and completed in 4.08 seconds. A
copy-on-write clone of a 5,497,105,352-byte live task completed cold in 14.95
seconds and unchanged in 0.41 seconds. After a 91-byte append, it read 262,235
bytes and completed in 0.37 seconds; cold, warm, and appended reports were
identical after removing their generated timestamps. The earlier unbuffered
prototype did not finish that same cold parse within 691 seconds, which is why
buffered binary I/O is part of the contract rather than an incidental tuning.
