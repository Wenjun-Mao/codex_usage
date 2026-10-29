# Theme-Only Presentation

Updated: 2026-10-29, America/Toronto.
Status: 2.13.4 publicly verified and released; closeout complete. The one-second engineering target was missed and explicitly accepted as a bounded material improvement.

## Outcome

Finish one small, independently shippable improvement: switching Day/Night/Auto
on an already loaded Usage dashboard must not rebuild its accounting just to
change presentation. Target a **fully displayed theme update within one second
median** on the representative warmed-data, first-unseen-theme case. This means
removing most of the observed multi-second wait, not saving only one second.
Correct data, current navigation state and freshness still win over reuse.

The owner selected the theme-only candidate for its effort/certainty ratio and
asked for Relay Plan first, then explicitly approved implementation through
release on 2026-10-29. The [roadmap](report-performance-slices.md) preserves shipped S0/S1
and the now-parked allowance proposal. No allowance/indexing/ingestion rewrite,
new model/runtime upgrade, history deletion, source TTL or 512 MiB cap. Do not
claim this fixes slow first Today, capture or first data-range loads.

## Verified Design Basis

- Retained checkout: `/Users/wjmao/projects/codex_usage-terra-release`, main at
  `7e5d2bd7a9f6f77ea49ab7e841318a963d61dd5c`. Product inputs match the fixed
  `v2.13.3` source `df74863a7b50d17a1cf94976629c3f7c6c1df4da`; current dirty
  changes are planning documentation and must be preserved.
- 2.13.3's recorded direct-collector 30d Day-theme operation took 5.479s;
  cached 30d took 0.083s. These establish an opportunity, not a measured native
  theme-selection latency or an automatic before/after result for this slice.
- `extension.ts` listens for configuration changes and calls
  `refreshVisibleDashboard`. It passes the selected display theme through
  `reportQuery(controls.theme)` to the collector. The theme is part of backend
  report/history identities, so a newly selected theme can miss expensive caches.
- `reportHtml.decorateUsageReport` already applies `state.theme` to the returned
  HTML root. Python `reporting.py` normalizes theme and writes that root attribute;
  `report_theme.py` supplies CSS for all modes, including editor Auto styling.
  No theme-specific numeric calculations were found in that rendering boundary.
- `DashboardNavigation` already excludes theme from its frontend query identity,
  but backend receipt contexts include the requested theme. Changing transport
  theme can therefore expire previously issued actions. Never repair this by
  weakening scope validation or blindly rewriting issued command payloads.

Preferred minimal design: use one stable **collector transport theme**, initially
`auto`, for every companion Usage report request, including the initial load and
navigation/recovery requests. Keep the user's persisted display theme unchanged
and apply it through the existing HTML decorator. Continue normal report/status
requests and existing cache/freshness rules; this is not another client data cache.
Other direct API/CLI clients retain their requested theme behavior.

If the first probe finds a real backend theme-dependent asset or command contract,
correct the narrow design before implementation. A source-query/cache rewrite,
new client freshness layer or relaxed webview security is a direction-review
trigger, not a prerequisite. Storage should still display its correct theme;
storage-inventory caching or eliminating its existing scans is not this slice.

## Implementation Path

1. Recheck the retained checkout/tag/runtime and inspect the complete theme
   configuration-to-report path. Confirm that initial render, config events,
   chart/history requests and typed recovery all use the canonical transport
   theme. Establish the real extension-path baseline with a loaded 30d report,
   not just the existing Python `theme=day` timer.
2. Add a failing extension-host/configuration test and narrow backend work
   counters. Cover initial display Night followed by first Day/Auto requests;
   prewarming only the later canonical request would hide a broken first switch.
   Exercise actual production activation/configuration handlers, not only a new
   helper tested in isolation.
3. Implement the small transport/presentation separation in existing owners.
   Keep display settings, filter identity, data status, command restrictions and
   latest-request-wins behavior. Preserve chart/history selections when the
   underlying scope is still valid. Evaluate loading-placeholder behavior, but
   do not add product scripts solely to avoid a document refresh or retain scroll.
4. Test unit/integration behavior, then the existing disposable real VS Code
   host. Reuse `vscode_breakdown_acceptance.js` / native acceptance support or a
   focused adapter; no new general harness/controller. Check rendered colors and
   controls, then invoke issued speed, breakdown and allowance actions after the
   theme change. Inspect valid expiry/recovery separately from theme-only reuse.
5. Freeze a credible candidate and gather the performance/correctness proof below.
   Independently review the scoped diff and do a proportionate Relay Review.
   When execution/publication is authorized, use the existing release pipeline
   through both official package checks and a committed/pushed receipt. Choose
   the next unused maintenance version at freeze, not during planning.

`extension.ts` is 491 lines: assess cohesion before substantial edits. Prefer a
focused presentation/query-policy owner if new state/logic warrants one; a tiny
existing call-site correction alone does not justify refactoring the whole file.
`reportHtml.ts` (199) and `dashboardNavigation.ts` (108) are existing small owners.
Follow the user's 400/500-line rule; explain any substantial oversized result.
Keep shared-file writes serial, with read-only support or genuinely disjoint
tasks where useful. Model/task selection already has standing approval.

## Decisive Proof

- Prime each arm through the same real user sequence: open Usage with display
  Night, let that report settle, then select a display theme not yet rendered for
  that revision/range. Candidate initial transport should naturally prime its
  canonical entry; do not manually prewarm extra candidate requests. Keep both
  data inputs, clock/freshness conditions and permitted warming equivalent.
- Measure from committed configuration change to the **complete themed report
  being visible**, with expected content, controls and requested effective colors.
  A themed loading page, quick RPC or HTML assignment alone is not completion.
  Use the real extension handler and native webview rendering in a disposable
  profile. Retain collector and decoration timings separately for attribution.
- Target <=1.0s median for that complete update, with one excluded setup pair
  and ten independent alternating baseline/candidate pairs. Reset each trial to
  the single-primed-view scenario: repeated flips in one already-warm baseline
  do not measure the first-unseen-theme problem. Preserve every sample/failure,
  source/fixture/runtime identity and actual cache state. Record the absolute
  before/after saving; do not call a tiny-fixture subsecond pass a multi-second win.
- Use a representative large input that reproduces the baseline's material
  theme-miss cost. Prefer already retained, authorized normal-ledger control or
  an existing/scaled public synthetic fixture; do not build a new indexer dataset.
  Private evidence remains local/ignored. Public/native CI artifacts must use
  public synthetic content. Source-backed or HTTP-only timing is supporting
  evidence, not a substitute for the promised visible-update measurement.
- On valid same-evidence warm theme updates, counters must show no new usage
  materialization, repricing, quota/history preparation or capture caused by
  presentation. Lightweight status/report/receipt operations are allowed. A real
  revision, midnight, deadline, timezone/filter or evidence change must still
  refresh/recompute when existing rules require it; do not force stale hits.
- Compare every numeric/accounting field and data membership with 2.13.3 for
  the same data state. Preserve range/projects, all CSV rows, chart/window/detail
  state and valid action semantics. Allow only declared theme/chrome/time metadata
  differences. Canonical theme can legitimately change opaque backend scopes;
  validate that commands are actually issued/accepted in their own context and
  carry the same intended states. Do not normalize away missing or invalid actions.
- Cover Day/Night/Auto, editor light/dark Auto behavior, no-op/cancelled selection,
  explicit settings persistence/reopen, custom range and project filters,
  non-default speed/breakdown/history state, rapid changes and out-of-order replies,
  panel disposal/view switch, capture/revision change during refresh, scope expiry,
  transport failure and malformed/unissued commands. Storage/loading/error colors
  remain correct. Preserve CSP, `enableScripts:false`, command allowlist and
  local resource restrictions; test interactions, not screenshots alone.
- Use `reportHtml`, `dashboardNavigation`, speed/breakdown/allowance navigation
  and refresh-policy tests, adding the actual configuration-route integration
  coverage. Build/test all extension cases, run full Python/Ruff and the existing
  selected visual preflight. Preserve all 3,031 shipped Python identities and 87
  extension identities plus new cases; no skipped hosted Core cases.
- Run existing report/CSV/capture regression checks proportionate to unchanged
  backend ownership. The direct Python `theme=day` case may remain slow because
  direct-client semantics are intentionally unchanged; label it honestly, not as
  the primary fixed UI path. No first-load/range/capture/resource regression may
  be hidden by priming more data or retaining large client graphs. Use existing
  material guards (BOTH >10% AND >100ms time; BOTH >10% AND >32MiB RSS).
- Full qualification still includes both packages, five visual suites and the
  exact-package native Mac proof, extended to the theme journey. Update the
  existing evidence validator/inventory as needed so missing or incomplete theme
  evidence fails qualification; an unused diagnostic artifact is insufficient.
  Preserve the existing native input cases. This small source-bound qualification
  contract update is within the slice, not a new framework or approval stage.
  Existing native
  Windows editor-UI and hosted-WebKit timing gaps stay explicit. Promote the
  exact artifacts, verify both official download/catalog hashes, and commit/push
  the generated receipt and plan closeout without moving the tag.

Completion requires the large visible theme-switch improvement plus preserved
behavior/security and authorized release closeout. A warm mock, only a new CSS
attribute, helper timings or a published package without the UI result is not
completion. Preserve useful work and review direction if the narrow mechanism
does not establish this outcome; do not drift into the parked allowance work.

## Authority And Forecast

The owner explicitly approved this plan E2E under Relay Direct on 2026-10-29,
including scoped implementation, local tests and disposable editor profiles,
optional offline copies of the already sealed private control, scoped
commits/pushes, required qualification/dry-run/promotion/publication and ordinary
recovery. Standing Relay task creation and explicit model/reasoning selection
remain approved. Use best judgment without routine permission pauses and record
only material decisions here for later owner review. This is a fresh scoped
release grant, not reuse of the closed 2.13.3 grant.

No live install/restart, live ledger/settings changes, original sessions/account
RPC, private artifact upload or later performance slice is included. Do not claim
representative proof from an inadequate substitute. Actual native confirmations
remain; routine review fixes, validation and recovery within the granted result
do not require repeated approvals.

Reuse the current release coordinator and retained publication intents. An
observer timeout or uncertain upload is not permission to dispatch/upload again;
reconcile the real run/attempt and resume observation. Preserve owner changes,
the fixed 2.13.3 tag, old work/evidence and wanted worker results before retirement.

Forecast: **2-4 hours local engineering, proof, review fixes and closeout**, plus
**0.5-1.5 hours hosted/build/publication waiting**, assuming canonical transport
fits the existing rendering/receipt contracts and fixtures. This is not a cap.
Review direction after the initial route/security probe or earlier if the fix
requires a new cache/freshness architecture. Revise the forecast with evidence;
no arbitrary retry limit, compulsory worktree or new automation is introduced.

## Planning Reviews

Outcome/completeness review requested Sol/Xhigh, fresh-context native worker: no material findings. It found that the
representative first-unseen-theme visible-update measurement, exact behavior/
security checks and enforced native evidence inventory rule out the credible
false successes considered. Initial and subsequent canonical transport, fixture/
counter placement and any extraction remain implementer decisions. The future
grouped execution grant remains a real user decision; no new task/model approval
is needed. It inspected source/docs/tests/harness only, with no execution or
private-data/network access. Effective requested settings remain host-unverified.

Avoidable-restrictions review requested Sol/Medium, separate fresh-context native
worker: no findings. It confirmed that the
future grouped grant is a genuine authority boundary, ordinary fixes/recovery
do not need repeated approval, extraction is discretionary, forecasts are not
caps, and outcome/security proof is proportionate. It changed no success/proof
assumptions, so another outcome-review pass was unnecessary. Source/document
inspection only; no edits, tests, builds, benchmarks, private-data/network access,
CI or delegation. Effective requested settings remain host-unverified.

Both reports are collected, reviewers closed and reporting routes removed.
The implementation handoff is this reviewed plan and the subsequent grouped
execution grant above, subject to any actual native confirmations. No production
work or release side effect occurred during planning.

## Execution Decisions

- 2026-10-29: use the retained main checkout above, serial source writes and the
  existing release coordinator. Keep parked allowance/indexing work and old
  checkouts untouched; no new worktree or release framework is needed.

- 2026-10-29: canonical `auto` transport applies from the initial Usage request
  through navigation and typed recovery. The existing decorator continues to
  apply the persisted display theme. Configuration theme changes keep the old
  report visible until the final replacement; explicit error presentation is
  independent of showing an intermediate loading document. No client data cache
  or product script was added. `extension.ts` remains 495 lines; these small
  changes belong to its existing refresh owner and do not warrant extraction.
- 2026-10-29: freeze maintenance candidate 2.13.4 after verifying that neither
  its remote tag nor official Marketplace version was occupied. Python changes
  are package-version metadata only; the runtime and accounting implementation
  remain those of the fixed 2.13.3 source.
- 2026-10-29: source-native replay uses pinned VS Code 1.141.0, preserves the
  original 21 rendered inputs, seeds nondefault speed/window and allowance
  inspection state, changes Day/Night/Auto including both editor palettes, and
  exercises changed issued actions afterward. The enforced native validator
  requires this journey; exact-package replay remains a separate release gate.
- 2026-10-29: independent scoped Sol/Xhigh review found no product correctness
  blocker. Its measurement/action findings were repaired: frozen identities,
  complete-content/color checks, screening versus ten-pair outcome separation,
  retained failed-arm counters, non-no-op actions, rendered allowance scope
  binding, exact Auto palettes, and nondefault state preservation. Requested
  reviewer settings and worker Sol/Medium remain host-unverified. The manager's
  independent pre-freeze review also found no product blocker.
- 2026-10-29: representative measurements remain local and ignored. Preliminary
  screens showed the material collector saving and zero accounting work on the
  candidate, but visible timings slightly above the one-second target. Retain
  those misses. The decisive run uses one excluded setup pair followed by ten
  independent alternating pairs, a committed-configuration-event start and a
  native compositor stop after real report/control/color verification. Do not
  subtract observation overhead or call screening evidence completion.


## Execution Outcome Review

The decisive run is retained locally at
`output/performance/theme-final-10pairs/evidence.json`. One setup pair was
excluded in advance; all ten subsequent alternating pairs and the 2.656-second
candidate outlier remain. Baseline median was **6.698710 s**, candidate
**1.229386 s**, an absolute **5.469324 s** saving (81.65%). The one-second
engineering target was **missed**; the raw result correctly records
`passed: false`, not a subsecond success. No observation time was subtracted.

The warmed first-unseen-theme requests use the render cache with no new
materialization, repricing, quota/history/account preparation or capture.
Collector median fell from 5.589651 s to 0.086924 s. Configuration-event to HTML
assignment medians were 5.8265 s and 0.2795 s. Remaining time includes transport,
decoration, native rendering and observation; those phases are not wholly
causally isolated. Full HTML and structured accounting/issued-state inventories
matched across the measured arms after only the declared theme/scope changes.
Initial visible-load medians were 31.279 s and 31.377 s; collector high-water
RSS was slightly lower. Neither material time nor memory regression guard fired.
This does not claim faster first loads, capture, new ranges or Storage scans.

Relay Review decision: retain the narrow implementation and continue the
already-authorized maintenance release, with the engineering-target miss
explicit. It removes the repeated accounting and most of the multi-second wait,
which is the owner's intended small improvement. Broadening the architecture
solely to remove the remaining ~0.23 s above the target would conflict with the
bounded slice. Qualification/publication cannot turn the missed target into a
pass; public closeout must preserve it. The manager independently inspected and recomputed the complete 22-arm result
and explicitly accepted this bounded material improvement for release under the
owner's best-judgment mandate, with the one-second engineering target missed and
disclosed. Exact publication evidence remains to be verified.

The exact measured performance-harness sources are preserved with their hashes
under the ignored run directory. The reusable source accepts the owner's sealed
control hash/size as explicit arguments, keeping private input identities out of
published code. Added receipt fields preserve the same timing boundary; there
was no later rerun, sample replacement or product change.

The strengthened source-native replay passed with exact Auto palettes and native
allowance command scopes binding the displayed inspection to the accepted
response. Complete 30-day CSV parity also passed: 2,073 rows, identical bytes and
filename on the fixed 2.13.3 source and candidate. Raw private CSV/timing evidence
remains ignored under `output/performance/`; public native evidence uses only
the synthetic fixture.

Standalone decoration attribution on the same 16,734,622-byte representative
HTML used the pinned host's Electron Node runtime and the frozen production
`decorateUsageReport` function: 0.00477 s median after one excluded setup call.
This is helper-phase attribution, not native visible latency, and is never
subtracted from the 1.229386 s primary result. Its private input and samples are
retained locally under `output/performance/theme-decoration/`.


## Qualification Recovery

The first 2.13.4 qualification at source `2cdbac3` failed its Windows extension
unit-test step before collector packaging. The new activation test double used
a POSIX-only parent-module path suffix, which fails for Windows module paths.
The job's reporter did not print individual test failures and its failed XML was
not uploaded; retain that diagnostic limit rather than inventing a test receipt.
The matcher was made separator-independent, and the actual activation/config
case now exercises a Windows-shaped parent filename locally. This is a test-only
repair; production output still matches the measured frozen candidate.

The nonqualifying old-source run was canceled to avoid further wasted jobs. Its
run, request intent and diagnostic evidence remain retained. The corrected
source uses a fresh coordinator directory and normal qualification, not a
failed-job rerun pretending to contain changed source. No tag, dry-run,
promotion or publication happened for the rejected source.


The repaired source `42fbbf7` completed every hosted job, including exact-package
native replay, but independent inspection rejected its new native scope check.
That check incorrectly equated an issued allowance action's origin scope with
the response scope after changing history state. Existing backend scope identity
is `digest([context, state])`, so a changed state legitimately receives a new
scope. The actual native journey visibly changed the selected period and its
inspection; the failed assumption belonged to the new validator, not product
behavior. Preserve the all-green-but-unqualified run and inspection failure.

The validator now requires the request's scope to match the issued origin and
the observed native DOM scope to match the new accepted response, while keeping
changed-state/content checks. A negative origin-scope case complements the DOM
scope corruption case. This contract repair needs fresh source-bound
qualification; it does not waive the rejected proof or alter any generated
receipt. Production output and the accepted timing result remain unchanged.


Before freezing the scope repair, a local diagnostic replay consumed the retained
real hosted manifest and exact Mac VSIX from the successful-but-rejected run.
The corrected current harness produced fresh observations, including separately
recorded accepted-response and observed-DOM scopes. The full corrected native
validator passed against those actual package/hosted inputs; corrupting the
request origin, rendered scope or inspection hash was rejected. The original
native JSON stayed unchanged and independently confirmed the legitimate
origin-to-new-response transition. This replay is diagnostic only, not a
qualification receipt for the new source. Its retained result is
`output/releases/2.13.4-scope-diagnostic/validation.json`.

Independent scoped read-only review found no new flaw in the corrected scope
contract or mandatory helper wiring. Fresh full local Python validation passed
3,055 cases with zero skips. The fresh source-bound hosted pipeline remains
required before publication.


## Published Closeout

Version **2.13.4** was publicly verified at **2026-10-29 02:39:45 EDT**.
The immutable [generated receipt](../release/2026-10-29-2.13.4-published.md)
binds source `2f20dd4b68e37c4d33ff9fc35cd6bc3f4e93db3c`, both official download and
catalog hashes, qualification `40826720874` attempt **2**, dry-run `40829313453`
attempt **1**, and promotion `40829553567` attempt **1**. Promotion reused the
qualified packages and did not rebuild them. The generated receipt bytes were
not manually edited.

Final local and hosted checks preserved every shipped case: **3,055 Python
cases, zero skips**, **91 extension cases per platform, zero skips**, all five
visual suites, both collector/archive/handoff package gates, and exact-package
native Mac replay. Native proof preserves all 21 original rendered inputs plus
five theme/editor-palette updates, nondefault speed/window/history state, and
changed issued breakdown/speed/allowance actions. Published Mac JavaScript
matches the measured output byte for byte; Windows matches after checkout
line-ending normalization. Full 30-day CSV parity retained all 2,073 rows.
The sealed private control's hash and read-only mode remain unchanged.

The representative warmed first-unseen Day update remains **6.698710 s →
1.229386 s median**, saving **5.469324 s**. The **1.0 s target was missed** and
accepted explicitly; neither publication nor successful qualification changes
that result. All candidate warm accounting/preparation/capture counters remain
zero. Initial load/range/capture improvements, Storage inventory optimization,
native Windows UI, and strict hosted-WebKit latency remain outside the proven
outcome. No live install/restart, live settings/ledger change, original account
RPC or private artifact upload occurred.

Recovery records are retained rather than replaced:

- `40821557736` failed Windows tests and was canceled. The new test double's
  POSIX-only matcher was an avoidable portability mistake.
- `40822670490` passed every hosted job but was rejected by independent native
  inspection. Equating action origin and changed-state response scopes was an
  avoidable contract assumption. Those two nonqualifying rounds consumed about
  **28 minutes of hosted observation**, plus repeated local checks. Comparing
  the new assertion with existing backend semantics and actual evidence earlier
  would have prevented the second round.
- `40826720874` attempt 1 failed the unchanged Firefox speed-tooltip guard at
  **277.4566 ms**, despite the expected hidden state. The original local suite
  then passed all 162 cases. After all healthy jobs settled, one explicitly
  checked failed-job retry passed without changing source, the 250 ms limit or
  the timing policy. A transient observation/scheduling delay is an inference;
  its cause was not isolated or claimed fixed.

Independent inspection verified all eight healthy original producer IDs from
attempt 1, with speed, hosted freezing and native replay from attempt 2. The
manual selected-attempt recovery preserved the coordinator's attempt-1 observer
restriction; no coordinator rewrite or duplicate qualification/publication
mutation was introduced. Retained intent, failure, diagnostic and public evidence
is under ignored `output/releases/2.13.4-*` and `output/performance/theme-*`.

The approved bounded implementation and release are complete. Subsequent
allowance/indexing work remains parked and needs its own authorization. The
manager owns worker retirement and the reporting route remains intact.
