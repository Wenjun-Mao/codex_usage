# ADR 0019: Bounded Parallel Cache Refresh

## Status

Accepted.

## Context

Large usage-cache refreshes were slow because independent file parsing and
cross-file transition work shared one serial path. The root cause was a
missing ownership boundary: raw candidates, mutable-file verification, and
SQLite generation commits could not safely be treated as independent child
work. A recovery design also needs to distinguish a file-level parse failure
from process-pool infrastructure failure without losing the last complete
generation.

## Decision

Use a bounded process pool for independent parsing. Resolve the worker bound
from `os.process_cpu_count()`, task count, and a hard maximum of four. Use the
`spawn` context. Report resolved worker count, worker PIDs, overlap,
`serial fallback`, the `infrastructure` error, and the per-file error count so
parallelism and failure classification are observable.

Workers return ordered parse results and raw candidates only. The parent
process owns mutable-file verification, transition evidence, and SQLite
access. It uses one global verification cache for all raw candidates, reads
the read-only `state_5.sqlite` evidence in the parent, and keeps child SQLite
guards to prove that workers do not access or mutate databases.

Commit refresh results in groups of eight. Each successful parse replaces one
complete file generation in one SQLite transaction. A per-file error records
the error and preserves the previous complete generation; it does not trigger
pool fallback. A pool construction, submission, or result-transport failure
is infrastructure-only and activates one observable serial fallback for the
current and remaining work.

There is no byte offset checkpoint. The recovery unit is a complete file
generation: after interruption, committed generations are reused and the
unfinished generation is reparsed. Preserve schema version 3 and the existing
cache identity and ordering contracts. Canonical session IDs are authoritative
cache keys. Files whose metadata cannot be read use deterministic SHA-256 keys
in an explicit path-fallback namespace; allocate those keys against all
canonical and fallback keys in the inventory so neither mtimes nor discovery
order can hide a valid session or an unreadable-file error.

Native packaged-smoke commands use durable process-tree ownership. POSIX uses
a new session and process-group termination. Windows creates a Job Object with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, starts a controller blocked on a launch
gate, assigns that controller to the Job, and only then releases it to spawn
the target. The target and descendants inherit Job membership, while the
parent retains the Job handle after the target root exits. Timeout cleanup
terminates and closes the Job before bounded output drain and reap.

Validate the native acceptance contract with source/frozen PID-overlap proof,
child SQLite guards, oracle equivalence, a Windows root-exits/child-survives
Job-ownership smoke, and a manual non-publishing dual-native workflow before
tag as a pre-publish gate on macOS Apple Silicon and Windows x64.

## Rejected Alternatives

- Threads would not provide the required process isolation or make worker
  ownership and overlap evidence unambiguous.
- Range pruning could skip changed content and would make complete-generation
  recovery depend on a fragile byte-range contract.
- Transition schema caching in workers would split schema ownership and could
  observe stale cross-file state.
- Worker path verification would duplicate mutable-file reads and break the
  parent-owned one global verification cache contract.
- Append checkpoints would expose partial generations and make interruption
  recovery mix old and new file records.
- Windows console process groups plus `taskkill` do not retain ownership after
  a target root exits. Assigning the target after `Popen` also leaves a race in
  which it can spawn an unowned descendant before Job assignment.

## Consequences And Guardrails

The refresh has a fixed upper bound of four child workers and remains
deterministic when completion order varies. A parse or transition read error
is reported as a per-file error, while infrastructure failure is separately
observable and may cause serial fallback. SQLite writes and all verification
remain in the parent process, including read-only access to `state_5.sqlite`;
children must satisfy the SQLite guards.

The eight-file commit group bounds the amount of work that can be replayed
after interruption without pretending that an append checkpoint exists.
Complete file generation replacement preserves the last known-good rows, and
schema version 3 remains the recovery compatibility marker. Source/frozen
PID-overlap proof must show real spawned overlap without the parent PID;
oracle equivalence must show the same aggregate result as the serial path.
Windows CI must additionally prove that a root can exit while a pipe-inheriting
child remains alive, then that timeout returns within its bound and the child
is gone. The manual non-publishing dual-native workflow before tag is required
as the pre-publish gate for macOS Apple Silicon and Windows x64.
