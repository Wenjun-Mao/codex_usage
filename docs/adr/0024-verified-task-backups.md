# ADR 0024: Verified Task Backups

## Status

Superseded by ADR 0031 in version 1.8.0 on 2026-08-27

## Context

Task Storage identifies large Codex task trees, but the files can contain
prompts, source code, and long-running context that a user may need to keep
before starting a fresh root task. Directly deleting or copying JSONL files is
unsafe: a tree can include structured descendants, archived copies, duplicate
physical files, and incomplete relationships. A backup therefore needs to
preserve the observed physical tree and prove that the source did not change
while it was being copied.

This release needs a portable safety net, not a restore system. The archive
contract must be strict enough to reject ambiguous or damaged input while
remaining local-only and practical for multi-gigabyte task trees.

## Decision

Version 1.5.0 adds verified backup for exactly one selected Task Storage tree.
The operation does not mutate Codex storage and does not delete or free disk
space. It preserves every currently present physical JSONL in the selected
root tree, including structured descendants, active and archived copies,
duplicates, and side-chat content already embedded in the root JSONL.

The `.codex-task-backup` format is a streaming PAX tar compressed with zstd.
Format version 1 has a strict manifest, canonical metadata, a SHA-256 for each
payload file, a SHA-256 for the selected session-index entries, and a final
whole-archive SHA-256 reported by both backup and verification. The archive
contains the selected `session-index.jsonl` entries needed to describe the
selected files. Session-index capture is bounded to 64 MiB with bounded input
lines, so an oversized index fails during selection rather than after payload
compression. Compression presets are:

- **Maximum:** zstd level 19; smaller output and slower compression.
- **Balanced:** zstd level 9; faster compression and larger output.

Source path and OS file identity are checked before reading, while each file is
read, and after the archive is written. The complete selected tree and selected
session-index metadata are inventoried again before publication so a new
descendant cannot silently fall outside a long-running backup. The archive is
first written to a sibling `.partial` file, fully reread and verified, and then
atomically published. An existing destination is preserved unless a verified
replacement succeeds. A graceful failure removes the partial. Forced process
termination can leave an unreported hidden sibling partial, but no failure or
cancellation publishes or reports the requested final archive.

Session metadata reads retry transient filesystem failures such as Windows
sharing violations, and an unreadable result is never reused as stable cached
topology. If any corpus file still has unresolved session metadata, every
backup candidate is conservatively downgraded to salvage-only: the unreadable
file's parent cannot be known, so no selected tree can honestly prove that it
contains every descendant.

Missing roots, relationship cycles, or storage-metadata diagnostics produce a
salvage archive with warnings. Such an archive can still be structurally and
cryptographically verified, but its manifest is not recovery-ready. A
recovery-ready archive must have a complete root relationship and no storage
diagnostics. No future restore implementation is promised beyond rejecting
unsupported or invalid format versions.

The CLI exposes:

```text
codex-usage storage backup --tree-id <id> --output <file.codex-task-backup> \
  [--compression maximum|balanced]
codex-usage storage verify <file.codex-task-backup>
```

The VS Code extension exposes a **Back Up** action on each Task Storage row and
the global **Codex Usage: Back Up Task** command. Both flows are project-first
and select exactly one task tree. Backup archives are local files: they are
compressed but not encrypted, and the extension makes no network request and
sends no telemetry for this operation.

## Verification And Publication Contract

Backup creation is successful only after the source identity checks, manifest
checks, payload hashes, session-index validation, decompression, and final
archive digest all pass. Publication is an atomic rename from the verified
sibling partial file. A failed or cancelled operation must not leave a file
that the UI or CLI reports as the final backup.

Verification accepts exactly one zstd frame and the canonical TAR record ending
written by the producer. Missing end markers, non-zero TAR suffix data,
concatenated zstd frames, compressed trailing bytes, global PAX metadata, and
noncanonical per-member PAX fields are rejected. The only permitted PAX field
is the exact `size` extension required when a regular payload exceeds the USTAR
size field.

The format is intentionally strict and versioned. Unknown members, duplicate
members, malformed canonical metadata, path traversal, relationship errors,
size mismatches, and hash mismatches are verification failures. There is no
compatibility promise for a future restore beyond strict rejection of an
unsupported format version.

## Consequences

Users can identify one large tree, preserve it with an auditable archive, and
then decide whether to start a fresh root task. They can verify an archive
without extracting it. The archive may contain sensitive prompts and source
code, so users must protect it like the original Codex logs.

The feature does not reduce the live Codex corpus, restore a task, delete a
task, or estimate reclaimed space. ADR 0027 composes this verified archive with
a text-only starter prompt and checklist, but task creation and deletion still
require separate user actions in Codex. Storage inventory remains read-only,
and backup output is the only new local write made by this workflow.

## Rejected Alternatives

- Copying only the root JSONL would lose structured descendants, archived
  copies, duplicates, or embedded side-chat context.
- Writing directly to the requested destination could expose a partial archive
  after cancellation or a source change.
- Trusting file size or modification time alone would miss replacements and
  in-place changes; identity and digest checks are required.
- Encrypting or uploading archives would add key-management and network
  contracts outside this local safety feature.
- Implementing restore or deletion together with backup would make the first
  release responsible for irreversible storage mutation before its recovery
  semantics are proven.
