# Independently Shippable Report Performance Slices

Updated: 2026-10-29, America/Toronto.
Status: S0/S1 remain closed at 2.13.3; theme-only presentation is released as
2.13.4 with both official packages verified.
Next: [On-demand allowance history](on-demand-allowance-history.md) passed its
product adoption review on 2026-10-29; the 2.13.5 candidate is ready for full
qualification. The older allowance proposal below remains parked. See the
[theme-only closeout](theme-only-presentation.md#published-closeout).

## Outcome And Scope

Improve a complete user workflow on the released normal report path without
waiting for the parked indexer to be finished. Each adopted slice must deliver
its own measured benefit, exact accounting/output and safe ordinary operation.
Do not replace one combined release with several unfinished infrastructure
projects whose benefits depend on all the others landing.

The owner initially requested Relay Plan for independently shippable slices,
starting with bottleneck confirmation on 2.13.2 and a usage-reading improvement.
**S0 and S1 below are closed records.** The subsequent quick review and
Brainstorm-and-Plan request scoped **S2 allowance preparation** in the final
section. The owner subsequently rejected a one-second gain as insufficient and
selected the lower-risk theme-only opportunity for a focused plan. The linked
theme plan is now a published closeout. The older allowance proposal and broader
invalidation backlog remain parked; the linked on-demand plan owns the current
bounded execution authority.
The director
may choose ordinary engineering details within an approved slice, including
diagnostic tools, task/model assignments and a simpler repair than anticipated.

The completed [SQLite/cleanup plan](dashboard-preparation-performance.md) and
[2.13.2 receipt](../release/2026-10-28-2.13.2-published.md) remain closed records.
Preserve the parked combined source/evidence in the separate release-2.14.0 and
original checkouts. Its experiments can inform a hypothesis, not qualify this
baseline or require resuming its semantic/Facts/publication machinery. No 512 MiB
retained-data limit, source TTL, live installation or automatic activation.

## Original Starting Point

- Execution checkout: `/Users/wjmao/projects/codex_usage-terra-release`, main at
  `fbf5b01b5b4dd6aa669da2798d26c69576837e41`. Tag `v2.13.2` is fixed at
  `570fe3f73090aeb7117cda8d69a91b5b3a657d1f`. Source, scripts, tests, workflows,
  dependencies and extension files currently match that tag; main adds docs only.
- Local diagnostic runtime: CPython 3.13.16, SQLite 3.54.1, OpenSSL 3.5.9. Preserve
  runtime identity in comparisons; do not add another runtime upgrade to S1.
- `agent_reports.render_ledger_report` enters `breakdown_reports`, which composes
  the existing base/speed/breakdown/allowance paths under a pinned read snapshot.
  `ledger_materialization.materialize_ledger` performs usage query, parent
  finalization, project transitions/filtering, valuation and activity generation.
  Full CSV is a separate consumer in `agent_reports.export_agent_activity_csv`.
- `ledger_queries.query_ledger_records` already restricts trusted generations and
  finite timestamps, orders by source key/original record index and supports
  finite range unions through `ledger_usage_ranges`. A timestamp index already
  exists. `RecordMetadata` already memoizes context/path values within a query.
  Do not propose these existing features as newly needed optimizations.
- Project filtering after lineage/transitions is intentional semantics to
  preserve, not permission to push a raw project-key predicate into SQL. The
  existing query's optional project filter alone is not equivalent to the full
  report's transformed project/alias membership.

Planning performed a public synthetic A/A diagnostic with the existing
`scripts/benchmark_collector.py`, identical released source/runtime on both arms,
`--mode report --profile --workload dashboard-extended --repeats 1`. Input is the
retained 3,180-record/30-day fixture, including Terra, quota/reset and credit
boundaries, frozen at 2026-10-28T12:00:00+00:00. SHA-256:
`63c35fc21efd69aae807bda420933817c2f47a3b48938c258ab538f1b01065cc`.
The original snapshot was not changed. No private database or account was read.

Evidence is retained under ignored
`output/performance/report-slices-2.13.2-planning-smoke-20261028/`. One preparation
pair and one measured pair completed with all 13 operation outputs/work checks
equal. This is an instrumented diagnostic, **not a speed comparison or a
representative large-history confirmation**. The harness's `private_input` flag
identifies report mode; this particular input is public synthetic. Per-operation
profiles are overwritten by later arms; the retained profiles belong to the
last measured baseline arm, not independent samples from every arm. The first
invocation failed before measurement because the output parent did not exist;
creating that owned parent was the only setup repair.

In retained `first-30d.prof`, the usage query including object materialization
has about 0.0224 cumulative seconds within a roughly 0.2341-second profiled
breakdown render. The profile also identifies aggregation/display work; the
cached 30-day profile performs no `query_ledger_records` call. These are nested
profile observations, not additive savings or uninstrumented wall timings.
They **do not establish usage reading as the dominant bottleneck**. S0 must not
turn this small-input result or the old indexer's profiles into a claim that a
large usage-reading rewrite is justified.

## Delivery Map

| Slice | Independently Useful Result | Boundary / What Stays Unchanged |
| --- | --- | --- |
| S0: confirm | A source-bound bottleneck and a justified next decision; a negative finding is valid | Investigation, not a product release or indexer bootstrap |
| S1: usage reads | Faster selected-range/project report or full CSV operation | Existing record values/order, pricing, lineage, quota/reset and report/cache contracts |
| S2: allowance preparation | Less quota/history preparation for a measured slow operation | Reset/credit semantics and ordinary usage reading remain the control |
| S3: report construction | Faster measured aggregation/composition/rendering operation | Same exact values/actions; no new source/index architecture merely to render |
| S4: valid reuse | Less repeated navigation/clock work where freshness permits | Existing fast hits remain fast; no cross-snapshot or stale-price reuse |

Only S0 is a dependency of choosing S1. S1 must run and be releasable without
S2-S4. Those candidates may be reordered or dropped based on evidence and need
their own concrete brief before implementation. Persistent indexing is an
optional technique inside a demonstrated component need, **not another global
platform milestone**. Keep 2.13.2 as the control; reuse parked code only when its
small dependency closure and total adoption cost beat a normal-path repair.

## S0: Confirm Before Implementing

1. Recheck the retained checkout, release tag, dirty state and actual runtime.
   Freeze baseline source and input/clock identities for the selected experiment.
   Never reset owner changes or modify original retained evidence. Use supported
   normal-ledger inputs, not old semantic products relabeled as a normal ledger.
2. Use the public fixture above for smoke only. Prepare a representative large
   input with both dense selected ranges and substantial unrelated history,
   source/context diversity and project/alias/transition cases. Prefer an
   existing supported, frozen normal-ledger control when local offline copy
   access is authorized; otherwise use a disclosed scaled synthetic fixture.
   Record selected/total event, source, context, project and quota counts and
   cache state. Synthetic-only findings must remain labeled synthetic-only.
   Stage a WAL-consistent SQLite backup or verified sealed snapshot in an owned
   disposable home; never copy only MAIN from a WAL-bearing database or open
   original retained evidence writably. Preserve and check original file hashes;
   do not delete sidecars or silently omit pending frames when staging input.
3. Exercise the real report/CSV entrypoints: first Today after revision, first
   unopened 30d, warm repeats, project selection and complete CSV. Include the
   existing usage-plus-quota append cycle, and distinguish usage-only, quota-only
   and clock-only changes rather than treating them as one invalidation class.
   Use the existing fixed-clock benchmark/work fixtures where suitable. Exclude
   preparation explicitly; cache state and permitted warming must match the
   operation being claimed. Do not silently exclude every first request.
4. Retain unprofiled operation wall/CPU/RSS first; then profile only the specific
   slow operation. Attribute SQL stepping/sorting, row decoding, lineage,
   valuation, allowance work, aggregation, HTML/JSON and cache publication. Use
   actual SQL plans, decoded-row/statement/VM counts and targeted wall wrappers
   when needed. Profile cumulation and nested phase times are not additive.
   Validate that instrumentation leaves output and work semantics unchanged.
5. Identify the dominant cost and the achievable end-to-end saving. A faster
   micro-query is insufficient if the whole operation remains dominated by
   another owner. Select the target workflow/input and positive performance
   target before changing production code; do not select a favorable target
   after seeing candidate timings.

S0 closes with a short decision in this plan: input/source/runtime pointers,
baseline operation timings, causal owner/work evidence, proposed narrow change,
expected whole-operation benefit and risks. Do not create a new controller,
certificate format or tracking system just to record it.

**Continue to S1** when representative evidence gives usage reading/materializing
a credible, meaningful whole-operation opportunity. The provisional engineering
target is at least 20% **and** 100 ms median improvement for the preselected slow
workflow. This target is proposed here, not an earlier owner requirement; the
director may select a justified alternative at S0 before candidate measurement,
recording its user-visible rationale. Do not weaken it retrospectively to pass.

**If reading is not the bottleneck**, S0 succeeds as an investigation, but S1 is
not delivered or automatically expanded. Retain the result and propose the
smallest appropriate later slice, or no change. A concrete breakdown-rendering
finding must not become an unrequested quota/index rewrite. No new cold build
is needed merely to reconfirm an already predicted miss; additional probes
should answer a stated uncertainty capable of changing the decision.

## S1: One Usage-Reading Improvement

### Implementation Boundary

Start with `ledger_queries.query_ledger_records`, `ledger_usage_ranges` and
`ledger_record_materialization`, following the actual S0 owner. Keep public
function signatures/result types and existing callers in `ledger_materialization`,
`breakdown_reports` and full CSV compatible. Measure both SQL work and Python
record conversion before choosing a repair. Possible techniques include a
better seek/join/projection or cheaper query-local decoding; none is prescribed
without evidence. Do not recreate existing metadata memoization.

Keep the caller-owned snapshot and preserve trusted-generation membership,
source/original-record ordering, exact timestamps and half-open range unions,
including overlap/empty unions. Preserve parent identity before project
transitions and project/alias filtering, root/subagent relationships and every
token/price field. If an early predicate cannot prove a safe superset through
those transformations, retain the existing later filter for that case. Do not
speed up by dropping source rows, changing accumulation order, approximating
money or relabeling unknown/excluded/review/image usage.

Try changes within existing read ownership first. A conventional SQLite index
is permissible when evidence requires it, but its creation, disk/write cost and
idempotent upgrade/rollback behavior belong to this same slice. Test populated
supported databases and active capture; do not inject an index into a prepared
copy and omit its production cost. A required long blocking build/new lifecycle
protocol is a direction-review trigger, not permission to import the parked
indexer. Prefer a smaller useful repair when it meets the goal.

Keep existing pricing, quota/reset interpretation, persistent cache identities,
normal capture orchestration and public report/CSV contracts unchanged. Scope
excludes semantic/Facts publication, new source formats, a replacement report
backend, generic scheduling/IPC, source schema rewrites and dependency upgrades.
Ordinary review fixes and a narrowly required index/migration do not each need
another human approval when execution already covers S1.

`ledger_queries.py` is 467 lines; evaluate a cohesive usage-query extraction
before substantial edits rather than expanding all query responsibilities.
`ledger_record_materialization.py` (57), `ledger_materialization.py` (71) and
`ledger_usage_ranges.py` (48) are existing small owners. The benchmark entrypoint
is 403 lines: prefer a focused existing-style adapter if new diagnostics become
necessary. Follow the owner's 400/500-line guidance, not size-only refactors.

### Proof And Release

- Add differential tests against frozen 2.13.2 on the same snapshot/clock, not
  merely a second call through the modified helper. Compare every record field
  and order before and after lineage/transitions, final totals/prices/coverage,
  all issued action payloads and complete CSV rows/order. Preserve exact float
  accumulation and Decimal values. Normalize only declared version/generated
  time/elapsed presentation differences, never accounting, membership or prices.
- Cover half-open/microsecond/DST boundaries, nonmonotonic and tied timestamps,
  overlapping/empty/unbounded ranges, aliases, effective transition boundaries,
  thread-scoped transitions, parent chains/cycles/missing roots, unknown models,
  Terra, excluded reviews/images, stale/staging/superseded/missing-retained sources
  and generation replacement. Include direct query, normal report, navigation,
  full CSV and any affected HTTP consumer.
- Extend `test_ledger_usage_ranges`, `test_dashboard_preparation`,
  `test_breakdown_navigation_work`, `test_project_transitions`,
  `test_session_provenance`, `test_valued_aggregation`, usage-breakdown/API and
  real-agent cases as relevant. Count actual decoded rows and SQL/VM work as
  unrelated history grows. A plan containing the word SEARCH is not alone proof
  of bounded work; whole-history queries still permitted by semantics need their
  actual cost recorded, not a false constant-time claim.
- Freeze the candidate before the final matched comparison. Reuse the existing
  collector benchmark: one separately reported preparation pair and ten
  alternating unprofiled measured pairs on the representative input. Preserve
  every sample/failure and exact input/runtime/harness identities. Profiling is
  separate diagnostic evidence, never an adoption timing sample. Rerun affected
  decisive checks after a material repair; do not requalify every tiny edit with
  the full campaign before it could plausibly meet the target.
- Require the predeclared positive whole-operation target and no material
  regression across Today/unopened 30d/warm/project/append/clock/CSV operations.
  Retain the established BOTH >10% AND >100 ms timing regression guard. Observe
  peak RSS, retained disk, admission wait and actual capture overlap, not only
  the query's CPU time. Proposed RSS nonregression guard: no increase exceeding
  both 10% and 32 MiB versus matched baseline. This is an experiment acceptance
  guard, not a retained-data limit. If S0 shows a necessary resource trade-off,
  decide and record it before candidate timing, within delegated risk authority.
- Exercise a real agent/report request overlapping ordinary capture, maintaining
  exact records, successful writes, bounded writer admission and clean shutdown.
  Test usage-only and quota-only changes and concurrent generation replacement;
  do not hold a write lease through a read optimization. Include index upgrade
  contention/build cost if that option was selected. No live home is needed.
- Independently review the scoped diff and run affected local tests/Ruff,
  extension tests/build and the existing selected preflight. Retain the full
  hosted Core/JUnit inventory with zero skips and all 3,011 shipped identities,
  both native packages, five visual suites and exact-package native Mac proof.
  Existing native Windows editor-UI and hosted-WebKit timing gaps remain explicit.
- Once this release's workflows/publication are authorized, use existing
  qualification, credential-free dry-run and exact-artifact promotion, then both
  official download/hash checks and a committed/pushed receipt. Select the next
  unused maintenance version at freeze; do not reserve it during planning.
  A transport/observer timeout never permits a duplicate upload or dispatch.
  Inspect real run/attempts; use the established manual checked-receipt recovery
  for an observer that cannot handle a genuine retry. No coordinator rewrite is
  a prerequisite. No other slice needs to be ready or included in that release.

S1 is incomplete if it has only faster query timings, passes on tiny fixtures,
requires an unfinished later subsystem, changes results or misses required
capture/resource/release evidence. A negative S0 result is not mislabeled as a
shipped S1. Keep usable code/evidence even when a candidate is declined.

## Ownership, Permissions And Recovery

Planning is authorized, including local public-synthetic diagnostics and the two
read-only planning reviews. Standing Relay task creation and explicit model/
effort selection authority applies; do not ask for it again. This request is
planning, not a new execution Goal. No production code, service or live data is
changed by writing this plan.

At execution handoff, authorize the chosen S0/S1 scope once and resolve whether
local offline copies of retained private normal-ledger controls may be used.
Without that access, useful public-synthetic work continues, but do not claim
production-shaped confirmation from an unrepresentative substitute. Do not read
live original sessions/account RPC, alter a live ledger/settings, upload private
evidence or install/restart the live agent. A later live activation needs its
own explicit authority; it is not part of package publication.

The completed 2.13.2 workflow grant does not authorize this next release or
unrelated CI. Before the affected publication steps, obtain one grouped grant
covering its required qualification, dry-run, promotion/publication, necessary
CI-triggering pushes and ordinary release recovery. Do not create a repeated
approval at every internal review, retry or candidate repair. Actual native
account confirmations cannot be bypassed. Local diagnostics/tests are distinct
from CI; covered local work need not wait for publication permission.

Default to serial production writes on the retained main checkout. Use parallel
read-only profiling/review or disjoint implementation work where contracts and
ownership are established; task count is not evidence of independence. One
integrator owns shared query contracts and whole-operation acceptance. Reuse a
worker for repairs within its assignment, then collect/review/close it and remove
its Relay route. Preserve wanted work before any worktree cleanup.

Use owned disposable homes and actual disk headroom; preserve original hashes
and old evidence. Do not inherit historical 6/24/32 GiB experiment caps as product
policy or require recreating already useful retained inputs. Adapt a benchmark
guard minimally when a legitimate experiment needs it, record the pre-run budget,
and continue counting actual retained/working allocations. Do not remove failed
samples to make a resource or timing result look better. On interruption, record
the source/input/run state, join owned processes and leave a recoverable patch;
do not reset files, delete sidecars or repeat an uncertain publication effect.

## Forecast And Direction Reviews

Forecast, not a cap: S0 about **1-3 hours** including representative input setup,
measurement and the decision. Conditional S1 about **3-8 hours** of implementation,
review fixes, focused/final verification and closeout, plus roughly **1-3 hours**
of external hosted/package/publication waiting. This assumes a narrow read-path
repair and existing runtime/release tooling. S0 determines whether that estimate
is credible; a new data representation or migration lifecycle changes it.
Later slices have no honest delivery estimate until their own bottleneck and
scope are established. Exceeding a forecast alone is not a stop or approval gate.

Use Relay Review at the S0 decision and proportionately before S1 publication/
closeout. Bring it forward if a faster component does not improve the whole
operation, repeated repairs move the bottleneck without progress, an index
requires substantial lifecycle machinery, or correctness/resource assumptions
change. Review means decide whether to continue/correct/redirect within scope,
not automatically ask the owner or launch another architecture.

## Planning Reviews And Handoff

Outcome/completeness review requested GPT-6.1 Sol / Xhigh, native worker
`01a1839e-c52c-72f1-b195-6015208d0db0`: no material findings. It found that the
representative-input/whole-operation gate, exact semantic/differential checks,
capture/resource requirements and independent release boundary rule out the
credible false successes considered. It read relevant source, harness and tests;
no edits, tests, builds, DB/private-evidence access, CI, services or delegation.
Explicit WAL-consistent input staging above clarifies existing snapshot safety.

Avoidable-restrictions review requested GPT-6.1 Sol / Medium, separate native
worker `01a183a1-d7b2-7fc2-8e50-8c6664a6193d`: no material findings or required
corrections. It checked director discretion, successful negative diagnosis,
premeasurement targets, actual permission limits, parallel ownership, resource
budgets and forecasts. It found no avoidable stall and no change requiring a
focused review-1 recheck. It read the draft/release guidance and confirmed main;
no edits, tests/builds, DB/private-evidence access, CI, services or delegation.

Both reports were collected; both reviewers are closed and Relay-unregistered.
Explicit requested settings remain independently host-unconfirmed. Current
checks establish a usable reviewed plan, not an implemented speed improvement
or representative large-input bottleneck confirmation. The latter is S0's job.

The owner subsequently explicitly requested E2E execution of this plan with
Relay Direct and an active Goal. That request covers S0 and conditional S1,
including the enumerated local offline control-copy access and this slice's
required qualification/dry-run/promotion/publication and ordinary recovery.
It does not authorize live installation/data changes, original-session or
account RPC access, private uploads, unrelated CI or the later backlog slices.
No routine review or retry adds another approval gate.

## Execution Checkpoint

Execution reuses retained main at `fbf5b01`, with only this plan initially
untracked. Released product/build/test inputs still match `v2.13.2`. The sealed
normal-ledger control in the preserved 2026-10-26 experiment matches its recorded
SHA-256 `c72afcf9c0245293a86c9c5800fd9e9aae30db2515b47d81d587a9d805a32f23`
(2,150,227,968 bytes), has no WAL sidecar and is opened immutable/read-only for
staging/metadata. Original metadata/evidence remain untouched. New measurements
use supported normal tables and the 2.13.2 report path, never old indexed-ready
products. Actual available disk headroom is about 390 GiB; the existing benchmark
staging check accommodates this isolated input and its working copy.

### S0 Decision And Direction Review

`output/performance/report-slices-20261028/` contains the frozen 2.13.2 source,
verified staged input and source-bound diagnostics. The control has 910,554
stored events / 489,402 trusted events, 209,743 selected 30-day events, 4,092
sources, 782 contexts, 76 projects and 383,034 quota observations. Unrelated
history and superseded generations remain present. Its clock is
`2026-10-26T22:33:16.414000+00:00`. Original and staged input hashes match.

The unmodified A/A screen (`s0-baseline-aa/evidence.json`) completed one separately
reported preparation pair and one measured pair with exact 13-operation output/
work parity. Measured first30d was 8.126/8.192 seconds, project-filtered 30d
5.554/5.550 seconds, CSV 2.344/2.358 seconds and warm 30d 0.090/0.079 seconds.
First-fill and post-append Today were approximately 14 / 8.4 seconds. These are
source diagnostics on this retained control, not packaged or ten-pair release
claims. Preparation's slower first arm is retained, not relabeled as a speed win.

`profile_released.py` replays the same home/path/clock once through the existing
benchmark; every profiled operation matches its unprofiled control output/work.
`profile-result.json` retains all 12 profiles (append write is not profiled).
In the project report, 409,982 usage records were decoded: 209,743 through the
ordinary usage reader and 200,239 through the speed-query project path. The
ordinary reader uses `RecordMetadata`; the speed path does not, repeatedly
constructing paths and decoding the same immutable context data. Its speed
aggregate took 3.494 profiled cumulative seconds, versus 1.908 account-wide;
409,982 total decoder calls consumed 3.129 cumulative seconds in the project
report. These nested observations are not additive savings or unprofiled timings.

`s0-mutations.json` separately records revision-fill, usage-only, quota-only,
clock-forward and rollback behavior on the owned home. Counts distinguish the
mutation classes. Usage/quota-only profiled Today requests took about 12.7/12.9
seconds while the ordinary usage query was about 0.058 seconds. Existing quota/
display preparation is the dominant Today issue and stays a later slice; S1
must not claim to fix it. These additional samples are diagnostic, not speed
adoption samples. No original sessions, live DB or account RPC were accessed.

Relay Review checkpoint: proceed with a narrow query-local decoding fix in
`speed_queries.speed_aggregates`, not a general SQL/index rewrite. Reuse existing
`RecordMetadata` only during one selected-project query; leave all public result,
snapshot, SQL, price, quota/reset and persistent-cache contracts unchanged.
The unfiltered path must still decode no full usage records. Source support
requested Sol/Medium, worker `01a183af-10ab-7a42-bba0-2a9cde5c24ef`, mapped the
callers/oracles and confirmed imported aliases/transition hazards; its read-only
report is collected and the worker closed/unregistered. Effective settings remain
host-unverified. It ran no tests or private-input queries.

Before any production patch, prototype or candidate timing, the director selects
the existing benchmark's **30d one project** operation (the same highest-count
project selection, not a newly favorable filter) as S1's primary workflow.
Predeclared target: **at least 10% AND 0.5 seconds median end-to-end improvement**
over frozen 2.13.2, with the original timing/RSS nonregression guards and exact
outputs for all operations unchanged. This replaces the provisional 20%/100 ms
proposal under S0's explicit target discretion: avoiding repeated context/path
allocation can provide a meaningful half-second interaction gain without
bundling another query/backend optimization. It is not a retrospective target
relaxation; no candidate implementation or measurement exists at this decision.
No new index, schema migration or cache format is needed. Broader first-report,
quota preparation and report-composition costs remain separately disclosed.

### S1 Candidate Checkpoint

The production change imports the existing `RecordMetadata` and constructs one
instance per selected-project speed query. SQL, query revisions and unfiltered
record-free behavior are unchanged. The speed-query owner remains 161 lines;
no oversized owner or new responsibility needs extraction. Frozen 2.13.2 speed
and decoder oracles independently compare every decoded field/order, aggregates
and SQL; structural conversion checks fail on the old implementation (24 versus
four context conversions) and pass with reuse. The affected cohort passed 121
tests. Three additional real-agent HTTP tests pass usage-only, quota-only and
trusted-generation replacement while the project report holds its snapshot;
capture finishes within the ten-second test guard, records stay pinned and the
next request sees current data. Integrity and clean shutdown pass.

Independent read-only review requested Sol/Medium, worker
`01a183c3-b540-7fe0-8f98-2c9521f3204e`, found no material issues in the production
diff, frozen-oracle independence, cache lifetime or HTTP concurrency tests. It
ran no tests/builds/private queries. Its reports were collected and it is closed
and Relay-unregistered; effective settings remain host-unconfirmed.

The first unprofiled screen retains its excluded preparation pair (5.584 to
5.006 seconds) and measured pair (5.527 to 5.024 seconds), with exact output/work
parity for every operation. The measured 9.1% / 0.503-second saving **does not
pass** the unchanged conjunction of 10% and 0.5 seconds. The final ten-pair
comparison decides acceptance, not preparation or the best sample. Version
2.13.3 is unused and selected for this frozen candidate; it is not yet released.

### S1 First Comparison And Bounded Correction

The first ten-pair campaign (`s1-final-10pairs/evidence.json`) completed with
exact output/work parity, no timing-guard regressions and peak RSS of
1,927,053,312 / 1,928,527,872 bytes (baseline/candidate). Its primary medians were
5.5079804585 / 4.9692037285 seconds: 0.53877673 seconds, **9.7817%** saved.
This misses the predeclared 10% conjunction and is not an adoption pass. All
samples, including preparation, remain retained. Product/benchmark source stayed
fixed; a later commit only registered the new changelog date in its test registry.

Relay Review checkpoint: correct one further repeated operation in the same
speed-query owner, not expand into SQL/index/quota work. The released profile
shows 200,239 project-filter helper calls (0.1636 cumulative profiled seconds).
Apply that unchanged helper once to the complete post-transition record list,
then retain row alignment with an object-identity membership set. Every row is
still decoded and transitioned; no early project predicate is introduced.
The same helper owns normalization and alias semantics. Keep the original
10% / 0.5-second and timing/RSS guards; added membership-set allocation must be
measured, not dismissed. There is no new index, schema or cache contract.

Independent read-only concept/actual-diff review requested Sol/Medium, worker
`01a183d8-14c1-7341-891d-b4d678534724`, found no material issues. Expanded frozen
oracle cases cover padded aliases/whitespace, and the structural test verifies
one selected-query call on the actual post-transition references, versus zero
account-wide calls. Its test-first assertion failed 24 versus one before the
repair. Oracle/concurrency tests now pass all 20 cases. The reviewer performed
no tests/builds/private queries; reports are collected and the worker closed
and Relay-unregistered. Effective settings remain host-unconfirmed.

### S1 Decode-Work Checkpoint

The identity-set candidate's complete ten-pair campaign
(`s1-batched-final-10pairs/evidence.json`) also missed the unchanged target:
5.5616532705 to 5.0673070630 seconds, 0.49434621 seconds / 8.8885% saved.
Exact outputs and timing guards passed; peak RSS was 1,929,461,760 /
1,938,440,192 bytes. No samples were excluded. Background OrbStack and unrelated
browser work were observed, not stopped or used to excuse/exclude results.
A streaming cursor removes the identity-set allocation while preserving the
helper's ordered reference subsequence. Its short screen still missed:
5.7472686670 to 5.2578950420 seconds. This is not an adoption pass. The same
independent reviewer checked cursor alignment/advancement/exhaustion, found no
material issues and was collected/closed/unregistered. All 130 affected tests
passed; the earlier full local suite passed 3,031 cases, preserving every one
of the shipped 3,011 identities, plus all 87 extension tests and five visuals.

Relay Review: do not keep repeating unchanged decoding or relax the target.
A read-only aggregate check of the frozen control finds 200,238 in-range trusted
speed rows across 430 contexts, but only 68,574 rows / seven contexts can match
the benchmark's preselected project; no transition source can move into that
selected key on this input. The report's existing synthetic append adds one
speed row. This supports a larger, bounded decode-work reduction in S1.

Before implementing or timing it, select a conservative context-level decode
prefilter: retain a context when its original key/aliases match, or any transition
from its original key could target a selected key. Ignore transition time/thread
restrictions in this early predicate, retaining false positives deliberately.
Actual transitions and the existing project filter still decide final membership.
`apply_project_transitions` rewrites each record independently and introduces
only its target plus retained original aliases, so this is a provable superset,
not a raw project-key SQL predicate. Empty/whitespace-only normalized selection
must bypass it. Keep SQL, source rows, public record/accounting paths, lineage,
snapshots, final filter and all original performance/resource gates unchanged.
Compare every retained decoded field/order with the frozen decoder and full
aggregates/HTML/CSV against released control; prove unrelated contexts no longer
cause full decoding. This adds no persistent representation or lifecycle work.

Implementation adds a small query-local candidate helper in the same 187-line
speed-query owner. Six test-first decode-work assertions failed against the
unpruned implementation; all 130 affected cases now pass. Every retained record
matches the independent released decoder and is an ordered subsequence; full
aggregate/SQL parity still compares against all released rows. Source/alias
changes and rollback invalidate decisions naturally with the query lifetime.
The same Sol/Medium reviewer independently checked the actual superset proof,
field/order tests and memory ownership, found no material issues and confirmed
that normal accounting rows are untouched. Its report was collected and the
worker closed/unregistered. A short screen precedes another final comparison.

`s1-decode-screen-01/evidence.json` completed preparation plus one measured pair
with exact outputs/work for all 13 operations. Project preparation was 5.9554
to 4.5991 seconds; measured was 6.4786 to 4.7517 seconds (1.7269 seconds saved).
These are source-backed screening results under observed background activity,
not ten-pair adoption evidence or a blanket first-report performance claim.
This candidate now has a credible larger end-to-end margin; proceed with the
unchanged final comparison and full release gates. No target was relaxed.
The final prefilter/cursor source subsequently passed all 3,031 local Python
cases with zero skips (`local-decode-tests.xml`), retaining the same shipped
3,011-case subset and 20 new cases. This supersedes the earlier candidate's
local full-suite evidence; hosted qualification remains required.

### Final Assessment And Release

The agreed S0/conditional-S1 outcome is achieved independently of S2-S4.
`df74863a7b50d17a1cf94976629c3f7c6c1df4da` is the qualified, tagged 2.13.3
source. The final frozen-source campaign
`output/performance/report-slices-20261028/s1-decode-final-10pairs/evidence.json`
completed one excluded preparation pair and ten alternating measured pairs.
Evidence SHA-256:
`6b8c11caeb44c949e5248973eef87e390448c3e5c76cbe9883d21b306758d59c`.

- Project-30d medians: **5.6138133960 to 4.4703350420 seconds**, saving
  **1.1434783540 seconds / 20.3690%**. The predeclared 10% AND 0.5-second
  conjunction passes without a retrospective relaxation.
- Every operation's complete HTML (including rendered action payloads), CSV,
  work and cache expectations match released control. No timing-guard failures
  occur. All runtime/dependency
  identities match between arms. The unchanged harness hash is
  `e6154b6aed96760a8af100176a6774b413de4a1c5cd81785a2eea2de8b8dd9fe`.
- Peak RSS is 1,929,150,464 / 1,934,311,424 bytes (baseline/candidate), passing
  the original comparative guard. Append-writer admission median/max is
  3.354/3.695 ms versus 3.221/3.601 ms. Real-agent overlap tests independently
  cover usage, quota and generation replacement with pinned/fresh snapshots,
  successful writes, integrity and clean shutdown.
- These are source-backed report-operation timings on the disclosed frozen
  normal ledger, not a claim about native VS Code interaction latency. First
  Today/30d remain roughly 13.9/8.1 seconds here; allowance preparation remains
  the principal Today issue. No broad first-load target is declared solved.

Normal qualification `40760420250`, credential-free dry-run `40763657217` and
explicit promotion `40763798041` all passed on attempt one. Full hosted Core
has 3,031 passes and zero skips. Its original payload was independently validated
and retained locally under `output/releases/2.13.3-process/core-proof-archive/`;
all 3,011 shipped identities are preserved, plus 20 new cases. Both platform
payloads independently pass all 87 extension cases, official SQLite 3.54.1 and
the required maintenance proof. All five visual suites and exact-package native
Mac proof pass. Existing native Windows UI and hosted-WebKit timing limitations
remain explicit; no new waiver or gate reduction was introduced.

Both official downloads and declared catalog hashes match qualified bytes at
2026-10-28T20:37:46.332Z. The generated
[published receipt](../release/2026-10-28-2.13.3-published.md) binds exact hashes,
sizes, source, tag and producer/publisher evidence. Promotion did not rebuild the
VSIX packages. The receipt hash was checked before documentation closeout.
The live ledger/settings and installation were untouched; no private ledger,
session contents or benchmark artifacts were uploaded. Original/staged control
hashes still match the sealed input.

Final Relay Review: accept this bounded release. It improves a complete project
workflow with exact behavior and no material resource/timing regressions, adds
no index/build lifecycle and needs no later slice to be useful. Reviewers are
closed/unregistered; owned tests, benchmarks and release observers are terminal.
S2-S4 and the preserved indexing work remain deferred, requiring their own brief.
The documentation-only closeout leaves the release tag and product bytes fixed.

## Quick Review After 2.13.3

Verdict: the agreed S0/S1 result was achieved. The final ten-pair operation gain,
exact outputs/capture checks and verified public packages support bounded
success; the unchanged slow Today path does not invalidate that scoped result.
Planning started on clean main at `7e5d2bd7a9f6f77ea49ab7e841318a963d61dd5c`; product inputs still
match the fixed `v2.13.3` source `df74863a7b50d17a1cf94976629c3f7c6c1df4da`.

Keep three lessons for the next slice. Work from the remaining measured owner,
keep changes independently useful, and screen causal work reduction before a
full campaign. The first two complete campaigns missed the chosen target;
metadata reuse and batched filtering alone were not sufficient. The eventual
conservative decode reduction produced a clear margin with only a small source
change. Do not spend repeated full campaigns trying to cross a marginal number
without a new causal hypothesis. One absolute primary target below avoids a
second, nearly coincident percentage threshold. This is a method improvement,
not an excuse to relax an observed miss or a new retry/time limit.

## S2: Today Allowance Preparation (Parked Draft)

Owner correction: a one-second saving is not material enough to justify this
effort. This reviewed draft is preserved for context, not approved or the current
execution handoff. Reassess a larger everyday benefit before reviving it.

### Result And Design Choice

Make a complete **Today report after ordinary usage-and-quota capture**
meaningfully faster on the shipped 2.13.3 path, with the same accounting,
allowance/reset/credit evidence, history, issued actions and complete CSV.
It must ship without S3/S4 or the parked indexer. This is source-backed report
latency, not a promise of native editor interaction latency or the old 3s Today
target. No new SQLite/Python/model upgrade, retained-data cap, TTL or live install.

The director recommends reducing cold/request-local allowance preparation first.
An alternative is extending granular historical reuse using existing tracking;
this could also help append captures if their real invalidation path permits it,
but needs more invalidation proof. Unchanged-quota memo hits alone are insufficient.
The diagnostic checkpoint may choose either small closure, not a new caching
platform. Existing persistent/window caches remain useful, not a system to replace.
These are director proposals for this planning request,
not additional owner decisions or authorization to execute.

### Current Evidence And Owners

Use `v2.13.3` as control. In S1's final unprofiled candidate samples, first Today
was 13.933s, post-usage-plus-quota Today 8.374s, first 30d 8.137s and warm Today
0.073s. These are measured 2.13.3 source operations on the frozen control, not
fresh S2 adoption results. The 8.374s case is the existing direct-append proxy;
the ordinary-capture baseline must be established or its equivalence proved
before using it for the primary gate. The normal-ledger control and its sealed SHA/clock
are already recorded above; it contains about 383k stored quota observations.
Count timestamp-expanded points separately rather than equating them to rows.

Retained 2.13.2 profiles are diagnostic clues: allowance code is unchanged in
2.13.3. Post-append `indexed_allowance_report` took 10.423 profiled cumulative
seconds; `_build_from_costs` 8.365, raw evidence loading 1.916, display history
1.909, pace preparation 1.873, report encoding 1.647, reset history 1.126 and
account partitioning 1.032. These nested values are not additive wall savings.
First-fill pricing is also expensive, but it is not the post-append bottleneck
to optimize by repricing semantics changes. Refresh the selected phase attribution
on 2.13.3 before choosing the repair.

Entrypoints: `agent_reports.render_ledger_report` / `breakdown_reports` share a
pinned read snapshot and one `AllowancePreparation`; `allowance_index` calls
`allowance_queries._build_from_costs`, then publishes only if revision/dependency
still match. Inspect `allowance_preparation`, `allowance_captures`,
`allowance_pace_inputs`, `allowance_display_history`, `allowance_report_codec`,
`allowance_capture_codec`, `breakdown_evidence` and `breakdown_preparation` as
the measured owner requires. Do not change them all merely because listed.

Already present: one request-local raw load, canonical exported capture
dictionaries, timestamp/hash memos, grouped pace inputs, compact/reference-based
report encoding, historical calculation caches and independent quota tracking.
The optional process memo rejects more than 50,000 expanded points to limit
retained graphs/GC; this is not a source-history limit. Do not relabel any of
these mechanisms as missing or blindly raise that memo bound. A justified compact
reuse/resource-policy change is ordinary director discretion when measured and
declared before adoption, not a mandatory separate approval.

### Work And Decision Points

1. Recheck retained main/tag, dirty state and runtime. Preserve S1 and all parked
   work. Freeze 2.13.3 control source, input and clock; reuse sealed normal-ledger
   input/evidence rather than reconstructing the old experiment. Private-copy
   access for the new execution must be covered by its grant below. Otherwise
   use disclosed public synthetic work without claiming representative proof.
2. Refresh the primary operation unprofiled, then attribute the specific slow
   phases separately. Distinguish first fill, usage-only, quota-only, combined
   append and clock changes. Count raw rows/expanded points, passes, conversions,
   allocations/retained graphs, SQL and serialization; nested profiles alone do
   not prove an achievable whole-operation saving. A short A/A/setup check is
   enough when needed; another ten-pair baseline-only campaign is not mandatory.
   Record pricing/derived-cache state: distinguish cold first-fill repricing
   from an ordinary capture after monetary caches are established. Both arms
   must have the same permitted warming and invalidation, including cache upgrades.
   Trace the ordinary growing-rollout capture's parsed/recovered quota upserts,
   live read and credit updates. `recover_allowance` revisits changed sources;
   recovered timestamp-blob upserts can conservatively invalidate all historical
   prefix certificates even when endpoint readings repeat. Do not assume a
   direct usage-plus-live-read insertion has equivalent preparation/cache work.
3. Select one small dependency closure with a credible whole-operation margin:
   avoid repeated normalization, projection, sorting or encoding where exact
   immutable facts can serve current consumers. Request-local transformations
   and existing cache APIs come first. Preserve the order and authority each
   consumer needs; different causal/plan/reset views are not interchangeable.
   Record the causal hypothesis, source/work counters and target before any
   candidate production patch or timing.
4. Add an independent 2.13.3 differential oracle at the changed boundary and a
   failing structural work assertion. Implement with existing owners, then run
   focused tests/Ruff and a short complete-workflow screen. Use enough screening
   evidence to see a credible margin before the full campaign. Profile/diagnostic
   samples and preparation stay separate from adoption samples; retain misses.
5. Review direction if the dominant phase is elsewhere, gains remain marginal,
   repeated fixes lack new causal evidence, or a cache change grows into schema,
   bootstrap, reset-ownership or publication machinery. Choose a smaller useful
   repair or retain a supported negative diagnosis. Do not silently widen to
   the parked indexer or another slice. A diagnostic no-go is useful evidence,
   not a shipped S2 or a completed improvement/release.
6. Freeze the credible candidate, run final proof below, then independently
   review the scoped diff. When authorized, carry the exact candidate through
   existing qualification/dry-run/promotion, both public downloads, receipt
   commit/push and safe worker/process closeout. No additional slice must land.

All likely owners are small; inspect actual sizes before substantial edits.
Respect the 400/500-line cohesion guidance and do not split unchanged modules
or build new abstractions merely to satisfy a count. A narrow derived-cache
codec revision is permissible if needed: bound its dependency closure, retain
legacy decoding or exact rebuild fallback, validate corruption and publish under
existing snapshot/dependency fencing. No authoritative schema/source rewrite,
generic scheduler, semantic/Facts store or new index lifecycle is included.
A narrowly justified quota-writer no-op suppression may be considered if it
preserves all durable values/provenance and invalidation for every real change,
with normal-capture differential proof. Do not weaken the conservative treatment
of compacted/mixed-offset evidence or disable recovery/triggers to manufacture
append reuse. A new invalidation/ownership protocol is a direction-review trigger.

### Acceptance And Completion Evidence

- Proposed primary target: **at least 1.0 second median whole-operation saving**
  for Today following a capture-shaped usage/quota update, versus frozen 2.13.3 on the representative
  control. This is an engineering proposal, not an earlier owner requirement.
  At the diagnostic checkpoint, the director may select a justified alternative
  before production patch/candidate timing, recording user-visible rationale.
  Do not weaken the chosen target retrospectively to pass or replace it with
  component CPU savings. Other operations use the established material timing
  regression guard: BOTH >10% AND >100 ms. Keep S1's project-report gain.
- Default to exact full report/value/coverage/evidence, complete HTML and issued
  action-state payloads, all CSV rows/order and normal mutation effects versus
  frozen 2.13.3. Compare scalar types and ordered serialized public values, not
  only Python equality: preserve capture field order, float/negative-zero and
  bool/int distinctions, duplicate identity and canonical reference ownership.
  Preserve sequential float/Decimal arithmetic, token/model fields,
  unknown/unpriced/partial/excluded usage, parent attribution and account-wide
  allowance semantics under project/date filters. A routine codec identity can
  alter opaque scope hashes only through a declared, validated issued-action
  mapping using existing harness support; never normalize away states or prices.
- Cover compacted/duplicate/conflicting/missing-provenance observations, live vs
  parsed/recovered sources, plan changes across durations, tied/microsecond/DST
  timestamps, rollback/future evidence, full-meter and credit cutoffs, scheduled,
  bracketed/early/ambiguous resets, missing anchors and partial/stale coverage.
  Test exact history navigation, cache corruption/legacy fallback, tracking
  repair, same-revision rollback and clock-only changes. Keep numeric/accounting
  algorithms unchanged; optimization must preserve all retained evidence.
- Relevant existing suites: `test_allowance_evidence_loading`,
  `test_dashboard_preparation`, `test_allowance_window_cache`,
  `test_allowance_report_codec`, `test_allowance_pace_evidence`, display authority/
  history, reset economics/boundaries, history quota journal, history navigation
  and breakdown navigation/work. Scale new tests to the actual changed boundary;
  do not duplicate every suite into a new oracle or use the modified helper as
  its own reference. Full frozen-source report/CSV comparison remains decisive.
- Bind the primary timed request to ordinary capture's actual mutation shape,
  including parsed/recovered replay/upsert, live quota and credit updates where
  applicable. Use normal capture on owned synthetic rollout files with the
  allowance probe mocked offline. A replay into the large disposable control
  is permissible only after demonstrating equivalent mutations, dependency/
  journal invalidation and preparation work against that normal capture.
  Never resolve retained original source paths or omit recovery to make it fast.
  Time the resulting Today request; record capture and combined capture-to-report
  wall/CPU cost too. The material regression guard applies to ordinary capture;
  moving expensive preparation there cannot hide an unchanged/worse workflow.
- Reuse the existing collector's dashboard-extended workload as the regression
  matrix. Its direct usage-plus-live-read append may serve as the primary proxy
  only when the equivalence check above establishes the relevant invalidation
  and work behavior; otherwise use one focused capture-shaped paired adapter.
  No new controller/framework is required. For the final primary and matrix,
  use one explicitly
  excluded preparation pair and ten alternating unprofiled measured pairs on
  the final frozen candidate. Preserve every sample/failure, input/runtime/source/
  harness identities and cache state. Include separate usage-only/quota-only and
  clock-forward/rollback checks where the harness's combined append does not.
  Report actual SQL/decoded work as history grows, not false constant-time claims.
- Observe RSS, retained graph/GC cost affecting full CSV, temporary/disk footprint,
  writer admission and real HTTP report/capture overlap. Keep the existing RSS
  guard: no increase exceeding BOTH 10% AND 32 MiB, unless a justified trade-off
  was explicitly chosen before candidate timing within authorized risk scope.
  Show successful usage/quota writes and generation replacement, old-snapshot
  isolation, next-request freshness, bounded writer admission and clean shutdown.
  Gate overlap at the changed allowance-preparation/publication boundaries,
  not only S1's speed decoder, and retain the existing ten-second synthetic
  capture-completion guard while the report holds its snapshot. Record actual
  admission/held durations against control on the representative workload.
  Never retain a connection across requests or a write lease through preparation.
- Run focused/full Python tests, Ruff, all extension cases/build and selected
  preflight. Full hosted Core must retain all **3,031 shipped 2.13.3 identities**,
  plus new cases, with zero skips; retain raw Core/JUnit proof locally. Both
  native packages, five visual suites, exact-package native Mac and official
  download/hash checks remain required. Keep the existing native Windows UI and
  hosted-WebKit timing gaps explicit. Choose the next unused maintenance version
  only at candidate freeze; do not reserve or change versions during planning.

An accepted S2 requires the primary workflow gain, exactness and operational/
resource proof, and authorized publication/receipt closeout. Faster helpers,
warm-only wins, tiny-input results or publication without the benefit do not
complete it. A failed adoption gate leaves an unshipped candidate and an explicit
next decision; useful code/evidence must be preserved.

### Ownership, Authority And Forecast

This user request covers quick review, source/retained-diagnostic inspection,
planning edits and the two read-only planning reviews. It does not start a new
Goal, production implementation, fresh private-ledger access, CI or publication.
The closed S0/S1 execution/workflow grant does not silently carry to S2.

Standing task creation and explicit Relay model/reasoning selection remain
approved; do not ask again. Default to manager-owned serial writes on retained
main, with attended read-only reviews or genuinely disjoint work when useful.
No new automation/controller, compulsory worktree or recurring human sign-off.

For an E2E execution handoff, obtain **one grouped grant** covering S2 local
implementation/testing, offline disposable copies of the already sealed private
normal-ledger control, scoped commits/pushes and this slice's required GitHub
qualification, credential-free dry-run, exact-artifact promotion/publication and
ordinary release recovery. Ask once when approving execution, not at each review
or retry. Actual native confirmations still apply. No live ledger/settings or
service install/restart, original session/account RPC access, private data or
benchmark-artifact upload, unrelated CI, retained-history deletion or later-slice
execution is included. Public synthetic work remains available if private access
is not granted. Source-bound exact proof must not be claimed from an inadequate
substitute. If only local work is approved, publication stays explicitly pending.

Use existing release coordination and receipt recovery; an observer timeout or
uncertain upload never permits duplicate dispatch/upload. Preserve process and
publication intents, real run/attempt identities and useful work. Review fixes
and verification within the granted result continue without another approval.
When interrupted, settle owned processes and leave recoverable source/evidence;
never reset owner changes or overwrite the fixed 2.13.3 tag.

Forecast, not a cap: roughly **2-5 hours engineering/local verification**, including
a short 2.13.3 diagnostic refresh, review fixes and final matched measurements,
plus **0.5-1.5 hours hosted/build/publication waiting**. This assumes a small
request-local preparation repair and existing release tooling. Revise the estimate
when evidence changes; a larger representation/lifecycle requirement triggers
direction review, not an automatic rewrite or an invented deadline.

### S2 Planning Reviews

Outcome/completeness review requested Sol/Xhigh, independent fresh-context
native worker `01a184e7-290f-7983-a5bb-43b3e13ae26d`. It found one material
pass-but-fail case: the existing live-read-only benchmark append can bypass
ordinary capture's parsed/recovered timestamp-blob updates, so an append-prefix
reuse gain could vanish during normal growing-rollout capture while all other
checks pass. The primary capture-shaped measurement/equivalence requirement
above resolves it. Capture/combined latency checks also prevent shifting cost
out of the report timer. A focused recheck of the repaired workload, bounded
reuse alternative and strict writer no-op conditions found no remaining material
gap. No extra finding in the bounded S1 review; no production execution occurred.

Separate avoidable-restrictions review requested Sol/Medium, fresh-context
native worker `01a184ee-f326-7c61-a5fa-b7d666484df0`. It found no material
avoidable restrictions: implementation choices stay with the director, one
future grouped grant covers foreseeable side effects, forecasts are not caps,
and proof protects the outcome without prescribing another mechanism. It made
no changes to success/proof assumptions, so no further review-1 recheck was
needed. Both reviewers performed source/document inspection only, with no
tests/builds/benchmarks, private-data access, CI, publication or delegation.
Requested model/effort selectors were explicit; effective settings remain
host-unconfirmed. Both reports are collected, workers closed and Relay routes
removed. The owner subsequently parked this proposal as described above; these
reviews do not approve implementation or override that later direction.
