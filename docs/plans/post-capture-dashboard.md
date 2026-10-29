# Post-Capture Dashboard: Ship Or Drop

Updated: 2026-10-29, America/Toronto.
Status: closed with a supported feasibility drop on 2026-10-29; no product release.

## Intended Result

Make the main Usage dashboard materially faster after an ordinary Capture Usage
operation on shipped **2.13.5**. Preserve exact current usage, allowance meters,
balances, estimates, causal pace/calibration, chart contents, freshness and issued
actions. Keep complete history and CSV available with the existing on-demand
history behavior. No further UI content moves behind a load action.

The owner selected the post-capture dashboard over cold 30-day/project reports
and explicitly retained **ship-or-drop** and the proposed **2.0-second saving**.
Use **at least 2.0 seconds median native capture-to-complete-visible saving**
against a matched 2.13.5 control as this slice's engineering adoption target,
not a universal latency SLA. A measured miss remains a miss. Do not lower the
target retrospectively or publish merely because code and release gates pass.

A supported finding that no narrow change can meet this target completes the
investigation. It is not a speed improvement or a release. Preserve useful
diagnostics and close the slice without a version bump. Ordinary corrections
within the same demonstrated dependency closure remain possible; ship-or-drop
is not a one-attempt rule or a reason to discard usable evidence.

## Baseline And Known Facts

Use the retained checkout `/Users/wjmao/projects/codex_usage-terra-release`.
At planning, clean `main` and `origin/main` are
`96bfbe332353acb9b789bb2119570c51c381cd2f`; shipped `v2.13.5` is fixed at
`497c5a846a60f8153eecb24c90f18c04e9ae7685`. Main adds documentation only.
Recheck actual state before execution; preserve owner changes and all parked
work. Do not switch to the original or release-2.14.0 checkouts.

The [previous slice](on-demand-allowance-history.md#published-closeout) is closed.
Its source/API-backed native comparison measured capture-to-visible medians of
15.402542 to 11.759839 seconds,
with capture 1.408551 seconds and first requested history 8.605889 seconds on the
candidate. These are retained comparison results, not a fresh baseline for a
new candidate or an actual packaged-collector capture baseline. The broader
source-only matrix records post-usage-plus-quota
Today 5.516 seconds, usage-only 5.418 seconds and quota-only 5.582 seconds.
Native and source timings are different boundaries and must not be mixed.

Retained evidence: `output/performance/on-demand-history-20261029/`.
The sealed normal-ledger control is
`output/performance/report-slices-20261028/input/ledger.sqlite3`, SHA-256
`c72afcf9c0245293a86c9c5800fd9e9aae30db2515b47d81d587a9d805a32f23`,
2,150,227,968 bytes. Reuse its supported frozen input and owned capture staging
under the fresh offline-copy grant below; do not reconstruct the old indexer.
Its offline unavailable-source/partial-coverage conditions limit generalization
and must remain disclosed. Use independent complete-coverage synthetic cases
for affected calculations as well; do not claim the retained fixture proves
live-source capture or account access.

Current owners and concrete hypotheses:

- `agent_reports.render_ledger_report` enters `breakdown_reports` under a pinned
  read snapshot. `_render_base_ledger_report` requests compact current allowance
  output when history is deferred, then materializes the monetary report.
- `allowance_index` already caches event prices, window calculations, compact
  pace state and distinct validated full/deferred reports. Publication checks
  both ledger revision and the existing dependency token.
- `allowance_queries._build_from_costs` still needs raw evidence, priced cost
  prefixes, window fits and causal references for exact current figures. It
  skips detailed display/reset history in deferred mode. `_cost_windows` still
  constructs window point lists that `current_projection` later strips. This
  is a redundancy hypothesis, not evidence of a two-second opportunity.
- `AllowancePreparation` already shares one raw load, canonical captures and
  grouped pace inputs. `breakdown_evidence.prepare_evidence` and
  `breakdown_preparation.prepare_account` still need captured readings for the
  immediately available chart. Skipping all canonical capture construction
  would change the promised product; removing discarded lists may not save its
  underlying graph at all.
- Existing process memoization deliberately declines more than 50,000 expanded
  points to avoid retained graphs/GC cost. Do not relabel existing reuse as
  missing, blindly raise this bound, or call it a retained-history cap.
- Warm navigation/clock hits are already roughly 75-95 ms. They are regression
  controls, not the positive target. Cold long-range optimization and broad
  cross-revision invalidation remain separate, parked candidates.

No fresh phase attribution establishes the remaining dominant cost. Old 2.13.3
profiles include work removed in 2.13.4/2.13.5 and cannot justify this change.

## First Decision: Is There A Credible Narrow Win?

1. Freeze the actual 2.13.5 control, runtime, clock policy, representative input and
   permitted warming. Verify the sealed original before staging. Use a sealed
   copy or SQLite backup with all committed WAL frames; never copy MAIN alone
   from an active WAL-bearing input or delete sidecars to make it consistent.
   Fixed-clock source diagnostics are useful. Actual packaged runs use normal
   product clocks with recorded request/capture times and matched fixture rules,
   stable selected bounds and equivalent freshness/reset eligibility. Do not
   modify the host clock or shipped executable to fake a frozen clock. Choose
   owned evidence timestamps that exercise the selected workflow and disclose
   any remaining clock variation; do not normalize away its mathematical effect.
2. Validate isolation and the timing observer before expensive runs. Reuse
   `collector_smoke_environment.isolated_environment`/synthetic fixtures and
   the corrected native harness, adapted narrowly to the new control. Use an
   authoritative missing-executable sentinel except for explicitly owned fake
   RPC fixtures. Guard the imported discovery alias and original rollout opens
   in source adapters; verify no installed/PATH fallback on fixture failure.
   Disposable HOME alone is insufficient. Keep unused bundled collectors from
   activating in source/API benchmark fixtures; exact-package proof must not
   alter shipped assets beyond its declared activation-metadata patch.
3. Check the observer on the actual rendered page: correct current figures,
   chart/controls, fresh scope and history-load invitation must be visible.
   Fixed-depth DOM observation is identical on both arms. Use atomic control
   files and move large artifact/log flushes after timing. Do not measure HTML
   assignment/RPC completion as a visible report, traverse hidden history on
   only one arm, subtract observer cost, or add a version-only local rerun.
4. Measure an ordinary capture on the owned growing rollout with offline quota
   input, including parsed/recovered timestamp-blob upserts, live-read-shaped
   quota/credit changes, journal invalidation and resulting calculation work.
   Reuse the earlier verified staging procedure, priming after relocation. A
   direct SQL append is a useful secondary proxy, not the primary operation
   unless its relevant normal-capture equivalence is demonstrated anew.
5. The primary operation is the default Today/all-projects companion panel with
   history **not yet requested**, immediately following that normal capture.
   Preselect it before production changes/candidate timing. Also measure capture
   after history was requested: retain intent and valid selection; never reset
   it or silently unload history to manufacture the primary improvement.
6. Record unprofiled capture/report/native wall, CPU and RSS first. Attribute
   the remaining cold work separately: raw SQL/expansion, grouping/sorting,
   current windows/fits/calibration, canonical projections, chart partitions,
   selected usage, rendering/serialization, publication and native transfer.
   Use work counts or disjoint wrappers where helpful. Nested profile cumulative
   times are not additive savings. A short A/A check is enough to settle setup;
   no mandatory ten-pair baseline-only campaign is needed.
7. Record one causal hypothesis, a small dependency closure, expected complete
   visible margin, unchanged required work and director's continue/drop judgment
   here. A diagnostic omission probe is an upper bound, never correctness proof.
   A small request-local projection/normalization or existing-cache repair is
   preferred. The owner of the real bottleneck, not the allowance label, decides
   where a narrow post-capture repair belongs.

Continue only when a material complete-workflow margin is credible. Drop when
only subsecond/marginal cleanup remains, required current mathematics accounts
for the cost, or the opportunity needs broad indexing, reset/source ownership,
cross-snapshot reuse or cache-lifecycle machinery. Do not build another slice to
rescue this one. Review direction when repeated repairs lack new causal evidence;
an estimate is not a time limit and a slow external run is not itself a drop.

## Conditional Implementation

1. Add failing structural work assertions and a frozen-2.13.5 differential at
   the actual changed boundary. Preserve every accounting field, row membership,
   order and exact arithmetic. Keep baseline oracle code independent of the
   modified helper. Cover current estimates, causal/future evidence, reset/plan
   boundaries, credits, partial and complete coverage as the closure requires.
2. Implement only the measured closure, with existing request-local ownership,
   snapshot/dependency fences, cache APIs and corruption/legacy fallback. Do not
   retain live connections or write leases through computation. A narrowly
   required derived-format revision is allowed; no new authoritative source
   representation or generic cache/scheduler protocol. No prewarming or shifting
   report computation into capture/background work to conceal the wait.
3. Preserve eager API/CLI behavior and full/deferred cache separation, explicit
   issued history load, requested intent, navigation, errors/retry and current
   charts. Keep native scripts disabled, CSP and command allowlisting. No UI
   redesign or new loading policy is needed for a backend preparation repair.
4. Run focused tests and a short whole-workflow screen before final campaigns.
   Obtain an independent scoped read-only code review. Material repairs refresh
   the causal/correctness proof they affect, not every unrelated check. Ordinary
   repairs within the same demonstrated closure do not add approval gates or
   require a new reviewer/operator for every attempt.

Follow the owner's 400/500-line cohesion guidance. Likely backend owners are
small. `extension.ts` is 498 lines and is not an intended edit; evaluate cohesive
extraction if an actual new responsibility is necessary, not a size-only split.

## Evidence That Decides Ship Or Drop

- Freeze the credible candidate, source/runtime/clock-policy/input/harness
  identities and matched cache state. Final primary proof uses the **actual
  bundled collectors** from official 2.13.5 and the locally packaged frozen
  candidate, with ordinary Capture Usage through the real extension/HTTP path.
  No replacement source/API server or disabled collector can supply the primary
  result. Adapt the disposable native driver narrowly; leave the existing
  no-capture qualification journey unchanged. Run one explicitly excluded setup
  pair plus **ten alternating independent measured pairs** on equivalent owned
  input copies. This replaces, not supplements, a full source/API timing campaign.
  Preserve every failure, outlier and raw sample. Do not replace
  misses with selected reruns. Use the same editor host for both arms; preserve
  the existing qualification host contract without imposing redundant local
  version matching. Keep heavy tests/other owned benchmarks out of timed runs.
- Adopt only with **>=2.0 seconds median native capture-to-complete-visible
  saving** against 2.13.5 and unchanged exact current figures, chart contents,
  controls and actions. Capture timings and work counters must rule out moving
  the cost elsewhere. Source/API runs are screening/attribution only, not proof
  that the packaged runtime saves two seconds. Bind measured package/collector
  hashes to the frozen source, runtime and assets, then reconcile qualified
  package provenance with those inputs. Refresh affected primary evidence if
  runtime or performance-critical content changes. A source-only speedup,
  missing current content or a loading page cannot pass this gate.
- Preserve ordinary operation: cold and warm Today/30d, project/custom/range
  switches, usage-only/quota-only/combined captures, clock forward/rollback,
  freshness/reset deadlines, pricing and source/generation replacements. Use
  the established matrix where valid. No median timing regression exceeding
  **both 10% and 100 ms**, or peak-RSS increase exceeding **both 10% and 32 MiB**.
  Record CPU, retained/physical disk and writer admission/hold time separately.
  Report requested-history capture and first load/later pages/combined cost;
  the already accepted shifted history cost does not excuse a new regression.
- Compare all current/status/pace/calibration fields, membership and HTML,
  account-wide evidence and chart partitions with frozen 2.13.5. Compare complete
  loaded history/captures/fits/provenance/order/pages and full/custom CSV bytes,
  rows and filenames. Normalize only declared timing/version/chrome differences,
  not missing data, prices or invalid actions. Preserve scope issuance and valid
  origin-to-new-response transitions, including requested-history navigation.
- Exercise affected eager/deferred request orders, shared-cache reuse, legacy
  and corrupt derived rows, snapshot races, rapid/out-of-order replies and
  failure/retry paths. Preserve no-autoload behavior through unclicked theme/
  range changes. Cover complete-coverage and future/stale/reset-boundary cases.
  Reuse `test_allowance_on_demand*`, allowance preparation/codec/window-cache,
  breakdown/dashboard/navigation and existing exactness tests as applicable.
- Gate a real HTTP report at the changed preparation/publication boundary while
  a normal owned capture runs. Prove coherent old results, successful bounded
  writes and fresh next-request results, integrity and clean shutdown. Existing
  HTTP overlap cases use a ten-second capture guard; retain rather than quietly
  relaxing it. No write lease or retained reader may be introduced to gain reuse.
- Preserve all **3,091 Python identities** and **95 extension cases per platform**,
  add focused coverage and require full Core zero skips. Run Ruff/lock/extension
  validation and existing preflight, all five visual suites and both package/
  collector/archive/handoff gates. Retain the existing exact-package native Mac
  journey, including 21 original inputs/five theme updates and deferred-history
  no-autoload/load proof. Reuse unchanged validators; if one must change, replay
  it locally against real complete package/native evidence plus the relevant
  negative corruptions before hosted spending. Native Windows UI and strict
  hosted-WebKit timing remain disclosed gaps, not fresh acceptance claims.

Relay Review decides adoption from the full product result and resources. A
measured miss stays recorded; review may authorize a causally justified repair
within scope, or close with drop. A target/scope waiver is a user decision, not
an internal relabeling. Passing local checks alone is not the release outcome.

## Conditional Release And Safe Closeout

If adopted and execution authority covers release, use the existing
`scripts/release_process.py` and qualified-promotion path. Choose the next unused
maintenance version only at credible freeze; do not reserve one during planning.
Run required hosted qualification, credential-free dry-run and exact-artifact
promotion, verify both official downloads/catalog hashes, and commit/push the
generated receipt unchanged plus plan/roadmap closeout. No rebuild at promotion,
old tag movement or live installation is included.

Retain before-dispatch/upload intents and reconcile uncertain outcomes before
retrying. A justified failed-job-only recovery may use existing mixed-attempt
original-producer validation/manual recovery when the coordinator assumes
attempt 1. Do not add a coordinator rewrite or repeat healthy jobs to bypass its
observer. Preserve strict existing WAL-zero/timeout and Firefox/WebKit policies.
The 2.13.5 Windows WAL timeout passed on one same-source retry; cause remains
unproven. A recurrence warrants focused observer-versus-product diagnosis, not
blind retries or speculative WAL changes. No arbitrary retry quota is imposed.

For ship or drop, preserve useful source/evidence and original hashes, collect
owned sessions, review the outcome, then retire idle worker/reviewer routes with
supported tools. Keep the retained checkout and parked work. Never edit Codex
lifecycle state to clean up an orphan. A drop requires no package or hosted run.

## Authority, Discretion And Forecast

The owner explicitly approved this plan **E2E with Relay Direct on 2026-10-29**,
including best-judgment decisions during their likely absence. Standing
separate-task/model/reasoning selection approval applies without another ask.
This is a fresh scoped grant; the completed 2.13.5 grant remains closed. No
native Goal, timer or automation is requested or created.

The E2E grant covers this diagnostic and conditional delivery, including owned
offline copies of the retained sealed control,
local tests/disposable editor profiles, scoped commits/pushes, this slice's
required qualification/dry-run/promotion/public verification and ordinary
repair/retry/cleanup. Those foreseeable effects are approved together; do not
ask again at each internal review or retry. Continue when the existing internal
conditions pass. Real native restrictions still apply.

Excluded from that grant: live extension/agent install/restart,
live ledger/settings mutation, original rollout reads or account RPC, private
uploads, unrelated CI, source TTL/512 MiB retained-data caps, runtime/model
upgrades, cold long-range optimization and the parked indexer. Public/CI proof
uses synthetic content only; representative measurements remain ignored/local.
The earlier original-account-access uncertainty stays recorded in the previous
closeout; do not infer its absence from later successful contained tests or
inspect credentials/keychain/original sessions to resolve it.

The director may choose narrow implementation details, diagnostics, reviewers,
existing-cache techniques and ordinary repairs within this result. Writes stay
serial on the retained checkout; attended read-only work may be independent.
When internal conditions pass, continue already-covered work. No compulsory
worktree, new approval framework, arbitrary experiment budget or new subsystem
is a prerequisite. Record only consequential decisions in this plan.

Forecast: **1-2 hours** attribution/feasibility; if viable, **4-8 additional hours**
for implementation, review fixes, local/final/native proof and closeout, plus
roughly **0.5-1.5 hours external release waiting** excluding unusual repairs.
These are forecasts, not time/retry caps. Feasibility can close with drop.
The principal uncertainty is whether enough remaining work is avoidable while
keeping current math and charts eager. Revise the forecast at that decision;
review direction early if it grows into lifecycle work rather than continuing
only because effort has already been spent.

## Planning Reviews

Outcome/completeness review requested GPT-6.1 Sol / Xhigh, fresh-context read-only
agent `01a188d6-47a3-7972-9ce9-a3476a58836f`: one justified finding resolved.
The first draft allowed a source/API-backed native speedup plus separate package
qualification, which could pass without proving the shipped collector saves two
seconds. Final primary proof now uses both actual bundled collectors; source/API
runs are diagnostic only. The same single ten-pair campaign, normal clock policy
and package/runtime/source/asset provenance close the gap without adding another
full campaign or changing release qualification. The focused recheck accepted
the correction, with actual feasibility/performance left to execution. It found
the remaining handoff sufficiently specified. No edits, tests/builds/benchmarks,
DB access, services/network/CI or delegation occurred. Effective settings remain
host-unconfirmed.

Avoidable-restrictions review requested GPT-6.1 Sol / Medium, separate
fresh-context read-only agent `01a188dd-6435-7510-9601-8209eca6148a`: no actionable
findings. It confirmed one grouped future E2E grant, ordinary director discretion,
forecasts rather than caps, no arbitrary retry quota and a single packaged
primary campaign rather than duplicated final proof. Isolation and existing
release gates protect the agreed evidence, not extra human sign-offs. It changed
no success/proof assumptions, so no further outcome recheck was needed. No edits,
tests/builds/benchmarks, DB access, staging, services/network/CI or delegation
occurred. Effective settings remain host-unconfirmed.

Both reviewer reports were collected and the reviewers closed. At planning
handoff only this plan and its roadmap pointer had been edited; implementation,
private-input staging, benchmark execution, CI and publication had not started.

## Execution Decisions

- 2026-10-29: fresh E2E approval recorded above. Begin attribution and a safely
  isolated actual-package baseline, not a compulsory release. Keep the retained
  main checkout and one execution writer; manager oversight remains read-only
  after handoff. Preserve the wanted planning edits in this checkout. Review the
  feasibility decision before substantial production work, then continue covered
  implementation/release or close with a supported drop. Record consequential
  decisions here, not routine activity or a new orchestration ledger.

## Feasibility Closeout: Drop

Relay Review decision on 2026-10-29: **drop this slice before production
implementation**. The two-second native adoption target is unchanged. The
remaining measured work does not support a narrow change with a credible margin
while retaining exact current mathematics and immediate chart contents. This is
a bounded negative investigation, not a claimed performance improvement or a
proof that every possible future optimization is exhausted.

Execution used retained main at `96bfbe332353acb9b789bb2119570c51c381cd2f`.
The worker registered its actual native ID
`01a188e2-792a-7843-802a-02eba33e7ceb` to manager
`01a02aa7-b98f-7091-8327-89c59c7624d1` before work. Product source, tests,
runtime, extension assets and version remained unchanged. The initial wanted
plan/roadmap edits are included in this closeout. Parked checkouts were untouched.
No new worktree, Goal, automation, live installation, CI or publication occurred.

Private evidence remains ignored/local under
`output/performance/post-capture-dashboard-20261029/`:

| Evidence | Result and boundary |
| --- | --- |
| `package-baseline-01/sample.json`, `http.json`, `captured.png` | Official 2.13.5 actual bundled collector, production extension/HTTP ordinary capture, normal clocks: **7.816147 s** capture-to-complete-visible; capture **0.743648 s**, report **6.638484 s**. One feasibility baseline, not a final performance campaign. |
| `source-01.json` | Fixed-clock source attribution after ordinary owned capture: capture **1.250501 s**, report **8.298895 s**, report CPU **6.224364 s**, process peak RSS **878,133,248 bytes**. This boundary differs from the packaged normal-clock baseline. |
| `profile-01.prof`, `profile-01.json` | Separate instrumented attribution of raw SQL/expansion, exact pace preparation, current fits, chart partitioning and publication. Profile overhead is excluded from comparisons; nested cumulative values are not additive savings. |
| `sql-screen.json` | Read-only SQL access-path screening on the owned ledger. Microquery differences motivated one whole-report probe; they are not adoption evidence. |
| `sql-probe-01.json` | Scratch-only probe on the frozen source workload of missing-price anti-lookup plus grouped provenance loading: report **8.400027 s**, CPU **6.237144 s**, peak RSS **868,696,064 bytes**. No production patch or exactness qualification. |
| `preservation-cleanup.json` | Original hash/size preserved, owned prepared WAL zero, native descriptor removed and no process referencing the owned native runtime remained. |

The package baseline is bound to official VSIX SHA-256
`364a7131e741790b4452ed52a3d5ab1c84abd05121881c29afa99adf6d368e2c`
and bundled collector SHA-256
`8e7dd9e6fa11b3de54a2659259a9bfe028c2c8615f944139313c1cfc99629037`.
It used the same official package already bound to shipped source
`497c5a846a60f8153eecb24c90f18c04e9ae7685` by the
[2.13.5 receipt](../release/2026-10-29-2.13.5-published.md).
The disposable copy restored the collector executable bit and changed only
activation metadata, with a separate acceptance observer. It retained the
actual packaged server/collector; no source server or disabled collector supplied
this baseline. The observer used the existing fixed-depth DOM path, verified
fresh current estimates/meters/balance, chart/controls and the history invitation,
then captured the compositor. Atomic control receipts and in-memory HTTP
observation kept large evidence flushes after timing. Owned timestamps exercised
Today and fresh/reset-eligible readings without shifting retained timestamps or
changing the host clock. Normal capture preserved the usage increment, recovered
quota expansion and conservative journal invalidation.

The packaged fixture contains one owned Today event (100 tokens), retained
history and partial offline coverage. Its capture added six quota rows and two
recovered samples; the fixed-clock source capture added three quota rows and
one recovered sample. These known clock/fixture boundaries prevent treating
the package's single 7.816-second observation as a median or comparing it
directly with the source 8.30-second result or the earlier slice's 11.76-second
native median. No mathematical clock effects were normalized away.

The causal decision follows the complete-workflow evidence. In the unprofiled
source control, the **entire** `_cost_windows` call took **0.450089 s**;
discarded point-list construction is only part of that call. Required canonical
capture construction took **0.249477 s**, raw evidence loading **2.115824 s**,
chart evidence **0.122200 s** and account partitioning **0.485034 s**. Those
capture/evidence/partition owners still serve the immediate chart. The separate
profile also identifies exact pace grouping/checkpoints, complete cost-prefix
iteration and publication work; removing them would change required behavior
or require broader reuse/invalidation machinery.

SQL screening suggested a possible larger opportunity, so execution tested it
at the whole-report boundary before deciding. The scratch probe moved the
missing-price model lookup behind an existence test and replaced correlated
provenance aggregation with a grouped join. Missing-price work fell from
**1.218802 to 0.589263 s**, but raw loading stayed effectively unchanged
(**2.115824 to 2.167069 s**), and the complete report did not improve
(**8.298895 to 8.400027 s**). Both ordinary captures retained the usage/recovered
quota increments and conservative invalidation. These individual source samples
are diagnostic screens, not statistically established speed estimates. They
do not support committing to a packaged candidate with a two-second margin.
No further full campaign or broad cache/source rewrite was justified.
The scratch probe's different raw HTML hashes were not treated as equivalent
output or accepted as an exactness proof; no product candidate was adopted.

Isolation preceded capture/launch work. The sealed original matched its stated
SHA-256 and 2,150,227,968-byte size before staging and at closeout, with no WAL
sidecar. Only owned offline copies were writable. Original raw paths were
remapped unavailable before capture; source adapters guarded both the imported
discovery alias and JSONL opens, with an authoritative missing executable.
The actual package used only the owned fake-RPC launcher and allowlisted
environment, with method-name-only audit for `initialize`, `account/read`,
`account/rateLimits/read` and `account/usage/read`. No original rollout or
account RPC was used in this execution. Offline unavailable-source/partial
coverage still limits generalization. The earlier account-access uncertainty
recorded in the previous closeout remains unknown and is not erased by these
contained runs.

The manager independently read the phase data, actual-package sample and driver/
probe code, and inspected `captured.png`, then accepted **DROP** through Relay
Review before any production work. Proportionate final review accepts this result:
the observed narrow opportunity lacks the required margin, and proceeding would
need a different scope. There is no adopted candidate, version bump, final
ten-pair campaign, full regression/qualification claim or release. Native Windows
UI and strict hosted-WebKit timing remain existing gaps. The owned native host
and collector shut down; useful scripts/raw evidence and the retained checkout
remain available for manager inspection. The worker's Relay route stays intact
until manager acceptance and idle retirement.
