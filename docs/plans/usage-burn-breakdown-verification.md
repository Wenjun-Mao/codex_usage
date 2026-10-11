# Usage Breakdown Verification History

Historical technical verification of the unpublished candidate before the
2026-10-09 human preview feedback. Counts and acceptance statements below are
bound to their recorded revisions, not acceptance of the proposed unified chart.
The active scope, approval gates and next deliverables live in
[Usage And Allowance Breakdown](usage-burn-breakdown.md).

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
Manager found Decimal general-format trailing zeros clipping the fixed axis
gutter, also affecting large-token general-format ticks. Shared compact numeric
formatting now covers usage/balance/change axes, with explicit common offsets
for collapsed large/small ranges and exact titles. Refreshed evidence below uses
real text-range containment guards, without widening or hiding axes.

Final Python fingerprint (sorted `src/codex_usage/*.py`, filename + NUL + bytes):
`7e0461b92a5d8706f195d3489bdc410d68d1e5c0cff57119e47b92a0c817204f`.

- Focused numeric/domain/HTTP/indexed-union tests: 74 passed. Full Python: 1,723 passed,
  one expected Windows-only junction skip. Ruff and whitespace checks passed.
- Extension build and 48 host tests passed, including strict issued/forged/expired
  commands, one recovery and stale cached-status behavior. macOS agent rebuilt.
- Script-disabled Chromium/WebKit/Firefox: 612 checks, Day/Night, 1440/760/360,
  six metric/view combinations, groups/drills, dated windows, Month, DST,
  unknown/unlimited, large/tiny/max-valid balances, signed changes and 182M/546M
  token scales. Actual text-range bounds fit every numeric span and padded gutter;
  fixed shared time axes and keyboard disclosures passed. Screenshots inspected.
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
| Cold total | 0.3186 | 0.3065 | 0.3018 | 17.8565 | 21.6385 | 21.0399 |
| Derived preparation | n/a | 0.0305 | 0.0348 | n/a | 2.3572 | 2.1677 |
| Derived cache write | n/a | 0.0231 | 0.0250 | n/a | 0.7615 | 0.7933 |
| Warm report | 0.0030 | 0.0246 | 0.0258 | 0.0090 | 0.0366 | 0.0364 |

Today extension queried/valued 1,152 additional union records versus accepted
864, not all 210,240 events. All-time reused selected valuation with no additional
record query/value work. Warm derived record/preparation work was zero; dated
switches took 0.0368-0.0440 s Today and 0.0347-0.0353 s all-time; warm controls
took 0.0336-0.0544 s Today and 0.0299-0.0350 s all-time. Nested times overlap;
do not sum them or infer causal speedups from these single observations. Added
cold preparation/cache-write cost remains real, especially all-time cache writes.
This is scaled synthetic evidence, not live-account or dense multi-year capture
validation; the smaller synthetic fixture is reported separately.

Final-source ignored evidence under `output/playwright/usage-breakdown/`:
`axis-format-accepted-ui/evidence.json`, `axis-format-accepted-native/evidence.json`,
`axis-format-released-parity.json`, `axis-format-synthetic-parity.json`,
`axis-format-scaled-perf.json`, `axis-format-small-perf.json`. Earlier
`extension-final-*` evidence remains retained but precedes the axis correction.
Use the existing UI/native/parity/performance entrypoints; comparison adds
`--accepted c9a7be13 --synthetic` to explicitly distinguish synthetic evidence.
Pending: manager acceptance retests, human product acceptance, native Windows/Tab
proof and separately approved release/publication. No version/tag/release/install,
live service/tunnel/Keychain mutation, historical credit backfill or apps/ changes.
Worker remains available for review fixes; manager owns archival/Relay cleanup.

## Extension Manager Acceptance (2026-10-09)

Candidate `60da7daf991f738c29912c697da333f69527cc75` is accepted for the
next release stage. Historical observed portions, estimated Standard credits,
account-wide captured balances and original net-change intervals preserve their
separate evidence contracts. The independent review's Selected-month navigation
finding and the manager's numeric-gutter finding are corrected with regressions.

Manager repeated the full Python suite: 1,723 passed, one expected Windows-only
junction skip; Ruff, 48 extension tests/build and whitespace checks passed.
Nine synthetic range/project cases retained exact v2.11.1 monetary, language,
image, repository and full/indexed allowance parity. An independent 36-view
Chromium/WebKit/Firefox check at 360/760/1440 verified actual numeric text-range
containment and distinct offset ticks for extreme balances, with scripts disabled.
Final narrow screenshots for large balances and realistic large-token scales
were inspected. The committed Python source matches the scaled-comparison
fingerprint above. The worker's 612 browser checks and 17 native inputs were
reviewed with their stated synthetic and native-input boundaries.

Disclosed cold preparation/cache-write cost remains an accepted limitation,
not a speedup claim. Dense multi-year capture performance, live-account behavior,
native Windows and native Tab traversal remain unproven. No version bump,
release CI, tag, publication, installation or live-state mutation was performed.
The implementation worker and read-only reviewer completed, were archived, and
their Relay routes were removed after review. Retained main and unrelated apps/
remain unchanged outside this assignment.

## Unified Chart Manager Acceptance (2026-10-09)

The revised candidate is implemented and technically verified on retained main
at `aedd9db4481841962762aba8a86f241d4d48ebc4`, with uncommitted changes and version
2.11.1. Human product acceptance remains open. No commit, version bump, release,
installation replacement, fresh live-ledger backup or live capture was performed.

Independent review found a historical-only project drill that could fail its
selected-range label lookup. Command issuance now requires selected-range
membership; historical-only rows retain exact evidence without invalid drills.
The Oct9 selection / Oct8-only project regression passes. The Firefox endpoint
glyph overshoot is fixed at tick alignment, not hidden by smaller text or axes.
ADR 0054 records the unified calendar/view contract and cache revision 5.

- Manager full Python suite: 1,736 passed, one expected Windows-only junction skip.
  Ruff, whitespace checks, extension build and all 48 extension tests pass.
- Fresh script-disabled browser matrix: 720 cases across Chromium/WebKit/Firefox,
  Day/Night and 360/760/1440 widths. Actual glyph containment, fixed axes,
  noncolliding ticks, shared coordinates, details, DST, unknown/extreme balances,
  dense history and reversible grain/project/overlay controls pass. Screenshots
  were inspected. Batched DOM reads preserve every per-mark assertion; the
  earlier slow, interrupted matrix is retained but is not accepted evidence.
- Disposable native macOS VS Code: 21 actual mouse/Enter transitions pass,
  including strict issued commands and unchanged script-disabled CSP. Native
  Windows and native Tab traversal remain unvalidated.
- Frozen-data controlled comparison against released `v2.11.1` and accepted
  `60da7daf991f738c29912c697da333f69527cc75` preserves byte-identical base HTML
  for Today and All Time. Input is the older private preview snapshot, not a
  fresh live-ledger backup. The clock is fixed at 2026-10-09T14:50:00Z, each copy
  starts with the same cost index and cleared derived caches, and each sampled
  drill obtains a fresh issued command. Warm derived preparation calls are zero.

Controlled timings are observations, not a speedup claim. Today candidate cold /
warm is 14.27s / 0.241s versus accepted 13.17s / 0.601s; All Time is 44.66s /
0.582s versus 40.54s / 0.608s. Candidate All Time whole HTML is 14.60 MB versus
9.76 MB, retaining mandatory boundary evidence rather than imposing a hard
point cap. Actual compiled AgentClient replay preserves the large response;
that transport check is not renderer-latency proof.

### New Frozen Local Preview

The new owned Codex Usage Local Preview is open from ignored
`output/local-preview/20261010T023718Z/`. It starts and ends at Last7, all projects,
Daily, API cost, model stacks and account-wide weekly allowance. The original
frozen live capture is Oct9 10:39:10 EDT; the copied older preview's later startup
timestamp is not a newer live capture. The old preview directory is retained.

The rebuilt collector's actual running PID is checked through `sandbox_check`:
both reads and writes are denied for the live ledger, live collector settings,
Keychain files and old preview snapshot. Live settings hashes are unchanged.
HOME, CODEX_HOME, extension directory, user data and settings are distinct;
scheduled capture is disabled, sessions are empty and the offline RPC returns
unavailable. Normal startup reads zero task-source bytes and adds exactly one
unavailable credit observation. All original normalized usage, image, speed,
quota and credit records retain their baseline hashes. No task logs, auth files,
runtime keys or live configuration are copied. Electron's renderer sandbox and
in-memory secret storage remain enabled; the product collector binary is unchanged
by the host-only launch wrapper.

Nine actual rendered-control transitions pass in the frozen-data preview: Tokens,
Hourly, Credit balance, Projects, a project drill, All projects, Weekly allowance,
API cost and Daily. Final state equals initial state, with exactly one time SVG
and no obsolete context/picker plots; project view uses the same area for ranks.
Actual initial/token/hourly/balance/project/final screenshots were inspected.
The private replay binds the owned CDP endpoint and single rendered chart because
its host-only wrapper has `nullExtensionDescription`; normal native extension
acceptance is separate. The report is nested inside the wrapper document, so
state readback uses pierced DOM discovery plus cached node attributes. The first
deadline-limited replay and root-document-selector attempt are not accepted
evidence; the complete replay and its nine assertions are retained.

Actual owned-service observations: Last7 whole HTML 9.42 MB, warm requests
0.40-0.42s; Last30 whole HTML 12.51 MB, uncached request 22.20s and repeat 0.612s.
Last7/30 retain 12,239/18,493 mandatory boundary marks respectively. These are
request/render observations, not user interaction latency or a speedup claim.
Dense history and cold loads remain disclosed limitations, not silently merged
evidence. Estimated Standard credits remain distinct from observed balance debits.

### Source And Evidence Identity

Python filename-NUL-content fingerprint:
`3d25900707bac63208d8da8ee8c9877588226ad03da6f294fe4a91f36865000c`.
Built macOS collector SHA-256:
`59a72846315aa243dc334882b4e1eaa8dc03aac859f7b71433da506b86c89901`.
Preview launch manifest:
`7fa9b4e309324807b2f7ed7f598495f1a8d55d5c29716a44c524b826709029ac`.
Final acceptance manifest:
`e198113daf5efb3f795b6db89553c2d404da76e60892623558d88f47f5ce5cbe`.
Only the active plan's completed-status text differs between those manifests;
all product, test, script and build-input hashes match. Manifests use sorted
compact JSON path/digest hashes, distinct from the Python fingerprint. The
verification-history file is excluded so acceptance evidence does not alter
the frozen candidate. Copied compiled-extension and binary hashes also match.

Ignored manager evidence under `output/playwright/usage-breakdown/`:
`unified-manager-ui-batched/evidence.json`, `unified-manager-native/evidence.json`,
`unified-manager-controlled-final.json`, `unified-manager-identity-final.json`,
`unified-manager-acceptance-identity.json`. The new private preview retains
`snapshot.json`, `verification.json`, `range-measurements.json`,
`ui-verification.json`, screenshots, launch/stop entrypoints and README.

Implementation and read-only review agents completed, were collected/reviewed
and closed, and both Relay routes were removed. No worker remains unattended.
Unrelated `apps/`, normal VS Code, installed extension and live collector remain
untouched. Next gate is the user's review of this new preview; release requires
separate authorization. Live-account behavior, native Windows/Tab input and
general historical-load optimization are not claimed by these checks.
