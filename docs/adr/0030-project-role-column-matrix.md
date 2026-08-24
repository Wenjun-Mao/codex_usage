# ADR 0030: Project Role Column Matrix

## Status

Accepted

## Context

ADR 0021 introduced adjacent root-task and subagent groups inside each project
bar. Repeating both role headings on every project row made the chart noisy and
tied headings to proportional role widths, which caused clipping and uneven
background geometry for small projects and small role shares.

The chart needs to support two comparisons at once: root-task usage across
projects and subagent usage across projects. A single shared scale makes the
smaller subagent values difficult to inspect on common corpora.

## Decision

Project Breakdown is a four-column comparison matrix: Project, Root tasks,
Subagents, and Total. Root tasks and Subagents are shared column headings shown
once. Each role cell contains its exact token total, share of its project, and a
model-stacked horizontal bar.

Each role column uses a zero-based scale whose maximum is the largest value for
that role among the displayed projects. Exact values and project shares remain
visible because bar lengths are comparable within a role column, not between
the two role columns. Empty roles render as zero rather than disappearing.

At narrow widths, each project becomes a compact block and the two role cells
stack vertically with local role labels. Model colors, accessible segment
labels, detailed tooltips, project totals, and the shared legend remain
unchanged.

This decision partially supersedes only the Project Breakdown presentation
described by ADR 0021. Its role classification, aggregation, conservation, and
model-palette contracts remain authoritative.

## Rejected Alternatives

- Repeating headings on every project row preserves unnecessary noise and
  reintroduces clipping pressure.
- One continuous project bar makes the role boundary hard to scan.
- A shared absolute scale across both roles hides meaningful subagent
  differences when root-task usage dominates.
- Encoding roles with additional colors conflicts with the model palette.

## Consequences And Guardrails

Role bars are comparable only within their column, so every role cell must keep
its exact token total and project share visible. Browser checks enforce equal
role-track geometry, contained model stacks, unclipped shared headings, visible
tooltips, and the stacked narrow layout. The generated Marketplace screenshot
is reviewed whenever this presentation changes.
