# ADR 0021: Explicit Usage Role Breakdown

## Status

Accepted; presentation partially superseded by ADR 0030

## Context

Project Breakdown currently reports one project total, although Codex stores
user-visible root tasks and internal structured subagents in the same session
tree. Task Transfer can distinguish them through
`session_meta.payload.source.subagent`, but usage records persist only an
optional parent task id. Parent ids are insufficient because automatic reviews
and guardians can be structured subagents without a parent id.

The dashboard also reports global model totals but does not show which models
contributed to root-task and subagent usage inside each project.

## Decision

Usage records carry an explicit `usage_role` of `root` or `subagent`, derived
from the same structured-source rule used by Task Transfer. Cache schema 5
persists the role and rebuilds incompatible disposable caches instead of
migrating or dual-reading them.

Report aggregation builds one project-role-model cube from the already range-
filtered cached records. Project Breakdown renders adjacent root and subagent
groups separated by neutral space, then stacks each group by model. The seven
largest models across the report retain exact visual identities and all
remaining models form `Other`. Project Breakdown and Model Mix share that
ordered model set and palette; exact Model Details remain ungrouped.

## Rejected Alternatives

- Parent-task id inference misses parentless structured subagents.
- Runtime metadata rescanning defeats the range-aware cache.
- SQL-native aggregation duplicates effective-dated pricing logic.
- A second role color encoding competes with model colors.
- Showing every historical model makes project rows and legends unreadable.
- Preserving schema 4 adds compatibility code for disposable derived state.

## Consequences And Guardrails

Task Transfer and reporting share one durable role definition. Project, role,
model, cost, credit, and token totals must conserve exactly. The new report path
performs no additional JSONL scan or cache inventory. Parser, cache, aggregation,
accessibility, theme, screenshot, and dual-platform release tests guard the
contract. Repository and Marketplace documentation lead with the capability
and use a repeatable Playwright-generated synthetic screenshot.
