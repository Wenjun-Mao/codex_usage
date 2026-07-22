# Final Review Docs Fix Report

## Root Cause

Both current READMEs described GPT-5.6 long-context ordinary-input rates as
"uncached input," even though API-equivalent cache writes are a separate rate
category. The CLI JSON serializer already preserved the legacy aggregate and
both new cost fields, but its end-to-end summary test did not assert them.

## Changes

- Reworded both current READMEs to label $10/$5/$2 as ordinary input and to
  list cache-read, cache-write, and output rates separately.
- Added the standard cache-write rates: Sol $6.25, Terra $3.125, Luna $1.25
  per 1M tokens.
- Added the long-context cache-write rates: Sol $12.50, Terra $6.25, Luna
  $2.50 per 1M tokens.
- Preserved the exact >272,000 boundary and stated that Codex credits do not
  use long-context or API cache-write categories.
- Clarified that API-equivalent USD figures are estimates, not actual billing.
- Added documentation regression assertions and JSON cost-mapping assertions
  for the existing GPT-5.5 sample.

## Verification

- RED: `UV_CACHE_DIR=.uv-cache uv run pytest tests/test_task_transfer_docs.py tests/test_cli.py::test_cli_summary_json_csv_and_report`
  failed only because the required standard cache-write prose was absent.
- GREEN: the same focused command passed: 13 passed.
- Full suite: `UV_CACHE_DIR=.uv-cache uv run pytest` passed: 561 passed, 1 skipped.
- `git diff --check` passed with no output.

## Scope

No production pricing, session-cache, ADR, version, lock, dependency,
screenshot, tag, push, publish, or workflow files changed.
