# ADR 0011: Flat Single-Process Sync

Status: Accepted

Date: 2026-07-13

## Context

ADR 0007 established selected-conversation sync through a user-owned local or cloud-synced folder. ADR 0008 established three-way, byte-prefix-aware conflict handling. Version 1 expanded each conversation into a directory with sidecar metadata and required separate status, import, and export processes. Large selections therefore repeated discovery and executable startup, while the remote representation was harder to inspect and more vulnerable to partial metadata updates.

This decision preserves ADR 0007's bring-your-own-folder model and ADR 0008's conflict semantics. It supersedes only their version-1 per-thread sidecar layout and multi-command mutation flow.

## Decision

Version 2 uses this exact remote tree:

```text
<sync-folder>/
  conversations/
    <portable-thread-filename>.jsonl
  sync-index.json
```

Each conversation JSONL is byte-preserved durable data. `sync-index.json` is a repairable catalog containing identity, location, hash, size, project, session-index metadata, and synchronization provenance. A missing or stale index entry never authorizes deletion of a conversation file. When identity can be established safely, later inventory work may reconstruct or refresh catalog data from the durable JSONL.

The mutating interface is `sync run`. One run uses one process, one active-session discovery inventory, one shared plan, conflict preflight, pulls before pushes, and one final index commit. `sync status` uses the same inventory and planner and remains read-only. The VS Code extension starts exactly one child process for Sync Now and passes selected project keys and thread ids directly to it.

Current sync discovery considers active `sessions` conversations only. Archived conversations remain available to usage accounting, but version 2 does not discover or synchronize `archived_sessions` conversations.

Selection governs participation only. Deselecting a project or conversation never deletes its remote JSONL or index entry. Project mode stores project identity rather than a frozen thread list, so later runs discover newly created matching active conversations.

The planner retains ADR 0008's byte-level three-way rules:

| State | Result |
| --- | --- |
| Local and remote equal | No transfer |
| Local changed; remote equals base | Push |
| Remote changed; local equals base | Pull |
| Remote is a byte prefix of local | Fast-forward push |
| Local is a byte prefix of remote | Fast-forward pull |
| Both have non-prefix divergence | Conflict |
| Local only | Push |
| Remote only | Pull |

The planner classifies all selected conversations before transfer. A true conflict stops all planned pulls and pushes; sync does not merge records or overwrite either authoritative side.

A cooperative sibling `FileLock` serializes mutating runs made by this tool. User-owned cloud folders provide no portable distributed compare-and-swap or lock, so non-cooperating writers remain outside that lock. Sync revalidates selected index entries and files at observable boundaries, and the final index merge preserves unrelated entries. This is optimistic validation, not distributed all-or-nothing behavior.

Conversation files and the index are written through sibling temporary files and atomically replaced. Hash and size verification confirms copied conversation bytes. Path guards prevent traversal after a parent swap; cleanup may intentionally leave a detached temporary file when traversing the changed path would be unsafe.

Verified byte transfer and repairable bookkeeping are separate guarantees. A run may be interrupted after conversation bytes are installed but before local base state, session-index metadata, or the remote catalog is committed. When the bytes already match, a later no-op run may reconcile that bookkeeping without copying the conversation again.

Machine mode is a strict protocol: progress is statefully decoded UTF-8 JSONL on stderr, and stdout contains exactly one final JSON object. Consumers parse the final result only after the process closes and both stdout and stderr have ended; the contract does not impose a cross-stream emission order. Results use structured `completed`, `conflict`, or `issue` outcomes; diagnostics must not corrupt either channel.

Version 2 performs no migration and no automatic destructive cleanup. Users with version-1 contents must empty the old sync-folder contents themselves and rerun sync to publish the version-2 representation.

## Alternatives Considered

- Keep separate status inspection plus import and export mutation commands with local fast paths. This retains repeated process startup and multiple inventories.
- Keep per-conversation directories and sidecars. This leaves metadata fragmented and increases partial-state combinations.
- Add automatic version-1 migration or cleanup. This adds a permanent compatibility path and risks deleting user-owned cloud-folder data.
- Claim a distributed transaction across cloud providers. Their filesystem abstractions do not offer a portable lock or compare-and-swap contract.

## Consequences

Large selections require one discovery pass and one executable launch from the extension. The remote folder is directly inspectable, and interrupted metadata updates can be repaired from verified conversation files. Conflict behavior remains conservative and byte based.

The central index can temporarily lag durable files. Concurrent non-cooperating writers can still race, so a run may stop with an issue after completing some verified file actions. Temporary files can remain detached after a detected parent swap and may require manual inspection.

## Guardrails

- Never treat deselection, a missing index entry, or a missing referenced file as permission to delete a conversation.
- Never rewrite, summarize, split, combine, or normalize a conversation JSONL.
- Keep status and execution on the same planner, and preflight conflicts before transfer.
- Revalidate selected remote state before observable mutations and merge unrelated index entries at the final commit.
- Verify conversation replacements by hash and size; keep bookkeeping repairable on a later no-op run.
- Keep version-1 cleanup explicit and user performed. Do not add migration-only or destructive cleanup behavior without a new ADR.
