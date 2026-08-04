# Final Fix Report

## Changed Files

- `src/codex_usage/report_breakdown.py`
- `src/codex_usage/report_breakdown_theme.py`
- `scripts/generate_marketplace_screenshot.py`
- `tests/test_report_breakdown.py`
- `tests/test_report_view.py`
- `tests/test_project_breakdown_html.py`
- `tests/test_marketplace_screenshot.py`
- `tests/test_report_command_breakdown.py`
- `tests/test_range_cache_public_contract.py`
- `docs/marketplace/dashboard-synthetic.png`

## Root Causes And Fixes

- `.project-role-group` owned both rounded fill clipping and its descendant
  tooltips, so `overflow: hidden` painted focused and hovered tooltips outside
  the visible region. The group now permits overflow while direct first/last
  segment corner radii preserve the rounded fill boundary. The browser gate now
  checks hover and keyboard-focus tooltips at desktop and narrow viewports using
  computed clipping-ancestor intersections and temporary tooltip hit-testing.
- Project ordering sorted only by descending token totals, so equal totals kept
  record insertion order. The breakdown now applies the project key as the
  deterministic secondary key before the top-twelve presentation limit.
- The report-command test observed a rendered breakdown but not its aggregation
  call contract. It now spies on `cli.build_report_breakdown` and requires one
  call with the range-filtered context records.
- Browser validation left a transient tooltip visible in the static screenshot.
  The generator now clears pointer/focus state and waits for the opacity
  transition before capture.

## Verification

- Focused regression suite: `29 passed`.
- Full Python suite: `929 passed, 1 skipped`.
- `uvx ruff check --no-cache .`: `All checks passed!`.
- `git diff --check`: passed with no output.
- Playwright: `uv run playwright install chromium`, screenshot regeneration,
  and `uv run python scripts/generate_marketplace_screenshot.py --check` all
  passed. The tracked artifact is
  `docs/marketplace/dashboard-synthetic.png` at 1440 x 900.
- Extension suite: `246 passed`; registration smoke passed.
- Synthetic cache acceptance passed with zero warm source JSONL read attempts
  and zero warm worker spans.
- `npm --prefix extensions/vscode run package:vsix:mac` passed, including
  packaged report and Task Transfer smokes.

## Commit And Artifact

- Commit: `fix: finalize project role model breakdown review findings` (this
  final-fix commit contains this report).
- macOS arm64 VSIX: `output/releases/codex-usage-dashboard-darwin-arm64.vsix`.

## Concerns

None. The single skipped Python test is pre-existing suite coverage.
