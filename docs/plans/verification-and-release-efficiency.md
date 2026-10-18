# Verification And Release Efficiency

Date: 2026-10-17 (America/Toronto). Status: owner approved implementation with
Relay Direct, including the bounded commit/push/nonpublishing pilot bundle below.
Production tags and publication remain excluded from this assignment.

This follow-up covers all three improvements selected after the
[2.12.5 wall-time profile](../research/2026-10-17-release-2.12.5-profile.md):
affected-visual preflight, three-runner visual qualification, and automated
release handoffs/receipts. Keep this as the single active plan for that scope.
The [original implementation history](verification-and-release-efficiency-history.md)
preserves earlier work and dated approvals. The deployed publication contract is
[ADR 0061](../adr/0061-qualified-artifact-promotion.md); normal timing policy is
[ADR 0071](../adr/0071-hosted-tooltip-observation-policy.md), not the old 2.12.3 exception.

## Outcome And Evidence

Reduce preventable failed qualification, visual queueing and agent-driven handoff
delays while preserving exact-package publication and the complete required gates.

| Improvement | Observed Problem | Success Target |
| --- | --- | --- |
| Affected-visual preflight | Stale date assertion escaped preparation; failure/correction occupied 9m22s | Catch that mismatch before dispatch; reject stale/incomplete local evidence |
| Three visual runners | Two-slot visual stage took 8m49s after eligibility; breakdown waited 2m43s | Trial three isolated standard runners; target roughly 2.5 minutes less qualification time |
| Automated handoffs/receipts | Inspection/tag handoff took 2m24s; closeout took 3m02s | Routine transitions and receipt generation need no agent round trips or repeated milestone approval |

Successful qualification took 12m19s; the scheduling model suggests about 9m40s
at unchanged job durations. Five visual slots add no modeled benefit over three.
A clean release with the old orchestration would still take about 30 minutes.
An initial 22-25 minute public-release target assumes similar external propagation;
it is not a promise or permission to weaken checks. Measure local preflight cost
and evidence reuse, not the whole 9m22s rework interval as guaranteed free savings.

## Scope And Exclusions

Keep complete Python/extension tests, Ruff, monetary parity/work guards, every
visual tuple/assertion, both platform packages, archive/collector/handoff checks,
original-producer/native proof, durable intents and official download hashes.
Keep runner OS/fonts, browser versions, real input sequences and timing limits.

Do not change the dashboard, collector, ledger, prices, Python runtime, PyInstaller,
browser navigation strategy, proof/journal transport, secrets/settings or installed
VS Code. No new service, larger runner, automatic retry, tag-triggered publication,
proof waiver, tracing campaign, journal rewrite or version replacement. Browser
sharding/caching and journal caching are separate future work. Published 2.12.5
packages, source tag and receipts remain immutable.

## Selected Design

Use a small on-demand local CLI around existing qualification/promotion commands.
A hosted coordinator would survive a sleeping local machine but extends workflow
permissions and receipt-commit responsibilities. The local CLI fits the existing
tools and authority; it stops when the machine stops and can resume later. It is
not a daemon, scheduler or second publisher implementation.

Expose two phases; final command spelling is left to implementation:

- `prepare`: validate candidate identity, finish affected preflight, dispatch/watch
  nonpublishing qualification and return its exact run and current attempt.
- `promote --run RUN --attempt N`: explicitly select that run, inspect proof and
  finish the credential-free dry-run, create/check the matching tag, dispatch
  existing promotion, watch it, verify public bytes and generate a receipt.

A future owner instruction to release can cover both phases without another
healthy-milestone prompt. Planning, successful preparation, a local state file or
tag creation cannot grant publication approval. Credentials stay in the existing
trusted hosted publisher; no Marketplace PAT is read or stored locally.

Progress lives under ignored `output/releases/<version>-process/`: a small atomic,
versioned record plus a single-invocation lock. Bind repo, candidate SHA/version/
contract, runs/attempts, package hashes and timestamps. Preserve unrelated files;
do not auto-stage or commit product source. Any receipt-only commit/push uses
explicit paths under covered Git authority. Resume state is a hint, never proof.

## Ordered Deliverables

### 1. Establish Contracts And Dispatch Correlation

- Reuse the profile/public receipt as the two-slot baseline. Freeze current
  required inventories, source identities and phase timings.
- Before dependent coordinator work, verify the installed `gh` dispatch interface
  and how its returned URL binds to actual workflow/repo/event/SHA/ref/attempt.
  Installed CLI help says a run URL is returned only "if available".
- For lost/absent responses, add an optional validated request UUID to workflow
  input/run-name solely for correlation. Require a unique UUID match plus actual
  trusted run metadata. Zero/multiple matches after bounded lookup remain pending;
  never select "latest run", infer origin from time, or redispatch on uncertainty.
- Preserve manual dispatch without a UUID. Correlation is not proof or authority.
  Include changed execution entrypoints/workflows in the trusted contract closure
  and negative tests. Amend ADR 0061 during implementation with the local-preflight,
  coordinator/resume and correlation boundaries; no new publishing policy.

Acceptance: missing/lost-response tests find exactly one matching run or stop
pending reconciliation, with no duplicate dispatch or newly inferred authority.

### 2. Add Affected-Visual Preflight

- Put a reviewed conservative file-to-suite mapping beside release tooling. Diff
  against an explicitly selected verified release base; include renames, deletions
  and new candidate inputs. Unknown/shared renderer, style, fixture, harness,
  dependency or workflow changes select all visual suites, never none.
- Reuse `run_visual_suite.py` and complete existing suite inventories. Run fast
  metadata/relevant unit/harness checks first, then selected full visual suites
  before hosted dispatch. Avoid weaker duplicate assertions or partial evidence
  resembling qualification; coordinate local browser resource use.
- Explain selected suites and reasons. Documentation-only exclusions need explicit
  reviewed mapping; they never affect full hosted qualification, which retains
  every gate regardless of local selection.
- Reuse a completed local pass only if actual candidate inputs, tool/lockfile
  identities, platform/browser environment and complete expected inventory match.
  Changed/new inputs or missing/malformed/partial evidence require a fresh pass.
  This is local work reuse, not evidence accepted by hosted proof readers.
- Exercise the readable-clock mismatch and timing-harness change through real
  selectors/assertion helpers. Failure must prevent dispatch; subsequent input
  changes invalidate a prior pass. Keep all timing requirements unchanged.

Acceptance: the stale 2.12.5 date assumption fails before transport; unknown inputs
cannot be skipped; full CI stays complete; reuse checks content/environment, not mtime.

### 3. Raise Visual Concurrency To Three

- Set the visual matrix cap in `package-vsix.yml` to three and update the independent
  workflow test. Keep five distinct jobs, `fail-fast: false`, serial engines inside
  each job, isolated processes, OS and complete inventories.
- No unlimited caller-controlled cap or silent runtime fallback. Approval of this
  plan for implementation would explicitly replace the earlier two-slot ceiling
  for this assignment, not silently inherit broader hosted authority.
- Retain metadata/core/package/freeze/native dependencies. Measure eligibility
  wait, setup, execution, pool wall time, native time, runner seconds and timing
  dispositions separately.

Acceptance: every original case/assertion and package/native binding passes with
no new exception. Compare measured runs with the historical baseline, disclosing
queue/host variability. A missed speed target leads to diagnosis, not a weaker
functional gate or green-seeking retry.

### 4. Automate Handoffs And Safe Resume

- Keep a thin CLI with cohesive candidate/preflight, observation, progress,
  promotion and receipt helpers. Call existing validators rather than duplicate
  financial or trust decisions. Remain serial on the retained checkout.
- Use one bounded observer per exact run, a configured poll/deadline policy and
  prompt transitions after validated completion. Avoid a second agent-side
  polling loop. Timeout remains pending; it never justifies repeating a mutation.
- Before write-like actions, record intent/expected identity. Resume reconciles
  GitHub/remote refs and original evidence, not a local completion flag. Reject
  overlapping invocations, changed candidates and superseded attempts.
- Under release authority, create a missing tag only at the qualified SHA; check
  and reuse an exact existing tag. Conflicts stop, never force/move. Resolve an
  accepted push with lost reply through remote readback.
- Persist exact qualification/promotion identities. Reconcile a lost promotion
  reply through correlation, never automatic redelivery. Generic `resume` only
  observes/reconciles; crossing a new tag/promotion boundary requires explicit
  promote mode for that candidate under current owner release authorization.
- Failed qualification stops with diagnostics. No automatic rerun, attempt advance,
  source edit or caller-declared proof reuse. Original-job validators still govern
  any separately approved failed-job retry.
- After possible upload, resume observes the recorded publisher/public verifier
  only. Partial or ambiguous outcomes stop automatic publication. An invisible
  attempted target stays pending; only official matching bytes permit safe reuse
  under the existing publisher contract and any required retry approval.

Acceptance: synthetic interruption tests at each boundary prove no extra tag,
dispatch or upload: lost acknowledgments, altered local state, changed main/tag,
stale attempts, expired artifacts and partial publication. The healthy path never
rebuilds and preserves both independent publisher proof checks.

### 5. Generate Receipts And Timing Summaries

- Generate deterministic receipts from independently verified qualification,
  promotion, durable-intent and official-download evidence. Prepare stable prose
  before propagation ends; label drafts unpublished until both targets pass.
- Preserve exact identities/hashes, links, known limitations and failed-candidate
  references. Use America/Toronto for user-facing dates and retain UTC proof times.
  Never infer public success from upload alone.
- After verification, atomically write the final receipt and update only bounded
  current-status sections in the release guide. Reruns reproduce the same verified
  facts, preserve historical receipts and refuse to overwrite manual edits.
- Emit phase timing JSON and a concise comparison automatically: preflight/reuse,
  dispatch/queue, execution, dry-run, promotion, public observation and receipt.
  Never add parallel job durations as elapsed time.
- Receipt commits occur after publication and never move the tag. A failed docs
  push is not a failed upload or permission to republish. Keep credentials and
  private task/usage data out of process state.

Acceptance: verified/pending/one-target/mismatch/unavailable fixtures produce a
truthful receipt or refuse. Test UTC/EDT midnight and DST. Target under ten seconds
for routine receipt generation after verified inputs, reporting Git/transport separately.

### 6. Verify And Measure The Combined Process

- Start with focused mapping/state/dispatch/receipt tests, then complete Python/
  extension checks, Ruff, monetary parity/work and unchanged full visual gates.
  Add source/contract/missing-case negatives to existing qualification tests.
- After scoped commit/push approval, run at most two fresh nonpublishing
  qualifications at the same final three-slot source. First proves the complete
  process; second is a predeclared timing repeat, never an unexplained-failure
  retry. Use the recorded two-slot baseline and label the comparison historical,
  not a controlled same-host experiment.
- Interrupt/resume the local observer during one of those same runs without
  canceling/redispatching it. Run one credential-free hosted dry-run against exact
  complete proof; preserve byte/inspection equality and skipped-publisher evidence.
  Simulate tag/upload/lost-ack faults locally, never in production.
- No version bump or eligible tag is needed for process pilots. Existing-version
  packages are nonpublishing measurement artifacts, never replacement 2.12.5 bytes.
  A later release requires its own unused version, final-source qualification and
  explicit promotion selection.
- Collect one bounded read-only review of preflight invalidation, dispatch
  ambiguity, credential/resume boundaries and receipt claims. Choose/announce
  model/effort at native dispatch; collect/close the reviewer. No parallel writers.

Acceptance: original inventories, package/native bindings, dry-run and interruption
tests pass. Publish measured before/after results with local preflight cost, runner
usage and remaining Marketplace latency. Technical readiness is not permission
for a production canary or the next release.

## Affected Files

- `.github/workflows/package-vsix.yml`, `promote-vsix.yml`, and workflow tests:
  three-slot cap and optional correlation; credentials/trust boundaries unchanged.
- A small release CLI and focused `scripts/release/` helpers: conservative mapping,
  progress/observation, coordination and receipts; update `policy.py` for any new
  trusted execution entrypoints.
- Existing `run_visual_suite.py`, `verification/visual_cases.py`, visual fixtures/
  assertions and `qualification.py`: reuse interfaces and strict proof readers.
- `verify_marketplace_release.cjs`: reuse exact public verification; expose
  machine-readable results/phase timings only where needed.
- New focused tests plus existing workflow, qualification, publisher, visual and
  journal regressions; ADR 0061, release guide and profiling notes.

## Autonomy Approval Review

The owner approved this bounded implementation bundle with Relay Direct. Approval
to publish 2.12.5 is fulfilled; past repair/tracing/journal permissions do not
automatically extend this assignment.

The approved bundle covers local source/workflow/
tests/docs changes, synthetic/disposable verification, scoped commits/pushes to
retained `main`, three concurrent standard macOS visual jobs, at most two fresh
nonpublishing qualifications and one hosted dry-run. No larger runners, new
services, settings/secrets changes or production side effects. Covered healthy
steps continue without renewed milestone prompts.

Production tags, actual promotion/upload, production-journal writes and the first
live automated publishing canary need a later explicit release instruction for
its selected version/source/run. New authority is also needed for hosted attempts
beyond this budget, new diagnostics/infrastructure, material trust changes or
recovery that could duplicate an unknown side effect. Unexpected faults first
get local/read-only diagnosis; continue unrelated covered work.

## Rollback And Handoff

Implementation checkpoint:

- [x] Conservative preflight and three-slot workflow contracts implemented with focused tests.
- [x] On-demand coordination, canonical intents and receipt generation implemented.
- [x] Complete independent safety re-review, Python/extension suites, Ruff and accounting guards.
- [ ] Complete the full local visual preflight.
- [ ] Complete the two declared nonpublishing qualifications, observer resume and dry-run.
- [ ] Record measured results and final implementation readiness; no publication.

Use retained `main` serially; preserve unrelated owner changes, untracked `apps/`
and consultant reports. If the coordinator fails, preserve state and use existing
manual commands after reconciliation, never a second publication attempt. If
three-slot pilots regress, restore two slots in a new scoped commit; fingerprint
changes require fresh proof before release.

Rollback only our scoped edits and preserve failed evidence. After any possible
upload, observe/reconcile first; retain all tags, packages, receipts and journal
history. No reset, rebootstrap, forced update or deletion. Distinguish implemented,
measured-ready and published outcomes. Planning creates no worker/task/worktree
and starts no implementation.
