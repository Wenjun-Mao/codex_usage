# Collector Implementation And Controlled Experiments

Date: 2026-10-16. Status: local candidate and experiments, not qualified/published.
Plan: [collector performance and runtime evaluation](../plans/collector-performance-runtime-evaluation.md).

## Shipping Candidate

The separate 2.12.4 candidate retains Python 3.13 and the existing dependency
lock. The changes address the observed owning layers:

- Frozen `agent_main.py` calls `freeze_support()` before application imports and
  ordinary argument parsing. It does not tolerate child flags in the app parser.
- The refresh-only capture path propagates worker infrastructure/fallback stats.
- Project identity resolves lazily per effective metadata scope within one parse
  chunk. Every used identity is freshly checked at exit; changes reject/retry
  rather than committing cached attribution. No cache crosses a checkpoint.
- Package proof requires the real collector's HTTP startup, overlapping workers
  on twelve substantive files, zero fallback/errors, no-op/append equivalence,
  exact serial-oracle records and shutdown. Proof binds the shipped executable
  SHA-256 and platform; one-file smoke alone cannot qualify a package.

The released 2.12.3 failure evidence remains in the
[original investigation](2026-10-16-collector-performance-investigation.md).
Successful token totals in that release do not prove parallel execution.

## Paired Python Optimization Measurements

Ten alternating pairs plus an excluded preparation pair. CPython 3.13.12,
SQLite 3.50.4, same dependencies, generated twelve-file / 12,000-response corpus,
same selected byte progress and exact full-record hashes at each operation.
Both sides have the bootstrap correction; this isolates identity reuse.

| Backend operation | Corrected baseline | Identity reuse |
| --- | ---: | ---: |
| Cold capture | 3.033 s | 2.582 s |
| Unchanged capture | 0.020 s | 0.020 s |
| One appended response per file | 0.133 s | 0.131 s |
| 100 more responses per file | 0.395 s | 0.340 s |

Cold capture improves 14.9% (0.452 s) on this synthetic corpus. These source
timings exclude process launch, HTTP queueing, real quota RPC and WebView paint.
They are not a released-binary before/after comparison or a real-workload promise.
Parent CPU was recorded; child CPU and concurrent process-tree memory were not.
No dispatch threshold is shipped: earlier single-run tiny-append differences
do not meet the optional end-to-end benefit gate.

A separate post-optimization serial profile records 36 total repository
resolutions (0.012 s cumulative) rather than the earlier 12,012. Structural
projection remains material: 72,012 calls / 5.955 s cumulative out of 11.142 s
instrumented cold capture. Normalized-ledger synchronization is 1.868 s.
These nested diagnostic times are not unprofiled latency estimates. The Rust
trial preserves the same row-reader call graph, rather than claiming a gain
from removing duplicate Python work in only one configuration.

## Representative Report Measurement

A coherent private SQLite backup was made through a read-only source connection;
only disposable copies received cache/revision/report writes. It is approximately
1.72 GB. The fixed clock, input SHA, exact HTML hashes and raw samples remain
private under ignored `output/performance/collector-implementation/`.

| Backend operation | Corrected baseline | Identity reuse |
| --- | ---: | ---: |
| First Today report after revision | 8.900 s | 8.934 s |
| Switch Yesterday | 1.611 s | 1.615 s |
| Cached Today | 0.063 s | 0.064 s |

All ten pairs produced exact matching HTML and cache-hit states. The parser
optimization does not explain or improve first report loading. A separate
instrumented pass attributes most work to allowance history/preparation and
SQLite queries: 15.56 s cumulative in `indexed_allowance_report`, including
11.42 s in `_build_from_costs`, out of 21.92 s across three report operations.
Nested times overlap and must not be summed. Profiling inflates runtime; these
figures locate work, not predict savings. Roughly 897,000 JSON serializations
also appear in the profile. A broader report/history redesign is not included
in this candidate and remains a named follow-up.

One exploratory profile was started before its disposable copy finished and
failed with a malformed-copy error. It is excluded. A fresh completed copy
passed and produced the profile above; the frozen input was not changed.

## Runtime And Rust Status

Standard GIL-enabled Python 3.15.0 is installed only in the owned experiment
directory. A transient uv-created user shim/runtime was removed, then recreated
with explicit `--install-dir --no-bin --no-registry`; no default runtime remains
changed. B/C environments share Pydantic 2.14.1/core 2.50.1, PyInstaller 6.22.3
and hooks 2026.7. The old hooks pin was correctly rejected as incompatible;
the Pydantic exact core dependency was not overridden. Watchdog 6.0.0 built
from source on macOS 3.15. Subsequent hosted checks pass on Windows too.

Actual macOS frozen collectors built for current 3.13, common-dependency 3.13
and common-dependency 3.15. Each passed the new real HTTP/worker test and legacy
smoke in an external sandbox denying live home data, foreign processes and
outbound networking. Those local wrapper hashes are not qualified artifact
identities. Final source/package-bound qualification remains required.

The single hosted [runtime compatibility run](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38970001352)
passed all six jobs at source `b7b603e03a54d62d912a2dffc18df3cbf5b00652`:
A/B/C on macOS ARM64 and Windows x64. Independent readback validates every
retained collector proof against its executable hash and source, ordinary GIL
enabled / JIT disabled runtime identity, three overlapping workers on macOS
and four on Windows, 12,000 cold records with complete checkpoint progress,
independent serial oracles, and observed forced-timeout collector exit.
The watcher delivered an actual file event and joined shutdown on every host.
No rerun was needed. Total elapsed time was 8m 40s at two jobs concurrently;
individual jobs took 2m 7s to 3m 7s. These are compiled-collector compatibility
results, not full VSIX, native VS Code replay, release qualification or adoption.

Ten paired B/C measurements isolate the runtime/build from dependency changes:

| Operation | Common dependencies, 3.13 | Same dependencies, 3.15 |
| --- | ---: | ---: |
| Cold capture | 2.602 s | 2.542 s |
| Unchanged capture | 0.020 s | 0.020 s |
| Tiny append | 0.140 s | 0.142 s |
| Larger append | 0.354 s | 0.357 s |
| First Today report after revision | 8.915 s | 8.721 s |
| Switch Yesterday | 1.599 s | 1.593 s |
| Cached Today | 0.062 s | 0.056 s |

All record/work/HTML hashes match. Cold capture improves 2.3% / 60 ms; first
report improves 2.2% / 194 ms. Neither meets the 20% and 250 ms adoption gate.
Cold capture ranges are 2.555-2.679 s / 2.484-2.579 s; first report ranges are
8.731-9.202 s / 8.551-8.939 s. These are min/max of ten samples, not p95.
Some short correctness checks overlapped the report block; no adoption claim
depends on small differences. macOS collector size grows from 11,793,136 bytes
for B to 13,084,480 for C. Recommendation: retain the current 3.13 runtime,
not a 3.15 migration for speed. Both builds are ordinary GIL-enabled, JIT off.

These are runtime/build comparisons, not a pure interpreter attribution:
the uv-managed 3.13.12 build uses Clang 22.1.1 / SQLite 3.50.4, while 3.15.0 uses
Clang 23.1.3 / SQLite 3.53.1. Python dependencies are identical for B/C, but those
native build differences remain part of the tested distribution.

A/B ten-pair control: cold capture 2.575 to 2.570 s, unchanged 0.020 to 0.020 s,
tiny append 0.134 to 0.136 s, larger append 0.347 to 0.344 s. The dependency
upgrade alone contributes no material capture benefit either.

The isolated Rust PyO3 projection prototype built on ordinary 3.13. Independent
replay confirms 136 differential cases, including bidirectional checkpoint
resume and bounded ignored content. It is not a production dependency. Its
first full-suite probe found a JSON-conversion instrumentation mismatch plus
documentation/version changes during that probe; these are preserved rather
than counted as a passing full suite. The adapter now uses the same dedicated
JSON decoder primitive as the Python scanner, with no assertion relaxation.
The relevance/projection regression now passes all 30 adjacent cases. A fresh
copy of the final 2.12.4 source with only this adapter substituted passes the
same full 3,109-case suite (one platform skip). Import-path verification confirms
that validation loaded the native adapter, not the Python oracle.

Two bounded ten-pair blocks replace only structural projection, retaining the
same Python row reader, interpreter, dependencies, byte budgets and record
hashes. First block cold capture: 2.649 to 2.128 s (19.7%, 522 ms). The one
allowed noise-check block: 2.582 to 2.079 s (19.5%, 503 ms). Larger append in the
second block: 0.354 to 0.304 s; tiny append 0.135 to 0.139 s; unchanged capture
0.020 to 0.021 s. Cold sample ranges are wide: first block 2.511-3.663 /
2.000-2.674 s, second 2.545-3.296 / 1.977-2.953 s. The first block overlaps
native correctness checks. All samples, including slow ones, remain retained.

Rust is promising but this prototype misses the agreed 20% total-operation
gate in both blocks. Do not round 19.5% up to an adoption pass or run more
blocks looking for one. Recommendation: retain Python, preserve the local
prototype for a separately chosen follow-up. Concurrent memory, child CPU,
Rust packaging/startup and Windows remain unqualified; they are not reported
as passing merely because the benefit gate already rejects adoption. The
prototype and exact Cargo lock remain in the owned ignored `rust-spike/` tree.

No interpreter or native scanner is adopted without the planned correctness,
both-target, total-latency and concurrent-memory gates and owner review.

## Verification And Open Qualification Gate

Final local candidate checks: 3,109 Python tests passed, one Windows-only skip;
86 extension tests passed; Ruff, frozen monetary parity and bounded-work checks
passed. No live capture, account call, ledger repair, VS Code
installation/restart, private upload, release tag or publication occurred.
The private frozen input hash was checked again unchanged; redundant report
copies were removed after profiles and aggregate evidence were preserved.

Independent review found and drove four acceptance fixes: keep the driver and
collector in one outer process group/Job, check complete cold records before
advancing, force a timeout and observe actual collector exit (retained native
process handles on Windows), and pin CPU availability in failure-injection
tests. Checkpoint offsets, not the broader read-work counter, establish complete
source progress: that counter also includes bounded discovery/header reads.
Each cold/appended stage uses a fresh independent full serial oracle; an
incremental oracle can legitimately defer discovery work within its budget.
No source-read budget, test assertion or deadline was loosened to hide this.

The old hosted WebKit timing disposition is immutable and bound to 2.12.3.
It cannot be reused for 2.12.4. The current qualification tooling itself assumes
that one retained release slot, so a new candidate cannot obtain a legitimate
timing binding through an ordinary append. New approval alone does not make
that structural restriction disappear. No journal rewrite, tolerance change
or tracing campaign is included here. This must be resolved explicitly before
claiming complete hosted/native qualification of the new candidate.
