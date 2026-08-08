# ADR 0025: Separate Usage And Task Storage Views

## Status

Accepted for version 1.6.0 on 2026-08-07

## Context

Task Storage added a second complete analytical workflow to a dashboard that was
originally a single usage report. Both workflows were correct, but placing the
storage inventory before every usage chart made the page long and obscured the
distinction between date-filtered token accounting and current on-disk state.

## Decision

The dashboard has two top-level views: **Usage** and **Task Storage**. Usage is
the default and owns the date range, token KPIs, pricing notices, transitions,
timeline charts, Project Breakdown, and Model Mix. Task Storage owns current
logical JSONL bytes, task-tree diagnostics, and verified backup actions. The
project filter and theme apply to both views; the usage date range does not
filter Task Storage.

Both datasets are still generated in one report. View switching is a pure
presentation operation and never reparses JSONL files or reruns the CLI.
Standalone HTML uses local fragment navigation and CSS. The VS Code webview
rewrites those links to a narrow command allowlist, remembers the selected view
in extension memory for the current session, and reapplies it after refresh.
The webview remains script-free under ADR 0002.

## Consequences

The primary Usage workflow is shorter, while Task Storage has enough room for
its complete inventory and backup controls. A refresh still computes both
views, so this change improves navigation rather than report-generation time.
The selected view resets to Usage when a new extension session starts and is
not a user setting.

## Rejected Alternatives

- Collapsing sections would leave two distinct filtering semantics mixed in one
  page and make the current view harder to understand.
- Lazy-generating storage would improve some refreshes but would create a new
  cache and command contract beyond this presentation release.
- Enabling webview JavaScript only for tabs would weaken the existing CSP when
  fragment links and allowlisted commands provide the required behavior.
