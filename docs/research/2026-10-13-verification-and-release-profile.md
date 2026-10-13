# Test And Release Profiling

Date: 2026-10-13. Status: baseline assessment plus measured local implementation.
Release authority: 2.12.2 at `11908ab947c4dc4eac9a991c144d8b6e1601ff35`.
The baseline assessment was read-only. Follow-up changes affect verification and
qualification tooling only; product accounting/rendering, deadlines, installed
extensions and live data remain unchanged. Hosted qualification is still pending.

## Method And Limits

Collected the complete local pytest suite with JUnit durations; profiled the
unchanged 720-case breakdown browser matrix; timed public synchronous browser
calls around their original implementations; and measured existing HTTP server
cleanup in 31 focused tests. Browser and lifecycle timers do not skip assertions
or replace behavior. Their small instrumentation overhead was not calibrated.
Local measurements are single runs on this Apple Silicon machine, not hosted CI
predictions. Async/greenlet switches made cProfile's per-API cumulative timings
misleading, so browser attribution uses explicit wall-clock timers instead.

Hosted timings come from the actual GitHub job/step timestamps and timestamped
stdout markers, not a new release. Reused jobs in preflight attempt 2 are excluded
from that attempt's executed-work accounting. Sequential visual-script intervals
include process startup; screenshot validation and allowance UI share one interval.

Raw JUnit, logs, workflow metadata, profiles, one-off diagnostic tools and
`summary.json` are retained, ignored, under `output/performance/test-release-profile/`.
Synthetic browser evidence is under `output/playwright/test-release-profile/`.

## Measured Costs

| Stage | Observed Time | Interpretation |
| --- | ---: | --- |
| Complete local Python suite | 65.7 s | 1,884 passed; one expected skip |
| Hosted Python tests, tag run | 166.5 s | Same test outcome; not the whole release bottleneck |
| macOS test/build/package step | 49 s | Includes 48 extension tests and bundled collector build |
| Windows test/build/package step | 41 s | Runs alongside macOS after core validation |
| macOS serial visual gate | 12m 05s | About 68% of the tag workflow's wall time |
| Complete 2.12.2 tag workflow | 17m 49s | Core, both packages, visual gates and publication |
| Complete 2.12.1 tag workflow | 14m 46s | Confirms this is not only this release's retry problem |
| Publication job itself | 23 s | Actual upload commands occupied about nine seconds |
| Publish-job completion to public verification marker | 7m 06s | Marketplace validation/propagation plus polling |

The 2.12.2 visual gate breaks down as follows:

| Sequential Interval | Time |
| --- | ---: |
| Screenshot validation plus allowance UI | 1m 48s |
| Observed-speed UI, 162 views | 2m 15s |
| Usage breakdown UI, 720 views | 6m 00s |
| Dense-overlay UI, 90 views | 1m 25s |
| Hover/focus UI, 72 views | 38 s |

The complete local breakdown wall-timer run took 141.3 seconds and retained all
720 cases across 40 scenarios, two themes, three widths and three engines.

| Browser Operation | Calls | Local Wall Time |
| --- | ---: | ---: |
| Locator evaluation | 6,696 | 32.1 s |
| Locator count | 4,932 | 22.6 s |
| Navigation | 720 | 18.2 s |
| Screenshots | 160 | 10.0 s |
| Viewport resize | 720 | 8.3 s |
| Real keyboard presses | 1,440 | 7.9 s |

The selected public browser APIs accounted for 21,112 calls. Evaluation and
count queries alone consumed 54.8 seconds, about 39% of this local run.
Screenshots are not the dominant measured cost. The matrix reloads the same
scenario/theme document for each width and sends many separate DOM queries.

The four largest Python modules contributed 22.63 seconds of per-test durations:
`test_breakdown_extension` 9.07 s, `test_breakdown_unified` 5.40 s,
`test_breakdown_navigation_work` 4.49 s and `test_usage_breakdown_api` 3.67 s.
These are valuable accounting, navigation and bounded-work tests, not disposable
coverage. The slowest individual test checks all warm window/metric/group/drill
paths and took 3.77 seconds.

A separate 31-test lifecycle sample passed in about 6.3 seconds. Eleven calls
to the unchanged `AgentHttpServer.stop()` consumed 5.44 seconds. The server uses
`serve_forever` with the standard library's default 0.5-second shutdown polling.
That explains the repeated roughly 0.5-second API tests, even though pytest labels
the waits as test-call time because shutdown is inside each test's `finally`.

## Why This Release Felt Especially Long

The interval from the first preflight request to the verifier's recorded public
validation marker was 62m 22s. It is not all test execution:

| Attempt | Time | Result |
| --- | ---: | --- |
| Initial metadata preflight | 2m 56s | Missing release-date registry entry |
| Corrected preflight, attempt 1 | 14m 18s | Late tooltip-hide guard failure |
| Failed macOS job retry, attempt 2 | 12m 08s | Passed; core and Windows reused |
| Tag qualification and publication | 17m 49s | Passed |

These attempts total 47m 11s. Investigation/fix/handoff gaps account for about
8m 06s; propagation/polling accounts for the remaining roughly seven minutes.
The metadata error was a release-preparation omission, not application runtime.
The tooltip failure's cause remains unconfirmed: two local checks, the unchanged
rerun and the fresh tag run passed without renderer or threshold changes.

The process deliberately qualifies the exact source SHA before tagging, but then
rebuilds and requalifies it on the tag. The macOS preflight and tag VSIX hashes
differed. Their embedded collector hashes also differed, requiring fresh native
verification of the final build. This is duplicated work, not proof that either
artifact is invalid. The tag artifact still matched both official downloads and
Marketplace declarations as recorded in the published receipt.

## Recommended Order

1. **Fail fast and make failures observable.** Run release metadata, lock and
   workflow-contract checks before the full suite. Split independent visual suites
   into separately required jobs so a 38-second hover check cannot force a complete
   package/visual rebuild. Upload bounded synthetic diagnostics even on failure:
   engine, case tuple, hover/focus state, screenshot and completed-case inventory.
   Investigate the hide flake with that evidence; do not loosen its threshold or
   add blind retries. This is the smallest initial workflow change.
2. **Build once, promote the qualified artifacts.** Replace the second full tag
   rebuild with a promotion gate that checks exact repository, source SHA, matching
   version/tag, approved workflow and run attempt, every required job's successful
   result, both platform manifests and immutable artifact IDs/digests. Publish those
   exact VSIX bytes, retain native qualification against their collector hashes,
   and keep public catalog/download hash verification. This could remove most of
   the observed 17-minute second pass, but needs a named artifact-authority contract
   and negative tests before it is trusted. No shortcut based only on a run ID or
   artifact name is acceptable.
3. **Reduce browser round trips without reducing coverage.** Batch related DOM
   snapshots while preserving every assertion. Trial one navigation per
   scenario/theme followed by viewport resize, with explicit focus/disclosure/scroll
   reset checks. Keep real keyboard and hit-testing actions. Compare full case tuple
   inventories, outcomes and bounded-work counters before accepting the change;
   a matching case count alone is insufficient.
4. **Pilot bounded parallelism.** Give independent browser suites/engines isolated
   jobs or bounded workers, rather than six serial programs on the packaging path.
   Keep the latency-sensitive hover gate isolated from resource-heavy neighbors.
   Record queue time, elapsed time and runner cost: extra macOS jobs can increase
   queueing. Pure UI tests need source/dependencies, not a completed bundled build;
   let them and full core tests overlap packaging after the fast metadata gate.
5. **Then tune Python and packaging.** Audit fixture reuse within the heavy modules,
   avoiding shared mutable ledgers, stale absolute paths or skipped capture paths.
   Consider conservative test shards after process/port/environment isolation review.
   Avoid the three TypeScript builds on each package path and the additional build
   during screenshot validation. Treat HTTP cleanup as a real lifecycle contract,
   not a hidden test-only fast-poll setting. These are smaller wins than promotion.

The two high-value structural changes are failure-local gates and immutable
artifact promotion. Neither requires dropping monetary, provenance, cross-browser,
platform smoke/archive, handoff or native UI evidence. Marketplace validation is
external latency: keep polling and hash checks; do not attempt to bypass it.
All proposed savings remain estimates until an exact-SHA pilot measures them.

## Local Implementation Results

Three alternating complete baseline/candidate breakdown pairs retained all 720
case/state tuples, 80 byte-identical report documents per pair and zero forbidden
warm historical work. Default navigation remains fresh.

| Measurement | Baseline | Candidate |
| --- | ---: | ---: |
| Wall pair 1 | 151.37 s | 96.80 s |
| Wall pair 2 | 150.13 s | 94.72 s |
| Wall pair 3 | 144.94 s | 95.29 s |
| Median complete gate | 150.13 s | 95.29 s |
| DOM evaluate/count queries | 11,628 | 720 snapshots |
| Query wall time, instrumented samples | 54.8 s | 7.93 s |
| Fresh navigations | 720 | 720 |
| Real keyboard presses | 1,440 | 1,440 |
| Screenshots | 160 | 160 |

The uninstrumented median is 36.5% lower on this machine. Instrumented samples
are attribution evidence, not paired speed predictions; candidate measurement
took 93.43 s, with timer overhead not separately calibrated. The candidate also
checks disclosure restoration after the second real Enter press.

A separate 720-tuple resize probe matched fresh DOM/layout snapshots and restored
focus, pointer, scroll and disclosure state across the three engines. It is not
pixel/native equivalence proof and has not replaced fresh navigation in any gate.

Local visual acceptance retains breakdown 720, speed 162, overlay 90, hover 72,
allowance 180 plus 36 painted-meter cases, and 15 screenshot/inspection cases.
The hover deadlines remain 250ms. An injected first-case failure retained the
exact tuple, original exception, DOM diagnostics and screenshot; aggregation
rejected the partial failed journal. Python collection/raw results and extension
test events reconcile with independent preserved-case inventories.
The final complete Python run passed 2,068 cases with exactly one expected
non-Windows junction skip in 64.66 seconds; all 2,069 unique collected identities
matched raw JUnit and preserved the independent historical baseline. Extension
qualification passed 48 cases; the early metadata gate passed 35. Ruff, frozen
monetary parity and bounded-work checks passed.

Early metadata and independent visual jobs, immutable original-attempt receipts,
exact-VSIX native inputs and explicit promotion are implemented as candidates.
No hosted normal/failure-retry/dry-run pilot or new release has run. Production
promotion is intentionally disabled: deleted later Actions runs can hide earlier
upload uncertainty from an older-run retry. Surviving run-number continuity is
an omission detector, not complete publication-history authority. An independent
durable receipt journal is a pending scope/qualification gate, not a solved risk.

Raw pair evidence remains under `output/performance/verification-efficiency/`
and `output/playwright/verification-efficiency/`; current visual/failure reports
are under `output/qualification/`. The reusable instrumented entrypoint is
`scripts/profile_visual_gate.py`; the bounded resize trial is
`verification.resize_probe`.

## Evidence And Reproduction

- [2.12.2 nonpublishing run](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38348832206)
- [2.12.2 tag run](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38351303141)
- [2.12.1 tag run](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38115502921)
- [Published receipt](../release.md#2122-published-receipt)
- Workflow ownership: `.github/workflows/package-vsix.yml`, especially the serial
  visual step and evidence uploads after it.
- Browser ownership: `scripts/check_usage_breakdown_ui.py` lines 141-219.
- Package build ownership: `extensions/vscode/scripts/package-vsix.js` and the
  extension's `test`/`vscode:prepublish` scripts.
- Lifecycle ownership: `src/codex_usage/agent_api.py` and `socketserver.serve_forever`.

```sh
uv run pytest -q --durations=0 --durations-min=0 \
  --junitxml=output/performance/test-release-profile/pytest.xml
uv run python -m cProfile \
  -o output/performance/test-release-profile/breakdown-ui.prof \
  scripts/check_usage_breakdown_ui.py \
  --output output/playwright/test-release-profile/breakdown
uv run python output/performance/test-release-profile/profile_browser.py
uv run python output/performance/test-release-profile/profile_api_cleanup.py
uv run python output/performance/test-release-profile/analyze.py
```

The last three commands use retained one-off diagnostic tools, not shipped APIs.
No CI run or new release was dispatched for the assessment or local follow-up.
