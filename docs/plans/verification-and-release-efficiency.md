# Verification And Release Efficiency

Date: 2026-10-13. Status: local candidate verified; hosted and independent-history
authority gates remain open. Production promotion is source-disabled.
Scope agreed: faster failure-local gates, exact qualified-artifact promotion,
and fewer browser round trips without reducing coverage.

Authority: [measured profile](../research/2026-10-13-verification-and-release-profile.md),
[proposed ADR 0061](../adr/0061-qualified-artifact-promotion.md), and the existing
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
No product accounting, pricing, dashboard rendering or timeout change is planned.

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

## Proposed Qualification Graph

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

- Run focused contract/harness tests first, then complete core/extension suites,
  Ruff, parity/work guards and all original visual/native/package gates.
- Run nonpublishing hosted pilots at the exact candidate SHA. Deliberately fail
  one bounded visual case and demonstrate the retry/aggregation provenance rules.
  No secret exposure or Marketplace upload during negative/dry-run tests.
- Capture per-job queued/start/end times, setup cost, suite wall times, API call
  counts, case inventories, artifact sizes and runner minutes. Compare at least
  three controlled local pairs; label limited hosted sampling honestly.
- Refresh the profile with before/after results. Target roughly 20% lower local
  breakdown runtime and 30% lower hosted qualification critical-path time as
  investigation goals, not guarantees or reasons to weaken gates. Promotion
  should remove the duplicate full tag pass by construction, measured separately
  from native replay, manual handoffs, runner queues and external propagation.
- Update release operating instructions and link a concise receipt. The existing
  495-line `docs/release.md` should not absorb another long workflow description:
  extract the active procedure into a cohesive release guide if needed, retaining
  historical receipt anchors and links.

Acceptance: correctness and authority gates pass; measured savings and remaining
costs are disclosed. Workflow readiness is not proof of a new published release.
Actual publication remains a separately authorized final canary.

## Files And Responsibilities

| Area | Existing entrypoints and planned ownership |
| --- | --- |
| Gate graph | `.github/workflows/package-vsix.yml`; dedicated explicitly dispatched promotion workflow |
| Metadata contracts | `tests/test_github_actions_workflow.py`, `tests/test_release_history.py`; small focused early gate |
| Browser harness | `scripts/check_usage_breakdown_ui.py`, `check_speed_ui.py`, `check_allowance_ui.py`, `check_breakdown_overlay_ui.py`, `check_breakdown_hover_ui.py`, `generate_marketplace_screenshot.py`; cohesive snapshot/evidence helpers |
| Package authority | `extensions/vscode/scripts/package-vsix.js`, `scripts/verify-vsix-archive.py`; small manifest and qualification validators |
| Native proof | `scripts/check_usage_breakdown_webview.py` and its existing native helpers; exact VSIX extraction and trusted receipt |
| Public verification | `scripts/verify_marketplace_release.cjs`; promotion negative tests in a cohesive new test module |
| Documentation | ADR 0061, this plan, profiling report, release guide/receipt links |

Implementer chooses concise helper names and structured parsers consistent with
the repository; this plan does not prescribe an oversized generic runner.

## Permissions And Rollback

Owner subsequently authorized implementation: retained-checkout code/workflow/
test/documentation edits and synthetic local verification are in progress.
No new release tag, Marketplace publication or secret/settings change is authorized.

Implementation approval should explicitly cover retained-checkout source/test/
workflow edits, synthetic local verification, isolated VS Code hosts without
Keychain access, and bounded nonpublishing hosted pilots/necessary commit-push.
Absent that operational scope, hosted pilots or native launch stay named gates.
Do not add workers/worktrees or concurrent writers by default. A bounded
read-only review of promotion authority is useful before the hosted canary;
if delegated after approval, collect and close it before ending the work.

Marketplace publication, new release tag and publisher-secret use need separate
release authority; existing 2.12.2 release approval is not reused. No repository
or organization settings/secret changes are included. If native proof requires
new trusted infrastructure, present that scope before applying it.

Before publication, revert only our changes or retain the current full
qualification workflow if probes/pilots fail. Do not silently fall back from
promotion to publishing freshly rebuilt, unqualified bytes. After publication,
preserve tags/artifacts/receipts and use a newly approved higher version for
corrections; never overwrite a published version or retag it.

## Review Checklist

- [x] Owner selected explicit promotion; tag creation alone will not publish.
- [x] Owner reviewed the plan and authorized implementation with Relay Direct.
- [ ] Required gate/case inventory and run-attempt/native trust probes are resolved.
- [x] Owner authorized local implementation and scoped commit/push/nonpublishing pilots.
- [ ] D1-D3 retain every coverage, accounting, security and artifact safeguard.
- [ ] D4 records actual savings, retry evidence and remaining latency.
- [ ] Separate release approval precedes any publishing canary.

Local milestones (not hosted acceptance):

- [x] D1 journals complete visual tuples and preserves failed-case diagnostics.
- [x] D2 batches DOM reads, preserves assertions and fresh navigation, and records
  three measured wall-time pairs plus a separate 720-tuple resize-state trial.
- [x] Complete local core/extension suites and independent result inventories pass.
- [x] Read-only promotion-safety review is collected, closed and unregistered.
- [ ] Independent publication-history authority closes deleted-run uncertainty.
- [x] Scoped commit/push and hosted-pilot permission is granted.
- [ ] Hosted normal, controlled failure/retry, pinned native/platform and dry-run
  pilots pass at the exact accepted source SHA.

## Implementation Checkpoint

Implemented locally, not yet hosted-qualified: early metadata gate, five isolated
visual suites with bounded concurrency and always-upload failure journals;
batched breakdown snapshots; immutable producer receipts and original-attempt
log markers; frozen hosted manifests; exact-VSIX native input; pinned isolated
VS Code download; explicit promotion with separate credential exposure; and
public/occupied-version hash verification. Default browser navigation remains
fresh; resize-only optimization is not assumed equivalent.

The read-only provenance review and independent REST readback confirmed that
GitHub copies successful jobs into newer attempts while retaining original
execution times. Artifact REST records lack originating job/attempt association.
Producer receipts therefore bind actual upload outputs and original-job log
markers, not reconstructed timestamps alone. The reviewer was collected, closed
and unregistered; there are no active workers or concurrent writers.

Three alternating unchanged/candidate local breakdown pairs retained all 720
case/state tuples, 80 byte-identical HTML documents per pair and zero forbidden
warm work. Wall times were 151.37/96.80, 150.13/94.72 and 144.94/95.29 seconds:
median 150.13 -> 95.29 seconds, approximately 36.5% lower. Single-machine workload
evidence, not hosted or universal predictions. The 72-case hover suite passed
with unchanged 250ms guards. Raw outputs remain ignored under
`output/performance/verification-efficiency/`,
`output/playwright/verification-efficiency/` and `output/qualification/`.

Earlier broad runs exposed an obsolete direct-command integration assertion and
a stale partial-upload expectation; both owning contracts were corrected before
fresh verification. The final complete run passed 2,068 cases with exactly the
named non-Windows junction skip in 64.66 seconds. Collection and raw JUnit match
all 2,069 unique cases and retain every independent 2.12.2 required identity.
The early metadata gate passed 35 cases. Extension qualification passed all 48
named tests with matching structured event collection and successful completion.
Ruff, frozen monetary parity, bounded-work checks and all five visual suites pass
locally; their complete tuple/assertion inventories were independently read back.

An instrumented complete breakdown run recorded 720 snapshots in 7.93 seconds,
replacing 11,628 separate DOM evaluate/count reads measured at 54.8 seconds.
All 720 fresh navigations, 1,440 real keyboard presses and 160 screenshots remain.
The separate resize probe matched fresh state/layout for 720 tuples, but does not
substitute for painted/native proof and has not changed default navigation.

Explicit GPT-6.1 Sol / High read-only review identified source/tag drift, immutable
dispatch binding, copied-job log resolution and same-directory preflight-reset
gaps. Focused regression tests exercise the actual per-target publishing entrypoint
with network/credential effects stubbed. The fixes were reviewed without claiming
effective model settings confirmed by the host.

One deeper authority gap remains: a deleted later Actions run can hide a possibly
accepted upload when an older run retries. Pagination/run-number checks detect
some omissions, not an independently retained lifetime high-water mark. Production
`validate-publication` and `check-files` therefore fail before network/credentials
under a source-owned, fingerprinted false gate. No inputs/environment can bypass
it. Nonpublishing qualification and inspection remain available.

The owner approved this follow-up: an independently pinned Git-backed append-only
receipt journal, with non-forced sibling updates before possible side effects.
Scoped Contents-write is job-scoped, not a ref-restricted credential. Production
and synthetic pilot namespaces have separate fixed refs, workflow IDs, roots and
event kinds. Local regressions cover lost responses, replay, malformed/missing
history and deletion of all Actions evidence. Production cutover begins at 2.12.3;
the bootstrap pins and hosted qualification remain open. Publication/new tags
still require separate release approval.
