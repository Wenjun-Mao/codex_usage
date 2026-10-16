# Python 3.15 Consultation Review

Date: 2026-10-16, America/Toronto.
Status: historical consultation synthesis; see the subsequent
[implementation evidence](../2026-10-16-collector-implementation.md) for executed
fixes and controlled measurements. No runtime/native scanner adoption.

Subsequent direct investigation reproduced the frozen worker-bootstrap failure.
See [collector investigation](../2026-10-16-collector-performance-investigation.md)
for executed synthetic evidence and the separate Python/Rust direction. The
original reports and the review-time evidence below remain unchanged.

## Evidence Boundary

The two submitted reports are preserved byte-for-byte locally as `report-1.md`
and `report-2.md`; the original submissions are not included in publication of
this source-verified synthesis. Author/model/mode identities were not supplied;
do not infer that overlapping findings are independent empirical confirmations.
Their recommendations are consultation evidence, not operating instructions,
implementation permission or release acceptance. Neither report ran our collector
or a Python-version performance comparison. No speedup is established.

Both inspected `2cef93bca5e1e000377fee1c16d9367d8129cae3`, which remains the local
HEAD during this review. The published 2.12.3 runtime source is
`28f4de27d8d8267548dba820943d6a695ba84a32`; the later commit contains release
documentation only. Our [initial assessment](../2026-10-16-python-315-performance-assessment.md)
is separate from the unchanged reports and this synthesis.

## What Changes Our Understanding

### Frozen Collector Dispatch Is The First Question

Independent source inspection confirms:

- Both platform build scripts freeze `src/codex_usage/agent_main.py` directly.
  That entrypoint imports the application and reaches argument parsing without
  `multiprocessing.freeze_support()`.
- The separate `src/codex_usage/__main__.py` does call `freeze_support()` before
  importing the CLI. Its AST regression in `test_parallel_acceptance_scripts.py`
  checks that CLI entrypoint, not the frozen collector entrypoint.
- `scripts/smoke-test-packaged-agent.py` creates one fresh source and asserts
  capture/report/accounting behavior, not multiple worker PIDs, overlap and no
  process-infrastructure fallback. Its preseeded speed fixture is not evidence
  of a cold multi-file collector parse.
- The older `packaged_parallel_cache_smoke.py` exercises the CLI `summary` route,
  not the collector's current lifecycle/HTTP entrypoint.
- `OrderedProcessMapper` uses spawn and can deliberately fall back to serial
  parsing on infrastructure errors, preserving successful accounting results.

[PyInstaller's multiprocessing contract](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html#multi-processing)
requires its `freeze_support()` diversion on all supported platforms. Without
it, worker invocations can reach ordinary argument parsing or application startup.

This establishes a source/bootstrap concern and a specific test-coverage gap,
not a reproduced released-binary failure. Our earlier description of parsing as
already parallel should have distinguished configured/source-tested capability
from verified parallelism through the released collector. Do not infer actual
fallback frequency, seconds lost, or data corruption from this inspection.

### Watchdog Extends The Compatibility Question

The October 16 direct PyPI metadata check independently confirms Watchdog 6.0.0
macOS CPython wheels stop at cp313; its Windows x64 wheel is py3-none. Missing
cp315/cp315t/abi3 wheels do not prove source compilation cannot work.

The exact upstream v6.0.0 `src/watchdog_fsevents.c` uses `PyModule_Create` and
contains neither `Py_mod_gil` nor `PyUnstable_Module_SetGIL`. Its downloaded
source SHA-256 is `b09bdb221588518d2b2e3061aa9928772614492a8da091feaca653f65d21d651`.
[Source](https://github.com/gorakhargosh/watchdog/blob/v6.0.0/src/watchdog_fsevents.c),
[release files](https://pypi.org/project/watchdog/6.0.0/).

[CPython documents](https://docs.python.org/3.15/howto/free-threading-python.html)
that unsupported C extensions may re-enable the GIL. If the unchanged extension
builds and loads, it is therefore a concrete collector-level free-threading
question. A parser-only benchmark omitting the watcher cannot settle it. Do not
force the GIL off to bypass an extension's missing safety declaration.

Pydantic/core and PyInstaller already have upstream 3.15-compatible versions as
recorded in our initial follow-up; the reports do not overturn that finding.
They show why those two upgrades alone do not qualify the full dependency set.

### Measurement Scope Needs Correction Before Runtime Comparison

Source inspection confirms the reports' benchmark cautions:

- `profile_dashboard.py` primes the monetary index before its report loop.
  It does not measure the full first post-capture report path.
- `benchmark_capture_load.py` compares source revisions under one
  `sys.executable`, defaults to v2.12.1 and excludes parsing/live quota RPC.
  Its existing implementation is not a Python 3.13-versus-3.15 benchmark.
- `CaptureResult.elapsed_seconds` starts within `capture_once`, after lane
  dispatch; it does not include preceding queue delay.
- Worker spans start inside parsing and end before result transport. They
  include file work/retries, not complete pool startup/import/IPC/shutdown cost.
- `refresh_files()` constructs one process mapper per refresh and retains
  completed result payloads in `all_results` through final statistics creation.
  Pool churn and retained memory costs are hypotheses to measure, not assumed
  dominant causes or permission to refactor them immediately.

## Insight Dispositions

| Class | Insight | Disposition |
| --- | --- | --- |
| Use | Verify actual frozen collector parallelism before treating it as baseline | Highest-priority bounded functional canary; use collector lifecycle/HTTP, not CLI summary |
| Use | Separate queue, quota, pool, coordinator, first-report and delivery costs | Record operation boundaries; do not label backend response time as WebView paint |
| Use | Keep dependency/toolchain changes separate from interpreter effects | Future A=current 3.13, B=3.13/common candidate dependencies, C=3.15/same dependencies |
| Use | Runtime identity and native dependencies matter | Record exact interpreter/build, SQLite, dependency/artifact hashes and watcher backend |
| Test | Standard GIL-enabled 3.15, existing processes | First interpreter candidate after the current frozen baseline is understood |
| Test | Selective imports, small-work serial threshold or releasing committed payloads | Only pursue the component supported by attribution; do not combine changes initially |
| Test | Watchdog build/load and actual post-startup GIL state | Ordinary compatibility and free-threading are distinct questions |
| Park | Free-threaded parser threads, persistent pools and JIT | Need measured benefit and separate lifecycle/native/shared-state evidence |
| Park | Replacing PyInstaller with uv-managed deployment | Different distribution contract; no demonstrated need to reach standard 3.15 |
| Discard as inference | Configured workers, source tests or CLI smoke prove current frozen-agent overlap | These are different execution paths; this corrects our earlier summary, not a claim made by the reports |
| Discard as inference | Matching reports, version updates or source imports establish user-visible speedup | No consultant or local experiment has measured that comparison |

## Recommended Next Experiment

One bounded current-runtime test should precede migration work:

1. Use the exact released 2.12.3 macOS collector in a disposable synthetic home.
   Assert its package/source identity. Prevent discovery of real Codex/account
   credentials or live data; quota acquisition must be deterministic or explicitly
   excluded. Keep logs, state and optional repository lookups inside the fixture.
2. First run one functional sequence: launch and automatic startup capture,
   explicit multi-file capture, unchanged capture, controlled append capture,
   first Today report, Yesterday, cached Today, and clean shutdown.
3. Require genuine non-parent worker IDs, overlapping worker activity, no
   infrastructure fallback, expected pending progress and exact accounting versus
   a serial oracle. Include more than eight files to exercise commit boundaries,
   while respecting existing byte budgets. Padding-only parser fixtures are not
   representative report workloads; use actual synthetic records for report work.
4. Stop if the functional parallelism check fails. Preserve original evidence;
   propose a narrowly scoped bootstrap/qualification repair before timing a
   different interpreter. Do not quietly repair the baseline or add blind retries.
5. If it passes, run up to five fresh-process, resident-agent sequences for a
   screening phase table. Measure parent/child CPU and sampled concurrent
   process-tree memory; do not sum unrelated process peaks or infer p95 from five
   observations. A separate diagnostic pass must not be mixed into timing results.

Use existing work/parity guards instead of designing a new general benchmark
framework. If a diagnostic binary is needed to expose worker audit data, retain
its source/instrumentation difference and never call it the untouched release.
Native Windows confirmation is required before generalizing packaged behavior
to that target. No browser tracing, OS security change or live-ledger access is
implied by this proposal.

The deliverable is the functional packaged-parallelism result, a phase/memory
table if it passes, and one next recommended component. This is intentionally
smaller than an immediate runtime migration plus packaging/concurrency rewrite.

## Follow-Up Recommendation

**None.** The reports identify a sufficiently concrete next experiment; another
consultation cannot substitute for observing the frozen collector. Reopen a
bounded Pro/Deep Research question only if direct tests leave a specific
bootstrap/native compatibility issue that external judgment or discovery can
materially resolve. Unrelated performance work need not wait for that question.

This review ran source/metadata checks only. No frozen collector was launched,
no benchmark or test suite executed, no runtime/dependencies/product source
changed, and no data, account, installed extension or release was modified.
Research files remain local and unpublished pending separate authorization.

## Original File Integrity

| File | SHA-256 |
| --- | --- |
| `report-1.md` | `81d81dc8c9746099c79b32a89a8f6c790bffd155dd0f2ab22794e58f8b01b003` |
| `report-2.md` | `e058b6fedbaf53a4323dfed208cfb747f3296a509cd5e60f5304aa797546cd84` |
