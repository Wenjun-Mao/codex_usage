# Collector Performance Investigation

Date: 2026-10-16. Status: investigation completed; no product fix or runtime adoption.

This records the preimplementation investigation at its named source anchor.
For subsequent fixes and measurements, see
[implementation evidence](2026-10-16-collector-implementation.md).

## Outcome

The exact released macOS 2.12.3 collector fails multiprocessing bootstrap on a
multi-file synthetic capture and recovers by parsing serially. This is a
reproduced packaging defect, not merely a source-code concern. Fix and qualify
that contract before comparing Python versions or planning a Rust rewrite.

Source-only profiling also identifies a credible narrow Rust candidate:
structural JSON projection. Repeated repository resolution is a separate
redundant-work candidate to address in Python, not a reason to port everything.
Neither Python 3.15 nor Rust has been benchmarked or adopted in this work.

## Authority And Isolation

- Source HEAD: `2cef93bca5e1e000377fee1c16d9367d8129cae3`, unchanged.
- Published runtime source: `28f4de27d8d8267548dba820943d6a695ba84a32`.
- macOS VSIX SHA-256:
  `25a65eee176994b5d1cc85633420ccbfac68dd230b3d6000ac4db50ecb8be08e`.
- Extracted, unmodified collector SHA-256:
  `b19ed9e9818ed9dc4da91857f7ccd9195fb05cf62031a89cc7f692947d336439`.
- Native ARM64 host. Source runtime: CPython 3.13.12, SQLite 3.50.4.
- Only generated usage records and fresh ledgers were used. No live ledger,
  raw task logs, credentials, installed extension, account or release changed.
- Frozen canary used an outer macOS sandbox: home-directory contents outside
  its fixture denied, foreign executable launches denied, outbound networking
  denied. Collector self-execution remained allowed for spawned workers.
  Quota acquisition returned `probe_unavailable`; it did not contact an account.
- Source attribution directly called capture/report functions, with a
  deterministic empty quota-probe replacement and isolated home/environment.
  It did not start the watcher, HTTP server or scheduler. V2 fixtures include
  their own minimal synthetic Git checkout, avoiding ancestor checkout lookup.

Investigation scripts and complete generated evidence are local, ignored under
`output/performance/python-runtime-investigation/`. They are experiments, not new
release gates or a generally qualified benchmark harness.

## Reproduced Frozen Failure

`released-canary-v2/evidence.json` records 12 files, approximately 21.5 MB,
12,000 response cycles, more than one eight-file commit group and no pending
capture bytes. This exercises actual usage/speed parsing, not padding-only scans.
Descriptor readiness was 2.00 seconds; startup capture reported 6.31 seconds.
These are single observations, not performance distributions.

The process exited normally after controlled shutdown, but stderr contains:

```text
error: unrecognized arguments: -B -S -I -c from multiprocessing.resource_tracker import main;main(...)
error: unrecognized arguments: --multiprocessing-fork tracker_fd=... pipe_handle=...
RuntimeWarning: process pool infrastructure failed; continuing serially
```

All 12,000 events and exact input/cached-input/output/total token sums matched
the generated expectations. This proves no token-count error for this fixture;
it is not a full accounting-equivalence or monetary acceptance run. The canary
stopped at the failed worker-dispatch check rather than silently repairing the
release and continuing migration timing.

Root cause and owning layer:

1. Both platform build scripts freeze `src/codex_usage/agent_main.py` directly.
2. That file does not call `multiprocessing.freeze_support()` before ordinary
   application/argument-parser startup. Spawned child invocations consequently
   enter the agent argument parser, which rejects multiprocessing arguments.
3. The process mapper catches infrastructure failure and runs the requests
   serially. Correct totals and successful capture therefore do not prove
   workers executed successfully.
4. The existing bootstrap regression checks `codex_usage/__main__.py`, not the
   frozen collector entrypoint. The packaged-agent smoke uses one fresh file,
   so it does not require a process pool. This is a qualification coverage gap.
5. The collector's returned stats still report zero worker fallbacks. Source
   inspection explains this second visibility gap: `load_cached_session_data`
   propagates `usage_run` failures into stats, but `refresh_cached_session_data`,
   used by capture, does not. Fixing bootstrap alone should not leave this blind
   spot in operational status.

[PyInstaller documents this bootstrap requirement](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#multi-processing).
The appropriate fix belongs in the frozen collector entrypoint plus its
qualification/diagnostic contract, not looser argument parsing or disabling
parallelism. No fixed packaged candidate has been built or accepted yet.
Windows has the same source concern but was not executed in this investigation.

## Source-Only Screening

V2 fixture: 12 files, 1,000 generated response cycles per file, one local
synthetic repository, six files on each of two days. Append adds one cycle per
file. Both worker counts captured exactly 12,012 events and their expected
token components; SQLite integrity checks returned `ok`.

| Operation | One worker | Four workers |
| --- | ---: | ---: |
| Cold capture | 6.122 s | 2.855 s |
| Unchanged capture | 0.020 s | 0.021 s |
| Append one response per file | 0.061 s | 0.137 s |
| First Today report after capture | 0.366 s | 0.363 s |
| Switch Yesterday | 0.340 s | 0.341 s |
| Cached Today | 0.002 s | 0.003 s |

Four-worker cold and append runs recorded four distinct non-parent PIDs,
maximum overlap four and no infrastructure fallback. Unchanged captures read
zero source bytes. In the four-worker cold capture, parser refresh took 1.56 s
(including 0.18 s grouped commit work); first normalized-ledger synchronization
took 1.27 s. These nested phases must not be summed twice.

These are one observation per configuration, not randomized repeated trials,
p95, a packaged fix's before/after result or a Python-version comparison. Parent
CPU timing excludes child CPU; no process-tree peak memory claim is made.
Imports, launch, queue delay, real quota RPC, actual allowance-history density,
large media, continuation histories, WebView transfer and paint are outside this
source screening. The source/frozen workloads and isolation are not identical;
do not attribute their timing difference solely to bootstrap.

Tiny append work being slower with four workers suggests measuring dispatch
thresholds, not making every capture parallel. The report fixture does not
reproduce the owner's multi-second dashboard delay; that remains a distinct
measurement question on a representative, safely isolated ledger snapshot.

## Profile Attribution

A separate serial V2 cProfile pass deliberately includes all parser CPU on one
thread. It is heavily instrumented (16.13 s versus 6.12 s unprofiled), so the
following figures locate work, not predict achievable savings:

| Component | Profiled cumulative time | Interpretation |
| --- | ---: | --- |
| Structural prefix projection | 6.35 s, 72,012 calls | Plausible native acceleration target |
| Repository identity resolution | 3.83 s, 12,012 calls | Repeated lookup/config parsing to investigate first |
| Normalized-ledger synchronization | 1.77 s, two calls | Investigate transaction/query/work design before language change |

`session_usage_record.usage_record` resolves the same source metadata's project
for every delta. `resolve_project_identity` already accepts a checkout cache,
but this call does not supply one. A durable optimization must define cache
lifetime and invalidation for origin changes, worktrees, repository replacement
and metadata changes; an unbounded global cache would be unsafe.

`classify_row_prefix` invokes structural projection for every row, including
rows later decoded for accounting. The scanner preserves bounded header fields
and lexer state without retaining message/media content. This is more specific
than merely replacing `json.loads` with a faster JSON library.

## Python And Rust Direction

Recommended order, not an adopted architecture:

1. Repair frozen collector bootstrap and fallback-stat propagation. Add an
   actual multi-file collector lifecycle/HTTP qualification requiring overlapping
   worker spans and no fallback, plus exact serial-oracle accounting/provenance,
   incremental/no-op behavior and process-tree cleanup on both targets.
2. Remove measured redundant work in Python with bounded, correctly invalidated
   repository resolution. Re-profile a representative disposable snapshot.
3. Compare standard Python 3.15 with dependency/toolchain-controlled Python
   3.13. Packaging failure is not evidence of an interpreter limitation.
4. If scanning remains material, test one Rust structural scanning/projection
   component against the same corpus and parity contracts. Keep Python's ledger,
   pricing and report orchestration initially. Select only if total capture or
   report latency improves materially, including conversion/packaging costs.

A Rust extension can perform Rust-only work detached from the interpreter even
on ordinary GIL-enabled Python; free-threaded Python is not a prerequisite.
[PyO3 parallelism](https://pyo3.rs/main/parallelism) and
[boundary/performance guidance](https://pyo3.rs/main/performance) support using
coarse-grained calls rather than repeated Python/Rust object conversion.

Serde's [typed deserialization](https://docs.rs/serde_json/latest/serde_json/)
and [IgnoredAny](https://docs.rs/serde/latest/serde/de/struct.IgnoredAny.html)
are useful building blocks, but not drop-in replacements for the current
resumable-prefix contract. Differential tests must cover split UTF-8/escapes,
partial rows, duplicate required keys, malformed input, bounded memory, late
headers after oversized content, checkpoint restart and unchanged usage/speed
facts. Do not decode or retain arbitrary full messages/media for convenience.

A standalone Rust collector could eventually eliminate CPython/PyInstaller from
distribution, but would also port the service lifecycle, watcher, migrations,
accounting authority, recovery and reporting contracts. This investigation does
not justify that larger rewrite. A native scanner spike is the useful first
Rust question, not replacing the entire application.

## Verification And Remaining Work

- Exact published package hash and extracted binary signature verified.
- Frozen multi-file functional canary reproduced the failure; expected token
  components matched, clean exit. Initial sandbox setup denied ancestor file
  metadata and exited before readiness; that setup failure is preserved
  separately and is not counted as a product failure.
- Source V2 serial/parallel capture, no-op, append and report sequences passed
  the listed assertions. V1 runs lacked a fixture-owned Git boundary and are
  retained only as exploratory evidence, not used in the screening table.
- 32 focused tests passed: source process overlap, structural projection,
  relevance gates and the existing CLI-entrypoint bootstrap regression. Their
  success alongside the frozen failure confirms the coverage gap, not a fix.
- No full suite, native Windows execution, fixed binary, Python 3.15 runtime
  comparison, Rust prototype, new release or installed-extension change.

Local entrypoints: `packaged_canary.py` and `source_probe.py` in the ignored
investigation directory above. They intentionally refuse to reuse an existing
run directory; preserve results before selecting a new destination for reruns.

This supersedes the unexecuted-canary status in the earlier
[consultation synthesis](2026-10-16-python-315-review/README.md), not the unchanged
consultant reports or their original evidence boundaries.
