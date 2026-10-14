# Verification And Release Efficiency

Date: 2026-10-13. Status: local and journal gates pass. Earlier normal/dry-run
evidence is retained; current source qualification is held by hosted WebKit
input/observation latency. Production promotion is source-disabled.
Remaining-work revision: owner approved stages A-F through the active goal,
starting from `1032b715`; A is in progress, dependent gates remain unmet.
Scope agreed: faster failure-local gates, exact qualified-artifact promotion,
and fewer browser round trips without reducing coverage.
Owner's latest revision approves bounded temporal tracing, adds within-project
model comparison, and requires owner UI acceptance before publication. This is
a reviewed plan; the owner has now approved the autonomy bundle and restarted
the Goal without a wall-time constraint. Publication still awaits UI acceptance.

Authority: [measured profile](../research/2026-10-13-verification-and-release-profile.md),
[ADR 0061](../adr/0061-qualified-artifact-promotion.md), and the existing
[release checklist and receipts](../release.md).
The published 2.12.2 release is complete and is not reopened by this plan.

## Outcome And Boundaries

Make verification fail earlier, make a failed visual suite independently
retryable, and publish the same packages that passed qualification instead of
building and qualifying a second set of packages at the same source commit.
Reduce browser transport overhead while retaining observable behavior checks.

Preserve complete Python and extension tests, Ruff, frozen monetary parity,
bounded-work guards, screenshot acceptance, all browser scenarios/themes/widths/
engines, both supported platform packages, collector smoke/archive/handoff
checks, hash-bound native macOS verification, and public Marketplace hash checks.
Existing native Windows acceptance gaps remain explicit, not newly claimed proof.
No product accounting, pricing or timeout change is planned. The additional
Project Economics presentation change below reuses existing model metrics.

Exclude Python fixture/shutdown tuning, Python test sharding, duplicate
TypeScript build cleanup, runner-platform migration, new distribution targets,
dashboard latency work, automatic retries, and Marketplace propagation shortcuts.
Do not modify live ledgers, installed extensions, credentials/Keychain, user
VS Code windows, services, secrets/settings, or unrelated untracked `apps/`.

## Diagnosis And Evidence

| Problem | Evidence | Owning layer |
| --- | --- | --- |
| Metadata mistakes fail late | Missing release-date entry failed a 2m 56s preflight | Qualification dependency graph |
| One visual failure repeats unrelated work | 38s hover suite is inside a 12m 05s serial package/visual step | Suite jobs and failure evidence |
| Same source is built and qualified twice | 17m 49s tag workflow; preflight/tag VSIX and collector hashes differ | Artifact authority and promotion |
| Many small browser reads dominate | 11,628 evaluate/count calls cost 54.8s in a 141.3s local breakdown run | Verification harness transport |

These are local and historical hosted observations, not promised future timings.
The earlier 250ms tooltip-hide failure has no confirmed root cause. Preserve
the deadline; instrument failures before deciding whether code or harness
changes are justified. An unchanged retry passing is not a diagnosis.

## Selected Publishing Flow

Owner selected explicit promotion on 2026-10-13. Creating a release tag alone
does not publish or rebuild anything. Separate nonpublishing qualification from
a dedicated promotion workflow dispatched on a matching release tag with the
selected qualification run and attempt. Selection never bypasses proof validation.

The release sequence becomes: qualify the exact candidate, collect trusted native
proof for its packages, create the matching tag, explicitly dispatch promotion,
then verify both official public downloads. The added release action provides a
clear selection and audit trail. Automatic tag discovery was considered but
rejected: it preserves today's trigger at the cost of ambiguity-resolution logic.
The owner approved implementation after reviewing this plan. Publication is not
authorized. On 2026-10-13 the owner explicitly approved scoped commit/push and
nonpublishing hosted pilots, plus the durable Git journal and its job-scoped
Contents-write access. Release tags, Marketplace uploads and secret/settings
changes remain excluded.
The subsequent explicit goal authorizes implementation of stages 1-6, including
source enablement and publication after their gates. Actual selected version,
final SHA and normal run/attempt must be recorded before the authorized release;
no permission to bypass gates or change credentials/settings is inferred.
The latest instruction supersedes unattended publication authority: prepare and
qualify the combined candidate, then wait for owner acceptance of its new UI.
Do not create its release tag or dispatch publication before that acceptance.

## Qualification Graph

1. A fast, nonpublishing metadata gate checks version/lock/changelog consistency,
   the independent release-history registry, supported targets, workflow
   contracts, and requested ref rules before expensive jobs start.
2. After that gate, full core validation, macOS packaging, Windows packaging,
   and visual qualification may run independently. Packaging remains unqualified
   until every required gate passes; there is no early publication path.
3. Separate visual units: screenshot plus allowance, observed speed, breakdown,
   dense overlay, and hover/focus. Start with a suite matrix capped at two
   concurrent visual jobs; run the three engines serially within each job.
   Keep current macOS visual OS/font authority, including screenshot references.
   Hover has its own runner/process, not concurrent heavy work in that process.
4. An explicit aggregation gate checks required suite IDs and complete case
   inventories, not merely workflow success or a total case count. Publish a
   qualification receipt only after all required hosted gates pass.
5. Native macOS replay consumes the qualified VSIX, not a fresh local build.
   Its separately trusted, hash-bound evidence is required before promotion.
   Candidate source, packaged assets and collector identities travel with it.

Suite isolation makes GitHub's failed-job rerun useful without rerunning healthy
platform builds. Reuse is allowed only under a proven run-attempt provenance
model; unsupported or ambiguous reuse fails closed rather than borrowing proof.

## Ordered Deliverables

### D0: Freeze Contracts And Probe Feasibility

- Capture the current suite/case/assertion inventory, source fingerprints,
  report HTML hashes, warm-work counters, tool/browser versions and timings.
  Preserve the 720 breakdown tuples, 162 speed views, 90 overlay views, 72 hover
  views, and allowance/meter/screenshot subcase inventories. New tests may add
  cases; no old case can disappear, be duplicated or silently move to skipped.
- Probe immutable artifact download, run-attempt/job/artifact association,
  rerun-failed-job behavior, and retention using nonpublishing runs. Establish
  whether GitHub's records bind reused artifacts to their originating attempt.
  If not, use a complete fresh qualification; do not invent an association.
- Probe a trusted native-proof path: hosted isolated VS Code replay if feasible,
  otherwise an explicitly authorized local replay with a receipt registered
  through a trusted validation channel. A caller-supplied JSON file is not proof.
- Freeze the required gate schema and explicit promotion input validation.
  Record the selected transport/trust model in ADR 0061 before promotion work.

Acceptance: an inspectable inventory and validated provenance design, with any
unsupported platform/API assumption resolved before its dependent deliverable.

### D1: Fail Fast, Isolate Suites, Preserve Failure Evidence

- Move focused metadata/history/workflow checks ahead of the full Python suite;
  retain them in the full suite as independent regression guards. Do not derive
  the historical registry from the same changelog it validates.
- Refactor the workflow dependency graph above. Give each suite a unique output
  and artifact identity. Ensure partial matrix failure cannot produce a qualified
  receipt and rerunning one suite does not rebuild packages.
- Persist completed tuples and current case/stage incrementally. On failure,
  attempt bounded synthetic screenshot/DOM diagnostics: engine, scenario, theme,
  width, current focus, hover target, computed visibility and hit-test state.
  Preserve the original exception and failing exit even if diagnostics fail.
- Always upload available diagnostics from failed suites, with an explicit
  incomplete status. Do not let partial evidence masquerade as acceptance.
  Keep success-evidence missing-file checks strict; do not require nonexistent
  screenshots when setup itself failed. Bound artifact size and retention.
- Exercise controlled fixture failures to prove early rejection, independent
  retries, readable diagnostics and aggregation rejection of missing gates.

Acceptance: full coverage is still mandatory; a failed hover job can be rerun
alone; every ordinary assertion failure identifies its exact case and preserves
completed-case evidence. Cancellation/runner-loss remains failed or incomplete.

### D2: Batch Browser Reads Without Weakening Assertions

- Start with `check_usage_breakdown_ui.py`, the measured largest cost. Collect
  related DOM geometry/style/text/count values in cohesive browser snapshots,
  then assert each original invariant in Python with case/node context.
  Use test-side evaluation only; product JavaScript stays disabled and CSP stays
  unchanged. Do not replace real interaction or pixel checks with DOM guesses.
- Preserve real Enter/Tab/hover and hit testing, axis-glyph containment, tick
  alignment/collision checks, controls, issued links, exact details and all
  per-mark assertions, including dense history and tiny/extreme/DST cases.
- Trial loading once per scenario/theme and resizing for its three widths.
  Before each case explicitly restore/check focus, pointer, disclosure, scroll
  and viewport state. Compare against a fresh-navigation reference. If reset
  equivalence cannot be demonstrated for a suite, keep its original navigation.
- Reuse only genuinely common verification helpers, grouped by responsibility;
  keep modules under roughly 400 lines. Batch other suites only where measured
  overhead and unchanged assertion coverage justify it.
- Compare full tuple and assertion inventories, outcomes, HTML hashes and
  forbidden-history-work counters. Counts alone cannot establish equivalence.
  Use alternating uninstrumented baseline/candidate wall runs plus instrumented
  call-count runs; don't compare misleading async cProfile cumulative totals.

Acceptance: every original case/assertion passes across all three engines and
widths/themes; deliberate invariant violations still fail. Report measured
call-count and wall-time changes separately from CI queue effects.

### D3: Promote The Exact Qualified Packages

- Implement the versioned manifest/receipt and validation contract in ADR 0061.
  Packaging records VSIX and embedded collector/extension asset hashes, sizes,
  targets and source. Aggregation binds these to immutable artifact IDs/digests,
  trusted workflow/job results, case evidence and originating run attempts.
- Adapt native acceptance to extract/use the qualified VSIX in a disposable
  profile, preserving synthetic RPC and in-memory secret storage. Declare any
  acceptance-harness-only metadata difference; verify shipped assets remain
  identical. Store exact native inputs, VSIX/collector/source hashes and result.
- Implement a nonpublishing validation mode and promotion entrypoint. Validate
  tag/version/main ancestry, repository/event/workflow trust, complete required
  gates, artifact identity/expiry and bytes, and trusted native evidence before
  the publisher receives credentials. Never rebuild on missing/expired proof.
- Update `verify_marketplace_release.cjs` to validate qualification plus promotion
  receipts and compare official downloads/catalog hashes against qualified
  bytes. Preserve bounded propagation polling; distinguish upload from verified
  public availability. Do not republish merely because catalog entries lag.
- Handle partial two-target publication explicitly: an already-published target
  is reusable only after its official hash matches the qualified package.
  A mismatching occupied version stops; an unavailable catalog stays pending.
  No blind `--skip-duplicate` success, tag movement or same-version replacement.
- Negative tests cover wrong repo/ref/SHA/version/target/event/workflow, missing/
  failed/skipped/canceled gates, duplicate/missing cases, incompatible schemas,
  stale attempt/native proof, missing/expired/swapped artifacts and hash mismatch.

Acceptance: publishing path runs no collector/VSIX build or complete test matrix;
it cannot upload bytes without complete matching proof. Source or artifact changes
invalidate qualification. Both public target hashes equal the qualified hashes.

### D4: Qualify And Measure The New Process

The remaining critical path is A -> B -> C -> D -> E, with U integrated before
final qualification and F held for owner UI acceptance. Preserve ADR 0063's strict
input-to-observation budget; neither a late visible result nor a diagnostic-only
passing run qualifies the candidate.

#### D4A: Locate The Hosted WebKit Delay

- Freeze source, fixture hashes, SDK and actual browser-binary revision/digest,
  OS/runner, viewport, scripts-disabled state and the original input history.
  Reproduce the first WebKit view through the affected second usage bucket;
  minimize only after the relevant input/state history is shown equivalent.
- Reuse the existing protocol/host/renderer-clock diagnostic. Compare the original
  style query with a minimal non-DOM control query on the same page. Record
  foreground/visibility/focus and lifecycle state outside the acceptance timer.
  Add one hypothesis-specific control only when prior evidence justifies it.
- Correlate input send/reply, target-query send/reply and expression execution
  by session/command ID. Distinguish driver/host delay, target scheduling, expression
  work and reply delivery. Do not subtract cross-process clocks, adjust acceptance
  times or claim paint timing from these markers.
- Every extra diagnostic read/listener must be declared and remain outside
  qualification authority. Preserve the original failed guard and raw evidence.
  Product scripts/CSP and acceptance inputs remain unchanged.
- Bound each diagnostic job to five minutes and each investigation batch to two
  new dispatches with prespecified hypotheses/controls. Repetition solely to get
  green is excluded. If the batch does not discriminate, report the remaining
  hypotheses and revise the next probe before further dispatch or full qualification.

Acceptance: a root-cause note identifies the failed stage, supporting controls,
and why the proposed correction belongs at that layer. A causal intervention
must change the predicted delayed stage; eventual visible DOM is insufficient.

#### D4B: Correct The Owning Layer

- Implement the evidence-backed correction with existing public APIs/patterns;
  do not silently patch the SDK, migrate runners or add engine-specific tolerance.
  Preserve readiness/hit checks, genuine hidden baselines, real Tab/hover/hide,
  scripts-disabled behavior and strict rejection at or beyond 250ms.
- Regression tests cover the diagnosed failure, late input/style replies,
  cancellation/cleanup, trial-hover priming and absence of corrective target focus.
  Add the root-specific guard to existing cohesive modules and ADR 0062/0063.
- Verify prespecified cold launches and warm passes of the affected input history,
  including at least three of each on the hosted authority, then all 72 local
  hover views. Stop on an unexpected failure; do not retry it into acceptance.
- Use one bounded independent read-only review of the causal correction and
  measurement contract. Collect and close any reviewer before ending the work.

Default: repair the current observation path without changing its requirement.
If evidence instead establishes that the requirement needs a different measurement
contract or toolchain/runner, present that alternative and its lost/new guarantees
for owner review before implementation. That is not an implicit fallback.

#### D4C: Fresh Normal, Retry And Native Qualification

- Run focused regressions, complete core/extension suites, Ruff, frozen monetary
  parity/work and complete visual inventories. Reconcile every original required
  identity with raw results; retain the exact platform-skip policy and real inputs.
- Commit/push only the approved slice and run one fresh normal qualification at
  the exact candidate SHA. Require every core/platform/visual gate, frozen manifest
  and hash-pinned native macOS replay of the actual qualified VSIX.
- Separately run the controlled first-case hover failure at the same SHA. Attempt 1
  must fail exactly the injected case, retain diagnostics and skip dependents;
  rerun failed jobs once with injection disabled. Any unexpected failure stops
  the pilot for diagnosis, not repeated reruns.
- Prove eight healthy producer origins remain attempt 1, the rerun hover origin
  is attempt 2, and aggregation/native evidence is fresh. Compare each probe
  package's IDs/digests/bytes across its own attempts, not against the normal run's
  independently built bytes. Probe runs remain permanently ineligible for release.
- Native replay uses disposable profiles, synthetic data and in-memory secrets;
  no Keychain or user-window changes. Native Windows UI remains an explicit gap;
  Windows package/archive/collector/handoff gates remain mandatory.

Acceptance: normal inspection validates complete source-bound proof; the probe
independently proves failure-local reuse without rebuilding healthy packages.
No old source's receipts qualify a changed execution closure.

#### D4D: Dry-Run And Process Acceptance

- Dispatch dry-run promotion on main selecting C's normal run/attempt. Require
  local/hosted inspection equality, unchanged exact package/collector/asset hashes,
  no build, a skipped publisher job, no PAT exposure and no production-journal write.
- Retain negative tests for malformed/stale/swapped proof, tag/dispatch drift,
  deleted Actions history, partial publication uncertainty and pinned-journal loss.
  Dry-run inspection is not positive proof of the disabled publication-only path.
- Refresh the existing profile/receipt/guide with queue/setup/execution times,
  original versus reused work, complete cases, artifact retention and runner-work
  cost. Retain the three local baseline pairs; label limited hosted sampling.
  The 20% local/30% hosted goals never override correctness or become promises.

Acceptance: A-D pass; readiness is explicitly nonpublishing. Expired artifacts
require renewed qualification, never a promotion-time rebuild or stale-proof reuse.

#### D4E: Production Enablement After Technical Gates

- Existing authority covers source enablement and new-version preparation, not
  bypassing UI review. Select an unused eligible version at least 2.12.3; synchronize
  Python/extension metadata, locks, changelogs and independent release history.
- Review the complete retained journal and publisher trust boundary. Preserve
  pinned roots, job-scoped Contents-write, before-credential proof/intent checks,
  two-target preflight, ambiguous-upload refusal and public hash verification.
- Test both explicit disabled and enabled policy states. Preserve the disabled
  pre-network guard test; add enabled-path regressions with publication effects
  stubbed. No real PAT/upload or environment override belongs in these tests.
- Enable only in the reviewed fingerprinted source. Then repeat C and D for the
  final enabled/versioned SHA: policy/version edits invalidate earlier proof.
  This is one-time activation qualification, not a routine second tag rebuild.
  Keep publication undispatched and create no eligible release tag in this stage.

Acceptance: the final enabled source is freshly qualified/inspected and separately
authorized for enablement. No flag/version/workflow edit occurs after qualification;
any such change starts a new candidate. Enablement is not publication authority.

#### D4F: Publication After Owner UI Acceptance

- Require owner UI acceptance, then record version, final SHA, normal run/attempt,
  both targets and existing publisher-credential authority. Any post-review source
  edit requires renewed matching qualification. Secret/settings changes are excluded.
- Create the matching tag and explicitly promote the exact qualified bytes.
  Revalidate original proof and fresh journal state before per-target intent/PAT;
  no rebuilding, forced ref update, tag movement or duplicate-upload shortcut.
- Verify both official public downloads/catalog hashes against qualified packages
  and retained promotion receipts. Partial/ambiguous uploads or catalog propagation
  remain pending; preserve possible-upload intents and never infer safe re-upload
  from absence. Record a verified release only after both target hashes match.

### U: Within-Project Model Comparison

The backend already supplies `ModelEconomics.metrics`; the renderer currently
shows the requested measures only at project level. This is a presentation gap,
not a reason for a schema migration, backfill, extra valuation or raw-log scan.

- Make each project's primary model table show Model, Average cost / response,
  Responses / turn, Tokens / turn, and Measured turns. Apply it to all models,
  including Sol/Astra/Luna, using the selected project/date scope.
- Preserve total tokens, token/cost shares and average cost / turn in secondary
  inspectable details. Expose model-specific response/turn counts, priceability,
  missing-turn coverage, unavailable values and small samples.
- Reuse existing measured populations: positive ledger responses with non-empty
  turn IDs; cost averages use priced responses. A mixed-model turn contributes
  once per participating model, using only that model's usage. Do not silently
  turn these observational comparisons into model-quality/efficiency claims.
- Use compact token units, one decimal for response ratios and bounded monetary
  precision that distinguishes small model costs from each other and zero, not
  just a shared `<$0.01` label. Keep exact values and denominators inspectable;
  use existing domain formatters where suitable. Cost is API-equivalent USD;
  tokens include input (including cached input) and output, not output alone.
- Scope renderer changes to `report_tables.py` or a cohesive extracted economics
  renderer if needed. Preserve precomputed economics, one valuation per record,
  monetary parity and bounded warm-report work; no new data query is required.
- Test mixed-model turns, missing IDs/prices, tiny values, zero/empty populations
  and unequal sample sizes. Add named, inventory-validated synthetic economics
  browser subcases to the report/screenshot qualification unit, retaining every
  existing case. Check both themes, all three engines and widths 1440/760/360,
  readable table headers/values, keyboard disclosures and no page-level overflow.

U can proceed alongside A/B in an isolated worktree with a disjoint renderer/test
write set. Integrate serially before final C/E qualification; never qualify one
branch and publish another. Produce the full-dashboard preview and exact VSIX
for owner review. U is not accepted merely because synthetic checks pass.

## Files And Responsibilities

| Area | Existing entrypoints and planned ownership |
| --- | --- |
| Gate graph | `.github/workflows/package-vsix.yml`; dedicated explicitly dispatched promotion workflow |
| Metadata contracts | `tests/test_github_actions_workflow.py`, `tests/test_release_history.py`; small focused early gate |
| Browser harness | `scripts/check_usage_breakdown_ui.py`, `check_speed_ui.py`, `check_allowance_ui.py`, `check_breakdown_overlay_ui.py`, `check_breakdown_hover_ui.py`, `generate_marketplace_screenshot.py`; cohesive snapshot/evidence helpers |
| WebKit diagnosis | `scripts/probes/hover_input_latency.py`, `scripts/verification/hover_observation.py`, `.github/workflows/hover-input-probe.yml`, `tests/test_hover_input_probe.py`, `tests/test_hover_observation.py` |
| Package authority | `extensions/vscode/scripts/package-vsix.js`, `scripts/verify-vsix-archive.py`; small manifest and qualification validators |
| Native proof | `scripts/check_usage_breakdown_webview.py` and its existing native helpers; exact VSIX extraction and trusted receipt |
| Public verification | `scripts/verify_marketplace_release.cjs`; promotion negative tests in a cohesive new test module |
| Production enablement | `scripts/release/policy.py`, pinned journal validators, `scripts/qualification.py`, `tests/test_qualification_transport.py`, `.github/workflows/promote-vsix.yml`; source-bound policy transition |
| Model comparison | `src/codex_usage/report_tables.py`, existing `project_economics.py` metrics; economics rendering/oracle tests and inventory-validated report browser subcases |
| Documentation | ADR 0061, this plan, profiling report, release guide/receipt links |

## Autonomy Approval Review

Earlier granted permissions cover retained-checkout code/workflow/test/docs,
synthetic verification, scoped commit/push, isolated non-Keychain hosts, the durable
journal, nonpublishing qualification/native/dry-run pilots and conditional source
enablement. Do not ask again for those routine checkpoints. The owner now approves
the bounded temporal-tracing batch in the linked review note and every recommended
preapproval below. The restarted Goal carries these permissions into implementation.

| Foreseeable action | Current authority / proposed decision |
| --- | --- |
| Hypothesis-led diagnostics beyond the approved batch | Approved: at most three two-job batches total, including the approved one; each job <=5 minutes, fixed hypothesis/control, no reruns for green |
| Profiler tool access on the isolated CI VM | Approved: preinstalled Apple tools and process-local `DEVELOPER_DIR`; optional noninteractive elevation solely for the approved tracing scope, never persistent security changes |
| Scheduling tools requiring system-wide collection | Approved narrow exception: <=30 seconds of scheduling metadata on that disposable VM, filtered to owned PIDs; artifact <=100 MiB, retention <=14 days; no memory, file contents, environment, command-line arguments or network payload capture; refuse a tool unable to meet this boundary |
| Official Playwright/browser update | Approved: a pinned official patch/minor update only if upstream or controlled evidence identifies an owning SDK/browser defect; update locks/provenance, retain failing baseline and requalify all original assertions; no vendored SDK patch |
| Additional corrective qualification and stale-job cancellation | Approved: up to two evidence-backed repair iterations beyond mandatory C/E cycles; diagnose unexpected failures, cancel only this assignment's verified live stale/hung jobs, never retry unexplained failure into acceptance |
| UI concurrency | Owner permits concurrent work; use an isolated managed worktree and attended subagent, not concurrent writers in main; integrate only owned commits serially |
| Delegation selector unavailable | Approved: do that assignment locally rather than spawn an inherited/default-model agent; do not bypass native restrictions or change global defaults |
| Stage E and release candidate selection | Already conditionally authorized; choose an unused eligible version >=2.12.3 and record exact source/proof; no release tag while UI acceptance is pending |
| Local full-dashboard review window | Approved: one new disposable Local Preview VS Code profile with in-memory secrets, reading a private local ledger snapshot only; no capture, production installation/profile change or private-data upload; open when owner is ready, not while asleep |
| Stage F publication | Held by the latest instruction until owner UI acceptance; prior Goal approval cannot bypass this review |

The owner removed the proposed ten-hour timebox. Retain standard existing hosted
runners, visual concurrency <=2 and the job/batch/repair ceilings above. Every new
diagnostic batch needs evidence that changes its hypothesis; two successive
non-discriminating batches stop diagnosis. No larger runners, paid services or
new infrastructure. Limits are execution ceilings, not a narrower completion claim.

Keep the <250ms guard, scripts-disabled product, genuine inputs, all case identities,
accounting and publication trust contracts. Measurement-contract redesign, runner
migration, lost guarantees, secret/settings changes, Keychain operations, live-data
writes, journal/tag rewriting and ambiguous re-upload remain unapproved. Stop the
affected path for review; continue independent permitted UI/preparation work.

Choose and announce subagent model/effort at native dispatch under Relay Direct;
collect, review and close them before ending work. Planning creates no agents or
worktrees. Human UI review is the unavoidable final gate, not a technical failure.

## Rollback

Before publication, revert only our changes or retain the current full
qualification workflow if probes/pilots fail. Do not silently fall back from
promotion to publishing freshly rebuilt, unqualified bytes. After publication,
preserve tags/artifacts/receipts and use a newly approved higher version for
corrections; never overwrite a published version or retag it.
If E fails, keep publication undispatched and restore the disabled source gate
through a new scoped commit; its changed fingerprint invalidates earlier proof.
Never reset/rebootstrap journal refs or erase possible-upload entries. After any
possible upload, stop automatic retries and reconcile public bytes/history first.

## Review Checklist

- [x] Owner selected explicit promotion; tag creation alone will not publish.
- [x] Owner approved the original implementation with Relay Direct.
- [x] Required inventories and exact-VSIX native path passed at historical `dc79adb6`.
- [x] Owner authorized local implementation and scoped commit/push/nonpublishing pilots.
- [x] Owner explicitly approved all six remaining stages through the active goal.
- [x] Owner approved the bounded temporal-tracing extension.
- [x] Owner accepts the unattended autonomy bundle without a wall-time constraint.
- [ ] U passes technical verification and owner UI review.
- [ ] A-B establish and fix the root cause with retained measurement guarantees.
- [ ] C-D pass current-source normal/retry/native/dry-run gates and update measures.
- [ ] E's final enabled/versioned source is requalified under existing authority.
- [ ] F follows owner UI acceptance and both public target hashes are verified.

## Implementation Checkpoint

Latest diagnostic source: `1b6325af`; promotion false, no new publication.
Stage A identifies a reproduced pre-expression wait but not its owning cause;
stages B-F remain gated. The read-only reviewer is collected, closed and unregistered.
Early gates, isolated visual jobs, batched snapshots, exact-artifact promotion,
original-attempt receipts and the independently pinned Git journal are implemented.
The journal pilot passes; production history remains empty and starts at 2.12.3.
Normal/native and dry-run gates passed at historical `dc79adb6`, not current source.

Local median breakdown runtime is 150.13 -> 95.29 seconds across three alternating
pairs, with 720 tuples/80 byte-identical documents and zero forbidden warm work.
Reads fall from 11,628 to 720 snapshots; fresh navigation, 1,440 real keyboard
presses and 160 screenshots remain. Resize-only equivalence is not accepted.
Latest core evidence: 2,178 passed, one approved skip, 2,179 unique identities;
all 72 local hover views and Ruff/parity/work guards pass.

Native polling/deadline defects were corrected under
[ADR 0062](../adr/0062-native-observation-transport.md). Trial-hover priming and
real-input baselines are guarded under
[ADR 0063](../adr/0063-real-input-observation-budget.md). Hosted diagnostics still
fail: a 345ms observation has a same-renderer 342ms baseline-to-expression-entry
gap with a fast input ACK and a body reporting 0ms at clock resolution. Sampling
changed timing and did not reproduce that failure. The cause is not established;
visibility onset/paint and every keyboard stall are still unproven. Current-source
qualification and controlled retry remain incomplete.

The complete chronology, immutable identities, failed evidence, trust-boundary
reviews and measured costs remain in the
[pilot receipt](../release/2026-10-13-qualification-pilot.md) and
[profile](../research/2026-10-13-verification-and-release-profile.md).
The proposed temporal-tracing extension and its tool/scope limitations are
captured in a [review note](../research/2026-10-13-webkit-temporal-probe.md);
the owner has now approved that bounded batch, but it is not implemented or
dispatched. The additional autonomy permissions above are approved and the Goal
is restarted. Owner UI acceptance remains pending before publication.
