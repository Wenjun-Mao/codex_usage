# ADR 0013: Manual Directional Cross-Platform Sync

Status: Accepted

Date: 2026-07-14

## Context

ADR 0011 defined one bidirectional `sync run` operation and required identical local and remote task JSONL bytes. Testing a Windows-to-macOS pull exposed a deeper contract problem: Codex groups a task under a project using the task's saved `session_meta.payload.cwd`. A byte-identical pull therefore retained the Windows checkout path and left the imported task outside the matching macOS project. Large task JSONLs can contain multiple session histories, and the effective project metadata can come from a later matching `session_meta` record rather than only the first row.

Rewriting cwd also makes automatic bidirectional sync too risky. A background run could publish a machine-local path rewrite or combine an unseen remote update with a local transfer before the user chooses a direction.

## Decision

Replace `sync run` with explicit `sync pull` and `sync push` commands. The extension exposes **Pull Tasks** and **Push Tasks** and has no activation, focus, timer, or file-watcher sync trigger. `sync status` remains read-only. Each directional command still uses one inventory, the shared three-way planner, full conflict preflight, snapshot validation, and one process.

Direction limits mutation:

- Pull executes only planned pull actions. It may write local task JSONLs, local sync state, backups, and local session-index metadata. It does not publish local tasks or commit remote index repairs.
- Push executes only planned push actions. It may write remote task JSONLs and the remote catalog plus local baseline state. It does not import remote task bytes or remote session-index metadata.
- Planned actions in the opposite direction remain visible in the result. Conflicts and structured issues block either direction before transfer.

On pull, bind an imported task to a local project through canonical project identity. Prefer an existing native local cwd when it already belongs to that identity. Otherwise, resolve exactly one matching project from Codex's saved workspace roots. A missing or ambiguous match is a blocking issue; sync never guesses a checkout path.

Use the workspace-root spelling exactly as Codex saved it. Filesystem resolution is allowed for existence checks and duplicate detection, but must not replace a saved symlinked or macOS alias path with a different spelling because Codex uses the saved path to group tasks.

When binding requires a different local path, rewrite `session_meta.payload.cwd` in every local metadata record whose normalized Git repository or cwd alias matches the selected task's project identity. Preserve unrelated metadata and every non-metadata record byte for byte, and leave the remote JSONL unchanged. If every matching cwd already has the local value, preserve the complete JSONL byte for byte. A task with local unsynced changes and a foreign cwd is blocked rather than overwritten or pushed.

Persist `last_local_sha256` and `last_remote_sha256` as a paired baseline. The planner treats differing local and remote hashes as synchronized only when each side still matches its own recorded hash. A real edit on either side is then classified against the corresponding baseline.

## Alternatives Considered

- Patch only Codex's SQLite cwd field. Codex rebuilds that value from the JSONL, so the patch is not durable.
- Write Codex desktop's private project-assignment state. That is an unsupported application-internal contract and is unavailable to the VS Code extension.
- Keep byte-identical pulls and ask users to find imported tasks outside their project. This fails the primary cross-platform continuation workflow.
- Keep automatic bidirectional sync with cwd rewriting. This makes a machine-local binding decision in the background and obscures which side is authoritative.
- Use a one-time migration helper. Existing selected tasks can be repaired safely by the normal Pull contract, so permanent migration-only code is unnecessary.

## Consequences

Users choose transfer direction explicitly. A cross-platform pull can produce an intentionally different local hash, but only because the local session metadata names the local checkout. The remote copy remains portable source data for other machines. A project must be open or saved in Codex, and Git-backed projects need matching canonical repository identity for automatic binding.

Codex can retain an already-imported task's previous cwd in its running SQLite projection after an in-place JSONL rebind. Quit and reopen Codex to rebuild that projection when the task remains grouped under the old path. Sync keeps SQLite read-only and does not add a private-database workaround.

The status result can report pending work in the opposite direction after a successful command. Pull and Push may therefore complete with zero transfers without implying that every selected task is synchronized.

## Guardrails

- Never run sync from activation, focus, timers, or filesystem watchers.
- Never execute a pull action during Push or a push action during Pull.
- Never commit remote repairs during Pull or merge remote session-index metadata during Push.
- Rewrite cwd only in local metadata records matching the selected project; preserve unrelated metadata and all non-metadata records, and leave the remote file unchanged.
- Require one unambiguous canonical local project match before importing or rebinding a task.
- Preserve the exact Codex-saved workspace-root spelling when materializing cwd.
- Block foreign-cwd tasks with unsynced local changes instead of overwriting or publishing them.
- Compare each side with its own recorded hash after local materialization.
- Keep conflict preflight, atomic replacement, backups, and observable-boundary revalidation in both directions.
