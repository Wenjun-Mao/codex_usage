# Three-Way Sync State Design

## Purpose

Make selected-conversation sync distinguish normal one-machine progress from real conflicts. The current sync logic compares only local and sync-folder hashes, so any difference is treated as a conflict. That protects data, but it blocks common workflows where one computer simply continued a Codex conversation and now needs to push or pull the newer JSONL file.

The new design adds a remembered base state and prefix-aware JSONL comparison. Sync should automatically handle linear history and stop only when both sides diverged.

## Current Behavior

Manual and automatic sync currently run the same core sequence:

1. Resolve selected conversations.
2. Run `sync status`.
3. Stop if any selected conversation is marked `conflict`.
4. Import from the sync folder.
5. Export local state back to the sync folder.

The Python sync engine marks a conversation as `conflict` when both local and remote session JSONL files exist and their SHA-256 hashes differ. It does not know what either side looked like at the last successful sync.

## Desired Behavior

Use three-way state for each selected conversation:

- Local: the current session JSONL in `.codex/sessions`.
- Remote: the current session JSONL in the bring-your-own sync folder.
- Base: the last content this machine successfully synced for this conversation and sync folder.

Sync should classify each conversation before changing files:

| Local vs Base | Remote vs Base | Prefix Relationship | State | Default Action |
| --- | --- | --- | --- | --- |
| same | same | any | `synced` | no-op |
| changed | same | any | `local_ahead` | push local |
| same | changed | any | `remote_ahead` | pull remote |
| changed | changed | remote is prefix of local | `fast_forward_push` | push local |
| changed | changed | local is prefix of remote | `fast_forward_pull` | pull remote |
| changed | changed | neither is prefix | `conflict` | stop and preserve both |
| missing | present | any | `remote_only` | pull remote |
| present | missing | any | `local_only` | push local |
| missing | missing | any | `missing` | skip with status |

For Codex JSONL files, prefix comparison is the safest automatic merge rule because normal continuation appends new events. The sync engine should not attempt record-level merging when both sides have different appended tails.

## Architecture

Keep the Python CLI as the source of truth for sync decisions. The VS Code extension continues to own scheduling, settings, status bar feedback, and notifications.

Add a local sync-state store under the Codex home associated with the target sessions directory:

```text
.codex-sync-state/
  <sync-folder-fingerprint>/
    threads/
      <thread-id>.json
```

The sync-folder fingerprint should be deterministic and local-only, derived from the normalized absolute sync folder path. This prevents two different sync folders from sharing base state by accident.

Each local state file stores:

- `sync_version`
- `thread_id`
- `sync_dir_fingerprint`
- `base_sha256`
- `base_size_bytes`
- `base_updated_at`
- `last_remote_sha256`
- `last_local_sha256`
- `source_relative_path`
- `project_key`
- `project_label`
- `synced_at`

The sync folder manifest remains useful for remote diagnostics and cross-machine metadata. Extend `threads/<thread-id>/manifest.json` with compatible additive fields:

- `session_sha256`
- `session_size_bytes`
- `updated_at`
- `exported_at`
- `machine_id`
- `source_relative_path`
- `project_key`
- `project_label`

Older manifests that lack new fields should still work by hashing the remote session file at runtime.

## Sync Planning

Add a planning step in Python that returns a per-thread sync plan. `sync status --json` should expose this plan without changing files. Import/export should use the same planner internally so status and execution agree.

Per thread, the planner gathers:

- local path, hash, size, and updated timestamp
- remote path, hash, size, and manifest metadata
- local base state, if present
- prefix relationship when both files exist and hashes differ

The planner then emits:

- `state`
- `action`: `none`, `pull`, `push`, `skip`, or `conflict`
- `reason`
- local and remote hashes
- base hash if known
- local and remote updated timestamps
- memory diagnostic fields that already exist

When no base state exists, the planner should still avoid false conflicts where possible:

- local only means push
- remote only means pull
- identical local and remote means synced and initializes base state
- differing local and remote with one as a prefix of the other can fast-forward to the longer file and initialize base state
- differing local and remote with no prefix is a real conflict

## Execution Flow

Manual `Sync Now` should still be pull-before-push from the user's perspective, but execution should be plan-driven:

1. Build the sync plan.
2. If any selected conversation has `conflict`, stop before changing files.
3. Pull all `remote_ahead`, `remote_only`, and `fast_forward_pull` conversations.
4. Recompute or update the plan for affected conversations.
5. Push all `local_ahead`, `local_only`, and `fast_forward_push` conversations.
6. Write local sync-state records after each successful per-thread pull or push.
7. Merge `session_index.jsonl` entries using the existing newest-entry rule.

Automatic sync uses the same plan and execution rules. The scheduler remains quiet unless user action is needed.

## Conflict Handling

A real conflict means both local and remote have content that cannot be explained as a prefix-based linear continuation from the base.

For MVP behavior:

- Do not overwrite either side.
- Save the remote candidate under `.codex-sync-backups/<timestamp>/<thread-id>/remote-conflict-session.jsonl`.
- Keep local unchanged.
- Return status `conflict` with a clear reason.
- Show a visible warning for manual sync and a rate-limited warning for automatic sync.

Conflict resolution commands are out of scope for this slice, but the design should leave room for later actions:

- keep local and push it
- keep remote and pull it
- fork remote into a separate local session file

## Edge Cases

### First Sync On A New Machine

If only remote exists, pull it and write base state. If only local exists, push it and write base state. If both exist and are identical, write base state without copying.

### Machine State Deleted

If `.codex-sync-state` is deleted, use prefix comparison and hashes to classify safely. Non-prefix mismatches become conflicts because the base is unknown.

### Same Thread At Different Local Paths

If the local thread id exists at a different path than the manifest's `source_relative_path`, prefer the actual local thread path. This preserves the previous duplicate-path safety rule and avoids creating a second local file for the same thread.

### Repository Rename Or Project Transition

Sync identity is thread id first, not project label. Project metadata in manifests is advisory for pickers and status. A repo rename or project transition should not create a sync conflict by itself.

### File Locked By Codex Or VS Code

Keep the existing backup-before-overwrite behavior. If Windows denies a replace because a file is locked, return an actionable issue state and let the scheduler back off. Do not retry rapidly.

### Remote Sync Folder Lag

Cloud folders can expose stale or partially updated files. Atomic temp-file-then-rename writes remain required. Status should treat missing manifest or missing session file as `missing` or one-sided, not as conflict.

### Truncated Or Corrupt JSONL

Prefix comparison should operate on bytes, not parsed JSON, so it can safely detect append-only relationships without needing to parse partial files. Parsing errors should still be surfaced in thread listing/reporting as they are today.

### Session Index

`session_index.jsonl` remains secondary. Sync planning is based on session JSONL files. Import should merge index entries after successful file updates, keeping the newest `updated_at` for each thread id.

### Memory Database

Continue diagnostics only. Do not sync SQLite. If memory rows are detected for a selected conversation, status should keep reporting that this beta does not sync memory database rows.

## Status And UX

`Codex Usage: Sync Status` should report useful states instead of only `synced` or `conflict`:

- `synced`
- `local_ahead`
- `remote_ahead`
- `fast_forward_push`
- `fast_forward_pull`
- `local_only`
- `remote_only`
- `conflict`
- `missing`

The summary message should be direct:

- `3 conversations synced`
- `2 local changes ready to push`
- `1 remote change ready to pull`
- `1 fast-forward update`
- `1 conflict needs review`

Manual `Sync Now` should show success when it completes a pull, push, or both. It should only show conflict when the planner finds true non-prefix divergence.

## Compatibility

This is a beta-breaking internal sync improvement, but public commands stay the same:

- `codex-usage sync status --json`
- `codex-usage sync import`
- `codex-usage sync export`
- `Codex Usage: Sync Now`
- `Codex Usage: Sync Status`

Existing sync folders should continue to work. Missing local sync-state files should be initialized on the next successful sync. Existing manifests should be read with defaults.

## Testing

Python tests should cover:

- local-only first sync plans a push
- remote-only first sync plans a pull
- identical local and remote initializes base and is synced
- local changed while remote equals base plans push
- remote changed while local equals base plans pull
- local extends remote by byte prefix plans fast-forward push
- remote extends local by byte prefix plans fast-forward pull
- both changed with non-prefix tails plans conflict and does not overwrite
- missing local state falls back to prefix rules
- duplicate thread id at a different local path preserves existing local path
- import creates backups before overwriting changed local files
- sync status JSON includes states, actions, hashes, and reasons

TypeScript tests should cover:

- parsing the richer status summary
- user-facing conflict messages remain visible for true conflicts
- manual sync still bypasses auto backoff
- action strip and status bar remain unchanged except for clearer status text when available

Smoke tests should cover:

- one machine pushes a selected conversation
- another machine pulls it
- the second machine continues the conversation and pushes
- the first machine pulls that continuation without conflict
- two machines append different tails and sync reports a conflict without overwriting either side

## Non-Goals

- Do not sync auth, config, caches, logs, or SQLite databases.
- Do not add cloud-provider APIs.
- Do not implement record-level JSONL merging.
- Do not add conflict-resolution commands in this slice.
- Do not change project/conversation selection UX.
- Do not change the VS Code scheduler timing policy.
