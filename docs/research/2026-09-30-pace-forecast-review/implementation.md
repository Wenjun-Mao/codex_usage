# Conditional Pace Candidate Evidence

The implementation follows the approved plan: signed Recent net rate and
exponentially weighted Daily interval rates, unchanged initial gates, six-hour
half-life, exact live endpoint and captured reset. ADR 0044 owns continuity,
expiry and cache contracts. Director review accepted the implementation through `a88be5b7`; human approval
for the 2.10.0 release was granted on 2026-10-01. This does not establish
predictive accuracy.

## Director Review And Durable Fix

Director review held the first candidate for two reproduced gaps: warm HTML
lookups decoded the complete historical allowance report, and each pace fit
rebuilt its full prefix. The 768-point benchmark and counters for raw quota
loading/pricing/fitting did not establish large-history performance or catch
cached-history decoding. Its timings are superseded by the large benchmark.

- Warm HTML identity now reads only a compact pace-state sibling row from the
  existing allowance-report cache. Its ledger/pricing/report/coverage key is
  exact, and both row variants are written atomically. Historical payload loading
  follows an HTML miss. Existing meter freshness and forecast expiry still use
  the injected clock. No table/schema migration or cost-index revision changed.
- A shared revision-scoped `PreparedPaceEvidence` index records causal continuity
  checkpoints and actual observation positions. Preparation includes active
  series and cross-duration plan events. Fits binary-search the active 24-hour
  suffix without visiting older evidence or resolving plans again. Old boundary,
  reset/credit and conflict state remains in checkpoints; future observations
  cannot rewrite earlier origins. The raw ledger and dollar path are unchanged.
- Preparation still processes history once per new report materialization,
  with one possible replay of a leading unknown run when its first known plan
  becomes available. It is shared across buckets, not persisted incrementally
  between revisions. Loading, preparation and uncached history rendering remain
  costs, explicitly separated below.

## Checks

- Pure tests retain reset/no-drop/credit/jitter safeguards, signed corrections,
  conflicts, recoverable suffixes, future exclusion, cross-duration plan changes,
  exact endpoints, gates, weighting, and nonpositive-rate refusal.
- Prepared results match the frozen full-prefix oracle over multiple generated
  histories and historical origins, including leading unknown bridges and
  future known plans. A 52,000-point guard rejects historical-prefix iteration
  and preparation during selection/fitting; raw-list fitting raises an error.
- Warm-hit guards use a multi-megabyte historical payload, SQL tracing, bounded
  decoding and a forbidden full-report loader. They cover freshness and stale
  meter transitions. Compact-key tests reject different ledger revisions,
  pricing identities and coverage, and retain pre-migration fallback.
- Existing view guards forbid JSONL opens, capture, probes, allowance pricing,
  evidence reconstruction and fits. Indexed/full equality preserves windows,
  qualified fits, headline/fallback and history exactly. No additional valuation
  pass was introduced; uncached general report valuation remains.
- Python: 1,371 passed, one existing Windows-only native-junction skip on macOS.
  Ruff passed. Extension: 28 tests passed with TypeScript build. Production
  screenshots/check and browser/expiry gates passed: 126 state/theme/viewport
  cases and 36 meter visual cases across Chromium, WebKit and Firefox, including
  Day/Night, 360px, keyboard access and no new overflow.
- Non-publishing macOS/Windows package, smoke, archive and disposable handoff
  checks run against the final commit; run URL and hashes are reported separately.

## Large Disposable Benchmark

Run `uv run python scripts/benchmark_allowance_pace.py`. It creates/removes a
synthetic Codex home with 10,000 usage events, 52,001 quota observations and two
active buckets; it never opens an installed ledger. One local run, not an SLA:

| Stage | Milliseconds |
| --- | ---: |
| Initial synthetic capture/rebuild | 625.5 |
| First indexed allowance report, total | 783.1 |
| Its existing allowance pricing, 10,000 events | 63.6 |
| Its quota evidence loading/expansion | 283.0 |
| Its shared causal preparation | 171.4 |
| Its selection plus fitting, both buckets | 0.128 |
| Its selection alone | 0.029 |
| First local HTML report after allowance materialization | 997.1 |
| Its historical report decoding | 29.4 |
| Warm same HTML view, total | 12.6 |
| Its compact state decoding | 0.017 |
| New theme/project view, total | 459.0 |
| Its historical report decoding | 29.5 |
| Quota-only update report, total | 837.8 |
| Its evidence loading | 404.4 |
| Its shared preparation | 215.3 |
| Its selection plus fitting, both buckets | 0.107 |
| Simulated upgrade allowance rebuild, total | 831.3 |
| Its one-time allowance repricing | 52.6 |

The historical JSON is 12,540,821 bytes; compact state is 1,711 bytes. Warm HTML
hits add zero historical payload decodes, evidence loads, preparations, fits or
allowance prices. New views still load/decode/render historical windows once.
Quota updates reprice zero events; simulated upgrades reprice all 10,000 under
the unchanged version/pricing coupling. Prepared latest/earlier-origin fits take
0.04–0.07ms in isolation. Selection/fitting meets the under-20ms target on this
workload; complete revision rebuilds clearly do not take under 20ms.

Raw per-phase timings and a separate read-only check against the frozen private
snapshot stay under ignored `output/research/pace-implementation/`. The private
check confirms full-prefix equality and sub-millisecond prepared fitting; no
corpus values are committed. UI/HTTP transport and end-to-end user latency were
not benchmarked. Warm totals include reading cached HTML and current status;
uncached HTML totals include existing usage valuation/query/render/cache work.

## Limits

No uncensored exhaustion outcomes exist in the calibration corpus. Conditional
arithmetic is verified; exhaustion accuracy and harmful-error rates remain
unidentifiable. Parsed/recovered evidence lacks complete historical availability.
Preparation is full-history work per materialized revision, and very dense data
inside 24 hours still increases fitting work: no samples are silently discarded.
No live ledger, installed extension, tasks or OS services were modified. Release metadata and publication follow the separately approved 2.10.0
release workflow; these measurement limits remain unchanged.

## Observed-Cycle Follow-Up (2.10.1, 2026-10-02)

The third Cycle row uses unweighted signed endpoints across the current coherent
suffix, including idle time, with an actual observed-span label. It does not
claim the reset start was captured. The independent read-only review supported
causal checkpoint endpoints, signed corrections and retaining long elapsed gaps;
the release keeps the existing Recent minimum gates. Code review found no
correctness defects; its suggested randomized summary coverage was added to
the committed full-prefix regressions. See ADR 0044 for the
boundary, left-censor and cache contract.

Local verification passed: 1,383 Python tests and one existing Windows-only skip,
28 extension tests/build, Ruff, screenshot generation/check, and 126 allowance
state/theme/viewport plus 36 meter cases across Chromium, WebKit and Firefox.
Day/Night wide and narrow screenshots and an isolated 360px allowance surface
were visually inspected. A local macOS VSIX build, collector smoke and archive
audit passed. Platform CI remains a separate pre-publication gate.

The expanded disposable benchmark uses the same 10,000 events, 52,001 quota
observations and two active buckets, plus a deliberately long coherent synthetic
cycle to exercise endpoint cost, not a realistic reset history. One local run:

| Stage | Milliseconds |
| --- | ---: |
| First allowance report, total | 733.5 |
| Shared causal preparation | 161.6 |
| Selection/fitting, both buckets and all three rows | 0.148 |
| Warm HTML view, total | 12.5 |
| Quota-update report, total | 797.2 |
| Long-cycle preparation, 52,000 observations | 160.1 |
| Prepared long-cycle fit, all three rows | 0.121 |

Warm HTML hits retained zero historical cache decodes, quota loads, preparation,
fits or allowance prices. Quota updates repriced zero events. Indexed/full
windows, headline and monetary history matched exactly; the frozen two-row
oracle guards unchanged Recent/Daily outputs. An endpoint-only access wrapper
forbids full-cycle slicing/iteration. Compact cache state was 2,651 bytes versus
12,541,761 bytes of historical payload in this fixture. Report/render revisions
advance to 4/21; cost index and schema stay unchanged. The existing version-based
pricing identity still causes one-time upgrade repricing.

These are local Python timings, not end-to-end VS Code latency or accuracy
claims. Hidden resets in observation gaps remain possible. No live ledger,
installed extension, task or OS service was changed.
