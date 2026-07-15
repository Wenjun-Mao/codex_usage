# Flat Single-Process Sync Design

Date: 2026-07-13

Status: Superseded in part by ADR 0013

## Goal

Make selected-conversation sync fast and understandable for large projects while preserving each Codex conversation as one byte-identical JSONL file.

The redesign replaces the per-conversation directory bundle with a flat conversation store and replaces the extension's multi-command pull/push sequence with one plan-driven CLI process.

## User Scenario

The primary workflow remains continuing selected Codex conversations across computers through a user-owned folder such as OneDrive, Dropbox, or another filesystem sync provider.

A particularly valuable case is a long-running task that Codex's built-in handoff cannot complete because the conversation is too large. Codex Usage sync should transfer the original conversation JSONL without summarizing, truncating, or repackaging its context, so the task can be continued on another computer.

## Root Cause Note

### What Failed

Syncing all conversations in selected projects could spend 30 seconds or more in the extension's `Pulling` state even when the destination folder was empty. The existing remote representation also expanded one source JSONL into a directory containing four files, making the sync folder cumbersome to inspect and manage.

### Why It Failed

One extension sync action currently launches separate bundled CLI processes to:

1. resolve project selections through `threads --json`;
2. run `sync status`;
3. run `sync import`; and
4. run `sync export`.

The status, import, and export paths each rebuild local thread state, and import/export rebuild it more than once. A normal large-project run therefore performs five full local session scans across four executable launches. Both packaged targets use PyInstaller one-file executables, so every launch also incurs extraction and startup work. Windows antivirus scanning can amplify that startup cost.

An empty remote folder does not avoid any of this local work, so the progress label makes repeated discovery and process startup look like slow network pulling.

### Evidence

A local macOS benchmark with 205 session JSONLs totaling approximately 379.6 MB measured:

- empty-remote `sync status`: 1.70 seconds;
- no-op `sync import`: 2.42 seconds.

Those measurements exclude the other discovery, export, and executable-launch costs in a complete extension run. They support repeated scanning and process startup as the dominant architectural cause rather than remote-folder I/O.

### Correct Fix Layer

The fix belongs in the sync storage and orchestration contracts. Adding isolated empty-folder checks to import, caching one caller, or changing the progress label would leave the repeated-process and repeated-inventory design intact. The durable fix is one discovery pass, one shared plan, and one execution process.

## Decision Summary

1. Store one remote JSONL for each source JSONL plus one central, repairable index.
2. Add a single `sync run` transaction that plans and executes pull and push actions in one process.
3. Keep the existing three-way, byte-prefix-aware conflict contract.
4. Treat conversation JSONLs as durable data and the central index as reconstructable metadata.
5. Make version 2 a clean break. Detect the old layout and require the user to empty it; do not ship migration-only code.
6. Retire the mutating `sync import` and `sync export` commands. Keep read-only `sync status`, backed by the same planner as `sync run`.

## Remote Storage Contract

The selected sync folder uses this version-2 layout:

```text
<sync-folder>/
  conversations/
    <portable-thread-filename>.jsonl
  sync-index.json
```

There are no per-thread directories, manifests, metadata sidecars, or index-entry sidecars.

### Conversation Files

Each local source JSONL is copied byte-for-byte to exactly one file under `conversations/`. Sync must not parse and rewrite, combine, split, normalize, or summarize the event stream.

The filename mapping must be deterministic and portable across Windows and macOS. A thread id that is already safe as a cross-platform filename may remain recognizable. Unsafe or excessively long ids use a stable hash-based filename. The original thread id remains the authoritative identity in `sync-index.json`, not the filename.

Selection controls participation, not remote deletion. Deselecting a project or conversation must not delete its remote JSONL or index entry.

### Central Index

`sync-index.json` is a format-versioned object keyed by original thread id. Its conceptual shape is:

```json
{
  "format_version": 2,
  "updated_at": "2026-07-13T12:00:00Z",
  "threads": {
    "<thread-id>": {
      "file": "conversations/<portable-thread-filename>.jsonl",
      "source_relative_path": "2026/07/13/<source>.jsonl",
      "index_entry": {},
      "project_key": "<canonical-project-key>",
      "project_label": "<display-label>",
      "sha256": "<content-hash>",
      "size_bytes": 123,
      "session_updated_at": "2026-07-13T12:00:00Z",
      "exported_at": "2026-07-13T12:00:00Z",
      "source_machine_id": "<machine-id>"
    }
  }
}
```

The exact optional fields in `index_entry` may follow the existing Codex session-index data, but thread identity, remote filename, source-relative path, project identity, hash, size, and update provenance are required.

Index merges are keyed by original thread id. A missing or stale index entry never authorizes deletion of a JSONL. When safe, an unindexed conversation file is repaired by reading its `session_meta` event and reconstructing the catalog entry. If identity cannot be reconstructed, sync reports an actionable issue and leaves the file untouched.

### Local Base State

Keep local three-way base state per thread and normalized sync-folder fingerprint. Base state remains local and is not copied into the remote folder. It records the last successfully synchronized content needed to distinguish one-sided progress from divergence.

When importing a thread that already exists at another valid local path, prefer the existing local path rather than creating a duplicate for the same thread id.

## Selection Contract

Both current selection modes remain supported:

- explicit conversations select exact thread ids;
- selected projects select all matching conversations at run time.

Project selection stores canonical project keys, not a frozen list of thread ids. `sync run` performs discovery so a conversation created after sync setup is included on the next run without reconfiguration.

## Single-Process Execution

### CLI Surface

The mutating CLI surface becomes:

```text
codex-usage sync run --sync-dir <path> [--project-key <key>] [--thread-id <id>] --json
```

The selector options are repeatable. The command accepts configured project keys and/or explicit thread ids, discovers the current matching conversations, plans both directions, and executes the plan.

`codex-usage sync status --json` remains a read-only preview. It uses the same inventory and planner code as `sync run`. The old `sync import` and `sync export` commands are retired rather than retained as alternate mutation paths.

### Run Phases

A run follows this contract:

1. Refresh local discovery state once and build one thread inventory.
2. Resolve project and explicit-thread selections from that inventory.
3. Hash only selected source JSONLs.
4. Read the central remote index once for planning and inspect relevant remote files.
5. Build the complete three-way plan before writes.
6. Stop before synchronization writes if any selected thread is a true conflict or the remote snapshot is invalid.
7. Pull all `remote_ahead`, `remote_only`, and `fast_forward_pull` conversations.
8. Push all `local_ahead`, `local_only`, and `fast_forward_push` conversations using the same inventory and plan.
9. Update successful local base states.
10. Merge and atomically replace the central index once after successful file actions.

An empty remote store has zero pull actions. After discovery and planning, the run moves directly to pushes without an import pass.

"Single transaction" means one process, one plan, conflict preflight, and one coordinated execution. It does not claim distributed all-or-nothing filesystem semantics across a cloud-folder provider. Per-file atomicity and repair rules make interruption safe.

### Extension Integration

The extension launches one `sync run` process for `Sync Now` and scheduled synchronization. It passes project keys and explicit thread ids directly; it does not launch a preliminary `threads` process.

In JSON mode, stdout contains one final result object. Progress events use a stable newline-delimited JSON protocol on stderr so the extension can update its status while the same process continues. Ordinary diagnostic logs must not corrupt either machine-readable channel.

Progress phases reflect actual work:

- `Scanning`
- `Pulling`, only when the plan contains pulls
- `Pushing`, only when the plan contains pushes
- `Idle` after completion

Diagnostic JSON includes elapsed time and counts for discovered, selected, remote, pulled, pushed, unchanged, conflicted, and issue entries. These diagnostics support troubleshooting without adding routine UI noise.

## Planning And Conflict Contract

Preserve ADR 0008's three-way, byte-prefix-aware rules:

| State | Action |
| --- | --- |
| local and remote equal | none |
| local changed, remote equals base | push |
| remote changed, local equals base | pull |
| remote is a byte-prefix of local | fast-forward push |
| local is a byte-prefix of remote | fast-forward pull |
| both have non-prefix divergence | conflict |
| local only | push |
| remote only | pull |

Prefix comparison operates on bytes. Sync does not attempt record-level merging or reorder JSONL events.

The planner must classify every selected conversation before applying synchronization writes. Any true conflict aborts all planned pulls and pushes for that run. The conflicting remote candidate may be copied to the existing local `.codex-sync-backups` area for diagnosis, but both authoritative conversation files remain unchanged.

Pulls happen before pushes. Before replacing a local session, preserve the existing backup behavior under `.codex-sync-backups`.

## Atomicity And Concurrent Runs

Every remote JSONL is written to a temporary sibling and renamed into place. `sync-index.json` is written the same way and is replaced last.

Transient filesystem failures in user-owned cloud folders use bounded `tenacity` retries with exponential backoff around idempotent reads, temporary-file writes, and atomic replacements. Validation failures, malformed data, missing referenced files, and detected concurrent changes are semantic outcomes and must not be retried as though they were transient I/O.

The planner records the remote index entry and file fingerprints it observed. Immediately before executing relevant writes, it verifies that those selected remote entries and files still match. Before the final index replacement, it re-reads and merges unrelated entries. If a selected entry changed concurrently, the run stops rather than overwriting another computer's work.

Cloud folders do not provide a portable distributed lock. Optimistic validation is therefore the cross-platform concurrency contract.

If a process stops after writing a JSONL but before updating the index, the JSONL remains valid durable data and the next run can repair its index entry. A missing file referenced by the index is an incomplete remote state, not a deletion signal; sync reports it and does not overwrite blindly.

Malformed index data must produce a clear issue. Repair is allowed only when identity and file state can be established without guessing. No repair path may delete conversation files.

## Version-1 Handling

Version 1 used `threads/<safe-thread-id>/session.jsonl` plus per-thread sidecars. Version 2 does not read or migrate that representation.

If a selected folder contains the version-1 `threads/` layout, both status and run stop with a clear instruction to:

1. remove the old contents from the user-owned sync folder; and
2. run sync again to publish the clean version-2 representation.

The application does not perform that destructive cleanup automatically.

## Module Boundaries

The current Python `sync.py` already exceeds 500 lines and owns storage, planning, execution, and CLI presentation concerns. Implementation must split the sync engine into focused domain modules or a `sync` subpackage with a clean public API rather than extending that file further.

Likewise, extension process orchestration and sync-result parsing should live in focused TypeScript modules instead of adding another responsibility to the already large `extension.ts` and `core.ts` files.

Planner and executor must share typed models. `sync status` and `sync run` must not implement separate classification logic.

## User Documentation

Update both the repository README and the VS Code extension README with:

- the flat version-2 folder layout;
- cleanup-and-resync instructions for existing version-1 folders;
- project and explicit-conversation selection behavior;
- the fact that sync copies original conversation JSONLs rather than summaries;
- the large-task continuation scenario.

Recommended scenario wording:

> Continue a long-running Codex conversation on another computer when a normal handoff cannot complete because the conversation is too large. Sync transfers the original conversation JSONL without summarizing or repackaging its context.

## Testing And Acceptance

### Storage

- One source JSONL produces one byte-identical file under `conversations/`.
- The remote store contains one central index and no per-thread directories or sidecars.
- Portable filename mapping is deterministic on Windows and macOS.
- Unsafe and long thread ids round-trip through their index identity.
- Index reconstruction never deletes unindexed JSONLs.

### Planning And Safety

- Cover unchanged, local-only, remote-only, local-ahead, remote-ahead, both prefix fast-forwards, and true divergence.
- A conflict leaves all selected authoritative local and remote conversation files unchanged.
- Pull replacements create local backups.
- Atomic index updates merge unrelated entries.
- Concurrent selected-entry changes abort rather than overwrite.
- Stale entries, missing referenced files, malformed index data, and unindexed files follow the documented repair/error rules.
- Version-1 layout detection gives cleanup instructions and performs no migration or deletion.

### Selection And Execution

- Project mode includes conversations created after configuration.
- Explicit-conversation mode remains exact.
- One run builds one local inventory and shares it across planning, pulls, and pushes.
- An empty remote folder produces zero pull actions.
- The extension launches one `sync run` process and no preliminary thread-listing process.
- Extension progress only shows pulling or pushing when those actions exist.
- Status and run produce identical classifications from the same snapshot.

### End To End

- A clean two-computer round trip preserves JSONL bytes and session-index metadata.
- Cleanup followed by a new version-2 sync republishes all selected conversations.
- Packaged macOS arm64 and Windows x64 CLIs complete the same sync scenarios.
- Full Python `pytest` and VS Code extension test suites pass after each major implementation slice.

Performance tests should assert operation counts instead of brittle wall-clock limits: one inventory per run, one index read for planning, zero pull actions for an empty remote, and one extension subprocess. A manual packaged-Windows smoke test remains a release check because PyInstaller extraction and antivirus overhead cannot be modeled reliably on macOS.

The practical target is a few seconds for a large selected-project bundle against an empty remote folder. Structured timings must make any regression attributable to discovery, planning, pull, push, or index work.

## ADR Follow-Up

Add ADR 0011 for the flat version-2 storage and single-process transaction contract. It should preserve ADR 0007's bring-your-own-folder decision and ADR 0008's prefix-aware conflict rules while explicitly superseding their version-1 layout and multi-command execution details.

## Rejected Alternatives

### Keep Status, Import, And Export With Fast Paths

Empty-folder shortcuts could reduce one scenario, but separate commands would still duplicate discovery and allow planner/executor behavior to drift. It does not address the root contract.

### Persistent Background Process

A daemon could amortize discovery and packaged-executable startup, but it adds lifecycle, upgrade, crash-recovery, and cross-platform process-management complexity. The agreed performance target does not justify that operational surface.

### Migrate Version-1 Folders Automatically

Migration logic would be exercised once, enlarge the permanent compatibility surface, and risk destructive mistakes in user-owned cloud folders. The user prefers explicit cleanup and a fresh sync.

### One File Per Conversation With Per-Conversation Sidecars

This preserves the clutter that motivated the redesign and creates more opportunities for partially synchronized metadata. One repairable central index is simpler to inspect and update.

## Out Of Scope

- Automatic deletion or cleanup of version-1 remote data.
- Direct integrations with OneDrive, Dropbox, iCloud, or other provider APIs.
- A persistent sync daemon.
- Record-level JSONL merging or conversation summarization.
- Syncing auth, settings, caches, logs, or SQLite databases.
- Conflict-resolution commands such as force-local, force-remote, or fork.
- Intel macOS packaging.
