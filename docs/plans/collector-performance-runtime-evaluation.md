# Collector Performance And Runtime Evaluation

Date: 2026-10-16, America/Toronto.
Status: implementation approved 2026-10-16 via Relay direct. Local scoped edits,
isolated builds/experiments and the proposed scoped commit/push/nonpublishing
qualification are covered. The owner separately approved release on October 16;
2.12.4 publication and public hash verification are complete. Installation and
runtime/Rust adoption remain separate owner decisions.

Progress: private report baseline, bootstrap/stat fixes and parse-scoped identity
reuse implemented. Current/common 3.13 and common 3.15 native compatibility
checks pass on both supported targets. Runtime/Rust evaluation recommends
retaining Python 3.13. The owner approved the normal hosted WebKit observation
policy on October 16. Full 2.12.4 VSIX qualification and independent local
inspection and promotion dry-run passed on source `3a906f5f`. The exact qualified
packages are published as `v2.12.4`, with both official target hashes verified.
No installed extension or live ledger was changed by this release work.
See [implementation evidence](../research/2026-10-16-collector-implementation.md).

Current execution checkpoints:
- Baselines: ten paired capture/report runs; private report input reproduces
  the loading delay. Capture workload is synthetic, not a private-source claim.
- Bootstrap/identity: implemented; local and hosted native frozen checks pass on
  macOS ARM64 and Windows x64. Full VSIX qualification and exact-package native
  acceptance pass on source `3a906f5f`.
- 3.15: coherent dependencies and both-target frozen compatibility pass; approximately
  2% operation gains fail the adoption gate. Keep 3.13.
- Rust: isolated resumable prototype and parity checks; two blocks show about
  19.5% cold-capture benefit, below the 20% gate. Keep it unshipped; no further
  performance blocks are authorized by the measurement protocol.
- Source `b7b603e03a54d62d912a2dffc18df3cbf5b00652` was committed/pushed and
  executed in one nonpublishing six-configuration hosted run, `38970001352`.
  All six jobs passed without a rerun. This was compatibility evidence, separate
  from the subsequent normal qualification of source `3a906f5f`.
- Hosted qualification: the prior timing slot cannot authorize a new release.
  The owner approved the future-candidate policy in ADR 0071. Hosted WebKit's
  250 ms observations are reported, with a two-second functional ceiling;
  other engines/local/native remain strict. No old journal binding or publication
  authority is reused. Normal qualification `38987823051`, attempt 1, passed
  all 11 jobs; independent inspection confirms both exact VSIX packages and
  native acceptance. Promotion dry-run `38988734228` passed with the publish
  job skipped. The subsequent owner-authorized promotion `38993041981` passed,
  retained before-upload journal sequences 6/7, and both public package hashes
  match qualification. See the [published receipt](../release/2026-10-16-2.12.4-published.md).

## Outcome And Decisions

Make captures and post-capture dashboard loads meaningfully faster without
changing accounting, project attribution, retained history or distribution UX.
First correct the verified frozen-worker defect. Then remove redundant Python
work and evaluate standard Python 3.15 and a narrow Rust scanner independently.

Owner decisions made during planning:

- Bootstrap corrections and measured Python optimizations are eligible for a
  separate fix release. They must not wait for interpreter or Rust experiments.
- Representative profiling may use a private read-only ledger backup and, if
  necessary, bounded copies of selected session files. All experiment writes
  stay on disposable copies. No live capture, account calls, raw-log edits or
  data uploads are authorized.

The prior 2.12.3 release and its completed release-efficiency plan remain closed.
This is the single plan for the new collector/runtime performance scope.

Evidence: [direct investigation](../research/2026-10-16-collector-performance-investigation.md),
[Python assessment](../research/2026-10-16-python-315-performance-assessment.md),
and [consultation synthesis](../research/2026-10-16-python-315-review/README.md).
The research anchor is `2cef93bca5e1e000377fee1c16d9367d8129cae3`; released
runtime source is `28f4de27d8d8267548dba820943d6a695ba84a32`.

## Facts, Hypotheses And Boundaries

| Finding | Evidence status | Owning layer |
| --- | --- | --- |
| Released macOS worker invocations enter ordinary argument parsing and fall back to serial | Reproduced with exact published VSIX; synthetic token totals correct | Frozen collector bootstrap and qualification |
| Capture stats report zero fallbacks despite that failure | Reproduced; refresh-only API omits propagation from `usage_run` | Shared capture diagnostics |
| Repository identity is resolved for each usage delta | Source and instrumented synthetic profile | Parse-scoped identity work |
| Structural JSON projection is material CPU work | Instrumented synthetic profile; real-workload share not established | Bounded row scanner |
| Current report delay is explained by those parser costs | Representative profile instead locates allowance-history preparation; first report remains about 8.9 seconds | Separate report-preparation follow-up |
| Python 3.15 or Rust offers a material user-visible gain | About 2% for 3.15, about 19.5% cold capture for the Rust spike; neither meets the adoption gate | Retain Python 3.13 and the Python scanner |

Preserve [ADR 0019](../adr/0019-bounded-parallel-cache-refresh.md)'s maximum
four spawned workers, parent-owned SQLite, ordered eight-file commits, observable
fallback and process-tree ownership; [ADR 0022](../adr/0022-guarded-append-parser-checkpoints.md)'s
append/budget/rollback semantics; [ADR 0035](../adr/0035-verified-local-project-continuity.md)'s
ancestry-backed identity rules; and the schema-7 writer/retained-accounting
contracts. Preserve [ADR 0058](../adr/0058-post-capture-preparation-work.md) and
[ADR 0060](../adr/0060-historical-allowance-calculation-reuse.md) invalidation.

Keep [ADR 0047](../adr/0047-extension-only-distribution.md): macOS ARM64 and
Windows x64 VSIX, bundled collector, no user-installed Python/Rust requirement,
no new daemon, and no dependency downloads on ordinary extension startup.
Excluded: a Rust collector rewrite, uv replacing the packager, persistent process
pools, free-threaded Python, JIT, visual redesign, new telemetry, live repairs,
service/settings changes and a new hosted WebKit tracing campaign.

## Ordered Deliverables

### 1. Establish Representative, Private Baselines

- Preserve the existing released-binary failure evidence; do not reclassify
  successful totals as successful parallel execution. Record source, VSIX,
  collector, interpreter patch/build/distributor, native dependency, SQLite,
  platform and benchmark identities for every comparison.
- Take a coherent SQLite read-only backup, with bounded busy waits. All schema,
  index, cache and report writes must use the copy. Deny benchmark access to
  original task paths, credentials and external networking; do not let copied
  absolute paths accidentally reopen live data.
- Capture inputs may additionally use at most 256 MiB of private source copies,
  selected to include small appends and substantive parsing. Validate source
  boundaries before/after copying with bounded retries; disclose unstable or
  omitted sources. Preserve any required continuation/base closure. A cropped
  file without that closure is not a representative accounting workload.
- Keep 64 MiB capture slices, 16 MiB file quanta, identical selected work and
  pending progress. A faster result doing less work fails comparison.
- Include synthetic fixtures for multi-file cold capture, no-op, tiny and larger
  appends, inherited/continued histories, late corrections, large bounded rows
  and two populated report days. Generate a local synthetic Git checkout.
- Measure startup/readiness, queue delay, quota acquisition, worker startup/
  parse/transport, commits, normalization/recovery, first report after capture,
  Yesterday and cached Today separately. Do not prime the monetary index before
  measuring first-report cost. Real quota RPC is excluded here, not assigned a
  synthetic zero-second production cost. Queue/HTTP/UI boundaries stay explicit.

Acceptance: reproducible input/work manifests and operation/phase tables with
private evidence local only. Unknown report or quota bottlenecks remain named
unknowns; they do not justify unrelated refactors. Backend timings are not
WebView transfer/paint timings, and fresh-process cache misses are not proof of
a cold operating-system disk cache.

### 2. Correct Frozen Bootstrap And Diagnostic Coverage

- Make the actual frozen `agent_main.py` entrypoint divert multiprocessing
  invocations with `freeze_support()` before argument parsing and heavy app
  initialization. Preserve its ordinary CLI, parent-bound lifecycle and schema
  fencing. Do not accept arbitrary child flags in the ordinary parser.
- Propagate infrastructure/fallback counters from `usage_run` through
  `refresh_cached_session_data` into capture results. Keep file errors distinct
  from infrastructure errors and preserve safe serial recovery.
- Add a regression for this entrypoint, retaining the existing CLI regression.
  Add forced infrastructure-failure and ordinary parse-error counter tests.
- Extend packaged-agent acceptance through its real lifecycle/HTTP route with
  more than eight substantive files. Require multiple non-parent worker PIDs,
  overlapping parse spans, no fallback, full expected progress and serial-oracle
  equivalence. Test startup capture/coalescing, no-op, append and shutdown.
- Reuse existing worker spans, private audit serialization and process-tree
  utilities. An opt-in bounded audit may carry infrastructure-only proof tied
  to a capture/run; normal capture must not accumulate telemetry or expose task
  paths, credentials, exception text or content. Transport details remain an
  implementer choice, not a new general diagnostics service.
- Validate native frozen collectors on both supported targets, including owned
  child cleanup on failure/timeout. Update required package evidence/contracts
  so a missing parallelism assertion cannot qualify as an old one-file smoke.

Acceptance: a bootstrap-only Python 3.13 candidate passes the new frozen gates,
all existing parity/ownership tests and correct failure-counter assertions.
Record this corrected baseline before adding optimizations. Source-only passing
tests, a green capture or a process-count observation without overlap do not
close this deliverable. Windows remains unverified until actually executed.

### 3. Remove Measured Redundant Python Work

- Reuse repository resolution within one bounded parse chunk/effective metadata
  scope. Reuse existing resolver/cache APIs; retain local-origin and commit-
  ancestry verification rather than replacing them with URL/name shortcuts.
- Define identity inputs and lifetime explicitly. No cache survives a capture,
  checkpoint resume or changed effective metadata. Preserve the coordinator's
  fresh reconciliation. Test origin/HEAD/config/common-directory changes,
  replacement/disappearance, linked worktrees, metadata switches and Git errors.
  If a checkout changes during a worker snapshot, fresh parent verification or
  rejection/retry must prevent stale attribution from being committed.
- Assert repository discovery/config reads scale with distinct relevant
  identities/chunks, not response count. Compare records, aliases, transitions,
  normalized ownership, financial values and checkpoints against the baseline.
- Measure serial versus spawned dispatch for small estimated unread workloads.
  Add a simple bounded dispatch threshold only if representative results justify
  it. Zero-work stays zero-work; large workloads must still qualify actual
  overlap. Do not add a persistent pool or special behavior for the benchmark.
- If representative first-report profiling identifies a different material
  component, report it with evidence. This phase does not authorize a new
  allowance algorithm or broad report/cache redesign to chase a timing target.

Acceptance: demonstrated redundant-work reduction, unchanged semantic results
and measured capture benefit without material no-op/append/report regressions.
Update the relevant existing ADR for the chosen cache lifetime/dispatch contract.
Do not grow near-500-line parser/test modules indiscriminately; prefer a cohesive
small resolver context and new focused tests over unrelated module churn.

### 4. Qualify The Separate Fix Candidate

- Freeze the bootstrap/Python-only source and dependencies. Experiments in
  phases 5-6 must not leak into this candidate or invalidate its package proof.
- Run focused tests first, then complete Python/extension tests, Ruff, frozen
  monetary parity, bounded-work guards, both packages, all existing visual and
  lifecycle/handoff checks, and exact-package native acceptance as required.
- Preserve existing case inventories and add the new collector gates. No test
  removal, generic retries, deadline increases or coverage waivers are implied.
- Present a before/after table separating released broken baseline, corrected
  bootstrap-only baseline and optimized candidate, with workload/identity limits.
  Reproduce all comparisons on equivalent data; do not present the earlier
  source-versus-frozen screening as a release speedup.
- Follow [ADR 0061](../adr/0061-qualified-artifact-promotion.md): qualification
  selects immutable packages; any eventual promotion uses those exact bytes.
  Publication and installation remain separate owner approvals.

Acceptance: independently reviewable correctness, performance and package proof,
ready for an owner release decision without waiting for experimental runtimes.
The historical WebKit timing disposition was candidate-bound, not a permanent
waiver. If the new candidate hits that unchanged limitation, surface its exact
gate and seek a new disposition; do not reopen tracing or borrow old acceptance.

### 5. Compare Standard Python 3.15

- Use isolated candidate environments; do not change the default runtime or
  production lock merely to run an experiment. Refresh upstream compatibility
  facts at execution, using the minimum coherent Pydantic/core, PyInstaller and
  watcher/toolchain versions. Do not override Pydantic's exact core dependency.
- Separate three configurations: A = corrected/optimized 3.13 with current
  dependencies; B = same source on 3.13 with the minimal common candidate
  dependency/toolchain set; C = same source and B's set on standard 3.15.
  A/B measures dependency effects; B/C measures the interpreter/build change.
- Build actual platform collectors. Verify watcher/native imports and lifecycle
  behavior, schema/financial parity, cold/no-op/append/report work and cleanup.
  An import-only or unfrozen benchmark is insufficient. Missing native support
  is a named compatibility failure, not permission to disable a feature.
- Reuse representative paired measurements and the gates below. Record package
  sizes, startup and process-tree memory alongside CPU/wall time. Tool defaults
  must not silently enable free-threading or JIT.

Acceptance: an adopt/retain-current recommendation with both-target compatibility
and user-relevant measurements. A failed compatibility or benefit gate keeps
3.13; it does not block the separate fix candidate. Production adoption requires
owner review and a concise durable runtime decision plus fresh qualification.

### 6. Evaluate One Rust Scanner Component

- Re-profile after the Python changes. If structural scanning is no longer
  material on representative work, record that stop decision instead of porting
  an irrelevant component. Otherwise build one isolated native-extension spike
  around bounded structural projection/row scanning, using the existing Python
  implementation as an independent behavioral oracle.
- Prefer a coarse-grained PyO3 boundary over per-character/field callbacks.
  Rust-only work may detach from ordinary GIL-enabled Python; no free-threading
  dependency is introduced. Use proven Rust parsing primitives where they fit,
  without mistaking full-document deserialization for resumable prefix parsing.
- Preserve bounded memory, original byte budgets/offsets, late headers, partial
  rows and UTF-8, escaped/duplicate keys, malformed input, split scalar state,
  checkpoint restart and nonretention of message/media content. Compare every
  projected result/state and downstream usage, speed and provenance output.
- Keep SQLite writes, pricing, allowance fits and orchestration in Python.
  Preserve checkpoint compatibility, or stop and propose a separately reviewed
  versioning contract before any incompatible persisted-state change.
- Compare Python-only and Rust-enabled configurations at the same source,
  interpreter, dependencies and input. Include conversion/copy overhead, native
  builds, packaged startup, both targets and actual capture/report timings.
  Evaluate maintained Python scanner optimizations before crediting Rust with
  savings caused solely by removing duplicate work.

Acceptance: a small prototype, reproducible parity/performance evidence and an
adopt/reject recommendation. No Rust dependency, new default execution path or
Cargo requirement enters the shipping candidate without owner adoption review.
A full collector rewrite is outside this plan.

## Measurement And Adoption Gates

These are proposed decision thresholds for plan review, not measured promises:

- Before each comparison, name its primary user operation and freeze inputs,
  clock, pricing identity, coverage, selected progress and expected outputs.
- Use ten paired, alternating unprofiled runs per configuration/operation after
  a separately reported preparation run. Keep first-fill and steady state
  separate; retain all failures. Report median, spread and raw samples, not a
  claimed p95 from a tiny sample. Run diagnostic profiling separately.
- For optional runtime/Rust adoption, require at least 20% and 250 ms median
  improvement in the nominated material end-to-end backend operation, not just
  a scanner microbenchmark. No other critical operation may regress by both
  more than 10% and 100 ms. Report smaller gains without calling them a material
  improvement. Functional bootstrap correctness is required regardless of gain.
- Optional adoption must keep concurrent process-tree peak memory within 20%
  of the appropriate corrected baseline, with platform/shared-page caveats.
  Report parent versus child CPU and do not sum unrelated process peaks.
- If noise prevents a decision, allow one additional ten-pair block with the
  same method, then report inconclusive. Do not search indefinitely for a green
  sample or alter thresholds after seeing outcomes.
- Exact integer/accounting/provenance/checkpoint invariants remain exact.
  Monetary fields use the repository's independent existing parity contracts;
  never relax tolerances or change prices/rounding for speed. Fix only expected
  presentation timestamps/identities when comparing HTML, with that normalization
  documented. No evidence/history may be silently dropped.

## Execution, Permissions And Rollback

Default: serial implementation in the retained checkout, preserving unrelated
`apps/` and user changes. Freeze experimental source/environments under an owned
ignored directory rather than making parallel writers or creating extra tasks.
A bounded attended read-only review is useful for bootstrap/identity authority
and Rust parity. If delegated after implementation approval, follow Relay direct,
announce explicitly selected authorized model/effort at dispatch, and collect
the result before completing the work.

| Action | Authority |
| --- | --- |
| Read source and write/review this plan | Current planning request |
| Private read-only ledger backup and bounded source copies; no live writes or uploads | Explicitly approved during this planning session |
| Scoped product/test/docs edits, local tests, isolated official toolchain/dependency downloads and noninstalled synthetic/private-copy collector builds | Approved by the owner's implementation request on October 16 |
| Scoped commit/push and bounded nonpublishing dual-target CI qualification/experiment runs, using synthetic inputs only | Covered by the approved implementation plan; exact source/ref and bounded runs must be identified before dispatch |
| Release tag, Marketplace promotion, normal VS Code install/restart or opening a new preview | Separate explicit owner approval; excluded from implementation approval |
| Live collector/account execution, ledger repair, credential/service/security/settings changes, private artifact uploads or renewed WebKit tracing | Excluded; require a new specific request |

Private source copies use a 256 MiB total cap; local ledger backups are kept
private with a recorded disk budget and removed only after useful aggregate
evidence is preserved. Never commit raw ledgers, task content, paths, account
readings, credentials or private profiles. Share only synthetic or anonymized
aggregate results. Authored research may be curated for Git; submitted consultant
reports are not automatically authorized for publication.

Before hosted execution, propose the exact candidate/ref and bounded runs:
normally one nonpublishing full qualification for the fix candidate and one
per adopted experiment configuration/target, with only diagnosed affected-job
retries. No automatic dispatch loop or runner/settings/secret change.

Rollback is source/artifact selection, not a live-data operation. Retain the
corrected 3.13 baseline, candidate dependency identities and package hashes.
Rejected experiments leave production Python/dependencies and default paths
unchanged. No ledger schema or parser checkpoint migration is planned; if one
becomes necessary, stop for a distinct compatibility/rollback decision. Clean up
only owned temporary processes/environments after preserving evidence. Do not
roll back unrelated user work or install the known-broken release as cleanup.

## Handoff Completion

Implementation handoff must carry the owner's split-release and private-snapshot
decisions, the exact granted execution permissions, source/package identities,
completed phase gates, unresolved findings and the next independent release or
adoption decision. Completion means verified deliverables, not exhausting a
benchmark budget or choosing a new language. This plan does not start a Goal.
