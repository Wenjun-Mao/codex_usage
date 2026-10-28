# SQLite And Cleanup Release, Without The Indexer

Updated: 2026-10-28, America/Toronto.
Status: owner authorized E2E execution with Relay Direct on October 28.
Normal-agent integration and scoped source/runtime checks pass; hosted native
package qualification and publication remain outstanding.

## Outcome And Owner Decisions

Publish the latest verified official, unmodified SQLite engine and safe idle
storage cleanup on the shipped **2.13.1 normal report path**, for macOS ARM64
and Windows x64. Preserve exact accounting, reports/actions/full CSV, Terra
support, capture responsiveness and retained source history. Do not restore a
512 MiB derived-data limit. Both official downloads must match qualified bytes.

The owner explicitly selected **SQLite + cleanup first; defer indexing and
performance** on October 28. This supersedes the original combined-release
requirement. Terra already shipped in 2.13.1; it is retained, not reimplemented.
The earlier acceptance of slower index construction remains a decision for
the parked indexer, not a reason to bring it into this release.

Technical proposal: a maintenance release, provisionally **2.13.2**. Check that
the version is unused at freeze; the director may choose the next appropriate
unused maintenance version without changing scope. No tag is reserved now.

## Current Facts And Preservation

- Remote main was verified at `2a9b0707e68ecf686f64a552744ce02eaa9aefa4`.
  `v2.13.1` remains at `7623df49ca789b72b67579194f23648bbe33fab9`.
- The clean checkout `/Users/wjmao/projects/codex_usage-terra-release` contains
  that main and is the proposed execution checkout. Reuse it after checking for
  concurrent changes; no new clone or managed worktree is needed by default.
- Combined code stays at `e740baf1`, followed by preservation docs `077a6098`,
  in `/Users/wjmao/projects/codex_usage-release-2.14.0`. The original v3 commit
  `70f546d82c054c422e6667bc1b306d53f2edc341`, preservation branch/bundles,
  `.local/` controllers, private evidence and unrelated owner files stay intact.
  The previous detailed combined plan is recoverable at `077a6098` under this
  same path; its measured results remain in the linked research record.
- SQLite 3.54.1 is currently the latest upstream release, independently checked
  October 28 against the [official download page](https://www.sqlite.org/download.html)
  and [release history](https://www.sqlite.org/chronology.html). Recheck once at
  freeze. Pin the chosen version, source ID and archive checksum consistently;
  never chase a moving latest version after qualification starts.
- Previous SQLite/cleanup local tests and synthetic WAL/capture results are
  reusable design evidence, not proof of the new extracted candidate. See
  [local qualification](../research/2026-10-25-sqlite-and-storage-cleanup.md),
  [ADR 0079](../adr/0079-sqlite-runtime-and-idle-reclamation.md) and the
  [delivery retrospective](../research/2026-10-27-combined-release-continuation.md#relay-review-delivery-retrospective)
  in the preserved checkout. Port/update only the relevant historical guidance
  when documenting the eventual candidate, not the whole research collection.

## Scope And Alternatives

Selected: port the standalone runtime/maintenance changes onto released main.
The two credible alternatives were continuing the entire unproved indexer or
shipping a runtime-only release. The owner chose the smaller SQLite/cleanup
outcome; neither alternative is silently substituted if extraction is harder
than expected.

In scope: official engine provisioning and package proof; operation-lifetime
notifications; coalesced idle PASSIVE progress; carefully fenced, event-driven
TRUNCATE; maintenance status; connection-owned TEMP cleanup; unchanged retained
data, normal report/cache behavior and ordinary update semantics.

Out of scope: `read_model/`, semantic/Facts products, resumable quota/reset
interpretation, prepared-index adoption, index reader renewal/WAL anchors,
new schedulers or transfer formats, dashboard speed optimization and the old
A1/C1 construction campaign. The unshipped 64/32 MiB indexed HTML/range cache
policies stay with that backend; do not add those formats merely to prune them.
Existing released caches keep their current behavior. No history TTL, aggregate
size cap, routine VACUUM, reduced durability or sidecar/temp-directory sweeper.

## 1. Extract A Small Complete Candidate

Refresh remote facts and check preservation refs without rewriting them. Copy
this reviewed plan into the clean execution checkout. Keep one writer there;
native reviewers are read-only. Do not merge or cherry-pick the mixed combined
commit (882 files), nor copy its agent/build files wholesale.

Use these preserved owners as a port map, checking their actual dependency
closure against 2.13.1 before copying:

- `sqlite_runtime.py`, `scripts/runtime_sources.py`, `runtime_windows_sources.py`,
  `build_sqlite_runtime.py`, `build_sqlite_runtime_windows.py`,
  `check_sqlite_runtime.py`, `macos-package-runtime.sh` and Windows toolchain
  helpers. Reuse hash/manifest-verified private builds where inputs match.
- `sqlite_activity.py`, `sqlite_maintenance_lock.py`, `sqlite_wal.py` and the
  non-indexer portion of `agent_storage_maintenance.py`.
- Small hooks in `ledger_schema.open_ledger`, `ledger_maintenance`,
  `sqlite_writer_admission`, `agent_rebuild`, `agent_runtime` startup/tick/status/
  shutdown and `agent_main`'s memory-only `--sqlite-runtime` diagnostic.
- The four existing native collector build entrypoints, package environment
  preparation, hosted Core runtime selection, and `scripts/release/policy.py`'s
  build-contract closure. Do not import index-specific report/build identities
  or `--report-runtime` merely because the saved build scripts contain them.

`ledger_writer_contract.py` already matches the released baseline; keep its
schema/accounting semantics. No source schema or report algorithm change is
planned. Remove index-specific methods from the port, not from preserved code.
Keep additive maintenance status separate from report content. If an apparent
dependency needs a new indexer/representation or a change in promised safety,
record that concrete coupling and reassess scope before doing the larger work.
Ordinary extraction fixes do not need human approval.

Keep actual per-platform Python/OpenSSL identities explicit. Reuse established
pinned builders without unrelated dependency upgrades, system Python changes or
TLS bypasses. Source/build hash checks must detect modified cached inputs.
The actual Python-linked/frozen engine, not the system sqlite3 CLI, is decisive.

## 2. Prove Normal-Path Integration Early

Before broad hardening, use a disposable home through the real agent scheduler
and HTTP/report/capture entrypoints. Prove that the installed candidate code,
not a directly constructed maintenance helper alone, requests and completes
idle progress; preserves a write arriving during maintenance; retries after
reader release without another write; and joins its maintenance worker on
shutdown. Exercise startup, an ordinary capture, reports, one existing source
rebuild/reclaim event and restart. No index bootstrap may occur or be required.
Include deferred eligible reclaim -> restart -> blocker release, with no new
write/rebuild: physical reclamation must eventually complete and logical data
must stay unchanged. Recover eligibility through existing durable information
or one safely fenced startup reclaim event; the director chooses the smallest
sound mechanism. This does not require a new persistent work-journal system.

Use real nonempty synthetic WAL and SQLite connections. PASSIVE may run without
holding the capture lane/general writer lease through disk I/O. TRUNCATE requires
an eligible reclaim/pressure event, caught-up progress, owned quiescence,
no-wait local/parser and cross-process maintenance fences, and SQLite's own
exclusive connection fence followed by NOOP frame recheck. Busy external readers
or writers defer reclamation; they are not terminated. Normal append/eviction
does not request physical truncation on every operation. A raced append cannot
turn the short exclusive phase into copying a large backlog.

Keep checkpoint growth reservation before I/O, close-time checkpoint suppression,
private paths/permissions and reader/writer ownership. The 512 MiB free-space
pressure signal is not a retained-data ceiling. TEMP belongs to its connection
through work/validation/commit and closes on success, failure and cancellation.
No database sidecar is deleted to make the test pass.

Decision point: if this integrated normal-path slice works, continue. If it
reveals a necessary architectural change, apply Relay Review to the concrete
gap rather than restarting the old repair queue. Merely exceeding a duration
forecast is not a stop condition or a reason to ask permission again.

## 3. Freeze Focused Safety And Regression Evidence

Port the applicable existing runtime, WAL, privacy, TEMP, writer-admission,
agent-maintenance and builder tests. Keep 2.13.1 tests/case identities; exclude
only genuinely unshipped indexer-specific cases by not importing that feature.
Check runtime mismatch, partial/busy checkpoints, reader-release retry, reclaim
coalescing/lost events, low space before writes, raced append, external process
fencing, startup/error cleanup, repeated close and shutdown. Review the scoped
production diff independently; repair findings and rerun affected checks.

Reuse `scripts/wal_maintenance_benchmark.py` through the existing collector
benchmark entrypoint. Port only its WAL adapter/dispatch arguments into the
released entrypoint, not the saved file's unrelated indexer CLI additions. Adapt
its experiment-budget dependency if needed; do not import a new backend or
create a new benchmark framework. Retain one
excluded preparation pair plus ten alternating cleanup-off/on measured pairs
with the existing 256 MiB random-data WAL and actual capture bookkeeping. Both
arms retain normal capture auto-checkpoint behavior. Assert actual capture/
checkpoint overlap, equal logical records and integrity, physical reclaim when
eligible, and the existing BOTH >10% AND >100ms material-regression guard. Record
queue delay, capture wall/CPU and checkpoint duration separately; a long PASSIVE
call is not itself a capture hold. Keep all measured/failing samples.

Also compare frozen released 2.13.1 and candidate normal-path Today, unopened
30-day, warm, post-append and full CSV results on identical disposable inputs,
paths and clocks, including Terra and quota/reset boundary cases. Require exact
accounting, output ordering, action semantics and CSV. Normalize only expected
version/generated-time and nondeterministic elapsed/cache presentation fields,
never prices, coverage, rows or totals. Use matched repeated measurements and
the same material-regression guard; no new speedup target or accepted-A1 race.
Retain baseline runtime and candidate runtime identities, work counters and
observed memory. No unexplained whole-history rebuild or maintenance queue
growth may be introduced into ordinary capture/report work.

Run affected local checks, Ruff, extension tests/build and the existing selected
release preflight. The full hosted Python inventory remains required; do not
duplicate it locally just to dispatch. Reuse valid exact-input preflight receipts
without relabeling older proofs. File modularity follows the owner's 400/500-line
guidance; no unrelated size-only refactors. No arbitrary experiment cap, one-home
restriction or repeated cold build from the old campaign is inherited. Preserve
existing private evidence; use actual free-space/headroom and owned scratch.

## 4. Qualify Both Platforms And Publish Exact Bytes

Freeze scoped metadata/changelogs, candidate commit, upstream engine inputs and
qualification contract. Build/runtime helpers and the in-package engine probe
belong in the contract. Use the existing main-based manual qualification,
credential-free dry-run and exact-artifact promotion workflow. First hosted
qualification must exercise the native Windows runtime/build too; portable
tests or the Mac builder do not establish Windows success. Repair native build
failures in their owning helpers, not by weakening linked-engine requirements.

Require complete hosted Core/JUnit with zero skips and preserved case inventory,
both VSIX package/collector/archive/handoff gates, existing five visual suites
and exact-package native macOS proof. Each frozen collector must report the
chosen official version/source ID and appropriate build options; Windows must
also prove its private loaded DLL path. Extend existing packaged smoke on each
target with a small nonempty-WAL fixture, real agent scheduler-driven frame
progress and eligible physical reclamation, preserving logical data. An
`absent`/`not_wal` outcome, status object alone or source-interpreter engine
probe is not cleanup proof. Reuse disposable fixtures, not another full timing
campaign for each package. Existing Windows editor-UI coverage remains
explicit; do not invent a new UI runner as a dependency of this release.

Observe existing runs by their actual run/attempt. A transport/observer timeout
is not permission to dispatch or upload again. The Terra release demonstrated
that the convenience coordinator rejects attempt 2: use the documented manual
inspection/public-verification and checked receipt APIs for genuine retries.
If a tiny observer fix is needed, do it before candidate freeze with focused
tests; do not require that optional repair or a coordinator rewrite to publish.
Never falsify an attempt, move an already qualified tag or discard intents.

After authorized promotion, wait for both official versioned Marketplace entries
and download each target. Compare SHA-256/size with qualified artifacts and
catalog hashes. Then generate, commit and push the receipt/status docs without
changing tag/packages. Close workers/reporting routes, reap owned processes,
retire only expendable owned scratch, and leave wanted work recoverable. Do not
remove the preserved bundle or its private evidence as release cleanup.

Completion means both public byte checks and durable receipt, not green source
tests, an uploaded package or one visible platform. No live installation is part
of completion. The indexer remains deferred after this release.

## Permissions, Forecast And Review

The owner has now explicitly authorized E2E implementation and created an active
Goal. Carry forward standing Relay task/model/effort authority, local dependency/build and
disposable verification permission, this bundle's required qualification/
promotion/publication authorization, and ordinary repairs/recovery. Do not ask
again for already covered actions; unrelated CI remains prohibited. A native
account confirmation, if actually required, cannot be bypassed. Record only
decisions that materially affect risk, scope, evidence or delivery.

No live agent installation/restart, live ledger/settings cleanup, original
session/account RPC access or private evidence upload is authorized. Existing
local retained evidence may inform diagnosis but need not be restaged for this
smaller release. Any new scope/safety concession goes to the owner; routine
internal reviews and safe retries do not create approval gates.

Forecast: **4-8 hours of engineering/local verification/review/closeout**, plus
roughly **1-3 hours of hosted build/qualification/publication waiting**, assuming
the saved builders remain viable. Expect the first integrated slice in roughly
1-2 hours. These are forecasts, not deadlines or artificial stopping quotas.
Native Windows build failure or unexpected coupling changes the forecast; state
that promptly with evidence instead of silently starting another architecture.

Direction reviews occur after the integrated slice and proportionately before
publication/closeout. They judge this narrow outcome, not the deferred indexer.
Planning review 1, requested GPT-6.1 Sol / Xhigh, worker
`01a18302-0ae4-7bd3-976e-15ac90c04c65`, found two proof gaps: lost deferred
reclaim eligibility across restart, and vacuous packaged smoke on an absent
WAL. Both were corrected above with integrated tests, not a broader backend.
Its read-only source review otherwise found sufficient implementation direction;
builder viability and the forecast remain to be established during execution.
Requested settings are not independent host confirmation. No tests, builds,
services, private-data access or workflows ran for this planning review.

Planning review 2, requested GPT-6.1 Sol / Medium, worker
`01a18309-2b36-7ef1-aaab-22e1fa409631`, found no decision-changing restrictions
or required corrections. It confirmed that routine extraction/recovery choices
stay with the director, forecasts are not stop quotas, historical experiment
constraints are not inherited and observer repair is optional. It proposed no
change to success/evidence/assistance assumptions, so no review-1 recheck was
needed. It inspected only this plan and repository instructions; no source
audit, tests, builds, services, private-data access or workflows ran. Requested
settings remain host-unverified. Both review reports were collected; reviewers
are retired and reporting routes removed before planning handoff.

Execution handoff: use this scope and steps 1-4 when the owner resumes work.
Carry forward the existing permissions above, recheck current base/runtime facts,
and continue covered review fixes through both public downloads and receipt.
Do not revive the parked indexer, start a new native Goal implicitly, or ask
for the same already granted release permissions again.

## Execution Checkpoint

- Execution uses the existing clean Terra release checkout, main based on
  `2a9b0707e68ecf686f64a552744ce02eaa9aefa4`. Public catalog and remote tags
  show no existing 2.13.2, so that maintenance version is selected.
- Standalone maintenance is ported without `read_model/` or report algorithms.
  One safely fenced startup reclaim event recovers lost eligibility; no new
  durable job system is added. Actual HTTP/agent restart, external reader
  release, retained usage, report and CSV checks passed (four integration/TEMP
  cases); the same package-smoke contract passed against a source subprocess.
- The first focused run exposed the missing maintenance priority; after adding
  its existing-lane enum value, 35 affected checks passed. Saved POSIX privacy
  fixes are retained because closing independent DB/SHM descriptors drops live
  SQLite record locks. No shared source schema or pricing schedule changed.
- Read-only runtime support requested Sol/Medium, worker
  `01a18315-1dc7-72d2-ac5a-da9082036dbf`, mapped the independent builder closure
  and identified provenance/frozen-DLL proof gaps. Worker closed/unregistered.
  Native input/archive reuse checks and frozen package DLL custody are included
  in this small runtime change; index-specific build identities are excluded.
- Existing official development runtime artifacts were rehashed (2,829 matches).
  A fresh package runtime completed with native-input provenance. The
  selected scoped portable runtime/build cohort passed 60 cases; Ruff passes.
  These checks do not yet qualify either native package or public release.
- Broad affected checks passed 579 cases with thread/unraisable warnings as
  errors. Independent read-only Sol/High review, worker
  `01a18326-99e4-72c0-bce0-e2480f50a4f4`, identified a coalesced-future race that
  could strand maintenance as queued. Its deterministic regression failed
  before repair; queued state now remains owned until the lane future completes.
  Focused final recheck found no actionable issue; 28 affected real-agent/WAL
  tests passed after repair. Worker closed and reporting route removed.
- `wal-capture-before-queue-fix.json` is pre-repair evidence, not current proof.
  `wal-capture-final.json` reran the repaired code. The final
  `wal-capture-allocated.json` additionally observes MAIN+WAL immediately after
  checkpoint I/O (which need not trigger a VM progress sample), retaining all
  earlier measurements. All use ten alternating pairs plus one excluded pair,
  a real 256 MiB WAL and one actual capture parser worker; no private inputs.
  Every final measured capture overlapped checkpoint I/O, record hashes/integrity
  matched and eligible WAL ended at zero. This is a scoped synthetic result,
  not a universal latency or production-p95 claim.
- `normal-reports/evidence.json` contains ten paired source cycles, 13 operations
  each, exact HTML/action/CSV/work parity and no BOTH >10% AND >100ms regression.
  The fixture has 3,180 usage records including 300 Terra records, quota/reset
  boundaries and complete CSV; no original sessions or private ledger were used.
  Control is frozen 2.13.1 source with local CPython 3.13.12/SQLite 3.50.4;
  candidate uses its fresh CPython 3.13.12/SQLite 3.54.1 runtime. This is not an
  old published-binary timing comparison. Median per-process peak RSS was
  77,070,336 / 76,259,328 bytes (control/candidate), not a multiplatform app peak.
- All 87 extension tests and build passed. No indexer, source schema, pricing or
  frontend runtime changes are included. Native platform gates still must pass.
- Initial candidate `9a8fef4` qualification run `40721001979` is retained as
  failed evidence, not promotion authority. All five visuals and the Mac package
  passed; Windows discovery excluded its VS 2026 runner, and Core stopped before
  tests on the Python assertion. Discovery now accepts installed VS 2022 or newer
  while retaining the actual x64 compiler, SDK, headers and libraries checks.
- Shipped 2.13.1 package logs on both targets establish CPython 3.13.16. Preserve
  that patch version rather than downgrade to the saved 3.13.12 builder; align
  POSIX OpenSSL to 3.5.9, matching the selected PSF Windows runtime. Official
  source/NuGet archives are independently hash-pinned. This is not a claim to
  ship the latest Python. The fresh local 3.13.16/3.5.9/SQLite 3.54.1 build passed
  engine and TLS probes. Old 3.13.12 measurements remain labeled historical;
  refresh matched normal-report and capture evidence for the final runtime.
- Core's initial Linux log also revealed `setup-python`'s `LD_LIBRARY_PATH`
  shadowing the private CPython library. Native probes and Core sync/test steps
  now select the private library explicitly, with focused regression checks.
  Qualification must be a new source-bound run after these owning repairs.
- Final-runtime affected checks passed 100 cases; Ruff passed. Read-only repair
  review requested Sol/Medium, worker `01a1834b-e50f-7b61-bac6-e126f9e04a5f`,
  found no actionable issue in runtime isolation or toolchain selection. Static
  review did not independently execute native builds or verify archive hashes.
  Its report was collected, worker closed and route removed; effective settings
  remain host-unverified.
- Final timing evidence uses separately run
  `wal-capture-py31316-isolated.json` and
  `normal-reports-py31316-isolated/evidence.json` in the existing qualification
  directory. Earlier refreshes overlapped experiments and remain retained but
  are not the isolated timing proof. WAL capture off/on medians were
  0.258952 / 0.021144 seconds, all ten measured captures overlapped checkpoint
  I/O, every eligible WAL reclaimed to zero, and observed owned-file high-water
  was 540,797,534 bytes. Normal reports retain exact output/work parity across
  all 13 operations in ten pairs with no material regression. Both interpreters
  are CPython 3.13.16; frozen 2.13.1 source control uses SQLite 3.53.1 and candidate
  uses 3.54.1. This remains a synthetic source comparison, not published-binary
  or production-p95 evidence. No private input or live account was accessed.
- Candidate `d8c2c61`, run `40725339531`, passed Windows compiler discovery but
  its SDK INCLUDE check rejected the expected 26100 header directory. The runner
  image declares that SDK installed; the combined error did not distinguish a
  missing file from equivalent path spelling. Compare canonical full directory
  paths (including doubled/forward separators and quotes), retain the actual
  file checks, and add native spelling regressions plus bounded failure details.
  This is a toolchain preflight repair, not a relaxation of engine/package proof.
