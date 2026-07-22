# Final Review Transition Fix Report

## Root Cause

Project transitions are derived cache data, but freshness was inferred only
from the current load's `CacheStats`. Rebuilds and source changes followed by
`auto_transitions=False` discarded that signal, so a later enabled load reused
an empty or stale transition table even though all source files were current.

## Durable Fix

- Persist `project_transitions_dirty` in `schema_meta`.
- Mark transitions dirty in the same commit as rebuild, parse, and removal
  state, regardless of whether automatic transitions are enabled.
- Treat a missing or non-clean marker as dirty for older current caches.
- Recompute on the next enabled load even when every source file is reused.
- Replace all transitions and persist the clean marker in one transaction;
  inference errors and replacement interruptions leave dirty state committed
  for retry and roll back partial replacement.
- Continue validating all three version keys while tolerating internal cache
  metadata, and never restore transition rows during a version rebuild.

## TDD Evidence

- RED before implementation: the five initial regressions all failed for the
  expected missing-marker/stale-cache behavior (`5 failed, 6 deselected`).
- GREEN after implementation: those five regressions passed.
- Added a sixth focused replacement-interruption guardrail; it proves old rows
  and dirty state survive rollback until a successful retry.

## Verification

- `UV_CACHE_DIR=.uv-cache uv run pytest tests/test_session_cache.py tests/test_cli_transitions.py -v`:
  30 passed.
- `UV_CACHE_DIR=.uv-cache uv run pytest -q`: 567 passed, 1 skipped.
- `git diff --check`: passed before report creation and rerun before commit.

## Review

No correctness concerns remain. Atomic schema rebuild, cached usage fallback,
and parse-error retry behavior remain covered by the focused and full suites.
No token, pricing, report output, README, version, lock, dependency,
screenshot, tag, push, publish, or workflow changes were made.
