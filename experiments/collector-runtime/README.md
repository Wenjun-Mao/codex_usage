# Collector Runtime Experiment

Manual, nonpublishing compatibility checks for current 3.13 dependencies (A),
common candidate dependencies on 3.13 (B), and the same set on standard 3.15 (C).
The default lock, shipped interpreter and extension installation are unchanged.

`.github/workflows/collector-runtime-evaluation.yml` runs each configuration on
macOS ARM64 and Windows x64. It records coherent native dependency versions,
compiler/runtime flags, watcher event/shutdown, frozen HTTP worker/serial-oracle
and forced-timeout cleanup proof, and package sizes/hashes. Only synthetic
fixtures and content-free JSON are uploaded. There are no publishing credentials,
tags, private inputs or qualification/journal writes. The script refuses a host
with a discovered account CLI; local macOS collector testing instead requires
an external sandbox and is described in the implementation evidence.

Run once on the named frozen main candidate; only diagnosed affected jobs may
be rerun. A passing experiment is not release qualification or runtime adoption.
Full end-to-end paired latency, process-tree memory and dependency-effect
measurements are independent gates in
`docs/plans/collector-performance-runtime-evaluation.md`.

`scripts/collector_snapshot.py` creates a fresh private read-only-input backup.
`scripts/benchmark_collector.py` compares frozen source trees/interpreters with
an excluded preparation pair and ten alternating pairs. Use a new output path
for every run. Report mode requires `--ledger-snapshot` and a fixed `--now`;
it never primes the monetary index before the first report. Diagnostic profiles
use `--profile --workers 1` separately and cannot count as adoption samples.
Keep all private outputs/profiles under ignored `output/performance/` and never
upload them to Actions. Benchmark helper output explicitly leaves memory/child
CPU adoption gates open when they have not been measured.
