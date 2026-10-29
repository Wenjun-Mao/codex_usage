# On-Demand Allowance History

Updated: 2026-10-29, America/Toronto.
Status: 2.13.5 published and both official packages verified on 2026-10-29.
Product adoption, qualification, promotion and public verification are complete.

## Intended Result

Make the main Usage dashboard materially faster after ordinary capture by not
preparing detailed allowance history until requested. Keep current usage,
allowance meters, balances, estimates, pace/calibration, chart behavior and
freshness exact. All history and CSV rows remain available; nothing is deleted,
truncated or subject to a new retained-data limit.

The owner accepts a possible wait when requesting detailed history and explicitly
agrees to **ship or drop**. A useful negative feasibility finding completes the
investigation, not an improvement or release. The owner rejected roughly one
second saved as insufficient for the earlier allowance proposal. Seek a clear
multi-second everyday benefit, not another marginal micro-optimization.

This is one candidate spanning the old S2/S3 labels, not approval for their entire
backlogs. Capture-invalidation work, general report/payload optimization, the
parked indexer, runtime/model changes, history TTL and the 512 MiB cap stay out.
The [roadmap](report-performance-slices.md) retains the older parked S2 draft;
that draft is background, not this execution handoff.

## Current Source And Design

Use `/Users/wjmao/projects/codex_usage-terra-release`, retained `main` at
`222bf3f1cf0ad102e3973ba6c5ec4c55e6c31e50`. Product/build/test inputs match
fixed `v2.13.4`, source `2f20dd4b68e37c4d33ff9fc35cd6bc3f4e93db3c`.
The original and release-2.14.0 checkouts remain parked and untouched.

- `agent_reports._render_base_ledger_report` requests compact pace state, but
  calls `indexed_allowance_report` when it is missing or allowance HTML is cold.
- `allowance_index` builds the full result with `allowance_queries._build_from_costs`
  before encoding full, pace-state and history-overview cache rows. Compact
  projections already exist; adding another overview alone does not remove
  cold history construction.
- `_build_from_costs` combines pricing/windows and causal pace calibration with
  display/reset history. Historical evidence and fits can be necessary to
  current figures; only genuinely history-only work may move off the main path.
- `breakdown_reports` also needs account-wide evidence, partitions and issued
  actions. Its consumers must be traced, not assumed independent of history.
- `allowance_history_reports` supports bounded pages over prepared results;
  `allowance_history_navigation` validates issued, context-bound actions.
  Response scopes depend on context **and state**: a valid changed-state request
  carries the origin scope, while the new response can legitimately have another.
- The webview has `enableScripts:false`. A closed native `<details>` element
  neither avoids server preparation nor emits a backend load request when opened.
- `DashboardNavigation.accept` currently retains the advertised current history
  action. A new load invitation must not become requested intent through that
  automatic acceptance path; only an actual user request should enable loading.

Preferred design, subject to feasibility: an explicit companion presentation
mode keeps not-yet-requested detailed history off the initial main-report path.
Show a clear issued **Load allowance history** action in its place. Use the
existing command/receipt/navigation boundary, extending it narrowly if needed.
Keep direct API/CLI behavior eager by default unless a compatibility-preserving
choice is explicitly documented. Parameter names and module placement are
ordinary implementation choices, not prescribed code.

A new panel starts with history not requested. Once requested, preserve that
intent and valid selection across theme/range/project refreshes in the panel.
Real evidence changes retain existing expiry/reset rules and fresh figures;
recover the requested history safely rather than silently showing stale details.
This is request intent, not tracking whether native `<details>` is currently
expanded. Closing that disclosure after loading is not a new performance claim.
No product scripts, client data cache or background history prewarming are needed.

## Feasibility And Decision

1. Recheck checkout, fixed baseline, instructions and runtime. Read the relevant
   consumers/tests; preserve owner changes and old evidence. Use the existing
   public synthetic fixture for smoke and the retained sealed normal-ledger
   control for representative local proof when its execution access is granted.
2. Measure first Today after an **ordinary usage-and-quota capture**, not merely
   a hand-inserted usage/live-read pair. Use owned rollout fixtures and an offline
   probe. A large-control replay is acceptable only after demonstrating matching
   recovery/upsert, journal/invalidation and resulting calculation work against
   the normal capture path. Do not access original session paths or account RPC.
3. Attribute unprofiled wall time first, then profile/work-count the slow owners.
   Distinguish required current estimates/calibration, raw evidence, display/reset
   history, encoding, HTML, transfer and native rendering. Nested cumulative
   profile times are not additive savings. Existing old profiles are clues, not
   a fresh 2.13.4 baseline or proof of removable work.
4. Identify one cohesive history-only dependency closure. A disposable diagnostic
   may isolate its cost, but omitted/wrong figures in a probe are never candidate
   correctness evidence. Do not publish partial objects into a full-report cache
   or manufacture gains through extra warming or capture/background work.
5. Before production implementation, record the causal hypothesis, ordinary-
   capture baseline, likely complete visible saving and director's ship/drop
   judgment here. Proposed adoption target: **at least 2.0 seconds median saved**
   on that native main-report workflow versus 2.13.4. This is an engineering
   proposal, not an owner-imposed SLA. The director may select a justified target
   before candidate measurement; do not relabel a measured miss as a pass.

Continue when the work can leave the main path without changing required figures
and a material whole-workflow gain is credible. Drop or defer when history is
mostly required by current semantics, the benefit remains marginal, or the change
needs new source/reset ownership, indexing, bootstrap or publication machinery.
Record the evidence and preserve useful diagnostics. Do not complete another
slice merely to rescue this one. An unexpected material direction change gets a
proportionate Relay Review; ordinary repairs within the closure continue.

## Conditional Implementation

1. Add failing work assertions and baseline differential tests at the actual
   boundaries. Prove the initial companion request avoids the identified
   history-only preparation/encoding/rendering while required calculations run.
2. Split only the identified ownership, keeping authoritative data and math
   unchanged. Full and deferred results must have distinct, validated cache
   identities/formats where their contents differ; a partial result must never
   satisfy an eager/full consumer. Reuse existing snapshot/dependency fencing,
   derived-cache APIs and corruption/legacy fallback. A narrow derived-format
   revision is allowed; no new authoritative storage or generic cache protocol.
3. Wire the production extension request, displayed load action, issued origin
   receipt, backend preparation and exact rendered history end to end. The first
   load must be possible without having prepared history to issue its action.
   Never accept arbitrary/unissued commands just to bootstrap it. Preserve
   canonical `auto` transport and local display theming from 2.13.4. Exercise the
   API parameter/response path and matching-collector compatibility as well as
   the frontend; an unsupported mode must not silently masquerade as deferred.
4. Retain correct loading/error/retry states, latest-request-wins, disposal and
   view switching. Existing data can remain visible while loading; errors must
   be explicit. Real revision/clock/deadline/timezone/filter changes still refresh
   what they invalidate, including a capture racing the delayed load.
5. Run focused tests and a short full-workflow screen before a final campaign.
   If findings require a material repair, refresh the affected causal and
   correctness evidence, not unrelated proofs. Review the scoped diff
   independently and apply Relay Review at the adoption decision.

Most owners are small. `extension.ts` is 495 lines; inspect cohesion before
substantial edits and prefer a focused history-intent owner if meaningful new
state belongs elsewhere. Follow the user's 400/500-line guidance without size-
only or unrelated refactors. Keep source writes serial on the retained checkout;
read-only support and separate tasks/models already have standing approval.

## Completion Evidence

- Compare frozen 2.13.4 with the final candidate on equivalent sealed-input
  copies, runtime, clock, filters and permitted cache warming. Use one excluded
  setup pair plus ten alternating independent measured pairs for the preselected
  post-ordinary-capture main-report operation. Preserve every sample/failure,
  source/fixture/harness identity and outlier; no best-sample or warm-only claim.
- Primary timing ends at a complete **visible native report** with correct
  current figures, controls and the issued history-load action, not HTML
  assignment, an RPC response or a loading page. Retain source/phase timings as
  attribution; never subtract observer cost from the primary result.
- Work counters prove the identified history-only construction was avoided
  before the user request. Do not defer required math, move that work into
  capture, or precompute it in the background to hide latency. Measure capture
  and capture-to-visible time so a shift into capture is not called a saving.
- Keep initial cold load, warm repeats, unopened ranges/project selection,
  capture responsiveness/concurrency, writer admission, CPU/RSS and retained
  disk visible. Reuse the established material nonregression guards: both >10%
  and >100 ms for timing, both >10% and >32 MiB for RSS. Legitimately deferred
  history work is an accepted exception to main-path timing guards, not a leak
  or permission to silently regress unrelated operations.
- Measure first requested history and subsequent pages, and record combined
  main-plus-history latency and retained cache/resource cost. The owner accepts
  this possible wait; **do not require the combined cost to beat eager loading**.
  History must actually finish, expose all prior data/actions and remain usable.
- Differentially compare every main numeric/status field, data membership,
  account-wide allowance/reset/credit and causal calibration result. Allow only
  declared initial history-placeholder/navigation and time/chrome differences.
  After loading, compare all history periods/fragments/uncertainties, exact
  captures/fits, provenance/order, pagination and valid action semantics with
  baseline. Full CSV rows/bytes and filenames remain exact. Do not normalize
  away missing fields, invalid actions or newly truncated history.
- Exercise eager then deferred and deferred then eager against shared derived
  caches, plus corruption/legacy fallback. An advertised but unclicked load
  action must stay deferred through ordinary warm refreshes and theme changes.
- Exercise actual activation/config/request handlers and real script-disabled
  native input: first issued load, nondefault history/speed/breakdown selection,
  repeat load, theme/editor Auto, range/custom/project changes, freshness/expiry,
  restart/reopen, rapid/out-of-order replies, capture during loading, failures,
  retry, stale/malformed/unissued/cross-context actions, disposal and Storage
  switching. Preserve CSP, command allowlisting and local-resource restrictions.
- Use existing allowance evidence/preparation/codec/history-navigation,
  breakdown recovery, dashboard navigation and theme-configuration tests.
  Full Python/Ruff and extension validation retain all **3,055 Python** and
  **91 extension cases per platform**, plus the new tests; hosted Core has zero
  skips. Run five visual suites and both package/collector/archive/handoff gates.
- Extend the existing exact-package native journey and enforced qualification
  validator for deferred loading, preserved state and changed issued actions;
  retain the original 21 inputs and five theme/editor-palette updates. Account
  for the legitimate origin-to-new-response history scope transition. Replay
  any changed validator locally against real complete package/manifest/native
  evidence, with wrong-origin, wrong-rendered-scope and stale-content negatives,
  before spending a hosted cycle. Fixtures alone missed this in 2.13.4.
- Native Windows UI and strict hosted-WebKit latency remain explicit gaps.
  Public/CI/native artifacts use public synthetic content only. Private data,
  screenshots and representative measurements remain ignored/local.

If the candidate meets the selected adoption standard, completion includes
qualification, credential-free dry-run, exact-artifact promotion, both official
download/catalog hash checks, generated receipt and committed/pushed closeout.
Publishing cannot substitute for a missing product result. A measured miss gets
an honest direction review; under the E2E best-judgment grant below the director
may accept a materially useful bounded result with an explicit deviation, but
must preserve the raw miss and rationale, not silently weaken proof.

## Authority, Recovery And Forecast

The owner explicitly approved this plan E2E under Relay Direct on 2026-10-29:
feasibility and conditional delivery/release, local tests/disposable editor
profiles, offline copies of the retained sealed control, scoped source/docs
commits and pushes, required qualification/dry-run/promotion/public verification
and ordinary repair/retry/cleanup. This is a fresh scoped grant; the 2.13.4
release grant remains closed. Standing task creation and explicit model/reasoning
selection remain approved and require no renewed request. Use best judgment
without routine permission pauses and record only consequential decisions here.

A supported drop needs no release or version bump. No
live install/restart/settings/ledger mutation, original sessions/account RPC,
private upload, unrelated CI or another performance candidate is included.
Actual native confirmations remain. Internal reviews passing, ordinary fixes,
adoption decisions and already-covered recovery do not add human approval gates.

Reuse the current release process, choose the next unused maintenance version
only at a credible candidate freeze, and keep v2.13.4 and earlier tags fixed.
Preserve intents and failed/nonqualifying runs. Reconcile uncertain dispatch or
upload before retrying. A justified failed-job retry can use existing checked
mixed-attempt producer receipts/manual recovery if the coordinator's attempt-1
observer restriction applies; do not build another coordinator or redispatch a
whole qualification just to bypass observation. The 250 ms Firefox bound and
existing WebKit policy do not change merely because a hosted sample is slow.

Forecast: **1-2 hours feasibility**, then **5-10 additional hours** for a viable
narrow implementation, local/native proof, review fixes and closeout, plus
**0.5-1.5 hours external release waiting**, excluding unusual repairs. An early
supported drop may finish with the investigation alone. The larger uncertainty
is how much history is truly independent of current estimates and charts;
revise the estimate from that finding. These are forecasts, not time/retry caps.
Do not introduce a compulsory worktree, new Goal, timer or approval framework.

## Planning Reviews

Outcome/completeness review requested Sol/Xhigh, fresh-context read-only worker
`01a187c8-4ed6-7581-9356-c36b60c48aa9`: no material findings. It checked actual
owners/tests/native validation and found the ordinary-capture baseline, visible
timing, exact current/history/CSV behavior, cold issued-load bootstrap and honest
miss/adoption disposition sufficient to rule out its considered false successes.
API/CLI compatibility and full/deferred cache isolation are covered; both cache
request orders are now explicit. No additional user-result decision was needed.
It ran no tests/builds/benchmarks/database/network operations. Requested settings
remain host-unconfirmed.

Avoidable-restrictions review requested Sol/Medium, separate fresh-context
read-only worker `01a187cd-0629-7b81-b52f-819afcf285af`: no material findings.
It confirmed the genuine grouped execution boundary, forecasts rather than
caps, conditional ship/drop scope, accepted deferred-history cost, useful
best-judgment deviation review and existing checked-retry/manual recovery.
The local native-validator replay addresses a concrete prior defect, not a new
framework. No wording changes or outcome-review assumptions changed, so a
focused outcome recheck was unnecessary. No edits, tests, builds, benchmarks,
database/private-data access, network, CI or commits occurred. Requested model
settings remain host-unconfirmed.

Both reports were collected, reviewers closed and reporting routes removed.
This reviewed plan and the subsequent E2E grant above are the current execution
handoff; the older parked allowance draft and closed theme release are not
execution authority for this candidate.

## Execution Decisions

- 2026-10-29: retain the existing main checkout with one implementation writer.
  Begin with the feasibility/adoption decision, not a mandatory release. Preserve
  all parked work and do not broaden the candidate to rescue a negative result.
- 2026-10-29 feasibility checkpoint: **continue to bounded implementation**.
  Select the proposed **>=2.0 s median native capture-to-visible saving** before
  candidate measurements. Source screening supports a credible margin, not an
  adopted performance result. The cohesive cut is display/reset history,
  full-history codec/overview publication and history rendering/navigation;
  raw quota loading, canonical capture exports, monetary fits, causal references,
  current headlines/pace and account/chart partitions stay on the initial path.
  Independent read-only Sol/High dependency review confirmed that ownership cut;
  effective model settings were host-unconfirmed.
  Private local diagnostics: `output/performance/on-demand-history-20261029/`.
  `baseline-03.json` records actual normal `capture_once` on a growing owned
  rollout with an offline probe: capture 0.532 s, following Today report 8.917 s.
  The deliberately overgenerous `omit-03.json` screen records capture 0.537 s,
  report 5.861 s (3.056 s source difference). Baseline history-only wrappers were
  display 1.345 s, reset 0.398 s, full encoding 0.872 s and overview 0.031 s;
  these are disjoint measured calls, not nested profile sums. This is neither
  native timing nor candidate correctness; a real deferred codec/load action
  still costs work, and native proof remains required for adoption.
  The sealed SHA/2,150,227,968-byte control was verified before copying; original
  source paths were remapped unavailable before capture. All 489,402 originally
  trusted usage events and all 383,034 quota rows remain, plus owned synthetic
  append evidence. Each trial is fully primed after relocation, then captures an
  additional real usage record, parsed quota, recovered timestamp-blob upserts,
  live quota and credit read; the quota journal records conservative `-1e300`
  invalidation. No recovery/triggers were bypassed. Coverage stays incomplete;
  unavailable raw sources change byte coverage to the owned file while retained
  usage/quota and original stale-source count remain. Recovery stays at 1,524
  unavailable, plus the owned completed source. These offline-source conditions
  bound generalization to live-source capture. Earlier setup-query/checkpoint
  failures and unprimed screens are retained and excluded from this decision.
- 2026-10-29 implementation checkpoint: the independent read-only diff review
  found receipt portability clobbering by an eager client and output-only first
  history-load errors. Both were repaired with regressions; the focused recheck
  found no remaining actionable findings. Typed chart-only expiry now preserves
  still-valid history selection, and eager cache decoding rejects even an inner
  deferred partial payload. Valid eager HTML can supply exact current content
  without another preparation; only its history slot becomes the invitation.
  `extension.ts` remains below 500 lines (498); new state lives in the focused
  `AllowanceHistoryIntent`, so no unrelated extension extraction was warranted.
  Relay Review judges the candidate worth qualifying, not yet adopted. Preliminary
  native screen failures and results are retained, including the initially deep
  history observer. A fixed-depth native screen completed the issued load with
  unchanged current allowance content. No screen is final adoption evidence.
  The next unused maintenance version is **2.13.5** (local/remote tags through
  2.13.4 checked). Freeze this candidate for the ten-pair native comparison and
  exactness/resource/qualification work; do not publish unless the product result
  and exact-package gates pass. No installed extension or live ledger changed.
- 2026-10-29 containment repair before qualification: invoking the existing
  `bash scripts/build-agent-macos-arm64.sh` built the candidate and passed its
  parallel/WAL subchecks, then failed the final fixture-preservation assertion.
  Audit found installed Codex discovery was possible in all three smoke launch
  paths despite disposable Codex homes. Original account access and the changed
  fixture's cause remain **unknown**; the assertion alone proves neither.
  The failed log remains private/local at
  `output/performance/on-demand-history-20261029/local-package-build.log`.
  The final smoke had exited its collector before the failed assertion; known
  owned parallel/worker/native API PIDs were subsequently absent in targeted
  checks. Earlier app-server PIDs were not recorded. No unrelated sessions,
  credentials, keychain or account RPC were used to investigate that uncertainty.
  Package/native/CI work was held while repairing the boundary. Explicit
  `CODEX_CLI_PATH` is now intentionally authoritative/fail-closed; default
  discovery without an override is unchanged. All three smoke launch paths use
  allowlisted disposable environments and the existing synthetic RPC fixture,
  with method-name-only completion evidence and original preservation hashes.
  Source containment checks passed 34 cases, including valid/missing/crashed/
  malformed real fixture probes that forbid installed-app/PATH discovery.
  Independent read-only Sol/High boundary review found no actionable findings.
  Fresh corrected-binary synthetic-probe and preservation proof must pass before
  hosted qualification or promotion resumes. Native performance's unused old
  bundled collector is made nonexecutable in its disposable source/API fixture,
  closing accidental supervisor fallback; exact-package qualification remains
  unmodified except its declared activation metadata patch.
- 2026-10-29 containment closeout: older source tests also contained default
  capture calls without a probe mock, so earlier local unit runs share the
  historical account-access uncertainty above. Future full runs use a disposable
  allowlisted environment and an authoritative missing-executable sentinel;
  hosted Core has the same explicit sentinel. This does not change discovery
  when no override is supplied. One corrected local build hit a descriptor
  timeout and is retained as failed; the manager's sole-writer build and a later
  fresh build after cache validation both passed all three real synthetic RPC
  smokes with all six preservation hashes unchanged. The later successful log is
  `output/performance/on-demand-history-20261029/local-package-build-cache-validation.log`.
  Its collector SHA-256 is
  `6b0e0bf34c2ffeb20ff69fedfba6188beb0d9d8b13e5e2333f4dabf90aa6632b`.
- 2026-10-29 correctness checkpoint: isolated full Python validation passed
  **3,091 tests, zero skips**; every original 3,055 identity remains. Extension
  validation passed **95 tests**, retaining all original 91. The private complete
  differential in `differential-01/comparison.json` matches full allowance JSON,
  initial nonhistory JSON, all **16,486** rendered/navigation frames and
  **388,730** canonical captures, plus full/custom CSV bytes and filenames
  (4,372/2,149 rows). Main HTML differs only in the declared initial history slot
  and disclosure state; loaded history differs only in disclosure-open state.
  Real HTTP overlap tests pin preparation while a normal capture completes,
  verifying coherent old and subsequent fresh snapshots in both modes.
  Local package/native journey 02 passed the original 21 inputs/five updates,
  two unclicked theme changes and actual issued load with unchanged current
  content. That local host was honestly recorded as VS Code **1.143.1**.
  The changed validator was replayed against its real package/manifest/native
  evidence and rejected wrong origin, wrong rendered scope and stale content;
  this is local validator proof, not an invented hosted receipt. The selected
  final performance and hosted qualification host remains pinned **1.141.0**.
  Final native campaign 01 failed only its excluded setup's post-primary JSON
  flush-control race. Raw primary/failure evidence is retained. Atomic control
  file replacement fixes that observer race; no latency was subtracted and the
  ten measured pairs restarted in `native-final-10pairs-02` on the same pin.
- 2026-10-29 final native comparison: **primary target passed** on the selected
  VS Code 1.141.0 host. One excluded setup pair plus ten alternating independent
  measured pairs completed; all 22 samples and the earlier failed setup remain.
  Median ordinary-capture-to-complete-native-visible time is **15.402542 s** for
  fixed 2.13.4 versus **11.759839 s** for the frozen candidate, saving
  **3.642703 s (23.65%)**. Every measured pair saves 3.28–4.30 s. Actual capture
  medians are 1.414957/1.408551 s, so the benefit was not shifted into capture.
  Main source CPU medians are 9.799/6.473 s and peak RSS 1073.68/850.43 MiB.
  All native pairs have exact current-content and control text before declared
  timestamp/load-duration/version metadata. Required raw/windows/pace/account
  work runs, while detailed display/reset/encoding work is absent before click.
  Candidate first requested history takes **8.605889 s** median; main plus that
  history takes **20.333325 s**, which is the accepted deferred cost, not a claim
  of faster combined completion. Source history CPU median is 8.042 s and
  cumulative peak RSS reaches 1043.31 MiB after load. The private raw campaign,
  screenshots, harness/source/runtime/input identities and cross-arm check are
  under `native-final-10pairs-02/`. Broader matrix/material guards and exact
  hosted package qualification remain required before adoption and publication.
- 2026-10-29 **Relay Review: adopt the bounded product candidate and proceed to
  2.13.5 qualification**. The preselected native target and exact current/full
  history/CSV contract pass, without moving work into capture. The independent
  final read-only Sol/High review found no actionable decoder/cache, containment
  or native-observer/validator findings; effective settings remain unconfirmed.
  The broader existing dashboard workload plus usage-only/quota-only and clock
  cases completed one excluded setup pair and **ten alternating measured pairs**,
  all **16 operations** with exact normalized-main HTML/CSV/cache-hit parity.
  Every established timing/RSS material guard passes, including cached and
  project/CSV operations; no raw sample or slow clock-forward sample was removed.
  Source medians: first Today 12.426/9.304 s; usage+quota append report
  8.806/5.516 s; usage-only 8.524/5.418 s; quota-only 8.460/5.582 s;
  clock-forward 74.6/74.4 ms. Initial 30d and selected-project reports are nearly
  unchanged, not additional headline claims. Append writer admission is
  3.22/3.11 ms and held time 48.33/47.14 ms. This matrix is a direct-append
  regression proxy, not the ordinary-capture/native primary result.
  Private evidence: `matrix-final-10pairs/evidence.json` and `review.json`.
  After the campaign, supplementary actual issued next-period/inspection/capture
  page requests completed on both frozen arms. Candidate first visits took
  0.143/0.948/0.960 s; repeated capture pages took 0.069–0.072 s. These are
  source/API times, not native compositor timings or another ten-pair claim.
  Post-history candidate allowance payload retains the identical 57,024,043-byte
  full report and 9,448,677-byte overview, plus its separate 227,320-byte deferred
  projection. Rendered payload costs 269,379 extra bytes before those later page
  visits. Physical SQLite files remain 2,150,260,736 bytes on both arms; lower
  retained payload is not a claim of a smaller physical database. Followup proof
  is in `history-followup/evidence.json`. Frozen source/extension/manifest bytes
  still match the measured candidate. The original sealed control is rechecked
  before qualification. Hosted/native-Windows/WebKit limitations above remain;
  adoption is a product decision, not completed qualification or publication.
  The manager independently recomputed all 11 matrix pairs/16 operations and
  their material guards, and rehashed all 266 Python/36 compiled extension files:
  no parity failure, regression or product drift. Its Relay Review also adopts
  the bounded candidate for the already-authorized qualification/release path.
  Final preservation confirms the original sealed SHA unchanged. The copied
  matrix source has a zero-byte WAL; MAIN-only and normal WAL-view event/quota
  counts match, so no pending frames were omitted by cloning.

## Published Closeout

Released **2.13.5** at tag `v2.13.5`, source
`497c5a846a60f8153eecb24c90f18c04e9ae7685`. Both official downloads match the
qualified packages and Marketplace catalog hashes. Public verification completed
at **2026-10-29 16:30:45 UTC / 12:30:45 EDT**. The generated
[published receipt](../release/2026-10-29-2.13.5-published.md) is retained unaltered;
it binds source, contract, complete manifest, original producers and publication
intents. Release evidence remains in `output/releases/2.13.5-process/`.

- [Qualification](https://github.com/Wenjun-Mao/codex_usage/actions/runs/40904854781),
  selected attempt **2**, passed. Core/accounting, metadata, macOS package and
  all five visual gates retain their checked original attempt-1 producers;
  Windows uses its successful attempt-2 producer. Hosted freeze and native proof
  originate in attempt 2. All **3,091 Python cases pass with zero skips**, retaining
  every original 3,055 identity. Both package platforms pass **95 extension
  cases**, retaining every original 91. The pinned **VS Code 1.141.0** exact-package
  native journey retains 21 original inputs/five theme/editor updates, plus two
  unclicked theme changes and the actual issued history load with distinct
  origin/response scopes and unchanged current figures.
- The first Windows package attempt passed synthetic parallel/oracle/cleanup
  checks, then its existing WAL smoke timed out waiting for reclamation after
  the held reader was released. Last telemetry was caught-up PASSIVE, busy 0,
  288/288 frames and `reclaim_deferred`; the runtime had no error. The unchanged
  test polls tracked status reads every 20 ms, while the sampled PASSIVE took
  61.7 ms, making polling interference plausible. **Root cause remains unproven**.
  One failed-job-only retry on the same source passed, including WAL zero-size,
  restart, retained rows/source, integrity and synthetic-probe checks. No source,
  30-second timeout, WAL-zero assertion or timing guard was changed. The failed
  log, retry intent and original-producer receipts remain; retry success is not
  proof of a diagnosed cause. No second qualification run was dispatched.
- [Credential-free dry-run](https://github.com/Wenjun-Mao/codex_usage/actions/runs/40909717189),
  attempt 1, independently matched local/hosted qualification and skipped its
  publisher. [Promotion](https://github.com/Wenjun-Mao/codex_usage/actions/runs/40910009130),
  attempt 1, published only the exact qualified bytes. Each before-upload intent
  was retained. Marketplace validation/propagation was awaited without another
  upload; official archives and catalog hashes then matched both targets.

| Target | Official/qualified SHA-256 | Bytes |
| --- | --- | ---: |
| macOS Apple Silicon | `364a7131e741790b4452ed52a3d5ab1c84abd05121881c29afa99adf6d368e2c` | 13,780,192 |
| Windows x64 | `f8146d3309b16d67554782fdd140250a792ddc36219b17572d6e51e1fa0271c5` | 12,960,293 |

The adopted benefit remains the representative Mac ordinary-capture workflow:
**15.403 to 11.760 s** median, saving **3.643 s / 23.65%**, with unchanged capture
time and exact current/history/CSV behavior. The accepted first-history wait is
8.606 s median; combined main-plus-history is 20.333 s, not a faster-combined
claim. All sixteen broader matrix operations pass material timing/RSS guards.
Offline raw-source availability/coverage conditions above bound generalization.
The initial 30d/project operations are nearly unchanged. No broader performance
slice, retained-data cap, live extension install or live ledger mutation was
part of this delivery.

**Native Windows UI remains unqualified.** Hosted WebKit timing remains
`hosted-webkit-observed` under the existing policy; this release does not claim
strict hosted WebKit input-latency acceptance. The historical original-account
access uncertainty from early local smoke/unit runs remains recorded above.
Subsequent contained probes and preservation checks passed; the original sealed
control's hash is unchanged. Known owned benchmark helpers finished. Retain the
checkout, parked work and Relay reporting route; no follow-on candidate is opened.
