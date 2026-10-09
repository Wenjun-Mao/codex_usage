# Usage And Allowance Breakdown

Status: Product direction approved 2026-10-08; implementation authorized and
started 2026-10-09, after the released 2.11.1 observed-speed usability patch.
Separate implementation candidate corrected and re-verified on 2026-10-09;
not shipped. Initial verification missed the reviewed interval, missing-evidence,
visual-axis and scope-recovery cases; corrected evidence is recorded below.
Manager implementation review accepted the corrected candidate on 2026-10-09.
The approved unpublished extension below is implemented; its independent manager
acceptance retest remains pending, distinct from the earlier base acceptance.
Human product acceptance, version/release approval and publication remain gated.

## Goal

Explain when captured usage happened, which models/projects contributed, and
how account-wide included allowance and credit balances changed within observed
weekly portions or the dashboard selected range.
Complement the compact Hourly Heatmap rather than replacing its overview.

## Approved Unpublished Extension (2026-10-09)

Extend this same candidate, not a second feature or release. Replace the binary
cycle/range control with a compact observed-window disclosure: current observed
weekly portion when supported, all dated retained weekly portions, and Selected
range. Entries identify limit, plan and continuity boundary as well as dates.
Historical portions remain browsable without a fresh current anchor; unknown
openings, conflicting captures, rebases and plan boundaries stay explicit.
Weekly membership remains `(origin, capture]`; Selected range stays calendar
`[start, end)`. Global filters are never mutated by chart navigation.
Selected calendar bounds remain complete, but the default day is the latest
in-range usage or account-wide capture; empty ranges clamp the clock to bounds.
Observed singleton windows open their actual capture day, including midnight.

Add Estimated credits to both views, groups, rankings and drills using existing
valued Standard credits, including included usage, free known zero and unknowns.
Do not change token/API-dollar accounting or imply actual per-project billing.
Align captured account-wide balances with hourly allowance on the same UTC domain.
Read all retained prospective captures, including missing placeholders; preserve
exact Decimal net changes and original endpoints across day/window/reset bounds.
Cross-boundary intervals are unallocatable, never prorated or assigned to an hour.
Invalid/missing/unlimited/plan-discontinuous adjacency is unknown. Increases are
possible reload/grant/refund/adjustment evidence, not negative spending. Neither
hasCredits nor exhaustion proves a particular event's funding.

Cold preparation reuses calendar valuation, queries/values only the missing
observed-window union using the ledger timestamp index, and reuses one continuity
index, then stores revision-bound scope/day/project/evidence partitions. No
window x history valuation or warm historical decode/fit/materialize/reprice/scan.
Measure added cold cost honestly against v2.11.1 and the accepted candidate.
Include an explicitly scaled long-history Today comparison, not just tiny data;
never value years before any weekly evidence merely to prepare Today.
Expand domain/HTTP/host/browser/native gates to six metric/view combinations,
dated scopes, no-current evidence, exact balances and zero warm window work.
Existing release/product/Windows/native-Tab gates remain; no version or install.

## Experience

- Compact controls: Hour / Project, Tokens / API cost / Estimated credits,
  and observed weekly window / Selected range.
- Hour: stacked hourly bars with Model / Project stack grouping; default to
  API-equivalent cost stacked by model for the current reset window.
- Project: ranked horizontal totals stacked by model for the selected interval.
- Selecting an hour reveals project-by-model detail with tokens, cost and estimated credits.
  Selecting a project reveals its hourly pattern.
- An aligned percentage chart below Hour view shows captured allowance remaining
  on the same time domain, not a dollar/percentage dual-axis overlay.
- Retain full-range context, readable axes and responsive bounded detail windows.
  Do not reproduce the speed chart's hidden-axis or misleading-range defects.

## Evidence Contract

Reuse trusted, already-valued event summaries; do not introduce another pricing
pipeline or infer quota from raw token totals. Tokens include cached input and
free included reviews. API-equivalent dollars are not subscription charges.

Actual allowance is account-wide and must remain so under project/model filters.
Clearly distinguish captured meter readings from cost-calibrated estimates.
Reuse compatible current/previous allowance references and established full-meter,
reset, plan, coverage and unknown-cost boundaries. Credit-funded usage must not
reduce the included-allowance estimate. Unknown/excluded monetary values are not
zero. Missing local usage or snapshots must not imply complete account coverage.

Prefer composition bars over a waterfall: empirical quota attribution does not
form an exact additive bridge to the captured balance. Estimated contributions
may be useful, but cannot be labeled exact per-project/model quota spending.

## Implementation Planning Before Coding

1. Bind reset-window bounds to verified allowance history and define behavior
   when the actual opening timestamp or readings are unavailable.
2. Define the indexed hour/project/model aggregation and cache identities;
   preserve monetary parity and warm ledger-only reports.
3. Specify filter scope, drill-down/navigation commands, empty/partial coverage,
   unknown-price and credit-funded states under the existing script-free host.
4. Validate the primary flow with representative synthetic fixtures before
   expanding it; test additive totals, DST, reset crossings, saturation, credits,
   keyboard navigation and wide/narrow rendering.

## Initial Implementation Decisions

- Default to Current observed window when available; offer all dated observed
  historical weekly portions and an explicit Selected range that follows the
  dashboard's range. Never silently change the global date filter.
- Identify the current weekly series from captured allowance evidence. Use
  verified continuity/reset boundaries; when the opening is unobserved, label
  the observed portion and do not invent a zero-usage opening or subtract the
  nominal seven-day duration from the deadline. Missing weekly evidence must
  leave selected-range usage and retained historical portions available, with
  current allowance explicitly unavailable.
- Use one local calendar day of hourly detail, initially the latest observed
  day, plus a full-range daily overview and validated Previous/Next/Latest
  navigation. Preserve repeated/skipped DST hours and fixed visible axes.
- Rank projects by the active metric. Show the top ten plus an inspectable
  Other group; grouping must preserve exact sums and never hide detail rows.
- Show actual captured allowance points on the aligned time axis. Do not
  interpolate an exact balance, connect across unsupported resets, or imply
  per-project meter ownership when usage is filtered.
- Estimated percentage-point contributions may appear in drill-down only
  when an existing compatible, capture-causal calibration supports the exact
  interval. Full-meter/credit-funded cutoffs, unknown costs, incompatible
  plans/reset series and incomplete coverage make the estimate unavailable.
  No exact per-project quota attribution or estimated replacement meter.
- Keep navigation and drill-down within the existing script-disabled host,
  with exact argument, scope, date/hour/project and stale-command validation.
- Prepare trusted valued summaries once per relevant revision and reuse
  indexed summaries for view/metric/group/drill-down changes. No second pricing
  policy, report-triggered source scans, or warm-control monetary repricing.
  The scope directory contains bounds/identity only; each active-window summary,
  day and project are separate partitions. Current alias reuses its observed
  historical window composition rather than repeating aggregation.

## Delivery Gates

Record the durable data/scope/evidence contract in an ADR before integrating
the feature. Verify full/indexed monetary parity, additive composition totals,
unknown/free-credit semantics, causal/reset boundaries, transitions, DST and
zero warm-control historical work. Exercise all six metric/view combinations, both stack groups,
drill-downs, empty/partial states, keyboard paths and wide/narrow layouts with
synthetic data, then real native script-disabled command links. Preserve the
live ledger, installed extension, Keychain, services and unrelated `apps/`.
Leave a reviewed implementation candidate for release approval; do not tag or
publish Marketplace packages as part of this kickoff.

## Initial Verification (62b72c29; Superseded By Review Fixes)

These checks passed on the original candidate but missed the manager/reviewer
reproductions below. Their historical observations are not acceptance of the
corrected candidate or proof that its additional cold cost was pre-existing.

- Implemented candidate: partitioned revision-bound valued composition,
  chronological local-hour occurrences, cycle/selected scope, fixed visible
  axes, model/project groups, project ranking/Other and native command controls.
- Proven: focused composition/cache/domain and authenticated HTTP tests, independent UTC
  sampling across Toronto/Lord Howe/Chatham DST, monetary baseline markup parity,
  unknown/free-review separation, expiry/rebase/multi-series, slot aliases,
  exact-interval/series/capture-availability calibration and strict commands.
- Proven: full Python suite 1,665 passed, one Windows-only native-junction skip;
  Ruff and diff whitespace checks passed; extension tests/build 38 passed.
- Proven: 252 script-disabled Chromium/WebKit/Firefox views across Day/Night
  and 1440/760/360 widths, four modes, both hour groups, scope changes, Other,
  drills, empty filters, stale anchors and partial coverage. Fixed-font visible
  axes, section/control overflow and exact-table keyboard disclosure checked;
  representative wide/narrow screenshots inspected.
- Proven: isolated macOS VS Code OOPIF DOM acceptance, 14 rendered inputs
  (13 recorded mouse activations and one real Enter), strict host rejection,
  scripts disabled and unchanged restrictive CSP. Keyboard focus originated
  through CDP DOM.focus, not demonstrated native Tab traversal. Disposable
  HOME/CODEX_HOME/profile and in-memory secret storage; fresh local bundled
  binary; startup used synthetic RPC only and settled before rendered clicks.
- Proven: read-only SQLite backup to a disposable home retained actual-baseline
  API-dollar, token, unknown/excluded and standard-credit totals. Live account
  values and identifying contents are absent from tracked evidence. Reports,
  cache writes and synthetic captures ran only on disposable homes/copies.
- Observed, not a benchmark or rollout-causality claim: final private copy took
  1.23 s; cold all-time report 56.59 s, including derived preparation 4.44 s;
  warm report 0.347 s and mode/metric/group controls 0.175-0.212 s. Synthetic
  cold report 0.097 s, warm report 0.0069 s, controls 0.0033-0.0087 s.
  Forbidden historical preparation/materialization/decode/fitting/repricing
  guards passed for warm controls, including day/project/hour navigation in
  focused tests. All-time HTML remains approximately 5.98 MB on this baseline;
  cold preparation and large existing report size remain material limitations.
- Diagnostics retained locally: initial native startup capture/status ordering,
  OOPIF Tab focus and screenshot node-lifetime failures. Startup now settles
  against synthetic RPC; newer rendered revisions survive older cached status;
  freshness/deadline expiry refreshes without ledger mutation; screenshot nodes
  share one DOM lifetime. Final native repeat passed after these root fixes.
- Gated: independent manager review, product acceptance, release approval and
  publication. Native Windows acceptance was not run; its junction test remains
  skipped on macOS. Exact-interval contributions deliberately remain unavailable
  for arbitrary intervals without an established compatible reference; no real
  per-project quota attribution is claimed. No version bump, tag, install or
  release run occurred. Retained main checkout and unrelated apps/ preserved.

## Verification Entrypoints

Run from the retained repository root; output stays ignored and local:

```sh
uv run pytest -q -rs
uv run ruff check .
npm --prefix extensions/vscode test
uv run python scripts/check_usage_breakdown_ui.py --output output/playwright/usage-breakdown/review-ui
bash scripts/build-agent-macos-arm64.sh
uv run python scripts/check_usage_breakdown_webview.py --output output/playwright/usage-breakdown/review-native
```

The baseline script `scripts/check_usage_breakdown_baseline.py` requires an
explicit `--ledger` path; it opens that ledger read-only and deletes the private
disposable copy after verification. Use an ignored `--output` path, never a
tracked data fixture. Semantics are recorded in ADR 0054. No schema migration
was introduced; partitions use the existing disposable rendered-report table.

Final local evidence: `output/playwright/usage-breakdown/review-ui/evidence.json`,
`review-native/evidence.json` and `private-review-baseline.json` under that same
directory. Browser PNGs are named by scenario/width; native PNGs by input number.
Failed-attempt diagnostic directories are retained there for manager inspection.

## Manager Review Corrections (2026-10-09)

- Implemented: optional-duration evidence no longer enters a mixed int/None
  tuple comparison. Weekly plots have explicit series/plan legends and weekly
  unavailable states; missing-duration and nonweekly readings remain exact raw
  evidence. Selected-range mixed/missing/5h full-report regressions pass.
- Implemented: named capture-causal `(origin, capture]` composition excludes
  opening events and includes closing events, including exact hour/day bounds.
  SQL microsecond padding is separate from display/calibration endpoints.
  Genuine valued-ledger/estimator cycle and one-hour renders now show compatible
  contributions; unknown/full-meter cases remain unavailable. Selected-range
  calendar membership retains baseline parity and does not borrow incompatible
  right-closed calibration. Independent UTC sampling guards partial/repeated DST.
- Implemented: fixed-font sparse HTML ticks align with actual chronological
  daily/hourly/meter geometry, secondary ticks hide on narrow displays, and
  hover/accessibility names carry dated project/model/value context. Complete
  day/hour commands remain inspectable disclosures. Bounds no longer show SQL
  microsecond padding; accounting prose is progressively disclosed.
- Implemented: expiry binds issued evidence, not the command's target basis.
  Authenticated HTTP distinguishes typed expired issued scopes (409) from
  malformed/unissued inputs (400). Host permits one typed bare-report recovery
  for midnight, timezone, transition, freshness and revision changes, preserving
  global filters. Reload clears chart state; older cached status cannot discard
  a newer rendered scope. Authenticated TypeScript transport regression passes.
- Implemented: receipt hashes survive ordinary old-report pruning under their
  own bounded 256-scope/24-hour policy. They never authorize stale composition
  reuse. Post-pruning two-client HTTP regression and cap/TTL tests pass. No new
  ledger schema or package version was introduced; see ADR 0054.
- Proven after corrections: full suite 1,677 passed with one pre-existing
  Windows-only junction skip; extension tests/build 47 passed; Ruff and diff
  whitespace passed. Final hover-label change additionally passed 28 focused
  domain/HTTP tests and the final browser/native repeats.
- Proven after corrections: 360 script-disabled Chromium/WebKit/Firefox views
  at 1440/760/360 widths, Day/Night, four modes/groups/drills, 30-day context,
  Chatham partial-hour and Toronto repeated-hour days, empty filters, stale/
  partial coverage, missing-duration/5h-only and multiple-weekly-series states.
  Tick geometry, fixed fonts, collision-free labels, same hourly/meter domain,
  dated hover/accessibility names and visible weekly legends were asserted.
  Wide/narrow screenshots were inspected; exact rows and commands remain.
- Proven after corrections: fresh macOS bundled-agent/isolated VS Code replay
  passed 14 rendered inputs with strict OOPIF CDP DOM, real mouse/Enter, no
  product scripts or CSP relaxation. Hour disclosure was opened with real
  input before drill-down. Native Tab traversal and Windows remain unproven.
- Proven after corrections: controlled `v2.11.1` comparison on one identical
  disposable SQLite backup, fixed clock, timezone, selection and accounting
  settings; both Today and all-time retained byte-identical base HTML. Each
  copy discarded rendered/speed/allowance report caches but retained the same
  pre-existing cost index. Release source came from tag commit
  b2eb6f02542be2a1aab1952bcad5ea5cde062aa6, extracted into a temporary directory,
  not a branch/worktree. Final trial ran without concurrent owned verification
  jobs; existing real services/windows were not stopped or changed.
- Observed paired performance, not benchmark/causal rollout evidence:

  | Component (seconds unless bytes) | Today release | Today candidate | All release | All candidate |
  | --- | ---: | ---: | ---: | ---: |
  | Cold total | 6.288 | 8.389 | 38.276 | 41.123 |
  | Base report, inclusive | 5.989 | 5.835 | 37.893 | 37.355 |
  | Derived preparation | n/a | 1.956 | n/a | 2.906 |
  | Quota evidence preparation, nested in derived | n/a | 1.828 | n/a | 2.159 |
  | Composition, nested in derived | n/a | 0.010 | n/a | 0.578 |
  | Final derived HTML rendering | n/a | 0.0033 | n/a | 0.0033 |
  | Derived cache write | n/a | 0.401 | n/a | 0.416 |
  | Warm report | 0.045 | 0.141 | 0.043 | 0.141 |
  | HTML bytes | 3,638,343 | 3,807,405 | 5,240,689 | 5,409,751 |

  Nested components overlap and must not be summed. Candidate warm controls
  were 0.131-0.151 s (Today), 0.131-0.142 s (all-time). Additional cold work is
  primarily the breakdown's second quota-history extraction/continuity
  preparation, composition and cache serialization/write layer, not monetary
  chart rendering. The base also has its own allowance preparation and full
  materialization cost; timing differences in this pair do not prove invariant
  baseline performance. This feature adds measurable cost; it is not dismissed
  as pre-existing. Warm synthetic forbidden-work gates remain zero, including
  navigation/drills. Further cold-history reuse is a potential optimization,
  not an acceptance claim or a new pricing policy in this candidate.
- Evidence for this corrected source is local and ignored under
  `output/playwright/usage-breakdown/`: `review-fixes-accepted-ui/evidence.json`,
  `review-fixes-accepted-native/evidence.json`, and
  `review-fixes-serial-controlled-perf.json` (includes Python source fingerprint,
  component timings and base-HTML parity hashes). Screenshot names retain
  scenario/width and native input number. Prior failed attempts remain local.
- At worker handoff, still gated: independent manager acceptance, native Windows proof, product
  acceptance, version/release approval and publication. Sole worker writes;
  manager/reviewer remain read-only. No live writes/capture/install/Keychain or
  unrelated apps/ changes.

Corrected verification scripts are the same UI/native entrypoints above with
the corrected output paths. The controlled performance entrypoint is
`scripts/compare_usage_breakdown_perf.py --ledger <explicit-ledger> --output
<ignored-evidence-path>`; its only live ledger access is one read-only backup,
and all reports/cache mutations run on temporary copies. It records nested
components separately rather than subtracting derived time from a total to
claim an unchanged base.

## Manager Acceptance (2026-10-09)

Reviewed candidate `c40df6c63a14a5af8f4a23292cdfda55cc79cece` is accepted for
the next release stage. The missing-duration, causal-interval, visual-axis and
scope-recovery findings, including post-pruning issued commands, are addressed.
The committed Python source matches the controlled-comparison fingerprint.

Manager verification: 28 focused domain/HTTP regressions; full Python suite
1,677 passed with one expected Windows-only junction skip; 47 extension
tests/build; Ruff and whitespace checks. The nine-case synthetic comparison
against v2.11.1 retained exact monetary, image, repository and full/indexed
allowance parity. Inspected corrected chart evidence includes 30-day context,
repeated-hour days and explicit multiple-weekly-series legends. The worker's
360 browser cases and 14 native inputs retain their stated evidence boundaries.

Measured added cold preparation and cache-write cost is accepted as a disclosed
candidate limitation, not as an invariant baseline or performance improvement.
Native Windows and native Tab traversal remain unproven. No version bump,
release CI, tag, publication or installation was performed for this candidate.
The worker completed, was archived, and its Relay route was removed after
review. Retained main and unrelated apps/ are preserved.

## Extension Candidate Verification (2026-10-09)

Sole-worker extension on retained main, without a new branch/worktree. Reviewed
calendar default-day correction passed independent review: Month opens Oct9 from
usage/account-wide captures, keeps Oct1-Nov1 bounds, and singleton midnight stays
on its observed day. Mixed-offset chronology and backwards-origin raw membership
regressions preserve points while prohibiting invalid deltas. Missing/unlimited
states expose Unknown axes, not false zero; small movement on large balances is
visible without interpolation. No live ledger or private backup was used.

Final Python fingerprint (sorted `src/codex_usage/*.py`, filename + NUL + bytes):
`08ba2a6f071f502f5cfcbbc2411b882521b35c13ec34216cead12c5285817a9a`.

- Focused domain/HTTP/indexed-union tests: 58 passed. Full Python: 1,707 passed,
  one expected Windows-only junction skip. Ruff and whitespace checks passed.
- Extension build and 48 host tests passed, including strict issued/forged/expired
  commands, one recovery and stale cached-status behavior. macOS agent rebuilt.
- Script-disabled Chromium/WebKit/Firefox: 540 checks, Day/Night, 1440/760/360,
  six metric/view combinations, groups/drills, dated windows, Month, DST,
  unknown/unlimited and large-balance cases. Shared fixed visible time axes and
  keyboard disclosures passed. Wide/narrow screenshots inspected.
- Disposable native VS Code replay: 17 real mouse/Enter inputs, including dated
  prior window and credits, restrictive script-disabled CSP, synthetic RPC only,
  in-memory secretstorage and isolated profiles. Native Tab/Windows are unproven.
- Nine frozen synthetic range/project cases retained exact v2.11.1 language,
  monetary, image, repository and full/indexed allowance parity. Additional
  synthetic breakdown totals preserved tokens/API cost/estimated credits.
- Warm guards prohibit preparation, historical decoding, materialization,
  repricing and fitting, including historical window switches. The directory has
  no composition bodies; only the active summary/day/project partitions load.

Scaled fixture: 210,240 events, 24 projects, 729.41875 days, ten weekly captures
in the last ten days. Generated with the existing extended fixture (`days=730`,
`projects=24`), seeded baseline cost index, identical disposable SQLite copies.
Serial paired observations against released v2.11.1 and accepted `c9a7be13`:

| Seconds | Today release | Today accepted | Today extension | All release | All accepted | All extension |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Cold total | 0.2331 | 0.2825 | 0.2878 | 15.7072 | 19.1099 | 19.1665 |
| Derived preparation | n/a | 0.0295 | 0.0348 | n/a | 2.0840 | 2.0875 |
| Derived cache write | n/a | 0.0219 | 0.0239 | n/a | 0.6380 | 0.7475 |
| Warm report | 0.0012 | 0.0239 | 0.0243 | 0.0084 | 0.0353 | 0.0361 |

Today extension queried/valued 1,152 additional union records versus accepted
864, not all 210,240 events. All-time reused selected valuation with no additional
record query/value work. Warm derived record/preparation work was zero; dated
switches took 0.0245-0.0248 s Today and 0.0352 s all-time. Nested times overlap;
do not sum them or infer causal speedups from these single observations. Added
cold preparation/cache-write cost remains real, especially all-time cache writes.
This is scaled synthetic evidence, not live-account or dense multi-year capture
validation; the smaller synthetic fixture is reported separately.

Final-source ignored evidence under `output/playwright/usage-breakdown/`:
`extension-final-ui/evidence.json`, `extension-final-native/evidence.json`,
`extension-final-released-parity.json`, `extension-final-synthetic-parity.json`,
`extension-final-scaled-perf.json`, `extension-final-small-perf.json`.
Use the existing UI/native/parity/performance entrypoints; comparison adds
`--accepted c9a7be13 --synthetic` to explicitly distinguish synthetic evidence.
Pending: manager acceptance retests, human product acceptance, native Windows/Tab
proof and separately approved release/publication. No version/tag/release/install,
live service/tunnel/Keychain mutation, historical credit backfill or apps/ changes.
Worker remains available for review fixes; manager owns archival/Relay cleanup.
