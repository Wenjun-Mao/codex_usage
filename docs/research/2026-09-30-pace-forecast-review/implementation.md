# Conditional Pace Candidate Evidence

The September 30 implementation follows the approved plan: signed Recent net
rate and directly exponentially weighted Daily interval rates, unchanged initial
gates, six-hour half-life, exact live endpoint and captured reset. ADR 0044 owns
the forecast-specific continuity and expiry contract. This is a candidate for
review, not release or a claim of predictive accuracy.

## Checks

- Pure tests cover strong/no-drop resets, retained metadata, small signed
  corrections, same-time usage/credit/plan/reset conflicts, recoverable suffixes,
  future-metadata exclusion, slot moves, plan changes reported by other duration buckets, exact live jumps, movement/span/count/gap
  gates, direct interval integration and nonpositive weighted rates.
- Injected-clock rendering/cache tests cover failed/partial, missing reset, stale,
  passed reset and prediction states, local midnight/DST, 15-minute rounding and
  small positive balances. Clock-state HTML invalidation reuses cached rates.
- Warm view regressions forbid source JSONL opens, capture, probes, allowance
  pricing, quota reconstruction and refitting. Existing general report valuation
  on a previously uncached view remains; pace adds no valuation pass.
- Indexed/full equality and a disposable synthetic monetary-path comparison
  preserve all windows, history, qualified fits and headline dollar outputs
  exactly. The dollar segmentation/estimation implementations are unchanged.
- Python: 1,365 passed, one existing Windows-only native-junction test skipped
  on macOS. Ruff and diff whitespace checks passed. Extension: 28 tests passed
  with TypeScript build. Offline calibration invariant checks passed.
- Production screenshot generation/check passed. Chromium/WebKit/Firefox:
  126 state/theme/viewport cases (Day/Night, 1440/760/360px), 36 meter visual
  cases including VS Code colors, keyboard disclosure and contrast checks.
  Pace rows wrap without page overflow and preserve disagreeing outcomes.
  Day/Night wide/narrow screenshots were inspected; additional 360px and wide
  allowance crops live in ignored `output/research/pace-implementation/`.
- Exact-candidate non-publishing macOS/Windows package, smoke, archive and
  disposable handoff checks run through `package-vsix.yml`; their result and
  artifact hashes are reported to the director separately after dispatch.

## Disposable Benchmark

Reproduce with `uv run python scripts/benchmark_allowance_pace.py`. It creates
and removes a temporary Codex home: 10,000 synthetic usage events and 768 quota
observations, never an installed ledger. Single local run, not a latency SLA:

| Stage | Measured milliseconds |
| --- | ---: |
| Initial synthetic capture/rebuild | 570.2 |
| First indexed allowance report, total | 90.2 |
| Its existing allowance pricing, 10,000 events | 50.1 |
| Its quota evidence loading/expansion | 3.3 |
| Its continuity selection | 3.2 |
| Its bounded rate/projection arithmetic | 0.12 |
| First local HTML report after allowance materialization | 575.9 |
| Same warm HTML view | 2.1 |
| Changed theme/project view | 74.4 |
| Quota-only update report | 19.1 |
| Simulated upgrade allowance rebuild, total | 87.3 |
| Its one-time allowance repricing | 48.4 |

Warm views added zero allowance prices, evidence loads or fits. Quota-only
updates repriced zero events; simulated upgrade repriced all 10,000, preserving
the existing release/pricing coupling. Rate/projection arithmetic and continuity
selection are separated; fitting including continuity stayed below the plan's
20ms target on this synthetic workload. HTML times include existing language
valuation/query/render/cache work. UI/HTTP transport and end-to-end user latency
were not benchmarked. Raw per-phase synthetic timings remain in ignored output.

## Limits

No uncensored exhaustion outcomes exist in the calibration corpus. Conditional
semantics and arithmetic are verified; exhaustion accuracy and false reassurance
or warning rates remain unidentifiable. Parsed/recovered evidence does not have
a complete historical first-availability record. This implementation did not
modify capture timing, live ledgers, installed extensions, tasks or OS services.
Publication, version bump and release acceptance remain outside this assignment.
