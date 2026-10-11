# Usage And Allowance Breakdown

Status: Unified-chart implementation approved 2026-10-09 and complete on retained
main. Independent review fixes, collector rebuild, full Python/extension checks,
cross-browser matrix and native macOS control replay passed. A new isolated
Codex Usage Local Preview is open with verified frozen records and controls.
Owner accepted the full isolated dashboard preview and authorized release on
2026-10-10. Released as 2.12.0 after exact-commit platform checks, matching-tag
publication and verified public downloads; see [Release Receipt](../release.md).
Current and historical technical evidence is in Verification History.
No live capture or installed-extension mutation is part of release verification.
Historical planning permissions below are retained as history.

Released source: `v2.12.0` at `3a1f9cc48794505ccf97ebde2daf5461ab0434d3` on main.
Release version is 2.12.0. Pre-existing untracked `apps/` is out of scope.
Prior technical acceptance is recorded in
[Verification History](usage-burn-breakdown-verification.md).
This is the same feature and release candidate, not a parallel implementation.

### Revised Candidate Checkpoint (2026-10-09)

Independent review follow-up: historical evidence could issue a project drill
absent from the selected calendar summary, then fail at its label lookup.
Command issuance now requires selected-range membership; historical-only rows
remain exact evidence marked "No selected-range usage", without drill links.
Calendar bounds, global filters and account overlays do not change. ADR 0054
records the contract; internal cache revision 5 expires old issued commands.
The Oct9 selected-range / Oct8-only project regression passes. The previous
source/binary freeze is superseded by the post-review rebuild identity.

The unified contract is implemented. The manager's full Python suite passes
(1,736 tests, one expected Windows-only junction skip), as do the extension
build/tests (48), Ruff and diff checks. The Firefox last-tick border-anchor
overshoot was fixed at the endpoint alignment contract; all 720 browser cases
pass across Chromium/WebKit/Firefox, narrow/medium/wide views and both themes.
Native macOS sandboxed/offline replay passes 21 mouse/Enter transitions.
Native Windows and native Tab traversal remain unvalidated.
Historical evidence and counts below remain historical, not reused verification.

Fresh private exploratory evidence is under ignored
`output/playwright/usage-breakdown/unified-private-worker-01a12389-r3/`:
158,249 frozen quota observations yield 20,477 display marks (20,337 mandatory
boundaries, 140 ordinary), 9,359,626 breakdown bytes / 14,604,001 full HTML bytes,
and 0.642s warm report rendering with zero forbidden historical work. Boundary
classification diagnostics are nonexclusive: 15,457 reset-deadline changes
(15,046 below 60 seconds), 2,055 plan changes, 923 used-percent decreases and
275 same-instant semantic conflicts. Deadline corrections are retained, not
merged to enforce a visual budget. Dense all-time overlays remain a limitation.
Actual compiled AgentClient authenticated loopback replay preserves the full
HTML (15,142,281 JSON bytes, 0.068s); Chromium narrow/wide screenshots render all
marks. This is not native VS Code webview acceptance or fresh preview creation.

The baseline Python fingerprint now uses real NUL separators, matching preview
preparation. Earlier literal-backslash-zero hashes are historical and cannot be
compared directly. The source freeze utility separately names its sorted JSON
path/digest-manifest convention and covers Python/TypeScript, scripts, tests,
active docs and build dependency inputs.

The manager's controlled comparison uses the existing frozen private snapshot,
identical disposable cost-index inputs, cleared derived caches and a fixed
2026-10-09T14:50:00Z report clock. Existing base-report HTML is byte-identical.
Today cold/warm observations are 14.27s/0.241s for this candidate versus
13.17s/0.601s for the prior accepted candidate; All Time is 44.66s/0.582s versus
40.54s/0.608s. All Time whole HTML grows from 9.76 MB to 14.60 MB because
mandatory boundary evidence is retained. These are observations, not a speedup
claim; warm derived preparation calls are zero. The comparison harness restores
fresh issued commands before sampling drills, respecting receipt expiry.

The frozen Last7/30 measurements, new isolated preview, normalized-record
preservation and actual running collector isolation checks pass. Nine rendered
preview control transitions pass and return to Last7/Daily/API cost/weekly
allowance. The preview reuses the original Oct9 10:39 EDT capture; normal startup
reads zero task bytes and adds only an unavailable offline credit observation.
Human product acceptance is the remaining gate. Source/binary identity accompanies
the checkpoint. No account/live source mutation or publication was performed.

## Goal

Explain when captured usage happened, which models/projects contributed, and how
account-wide weekly allowance or credit balance changed. Make the breakdown
useful in one chart rather than requiring comparison of several repeated plots.
Complement the Hourly Heatmap; do not change token, pricing or allowance math.

The revised full-dashboard **Codex Usage Local Preview** was accepted and the
gate-verified Marketplace release is complete. The isolated frozen preview
remains separate from the user's installed extension and live ledger.

## Root Cause And Layer

- Numeric labels follow an eight-character, general-precision containment
  contract. It deliberately produces scientific notation and preserves more
  dollar decimals than a scanning chart needs. Fix the metric-aware formatting
  and tick-scale contract, not isolated strings or smaller fonts.
- The period picker exposes allowance continuity suffixes as user-facing
  periods. Rebases and conflicts can produce adjacent or singleton fragments;
  these are legitimate evidence boundaries, not useful navigation choices.
  Separate evidence continuity from the displayed date range. Do not merge
  fragments in the calibration model merely to simplify labels.
- The "full-range" daily chart is clipped to the selected observed fragment.
  A short fragment becomes one oversized daily bar with intraday ticks.
  A second hourly plot and separate allowance/balance/change plots repeat the
  same time domain. Fix composition and navigation at the breakdown view layer.
- Previous visual gates proved containment and accounting, not that defaults,
  units and range controls were understandable. Add observable UX criteria
  alongside parity, security and responsive tests.

## Proposed Experience

### One Range, One Chart

The dashboard's existing Range control is the sole date-range authority:
Today, Yesterday, Last 7 days, Last 30 days, This month, All time and custom dates.
Remove the breakdown's observed-period picker. Never silently replace the
selected calendar range with the latest allowance suffix or mutate global
filters during drill-down.

Historical allowance windows remain visible through wider/custom dashboard
ranges and captured boundary evidence. Raw continuity fragments stay in a
collapsed evidence disclosure; they are not called complete reset cycles.
No inferred nominal cycle opening or automatic reset-aligned usage total.

Use **Time / Projects** as the main view control. Time has **Daily / Hourly**,
the existing Tokens / API cost / Estimated credits metric control, and
Model / Project stack grouping. Use a compact menu for the account overlay:
**Weekly allowance / Credit balance / None**. Hide time-only controls in
Projects. All controls remain native issued command links with scripts disabled.

Default to API cost, model stacks and weekly allowance. Today/Yesterday start
Hourly; wider ranges start Daily. Explicit grain choices survive metric/group/
overlay changes within the same valid scope; a new global range resets to its
appropriate default. Do not automatically switch the account overlay when the
usage metric changes: estimated credits are not observed balance deductions.

Daily shows the entire selected calendar range, including empty dates.
Hourly shows at most seven consecutive local calendar days, initially the
latest in-range day with usage or an account capture and the preceding six
days, clipped to the selected range. Previous/Next/Latest move by bounded
seven-day windows; show their actual dates. For an entirely empty selection,
use the clock day clamped to the selected bounds. UTC chronology preserves DST
repeated/skipped/partial hours and visible offsets where needed.

Drilling a daily bar opens the hourly window containing that day and a selected
day/hour detail. Return to Daily restores the whole range, not a clipped
"overview." Every bucket has accessible exact-value inspection; details update
beneath the chart rather than creating another plot. Project selection filters
usage detail only; the account overlay stays account-wide and visibly labeled.

### Shared Timeline And Honest Axes

Use one time domain for stacked usage bars and captured account readings.
The left axis is the selected usage metric with a zero baseline. The right
axis is weekly remaining percentage, fixed at 0-100%, or captured credit
balance, explicitly labeled account-wide and observed-range when not zero-based.
Only one account overlay is visible; None removes its axis.

Use distinct mark styles and a visible key for usage stacks versus account
readings. Keep captured points as points, not interpolated balances. Do not
connect across resets, corrections, conflicts, plan changes or missing readings,
and do not suggest that bar heights reconcile to exact quota or credit debits.
Keep both numeric axes and the common time axis visible without horizontal
panning. Prefer readable sparse local date/hour ticks over arbitrary repeated
timestamps. Empty/future/unobserved spans must not imply measured zero workload.

Multiple supported weekly limit/plan series remain separately identifiable on
the percentage axis; ambiguous/unsupported/nonweekly evidence is disclosed,
not combined into a fabricated weekly meter. A missing requested overlay
stays explicitly unavailable rather than silently selecting a different one.
Retained historical points remain usable when the latest live probe is stale.

Credit balance points retain exact finite Decimal values. Original interval
net decreases/increases and boundary-crossing intervals remain in an expandable
exact table; remove the separate signed-change chart. Missing/invalid/unlimited/
nonchronological/unknown-plan captures continue to break delta adjacency.
A weekly reset alone does not break credit balance continuity. Never prorate
a spanning interval, infer an hourly debit or subtract included usage estimates
from actual credits. Possible purchases/grants/refunds remain increases, not
negative spending.

Projects uses the same chart area for ranked horizontal totals, stacked by model,
with top ten plus inspectable Other. Hide the account overlay: a time-based
account balance cannot be drawn against categorical project positions.
Selecting a project opens its Time detail without changing global filters.

### Human Number Formatting

Use metric-aware, human-unit labels and sensible tick spacing:
`139.03 M tokens`, `$28.61`, `1.23 K credits`, and `50%`.
Tokens/credits may use consistent K/M/B/T units; currency uses readable dollar
ticks, ordinarily at most two fractional digits. Axis titles carry units;
rounded tick ceilings must still contain every unmodified plotted value.

Do not show scientific notation in ordinary visible axis/rank/summary values.
Increase meaningful precision or use a clearly named common scale/offset when
rounding would hide nonzero tiny amounts or distinct large-balance movement.
Retain full numeric/Decimal values and original timestamps in inspection,
accessible names and titles. Never round stored or aggregated values.
Wide/narrow labels must fit without shrinking text or hiding axes.

## Preserved Contracts And Exclusions

- Reuse trusted dashboard-valued records, transitions and global project
  filtering. Tokens include cached input and included reviews; API-equivalent
  dollars are not subscription charges. Images stay separate.
- Selected-range composition retains calendar `[start, end)` membership and
  baseline parity. Retained evidence/calibration intervals keep their established
  capture-causal `(origin, capture]` semantics; do not borrow calibration merely
  because calendar totals resemble an evidence interval.
- Actual allowances/balances are always account-wide. Exact captured points,
  estimated Standard credits, known free zero and unknown/excluded values remain
  distinct. No exact per-project/model funding attribution or new forecast.
- Keep continuity/reset/calibration math, raw balances, pricing and ledger schema
  unchanged. This is a view/navigation contract revision, not historical capture,
  repricing, deletion, task transfer or collector ownership work.
- Reuse revision-bound partitions and issued receipts. Warm controls do no source
  scans, historical decoding/materialization, repricing, continuity preparation
  or fitting. Do not load every historical composition for one visible window.
- No new frontend framework, product webview scripts, CSP relaxation, telemetry,
  backend deployment/tunnel, installed-extension replacement or Marketplace work.
  General cold-history optimization and unrelated UI refactors are excluded.

[ADR 0054](../adr/0054-usage-allowance-breakdown.md) remains the existing technical
contract until implementation approval. The revision explicitly supersedes its
separate-chart, primary observed-period picker and scientific-tick presentation
choices, not its accounting/evidence guarantees. Update those sections after
approval; do not append contradictory active decisions.

## Ordered Deliverables

1. **Bind the revised view contract.** Update ADR 0054 and the strict Python/
   TypeScript navigation state, defaults and revision/cache identities. Reject
   forged/unsupported actions; preserve typed expiry recovery for genuinely
   issued old scopes without interpreting old fragments as the new date range.
2. **Prepare reusable time summaries.** Add daily model/project composition and
   bounded seven-day hourly reads using existing valued partitions. Fix stable
   legend identity across grain/metric/drill changes. Do not repeatedly scan
   all project partitions or reprice records to assemble each daily view.
3. **Build shared plot primitives.** Separate usage stacks, account point
   overlays, axes and inspection composition into cohesive modules. One shared
   UTC transform must drive bar bounds, captured points and time ticks. Keep
   formatting unit-aware, both axes fixed and responsive controls bounded.
4. **Replace the old view.** Remove the period picker, redundant daily context,
   standalone meter/balance/net-change plots and their obsolete commands.
   Implement Time/Projects, grain/overlay choices and reversible drill-downs;
   retain exact tables and progressively disclosed evidence.
5. **Resolve dense-history display before acceptance.** Test realistic retained
   capture density, not only small synthetic data. Daily must keep the full
   selected domain; use explicit below-resolution marks where bars are tiny.
   If account points need bounded display reduction, retain actual bucket
   endpoints/extrema and continuity boundaries, never averaged/interpolated
   balances. Keep every original reading accessible in partitioned inspection.
   Measure preparation, HTML size and warm latency; do not call the rewrite a
   performance improvement without a controlled comparison.
6. **Verify the revised candidate.** Run focused regressions first, then Python,
   Ruff and extension tests/build; extend existing browser/native/parity gates
   for the matrix below. Inspect representative screenshots rather than relying
   only on bounding-box assertions. Any unproven host/input path stays disclosed.
7. **Build and open a fresh isolated preview.** Reuse the existing private
   snapshot baseline in a new ignored preview directory; rebuild the collector
   from the verified revised source and record source/binary identity. Verify
   isolation and normalized-record preservation before presenting the new window.
   Leave the older preview available for comparison.
8. **Human review.** User reviews the new Codex Usage Local Preview. Capture
   actionable feedback here and iterate within the approved scope; technical
   test passes do not stand in for product acceptance. Release only under
   separate explicit authorization.

Default to serial work on retained main. A bounded read-only review of the
state/evidence and overlay contract is useful after the candidate stabilizes;
do not create parallel writers. Once implementation is approved, use Relay
direct for any delegated work and remain with workers through verification,
review and completion. No task creation/delegation is authorized by planning.

## Acceptance Matrix

- **Reported preview defects:** a short Oct 9 fragment cannot become the primary
  period; Last 30 days displays the whole selected range in Daily; one main
  plot appears in Time, no daily-context/meter/balance/change plots beneath it.
  Values around 139,030,000/278,050,000 tokens and $28.61067/$57.22134 are readable.
- **Controls and navigation:** Today/Yesterday, 7d, 30d, Month, All time and
  custom ranges; Daily/Hourly/Projects; all three metrics; both time stack
  groups; all overlays; day/hour/project/Other drill and return; earliest/latest
  seven-day windows; no global filter mutation or unreachable retained detail.
- **Accounting/evidence:** additive model/project totals and exact base monetary,
  language/image/allowance parity; selected calendar boundaries; included
  reviews/free/unknown; current/prior resets and corrections; stale/no current
  probe; multiple/missing weekly series; exhausted allowance with credit decrease,
  later reset, unchanged credits, increases, unlimited/unknown and spanning
  intervals; ordinary and extreme finite Decimal balances.
- **Visual correctness:** Day/Night at 360/760/1440 widths in Chromium, WebKit
  and Firefox; actual glyph containment, noncolliding dates, both visible axes,
  correct shared-domain coordinates, explicit scales and dense/sparse/empty data.
  Test Toronto/Lord Howe/Chatham DST, midnight boundaries, partial days and
  singletons in evidence. Account marks must be distinguishable from stacks
  without depending solely on color.
- **Security/cache:** existing restrictive script-disabled CSP, forged/unissued/
  stale command rejection and one typed recovery; revision/pricing/timezone/
  transition/filter identity; zero forbidden warm work across grains, overlays,
  seven-day navigation and drills. Native VS Code mouse/keyboard paths remain
  separate from browser proof; native Windows/Tab gaps must be reported honestly.
- **Human acceptance:** user can identify the selected range, leading model or
  project, metric units, allowance versus credit balance and unknown evidence
  from the revised preview without inspecting technical continuity labels.

## Preview Permissions And Rollback

Historical planning-stage permission: that turn authorized plan-file changes only. Approval to implement this plan
will also cover local tests/builds, ignored verification artifacts, a read-only
backup from the existing private preview ledger and launch of one new disposable
VS Code development-host window. It does not authorize a new live capture,
fresh live-ledger backup, account login, installed-extension replacement,
release, Keychain reset or stopping the user's normal VS Code/collector.

Use distinct preview HOME/CODEX_HOME, user data, extension directory and settings.
Copy no task logs, auth files, runtime keys or live configuration. Disable
scheduled capture; retain the normal startup path against empty sessions and
an offline RPC that returns unavailable, never synthetic account values.
Record zero task-source bytes and any added unavailable startup observations.
Compare original normalized usage/image/speed/quota/credit records with the
frozen baseline; all derived writes remain in the new copy.

Reuse the reviewed preview-only collector sandbox wrapper: block live Codex,
collector settings and Keychain access and verify the actual running collector.
Keep Electron's native renderer sandbox and in-memory secret storage; do not
sandbox the whole Electron host or bypass its sandbox. Host-only launch seams
must not modify product modules, binary contents, scripts or CSP.

Rollback is closing/stopping only the new verified owned preview process group.
Retain its private source hashes, logs and snapshot for diagnosis; leave the old
preview, normal windows, live services and installed extension untouched.
Private snapshot values and screenshots remain ignored and must not be published.

## Verification Entrypoints

Run focused tests covering the affected modules before broader checks. Existing
entrypoints should be extended for the revised contract, not replaced with an
unrelated harness:

```sh
uv run pytest -q -rs
uv run ruff check .
npm --prefix extensions/vscode test
uv run python scripts/check_usage_breakdown_ui.py --output output/playwright/usage-breakdown/unified-ui
bash scripts/build-agent-macos-arm64.sh
uv run python scripts/check_usage_breakdown_webview.py --output output/playwright/usage-breakdown/unified-native
```

Use the established baseline/parity and controlled performance scripts on
synthetic fixtures or explicitly supplied disposable/private copies. Never
report a changed live workload as a controlled comparison. Check source/binary
fingerprints, actual preview isolation, startup behavior and unchanged live
settings separately from rendering. Do not reuse old verification counts as
proof of the revised chart.

## Affected Files

- `src/codex_usage/report_usage_breakdown.py`,
  `report_usage_breakdown_chart.py`, `report_breakdown_axis.py`,
  `report_breakdown_numbers.py`, `report_breakdown_balances.py` and theme helpers:
  view composition, shared axes/overlays, human units and detail disclosures.
- `src/codex_usage/breakdown_reports.py`, `breakdown_aggregation.py`,
  `breakdown_commands.py`: derived summaries, range/state/cache revision and
  strict issued navigation. Evidence/window/balance modules change only if
  needed to expose existing facts to the view, not to weaken continuity.
- `extensions/vscode/src/types.ts`, `breakdownNavigation.ts` and relevant
  report transport/host tests: matching state and expiry handling. The existing
  global range picker keeps its current semantics.
- Existing `tests/test_*breakdown*.py`, browser/native checking scripts,
  ADR 0054 and this plan. Add cohesive focused modules where responsibilities
  require them; do not expand a catch-all file beyond repository size guidance.
- Ignored `output/local-preview/<new-id>/`: fresh candidate harness, snapshot,
  source/binary identities, launch/stop instructions and verification readback.

## Decisions Left To The Implementer

Exact state field names, tick-step algorithm, module splits, bounded display
point budget and partition layout are engineering choices within the contracts
above. They must pass dense/narrow/history gates before the new preview is
called ready. A material scope change or weaker evidence/isolation guarantee
requires renewed discussion, not a hidden exception.
