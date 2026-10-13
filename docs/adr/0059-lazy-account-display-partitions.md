# ADR 0059: Lazy Account Display Partitions

Status: Implemented locally; not released.

## Context

After ADR 0058, the first dashboard after capture still rebuilt display reductions
for every historical quota day and both overlays, even when showing only Today.
The same request also decoded identical provenance labels for each observation.
This is unnecessary presentation preparation, not a need for fresher collection
or looser accounting. The earlier frozen-ledger median was 7.20 seconds.

## Decision

Keep account-wide allowance calculations and all exact readings unchanged. Cache
raw readings by their actual local day, plus the previous and next reading for
each series across day boundaries. Derive and cache a display partition only
when requested by the visible chart. This preserves the eager reducer's exact
endpoints, extrema, ordering, counts, conflicts and both sides of each boundary,
including sparse histories and DST. Balance inspection still uses its original
interval partitions; display inputs use endpoint-day partitions separately.

The disposable breakdown format advances to revision 8. Derived display entries
retain ledger revision, pricing, coverage, timezone and freshness identity, and
are shared across compatible project/range views. Read raw/context partitions
inside the pinned snapshot. The existing writer revision guard also covers lazy
display writes. A late historical reading invalidates context under a new ledger
revision; neither immutable-history assumptions nor latest-timestamp shortcuts
are introduced.

Quota loading projects the observation fields in dataclass order and uses the
existing provenance primary-key index. Identical encoded origin combinations
are decoded once per request. Compacted timestamp expansion, observation order,
all provenance labels, live membership and conflicting readings stay unchanged.

## Alternatives And Consequences

Rejected hiding historical readings, dropping cross-day neighbors, reusing an
old revision's account data, and shifting all work into capture. This removes
unneeded first-load work, but first opening another day pays for that day's
display reduction. Full-history views naturally require all requested days.
Monetary window fitting and quota continuity still inspect account history;
this change does not promise instant cold reports or improve quota RPC latency.

## Guardrails

`test_breakdown_lazy_display.py` compares every lazy day against the eager reducer
with duplicates, conflicts, gaps, spring/fall DST and mixed UTC offsets. It checks
visible-day-only work, warm reuse, project/range reuse, timezone isolation, late
historical evidence and concurrent-capture rejection. `test_allowance_evidence_loading.py`
compares the loader to its prior query with compacted, duplicate, conflicting and
missing-origin evidence, and checks indexed access and bounded origin decoding.

Use `scripts/benchmark_capture_load.py` on a frozen read-only ledger backup.
`--baseline-source` accepts a frozen `src` tree for comparison with the preceding
uncommitted checkpoint. The benchmark pins the disposable presentation revision
on both sides so full HTML (including command scopes) remains comparable; it
never overrides monetary accounting revisions. All writes use temporary ledger
copies. Native VS Code capture, network probes and painting are not measured.

## Local Verification And Remaining Work

Three alternating runs against the frozen ADR 0058 implementation produced these
medians (the earlier 7.20-second case reran at 6.46 seconds under current load):

| Operation | Previous preparation | Lazy display preparation |
| --- | ---: | ---: |
| First Today after revision | 6.46 s | 5.34 s |
| First switch to Yesterday | 1.13 s | 1.36 s |
| Cached Today | 0.040 s | 0.042 s |

First-load CPU time decreased from 6.33 to 4.97 seconds. All paired full-HTML and
transition hashes matched. These results demonstrate reduced first-load work,
not constant-time account preparation. The first visit to a previously unopened
day pays its display-reduction cost rather than having it prepaid on Today.

`pytest -q`: 1,841 passed, one expected skip. Changed-file Ruff and
`git diff --check` passed. Independent read-only review found no actionable
defects; its additional DST, timezone and concurrent-capture test suggestions
were added and passed. No installed extension or live ledger was changed.

Open follow-up: can exact historical allowance-window/continuity preparation be
reused incrementally across captures? Any design must account for late recovered
readings, changed provenance, replaced trusted generations, pricing and plan
changes, and capture-causal cutoffs. A latest-timestamp or append-only shortcut is
not sufficient. This larger optimization is not implemented by this decision.
