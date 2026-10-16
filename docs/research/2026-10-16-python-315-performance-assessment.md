# Python 3.15 Performance Opportunity

Date: 2026-10-16, America/Toronto.
Status: initial research and experiment proposal, not an adoption decision.
No interpreter, dependency, build policy, installed extension or live ledger was changed.
Subsequent [consultation synthesis](2026-10-16-python-315-review/README.md)
qualifies the configured-parallelism claim and prioritizes a frozen-collector
baseline check before the runtime comparison below.

## Answer

Python 3.15 merits a bounded experiment, not an assumed performance fix. First
compare the standard interpreter against our current runtime with compatible,
controlled dependencies. Treat selective lazy imports, free-threaded workers and
the experimental JIT as separate options with different costs and evidence needs.
Use profiling to choose among them, rather than combining all changes initially.

Python 3.15.0 is stable, released October 9, 2026. Primary sources:

- [Release](https://www.python.org/downloads/release/python-3150/).
- [Language/runtime changes](https://docs.python.org/3.15/whatsnew/3.15.html).
- [Free-threading behavior](https://docs.python.org/3.15/howto/free-threading-python.html).
- [Tachyon sampling profiler](https://docs.python.org/3.15/library/profiling.sampling.html).
- [PyInstaller support history](https://pyinstaller.org/en/stable/CHANGES.html).

## Project Evidence

Discovery: <https://github.com/Wenjun-Mao/codex_usage>, branch `main`.
Inspected and remotely verified anchor:
`2cef93bca5e1e000377fee1c16d9367d8129cae3`.
The 2.12.3 release tag is `28f4de27d8d8267548dba820943d6a695ba84a32`;
the later anchor changes release documentation only. The following are source
observations, not a new end-to-end profile:

- `.python-version` and `.github/actions/qualification-tools/action.yml` select
  Python 3.13. `pyproject.toml` supports Python >=3.13.
- Both `scripts/build-agent-*.{sh,ps1}` produce PyInstaller `--onefile` collectors.
  Users run the bundled runtime; upgrading their system Python does not upgrade it.
- `parallel/execution.py:OrderedProcessMapper` uses a spawn `ProcessPoolExecutor`,
  capped at four workers, and retains input-result ordering. Parsing is already
  capable of using multiple cores without a free-threaded interpreter.
- `session_cache_refresh.py` prepares parse requests, maps batches in the process
  pool, validates results and commits groups through the coordinator.
- `agent_jobs.py:HeavyIOLane` deliberately serializes heavy jobs on one worker.
  The GIL is not what establishes this writer/job ordering.
- `agent_main.py` eagerly imports the runtime graph before argument handling.
- Existing profiling/benchmark entrypoints include `scripts/profile_dashboard.py`,
  `scripts/benchmark_capture_load.py` and `scripts/benchmark_allowance_reuse.py`.
  Report profiling can use a read-only SQLite backup and temporary working copies.

The [earlier test/release profile](2026-10-13-verification-and-release-profile.md)
attributes substantial visual-gate time to browser round trips and some API-test
time to server shutdown waits. These historical findings do not establish the
current collector's CPU/wait breakdown. A faster Python runtime cannot be assumed
to fix browser/IPC scheduling or Marketplace propagation. The [2.12.3 receipt](../release/2026-10-15-2.12.3-published.md)
records the released graph and deferred hosted-WebKit issue.

### Small Import Probe

Five alternating fresh subprocess pairs on the existing local CPython 3.13.12:

| Source-only operation | Median wall time |
| --- | ---: |
| Start interpreter and execute `pass` | 0.0134 s |
| Start interpreter and import `codex_usage.agent_main` | 0.1257 s |

The import series was 0.2164, 0.1249, 0.1257, 0.1247 and 0.1296 seconds.
No agent was instantiated and no ledger was opened. This is a small local probe
with warmed filesystem caches, not frozen-binary startup, a Python 3.15 comparison,
or an end-to-end speedup ceiling. It gives no support for attributing multi-second
dashboard latency to parent-process imports alone. Worker startup remains separate.

## Feature Fit

| Option | Potential benefit here | Important limitation |
| --- | --- | --- |
| Standard 3.15 | Faster execution of some existing Python work without concurrency redesign | Actual capture/report benefit is unmeasured; native I/O, SQL and waits remain |
| Selective lazy imports | Parent and spawned-worker import work not used on a path | Defers work/errors to first use; not an automatic warm-report optimization |
| Free-threaded 3.15 | An alternative parser thread pool might avoid spawn, pickle and duplicate interpreter costs | Requires a distinct implementation and shared-state audit; existing processes already parallelize |
| Tachyon | Separate wall, CPU and GIL samples to choose the owning bottleneck | Not a speedup itself; cannot attach its 3.15 profiler to our 3.13 collector |
| Experimental JIT | Possible improvement for sustained Python-heavy loops | Benchmark-dependent, build-dependent and separate from default-runtime adoption |

Free-threading is a specific build/runtime configuration, not an automatic result
of selecting version 3.15. Check `Py_GIL_DISABLED` and the actual GIL state after
importing extensions; unsupported extensions can re-enable it. Standard-library
documentation also identifies single-thread overhead and higher memory use.
Independent parser computation is a possible thread candidate, not permission
to share SQLite connections or remove single-writer ordering and source guards.

Lazy imports must be selective and measured through first useful output, not just
process-ready time. Do not assume new syntax, global lazy mode, deferred imports
and PyInstaller module discovery have identical semantics. Retaining source
support for 3.13 is a distinct choice from selecting a newer bundled interpreter.

Tachyon requires the same Python minor version in profiler and target. Its macOS
attachment requirements include root or debugger entitlement; Windows requires
appropriate process-memory privileges. Do not disable SIP or change OS security
to conduct this assessment. Use existing profiling tools where suitable, and
unprofiled timing runs to assess collector latency and profiling overhead.

## Concrete Compatibility Work

Direct PyPI JSON inspection on October 16 confirmed:

- Locked PyInstaller 6.20.0 declares `Requires-Python: >=3.8,<3.15`.
  Upstream added 3.15 support in 6.21.0; newer support does not prove this
  collector's frozen free-threaded/lazy-import behavior on both target platforms.
- Locked `pydantic-core` 2.46.3 has no CPython 3.15 wheel for macOS or Windows x64.
  This is a wheel-availability finding, not proof that source compilation is
  impossible. A compatible Pydantic/core pair and the full dependency graph need
  review; do not blindly unpin everything or force an unsupported interpreter.
- Watchdog's native macOS component and bundled stdlib/native libraries also need
  runtime testing, including actual GIL state, rather than version-number inference.

Reproducible metadata endpoints:
<https://pypi.org/pypi/pyinstaller/6.20.0/json> and
<https://pypi.org/pypi/pydantic-core/2.46.3/json>.
The [3.15 porting guide](https://docs.python.org/3.15/whatsnew/3.15.html#porting-to-python-3-15)
also changes SQLite API signatures. Accounting/transaction and Windows encoding
behavior deserve focused compatibility checks, not a new data migration by default.

## Follow-Up: Upgrades And uv Distribution

The pinned packages are a compatibility task, not evidence that upstream support
is missing. A fresh October 16 PyPI metadata check finds Pydantic 2.14.1 requires
`pydantic-core==2.50.1`; that core release publishes both ordinary and free-threaded
3.15 wheels for macOS ARM64 and Windows x64. PyInstaller 6.22.3 declares Python
`>=3.8,<3.16`, following 3.15 support added in 6.21.0. Upgrade Pydantic/core as
a compatible pair instead of overriding Pydantic's exact core pin. These facts
justify testing; they do not qualify our frozen dependencies or application.

- [Pydantic metadata](https://pypi.org/pypi/pydantic/2.14.1/json).
- [Core wheels](https://pypi.org/project/pydantic_core/2.50.1/).
- [PyInstaller metadata](https://pypi.org/pypi/pyinstaller/6.22.3/json).

`uv` already manages the build environment here. Its [build command](https://docs.astral.sh/uv/guides/package/)
creates Python package distributions, while [tool execution](https://docs.astral.sh/uv/concepts/tools/)
uses Python environments. It can [provision Python](https://docs.astral.sh/uv/guides/install-python/),
but that is different from producing our self-contained frozen collector.

A uv-managed deployment is feasible: ship or acquire uv, a pinned interpreter,
application and wheels, then launch an extension-owned environment. Users need
not install Python themselves. Download-at-first-use adds provisioning/network
failure states; bundling all artifacts can avoid that requirement but leaves us
owning the portable runtime/dependency layout. Both variants need lifecycle,
updates, cleanup and exact-payload qualification. ADR 0047's current distribution
contract instead includes exactly one matching collector in each VSIX. Changing
that contract is an architectural option, not a prerequisite for Python 3.15.

uv's fast dependency installation is not evidence of faster steady-state capture
or reporting under the same interpreter and code. A uv-launched development run
is a useful comparison, but must not confound interpreter changes with frozen
startup changes. PyInstaller [one-file extraction](https://pyinstaller.org/en/stable/operating-mode.html#how-the-one-file-program-works)
adds startup work relative to one-folder deployment. If that work is material,
compare `--onedir` before assuming a different provisioning system is necessary.
Do not assume every spawned child independently extracts the archive; measure
actual packaged parent/worker behavior. Neither layout change is approved here.

Current recommendation: retain uv for environments, test compatible package
upgrades and ordinary 3.15 frozen collectors first. Keep free-threaded/lazy-import
frozen behavior as explicit checks, not an inference from generic 3.15 support.
Revisit replacing PyInstaller only for a demonstrated remaining limitation or
measured deployment benefit. Consultants are working per owner report; no
external account has been operated or consultation result received here.

## Proposed Learning Sequence

1. Attribute fresh representative capture, first post-capture load, range switch
   and warm load to Python CPU, native SQL, disk/network, queue and presentation
   phases. Keep startup/worker startup separate. Do not reuse historical timing
   as proof of today's bottleneck or reopen deferred WebKit tracing implicitly.
2. Check compatible packages and disposable frozen builds for both targets.
   Compare standard 3.13 and 3.15 with the same compatible dependency versions;
   include a 3.13 dependency-update control when dependencies must change.
3. Alternate repeated unprofiled runs on identical disposable input/cache states;
   record wall/CPU time, RSS, package size and exact monetary/report results.
   Profile separate runs to explain differences, not manufacture a time adjustment.
4. Pursue selective lazy loading only if import/worker-start cost is material.
   Pursue a bounded free-threaded parser-thread experiment only if CPU/transport
   attribution justifies it, preserving ordered results and coordinator writes.
   Compare against the existing process pool, not an artificially serial baseline.
5. Consider JIT only if sustained Python hotspots remain and suitable distributable
   builds exist. Keep full correctness, native/package and release qualification
   for any adoption; a source benchmark is not release acceptance.

This sequence proposes experiments, not permission to install a runtime, access
private data, change deployed collectors, dispatch CI or publish a release.

## Consultation Recommendation

Recommend one **Pro** consultation now: independent repository-grounded option
selection and experiment design after the primary-source checks above. Let the
consultant challenge these priorities, including whether retaining 3.13 or trying
3.14 is simpler. Deep Research is not needed merely to repeat release facts; use
it later only for a named unresolved compatibility/architecture question requiring
broader external discovery.

Consultants have GitHub-only access, not local files, services, private ledgers,
raw logs or conversation history. Anonymous remote reads of 16 required source
and evidence files at the exact anchor matched `git show` byte-for-byte. This
new uncommitted note is supplementary; the self-contained handoff prompt must
carry its necessary facts rather than require an unpublished document.
No consultant browser/account has been operated. Two reports were subsequently
received and preserved unchanged in the linked consultation review; that review
records their dispositions and the recommended next experiment.
