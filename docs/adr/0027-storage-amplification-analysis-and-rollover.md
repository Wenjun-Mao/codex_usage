# ADR 0027: Storage Amplification Analysis And Task Rollover

## Status

Accepted; implemented in version 1.7.0 on 2026-08-08

## Context

Task-tree size alone does not explain why some Codex tasks consume tens of
gigabytes. A local corpus investigation found that repeated `compacted` rows
can carry large snapshots of prior history, including inline media. Repeating
those snapshots across descendants can dominate storage even when another task
has more turns or more subagents.

The ordinary usage parser can collect this evidence while reading a file, but
existing schema 7 generations do not contain it. Inspecting every historical
file during each Task Storage refresh would also make a normally bounded
inventory unexpectedly expensive. Any diagnosis must therefore state whether
its evidence is complete.

Starting a fresh root task is the safest way to stop inheriting a large active
history, but Codex Usage must not create or delete Codex tasks. Preparation must
first produce a newly verified recovery archive and leave the irreversible
decision to the user inside Codex.

## Decision

Version 1.7.0 replaces the disposable cache with schema 8 and stores
path-keyed content diagnostics for each current JSONL. The diagnostic records
the analyzed byte boundary, guarded file identity, compacted-row bytes, the
largest compacted row, descendant concentration, and bounded inline-media
markers. The normal usage parser and the explicit analyzer share one byte-level
observer; a terminated compacted row can be measured without decoding its full
JSON payload.

Task Storage presents three analysis states: `not_analyzed`, `partial`, and
`complete`. Positive **History amplification** and **Inline media** claims are
permitted only when every current file in the tree is completely covered.
History amplification requires at least 1 GiB of compacted rows and at least
50% of the tree's logical bytes. Inline media is reported only when that
amplification threshold is met and media markers were observed. Unknown or
partial evidence remains visibly unknown rather than being interpreted as a
negative result.

`codex-usage storage analyze --tree-id <id>` scans exactly one selected tree.
It uses at most four read-only workers, prioritizes unread bytes, checkpoints
guarded active-file tails, fully rescans archives, and commits diagnostics in
the parent SQLite transaction only after the selected operation succeeds.
Cancellation or failure retains the previously complete diagnostics.

**Prepare Rollover** is available only for a completely analyzed tree that is
large or history-amplified and is already recovery-ready. It always creates a
new verified format-v1 backup, then provides a text-only starter prompt and a
checklist. It does not create, archive, restore, or delete a Codex task, and it
never replaces an existing backup.

## Consequences

Task Storage can distinguish ordinary tree growth from repeated-history
amplification without pretending that an incomplete scan is conclusive. The
first schema 8 usage refresh rebuilds the disposable cache; afterward both the
usage parser and explicit selected-tree analysis maintain the same evidence.

Content diagnostics count bounded marker occurrences, not decoded media bytes
or filesystem allocation. They are diagnostic evidence, not a promise of exact
reclaimable space. Rollover preparation creates a recovery point and practical
handoff material, while task lifecycle changes remain owned by Codex and the
user.

## Rejected Alternatives

- Treating task size, turn count, or subagent count as the cause would confuse
  correlation with the repeated payload actually occupying disk.
- Scanning the complete corpus whenever Task Storage opens would make a
  read-only inventory too expensive for multi-gigabyte installations.
- Reporting no amplification from partial evidence would be a false negative.
- Decoding every compacted payload would allocate large objects only to count
  bytes and markers already observable from the raw row.
- Automatically creating or deleting tasks would depend on unsupported Codex
  lifecycle mutation and combine diagnosis with an irreversible action.

## Guardrails

- Full-parser and explicit-analyzer results must match byte-for-byte metrics.
- Ordinary append refreshes may read only fixed guard windows and the new tail;
  truncation, replacement, identity loss, or digest mismatch forces a full scan.
- Workers remain read-only and bounded to four; SQLite publication stays atomic
  in the parent process.
- Rollover requires complete analysis, recovery-ready topology, a new output
  path, and successful whole-archive verification before starter material is
  emitted.
