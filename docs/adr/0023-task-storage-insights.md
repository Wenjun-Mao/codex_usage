# ADR 0023: Read-Only Task Storage Insights

## Status

Accepted; backup portions partially superseded by ADR 0024 and guardian
ownership clarified by ADR 0026

## Context

Codex session storage can grow far beyond the visible root task history because
structured descendants append large amounts of context and output. A storage
release-validation audit on 2026-08-07 observed 196.08 GiB across 2,525 JSONL files; 187.63 GiB
was in structured descendants. The largest trees were therefore not obvious
from a root-task list alone.

Users need to know which task tree consumes space before deciding whether to
start a fresh root task. Direct deletion is risky, and backup, restore, and
compression need a separate verified contract. Task Storage was consequently
a read-only visibility feature in 1.4.0. ADR 0024 adds a non-mutating,
verified backup operation; restore and deletion remain outside this ADR.

## Decision

Version 1.4.0 adds a Task Storage inventory to the dashboard and to the
`codex-usage storage snapshot` command. It reports the current local corpus,
independent of the usage date range, while the dashboard's selected project
filter applies. It uses logical JSONL file bytes, not filesystem allocation,
compressed size, or an estimate of reclaimable space.

The inventory has two deliberate accounting layers:

- Physical-file inventory counts every JSONL file currently present, including
  active and archived files and distinct duplicate physical files.
- Canonical usage generations remain deduplicated for usage, pricing, and
  historical retention. A duplicate or moved file must not create duplicate
  usage, but its physical bytes remain visible in storage accounting.

Each file is assigned to a user-visible root task tree. Nested structured
subagents roll up recursively to their root. Forked user-visible tasks remain
roots. Missing parents are represented as explicit root-missing groups, cycles
and malformed relationships are reported as diagnostics, and no file bytes
are silently dropped. Missing cache entries have zero physical bytes because
the source file is no longer present.

Codex guardian approval logs are structured subagents with a distinct ownership
shape. ADR 0026 defines how their explicit immediate-parent and owner metadata
folds them into the user-visible task tree without hiding their bytes or usage.

Storage metadata is cached and refreshed with bounded reads. Unchanged files
reuse cached metadata; new or changed files read only the bounded metadata
prefix needed for task identity, parent identity, role, project, and title
resolution. Storage aggregation never requires a full usage parse.

The dashboard shows root bytes and structured-descendant bytes separately,
along with total bytes, counts, state, and share. A 1 GiB root-size badge and a
10 GiB total-tree badge are transparent visibility thresholds, not deletion
rules. The original 1.4.0 inventory did not delete, back up, restore, compress,
or estimate compressed size. The backup portion of that boundary is now
governed by ADR 0024; the inventory remains read-only and does not free space.

Codex documentation describes side chats as ephemeral forks. In the observed
local format, a side-chat turn is stored inside its parent root JSONL without a
separate task, file, or durable discriminator. Its bytes and token usage are
therefore included under Root task. The report discloses that inclusion and
does not invent a heuristic third role. A future separate side-chat category
requires reliable upstream metadata and must not retroactively guess older
records.

## Consequences

Task Storage can identify the large root trees and descendant-heavy projects
that should be considered before a fresh root task is started. It can now
provide the input to a verified backup, but it still cannot perform deletion
or restoration. Backup verification and publication are defined separately in
ADR 0024, and safe restore and deletion remain follow-up releases.

The schema 6 cache is disposable and is rebuilt as schema 7 for the first
1.4.0 report. There is no migration or dual-read compatibility path.

## Rejected Alternatives

- Counting only canonical usage generations would hide duplicate physical files
  and make the storage total unsafe for disk-planning decisions.
- Treating every JSONL as an independent visible task would expose structured
  subagents as if they were user-created roots and obscure the actual task
  tree that should be continued or restarted.
- Guessing a separate side-chat role from turn shape would misclassify older
  data because the local format has no durable discriminator.
- Estimating compressed size before implementing verified backup would create a
  number users could mistake for a recovery guarantee.
- Adding delete actions to the first storage view would combine inventory with
  irreversible behavior before a deletion contract is tested. Verified backup
  was intentionally added later as a separate, non-mutating contract in ADR
  0024.
