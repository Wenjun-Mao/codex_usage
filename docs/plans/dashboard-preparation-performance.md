# Dashboard Preparation And Long-Range Performance

Date: 2026-10-22, America/Toronto.
Status: implementation approved 2026-10-22 via Relay direct. Bounded local
implementation and disposable verification complete; performance targets remain
unmet. Hosted execution, publication and normal VS Code activation remain outside
this approval.

The proposed combined release handoff is now in
[Task Transfer Retirement And Performance Release](task-transfer-retirement-and-performance-release.md).
It packages the verified work here without declaring the remaining 3s/5s targets
complete. Release execution requires approval of that plan's operational scope.

## Second Pass (Approved October 22)

### Serialization And Valuation Follow-Up (Approved October 22)

- [x] Freeze the current candidate and one coherent private read-only snapshot.
- [x] Implement compact validated capture layouts, per-batch schedule bindings,
  and ordered scalar turn costs under ADR 0075.
- [x] Check numeric identity, legacy/corrupt cache handling, pricing boundaries,
  schedule replacement and exact turn addition order.
- [x] Complete independent diff review and broad regression verification.
- [x] Compare complete HTML/CSV and timings on the frozen input; retain all pairs.
- [x] Record remaining 3s/5s gaps and remove owned private database copies.

This follows the owner's request to optimize full allowance serialization and
30-day pricing/turn calculations. Existing local-only boundaries remain active.

Ten matched pairs measured first 30 days 8.96 -> 8.06s, post-append Today
8.27 -> 8.12s, and post-append 30 days 7.33 -> 6.72s. CSV is effectively
unchanged. The allowance payload fell 40.7%; whole-encoder CPU did not improve.
Targets remain unmet. Coarse phase measurements show that eliminating encoding,
pricing and turn calculation alone would still leave more than 7s Today / 6s
30-day CPU; the remaining full-history and range work needs attention. See
[serialization/valuation evidence](../research/2026-10-22-serialization-and-valuation.md).

### Incremental Follow-Up (Approved October 22)

- [x] Freeze a new coherent private snapshot and retain the previous candidate
  as the matched baseline.
- [x] Reject the full-scalar-prefix-hashing prototype after it failed to show
  a reliable gain despite exact output parity.
- [x] Implement bounded independent quota change certificates, display/pace
  checkpoints and exact-content chart-day reuse; retain fresh reset/economics.
- [x] Add focused correction, unknown-plan, authority, journal and DST guards.
- [x] Finish independent review, broad tests, browser parity and matched timings.
- [x] Report remaining 3s/5s gaps and remove owned private database copies.

The adopted contract is recorded in
[ADR 0074](../adr/0074-incremental-history-preparation.md). Work remains local;
no CI, push, release, installation or native VS Code activation is implied.

Ten new matched pairs measured post-append Today 8.79 -> 8.48s, post-append
30 days 8.87 -> 7.52s, first 30 days 9.99 -> 10.18s and CSV 2.49 -> 2.20s.
Incremental reuse helps repeated capture workloads but not the first 30-day
load. Both targets remain unmet; full report encoding and selected-event
pricing/turn materialization are the next measured costs. See
[incremental evidence](../research/2026-10-22-incremental-history-preparation.md).

The owner requested continued full-history/30-day optimization toward 3s/5s
and correction of the measured CSV regression. Work remains local and bounded
by the same privacy/storage/activation limits.

- [x] Freeze a new coherent private snapshot; compare with the completed first
  pass, not with differently timed live input.
- [x] Run a retained-quota eviction ablation to distinguish CSV allocation cost
  from CSV accounting work.
- [x] Reduce duplicate provenance/identity allocation and request-local scans;
  stream ledger rows with query-local normalized metadata reuse.
- [x] Measure the combined candidate and address the retained-object CSV cost.
- [x] Verify exact HTML/CSV/monetary parity, invalidation, browser behavior and
  report the 3s/5s gaps using unprofiled paired measurements.
- [ ] Close the remaining target gaps beyond verified history reuse; full
  report encoding, reset/economics assembly and selected-event work remain.

No generation or continuity boundary is weakened. Persistent history reuse is
still gated on a causal/invalidation proof; cross-request retention must earn
its cost in both dashboard and export workloads.

Five new matched pairs measured Today after append 12.77 -> 8.86s, first 30 days
13.72 -> 10.35s, and CSV 3.79 -> 2.37s. Peak RSS fell 26%. The complete 1,925-row
CSV and all HTML bytes matched. See the
[second-pass evidence](../research/2026-10-22-dashboard-preparation-followup.md).
Targets remain unmet; no release/native acceptance is implied.

## Implementation Checkpoint

- [x] Freeze the matched baseline/input and attribute request-level work.
- [x] Implement ordered accumulators, dashboard-only daily activity, canonical
  captures, scalar memos and a lazy history overview.
- [x] Add independent source/quota tracking and bounded unchanged raw/pace reuse.
- [x] Move pure allowance preparation outside writer ownership; reject stale
  publication without consuming newer dirty evidence.
- [x] Qualify exact accounting, correction/rollback/concurrency behavior and the
  affected script-disabled browser surfaces locally.
- [x] Finish ten alternating paired measurements, extended navigation/export
  parity and remaining-hotspot profile; assess the targets explicitly.
- [ ] Owner-requested isolated native/package verification, if advancing this
  candidate toward release. No native activation or hosted execution implied.

The initial checkpoint did not adopt incremental quota-boundary rebuilding or
persisted selected-event partitions. The approved incremental follow-up above
now reuses proven display/pace prefixes; monetary/reset segmentation remains
fresh. Persisted selected-event partitions have not been shown preferable to
simpler ordered aggregation. Initial implementation and evidence are recorded in
[ADR 0073](../adr/0073-snapshot-pinned-dashboard-preparation.md) and the
[local qualification report](../research/2026-10-22-dashboard-preparation.md).

## Outcome And Scope

Make the complete VS Code dashboard load materially faster after capture and
when switching from Today to Last 30 days. Keep the existing visible report,
accounting, filters, history, CSV export and script-disabled interaction contract.
The initial delivery keeps one consistent report snapshot; progressive sections,
stale values and background prewarming are not part of this proposal.

This is the active plan for the report-preparation follow-up identified in
[collector/runtime evaluation](collector-performance-runtime-evaluation.md).
That plan's released bootstrap/identity fixes and completed runtime experiments
remain closed. Release scheduling, finer local test reuse and test parallelism
are the next workstream after this scope; they are not implementation steps here.

Work serially in the retained checkout. Preserve the pending writer-admission
fix, its tests and ADR, unrelated `apps/` work, and submitted research reports.
No new worktree, task, Goal, automation, runtime migration or Rust component is
required. An independent, bounded review of invalidation and transaction changes
is useful after implementation; use Relay direct and announce selected model
and reasoning effort before any authorized delegation.

## Evidence And Starting Authority

- Recorded representative medians: first Today after revision 8.934 seconds,
  Yesterday 1.615 seconds, cached Today 0.064 seconds. These are backend timings
  from the October 16 comparison, not current end-to-end VS Code measurements.
- The owner observed 22.97 seconds for Today -> Last 30 days on 2.12.5. Its exact
  workload has not yet been profiled. Do not attribute all of it to allowance work.
- The retained diagnostic profile spends 15.557 seconds cumulatively in
  `indexed_allowance_report` across 21.921 seconds of report operations. It also
  records 896,762 JSON serializations. Instrumentation inflates elapsed time and
  nested costs overlap; these locate work, not forecast savings.
- Current range materialization loads selected event objects, values them, and
  performs multiple aggregations. It still builds per-agent/export structures
  although the dashboard consumes only daily activity rows.
- Historical fitted-window reuse already exists. Raw evidence expansion,
  segmentation, pace/history preparation, prefix accumulation and report codecs
  still perform substantial work after invalidation.
- Expensive allowance preparation currently runs within `BEGIN IMMEDIATE`.
  The locally implemented writer-admission fix prevents the reproduced
  same-process writer race but does not shorten preparation or capture waiting.

Sources: [collector measurements](../research/2026-10-16-collector-implementation.md),
[ADR 0055](../adr/0055-range-independent-breakdown-preparation.md),
[ADR 0058](../adr/0058-post-capture-preparation-work.md),
[ADR 0060](../adr/0060-historical-allowance-calculation-reuse.md), and
[ADR 0072](../adr/0072-in-process-sqlite-writer-admission.md).

Before benchmarking, freeze a source manifest containing HEAD, relevant tracked
and untracked implementation bytes, dependencies and the writer-admission patch.
Use that same correctness fix on both comparison sides. Its benefit must not be
counted as a dashboard optimization. The installed 2.12.5 package is a separate
reference, not an interchangeable source baseline.

## Design Choice

| Approach | Benefit | Limitation | Decision |
| --- | --- | --- | --- |
| Remove repeated work within the existing request | Smallest change; helps first fill and tests | Still scales with selected events/history | First pass |
| Reuse prepared summaries and affected partitions across requests/captures | Addresses recurring post-capture and large-range work | Requires complete invalidation, exact arithmetic and bounded storage | Main follow-up, gated by measurements and parity |
| Prewarm or load sections progressively | Can improve apparent first display | Moves work into capture/background and changes UI/freshness behavior | Excluded from this pass |

Preserve the current full estimator/materialization as an independent oracle.
Prefer extending existing preparation/cache ownership over adding another report
stack. Do not assume daily monetary totals can be summed to reproduce the
original event-order accumulation, or that an old/reset period is immutable.

## Acceptance

Proposed performance goals on the same representative snapshot and machine:

- At least 50% lower median backend time, saving at least one second, for both
  an ordinary post-capture report and the first Today -> 30-day switch at an
  unchanged revision. Establish the matched baselines before judging the gains.
- Engineering targets: post-capture Today within 3 seconds, first 30-day view
  within 5 seconds, and repeated Today/Yesterday/30-day views within 500 ms.
  These are targets for review, not promises established by the old profile.
- Report first installation/empty-cache cost separately. Shifting computation
  into capture, startup or first setup does not count as eliminating it.
- No capture, Yesterday, warm navigation or explicit-history operation may
  regress by both more than 10% and 100 ms in paired measurements. Measure write
  admission wait, transaction duration, peak memory and derived-cache growth too.
- Preserve exact token/cost/credit values, model/turn populations, history and
  correction behavior. No relaxed tolerances, missing cases, reduced fidelity,
  or changed prices/rounding are permitted to meet a speed target.

Use one preparation pair and ten alternating unprofiled baseline/candidate
pairs for final primary measurements. Profile separately. Retain failures and
all samples; report medians and ranges, not p95 from ten samples. A single extra
block may resolve material noise; do not repeat until a favorable result appears.
If targets remain unmet, identify the remaining component and report the gap
before expanding architecture or scope.

## Ordered Deliverables

### 1. Reproduce And Attribute Both Slow Paths

Extend existing benchmark/profile entrypoints rather than creating a parallel
harness. `profile_dashboard.py` currently primes the allowance index; retain
that as an explicit warm-account scenario, not the post-capture baseline.
`benchmark_collector.py` currently measures only Today/Yesterday/cached Today;
add long-range sequences and real disposable-input mutations.

Use one coherent private read-only SQLite backup and one disposable working
copy at a time. Reports must be denied access to original sessions, account
services and external databases. Raw session copies are unnecessary for this
report-only investigation. Capture-overlap tests use synthetic fixtures.

Measure separately:

1. First fill with empty derived caches, without priming allowance work.
2. Revision-only change, ordinary current usage/quota append, and subsequent
   Today report. A revision bump alone does not simulate real capture changes.
3. Today -> Yesterday -> 7 days -> 30 days -> Today at a fixed revision, plus
   a fresh 30-day report immediately after append.
4. Repeated ranges, a representative project filter, theme change, and explicit
   history/CSV requests. Keep account-wide and selected-project scope distinct.
5. Late usage/quota corrections, pricing changes, and concurrent synthetic
   report/capture requests; measure correctness, delay and duplicated work.

Record phase wall/CPU time, decoded/priced event counts, expanded quota counts,
segmentation/codec calls, SQL work/query plans where material, HTML bytes, cache
bytes, memory, writer wait and transaction time. Separate agent acquisition,
HTTP, backend computation and WebView update/visible readiness in isolated UI
verification. The current Usage "Loaded in" label reports backend elapsed time;
it is not a measurement of transfer or paint.

Deliver a before table and a short root-cause note for each proposed change:
what repeats, why, the owning layer, and the parity/work assertion guarding it.
Use measured 30-day event and quota cardinalities for a reproducible synthetic
scale case. Do not publish private profiles or data.

### 2. Remove Unnecessary Work Within A Request

Start with the measured low-risk work:

- Give dashboard activity a daily-summary path. Build per-agent, per-agent-day
  and export-only structures on explicit CSV export. Preserve task ancestry,
  daily distinct root/subagent counts and complete export rows.
- Share selected valuation and reusable time/identity conversions across
  summary, economics, chart and activity consumers. Retain any deliberately
  different ordering used by those consumers.
- Replace repeated JSON-based point identity construction where a complete
  typed identity or a once-built canonical index preserves all fields,
  provenance, ordering and duplicate validation. Avoid identity shortcuts.
- Read compact history directories/summaries for the default view. Load exact
  captures for the requested detail/page without eagerly decoding all history
  merely to display its first page. All existing detail remains available.

Measure each retained change. Do not implement unrelated micro-optimizations
because they happen to be nearby. This pass also establishes reusable building
blocks for the following cache work.

### 3. Reuse Allowance Preparation And Shorten Writer Ownership

Probe and document the dependency boundary before caching segmentation or pace.
Current fit tracking intentionally assumes fresh segmentation and ordered cost
prefixes; its dirty spans alone are not proof that prepared history is reusable.
Plan changes and later recovered evidence can affect earlier unknown identities.

Implement only the portions shown material by step 1:

- Separate compact current allowance/pace and reset-period summaries from
  exact capture payloads. Reuse unchanged prepared components across captures
  under a versioned dependency identity; do not duplicate entire histories.
- For append/revision-only changes, reuse a proven unaffected portion and
  recompute its dependent boundary/current portion. For unbounded identity,
  provenance, compressed-timestamp or pricing effects, conservatively rebuild
  the affected series or full component. Preserve causal-origin boundaries.
- Compute expensive pure preparation against a pinned read snapshot. Publish
  derived results in a short admitted write transaction only if source revision,
  pricing/coverage and tracking generation still match. Recheck the source after
  acquiring admission; never clear newer dirtiness or store stale results.
- On a race, serve only results consistent with the pinned snapshot and omit
  stale cache publication. Preserve existing issued-scope expiry/recovery and
  avoid unbounded recomputation/retry loops or capture starvation.
- Dirty evidence must have explicit ownership across all cache consumers.
  One cache finishing must not consume invalidation still needed by another.
  Validate this before splitting the existing transaction. Missing/damaged
  tracking invalidates dependent caches; existing writer fencing remains.
- Add request coalescing only if measurements show duplicate simultaneous
  preparation. Keep it bounded by ledger/revision/semantic key, with correct
  failure cleanup; do not introduce a background service.

Preserve exact prefix arithmetic, late-correction behavior, reader concurrency
and ADR 0072 admission. Measure long read snapshots/WAL growth as well as write
lock duration. Update the owning ADRs with the adopted transaction/cache contract;
do not label the previous fit cache unsafe or silently change its assumptions.

### 4. Accelerate 30-Day Materialization

After step 2, use the 30-day profile to choose the smallest effective structure:
reused priced records, exact ordered partial results, or derived day/project/
model/turn partitions. Persist aggregates only where they beat simpler reuse
including first-fill, write and decode costs. This is an implementation decision
after measurement, not authorization for an unconditional second event store.

The chosen representation must:

- Retain event-time pricing, trusted-generation selection, project transitions,
  record ordering and all accounting components. Query only needed intervals.
- Preserve exact cost accumulation. Ordinary SQL SUM or sums of daily floating
  totals are not substitutes for the current oracle unless exact parity holds.
  A representation that cannot preserve it must be revised or rejected.
- Preserve `(project, task, turn)` and model-turn identities, blank-turn
  coverage, cross-midnight turns, mixed-model turns, partial-range turns,
  distinct counts, weighted averages and medians. Never average daily averages
  or add daily distinct-turn counts to produce range totals.
- Include calendar/timezone/DST semantics in any relevant partition identity;
  preserve `[start,end)` calendar versus `(origin,capture]` causal intervals.
- Invalidate source corrections/deletions, trust/model/pricing changes,
  transition/label/task-ancestry changes and relevant coverage changes.
  Demonstrate that identical revision-only changes do not revalue unchanged data.
- Have bounded retention and deterministic pruning across dates, projects,
  themes, revisions and algorithm versions. Raw history remains authoritative.

Do not change speed-statistic sample populations or image accounting to accelerate
unrelated language totals. First-fill versus reusable-range gains stay separate.

### 5. Verify, Review And Prepare The Handoff

Keep the baseline estimator in a separately frozen source tree for differential
checks. Compare selected totals, model/project/turn metrics, allowance values,
reset periods, pace, raw detail, CSV and visible report content. Internal cache
or issued-command identities may change only under an explicit, narrow comparison
rule; timestamps or hashes must not mask a semantic/display regression.

Extend the existing tests rather than adding another acceptance system:

- `test_dashboard_work_contract.py`, `test_capture_preparation_work.py` and
  `test_allowance_window_cache.py`: bounded work and full invalidation matrix.
- `test_allowance_report_codec.py`, history/reset-period tests: exact references,
  lazy detail, no lost captures, malformed cache and reconstruction.
- `test_breakdown_navigation_work.py`, `test_ledger_usage_ranges.py` and
  economics/activity tests: ranges, filters, DST, turn metrics and export parity.
- `test_ledger_writer_contention.py`: both writer entrypoints, concurrent capture,
  exception auditing, lost-publication races, rollback and no deadlocks.

Run focused checks first, then the full Python/extension suites, Ruff, monetary
parity and bounded-work checks for the final candidate. Use existing affected
browser tests and isolated native verification for the touched surfaces, retaining
their input/timing policy. Do not broaden or repeat completed checks without a
change, failure or unresolved concern. Review invalidation, compatibility and
transaction ownership independently before the handoff.

Deliver before/after timing tables, source/input identities, correctness results,
first-fill/capture/storage trade-offs, remaining target gaps and one reviewable
candidate. Local qualification is not release, installation or native acceptance
that has not actually been executed.

## Storage, Compatibility And Permissions

The earlier private read-only snapshot permission is retained: no live writes,
source-log edits, account calls or private uploads. For this work use at most
one frozen ledger and one active benchmark copy, with a 6 GiB total budget for
new benchmark files. Check logical sizes and free space before copying; APFS
clone sharing is not permission to exceed the budget. Stop allocating if the
budget cannot fit the representative input and report the constraint.

Use private directories/files and existing benchmark guards. Preserve compact
timings, input hashes and anonymized counts; remove owned working ledgers and
temporary environments after verification. Retain no extra large snapshot
without a named need and budget. The verified rollback archive and live ledger
are outside cleanup scope.

New caches must be disposable, bounded and independently versioned. Prefer
additive derived structures compatible with existing writers; old readers must
not decode a new payload under an old key. Test old-writer updates, missing tables,
partial installation, crash/rollback and tracking repair on disposable data.
Do not bump canonical ledger/parser formats for a report optimization. If that
becomes necessary, bring back the concrete compatibility/rollback proposal.

| Action | Authority / boundary |
| --- | --- |
| Source inspection and this plan | Current planning request |
| Read-only private snapshot method | Previously approved; bounded above |
| Product/test/docs edits and local disposable benchmarks after plan approval | Proposed implementation scope; not started by planning |
| Local synthetic browser/build checks and isolated collector tests | Included in proposed implementation scope; no installed extension change |
| Open a new native preview window or activate/restart normal VS Code | Separate owner request; prepare candidate first |
| Commit/push, GitHub CI/Actions dispatch or retry | Not started here; obtain a fresh explicit request before any hosted run or CI-triggering push |
| Tag, publish, install, live repair, settings/secrets/service changes | Not authorized by this plan |

Rollback removes only new derived caches or selects the prior source/package;
the canonical ledger and raw logs remain unchanged. Test rollback on copies.
After implementation approval, continue the covered local steps through
verification without requesting repeated milestone permissions. Present the
concrete candidate before seeking any remaining native/hosted/release action.
