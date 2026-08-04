# Project Role And Model Breakdown Design

## Status

Approved in conversation and ready for written review.

## Summary

The next feature release will make Project Breakdown explain not only which
projects consumed tokens, but also whether that usage came from user-visible
root tasks or structured subagents and which models produced it. Each project
will keep one absolute-scale horizontal row. Within that row, adjacent root and
subagent groups will be separated by a neutral gap, and each group will be
stacked by model color.

The dashboard already retains model ids and structured subagent metadata. This
change makes usage role an explicit persisted dimension, aggregates the two
dimensions from range-filtered cached records, and presents them without
adding another source scan.

## Goals

- Separate root-task and structured-subagent usage for each project.
- Split both role groups by model with a shared visual palette.
- Preserve exact project totals, effective-dated API costs, and Codex credits.
- Keep the overall Model Mix section as the global model summary.
- Keep Project Breakdown readable when historical reports contain many models.
- Feature the new capability in repository and Marketplace documentation.
- Regenerate the Marketplace screenshot through a repeatable Playwright flow.

## Non-Goals

- Listing individual root tasks or individual subagents in the dashboard.
- Changing project identity, parent-project inheritance, or project-transition
  semantics.
- Replacing the existing global Model Details table.
- Moving pricing or aggregation into SQLite.
- Preserving or migrating the disposable schema 4 cache.
- Adding remote assets, runtime JavaScript, or a charting framework.

## Terminology

- **Root task**: a user-visible Codex task whose session metadata does not
  contain a structured `payload.source.subagent` object.
- **Subagent**: any session whose metadata contains a structured
  `payload.source.subagent` object. This includes spawned agents, automatic
  reviews, and guardians, even when no parent task id is present.
- **Usage role**: the exact persisted value `root` or `subagent` attached to a
  usage record.
- **Other**: the visual bucket containing models outside the seven largest
  models in the selected report range.

This role contract intentionally matches Task Transfer's structured-subagent
classification. `parent_thread_id` is not a role classifier because some
structured subagents have no parent id.

## Data Contract

`UsageRecord` gains a required `usage_role` value of `root` or `subagent`.
Session parsing derives it once from `SessionMetadata.is_subagent`, which is
already populated by the shared structured-source detector. Every usage delta
from the session receives that role.

Usage cache schema 5 stores `usage_role` as a non-null field in
`usage_records`. Cache queries restore it without inference. Schema 4 remains
unsupported after the change: because the cache is disposable derived data, a
schema mismatch drops only known plugin-cache objects and rebuilds from source.
No dual reads, migration, or compatibility shim will be added.

Malformed or absent structured source metadata classifies as `root`. Only an
explicit structured `source.subagent` object establishes subagent status.

Existing project attribution remains authoritative. Parent identity
inheritance, canonical repository identity, archive retention, missing-file
retention, and effective-dated project transitions run exactly as before.

## Aggregation

The report command already obtains records filtered to the selected range and
projects from the cache. One Python aggregation pass over those records will
build a project-role-model cube:

```text
project
  -> role: root | subagent
    -> model
      -> usage, API cost, Codex credits, event count
```

Segment costs and credits are sums of the existing per-record effective-dated
calculations. They are never reconstructed from aggregate or averaged rates.

The visual model set is selected globally for the report, not independently
per project:

1. Sum total tokens by exact model id across the selected records.
2. Sort by descending total tokens, then model id for deterministic ties.
3. Keep the first seven exact model ids.
4. Combine every remaining model into `Other` for visual charts only.

The same ordered visual model set and curated eight-color palette feed Project
Breakdown and Model Mix. Palette assignment follows that deterministic report
order; `Other` always receives the neutral final color. Model Details continues
to list every exact model separately.

The following conservation rules are mandatory:

```text
project total = root total + subagent total
role total = sum(role model segments)
all exact model totals = seven displayed models + Other
```

The equalities apply independently to token categories, API cost, Codex
credits, unpriced tokens, credit-unpriced tokens, and event counts.

## Project Breakdown Presentation

Project rows retain the current absolute comparison: the largest displayed
project defines the maximum width, and every other project's outer width is
proportional to its total tokens. The existing top-twelve project limit remains.

Inside each project's outer width:

- Root-task and subagent groups divide the available width in proportion to
  their token totals.
- When both roles are nonzero, an 8 px neutral gap separates two independently
  rounded groups.
- Each role group is horizontally stacked by the shared visual model set.
- When one role is zero, the empty role and gap are omitted.
- Positive but narrow groups remain quantitatively proportional. Their visible
  labels may be omitted when space is insufficient, but their accessible label
  and tooltip remain complete.

Each model segment supports pointer hover and keyboard focus. Its accessible
label and tooltip name the project, role, model, total tokens, share of project,
API-equivalent cost, and Codex credits. The value to the right of the bar
remains the complete project total.

Project Details remains a compact project-level table. It adds `Root Tokens`
and `Subagent Tokens` columns but does not expand into project-role-model rows.
The visual segment tooltips provide exact intersection values, while Model
Details remains the complete exact-model table.

## Model Mix Presentation

Model Mix remains the overall cross-project ranking. Its visual rows use the
same top-seven-plus-Other model set, order, and colors as Project Breakdown.
The underlying Model Details table remains ungrouped so no exact model data is
hidden.

Empty reports keep the existing empty state. Root-only and subagent-only
projects render one role group. Unknown model ids participate like any other
exact model and may rank into the top seven or fall into `Other`.

## Architecture Boundaries

- The parser owns role classification.
- The cache schema and query layer own role persistence.
- A focused report aggregation component owns the project-role-model cube,
  visual model selection, conservation checks, and role totals.
- The report view model owns presentation-ready immutable points and palette
  assignments.
- Chart rendering owns semantic HTML, accessible interaction, and layout only.
- README and screenshot generation consume production report rendering rather
  than maintaining a second mock implementation.

No report component will reopen source JSONL files or issue a second cache
inventory/query pass for this feature.

## Documentation And Screenshot

Both root `README.md` and `extensions/vscode/README.md` will lead with the usage
reporting capability. Their opening feature copy will explicitly mention:

- per-project root-task versus subagent usage;
- per-project model composition with shared colors;
- overall Model Mix and effective-dated cost and credit estimates;
- optional Task Transfer as the second major capability.

`docs/marketplace/dashboard-synthetic.png` will be regenerated from a fixed
synthetic report using production rendering. Python Playwright will be a
development-only dependency. After the one-time browser setup command
`uv run playwright install chromium`, the repository command
`uv run python scripts/generate_marketplace_screenshot.py` will render fixed
dates, projects, role shares, models, totals, and night theme, then capture a
1440 x 900 viewport centered on Project Breakdown and Model Mix. The output path
remains stable so both READMEs and the Marketplace listing update together.

The release checklist will require running and visually reviewing this command
whenever dashboard presentation changes. Repository and extension changelogs
will describe the feature and the one-time schema 5 rebuild.

## Error Handling And Edge Cases

- Unsupported cached role values are a schema/contract failure and trigger the
  normal disposable-cache rebuild path; they are not silently coerced.
- Missing or malformed source objects remain `root` under the explicit-source
  rule.
- A role with zero tokens is omitted instead of rendering an empty group.
- A tiny positive role or model segment stays proportional and accessible even
  when its visible label cannot fit.
- Unknown models remain visible and retain unpriced-token disclosures.
- `Other` aggregates actual per-record costs and credits; it never applies a
  synthetic price.
- Partial retained history continues to use the existing missing-source notice.

## Testing And Acceptance

Parser and cache tests will prove:

- spawned and parentless structured subagents receive `subagent`;
- ordinary tasks and user-visible forks receive `root`;
- schema 5 persists and restores role exactly;
- a schema 4 cache rebuilds without a compatibility path;
- range queries preserve role and parent identity lookup behavior.

Aggregation tests will prove exact conservation for every usage, cost, credit,
unpriced, and event-count field. They will cover deterministic ties, fewer than
seven models, more than seven models, `Other`, unknown models, root-only,
subagent-only, and mixed projects.

Rendering tests will cover absolute project scaling, the role gap, shared model
colors, zero and tiny groups, tooltip content, keyboard focus, accessible
labels, day/night themes, narrow viewports, and the unchanged no-script/no-
remote-assets contract.

The deterministic Playwright documentation test will exercise the generator
and assert the output dimensions, meaningful nonblank pixels, expected report
landmarks, and absence of clipping at the role bars and tooltips. It will not
require byte-identical output across operating systems or font stacks. The
release checklist retains a human visual review of the tracked image. Existing
Python, extension, registration, packaged native, and dual-platform pre-publish
gates remain required.

## Rejected Alternatives

- Inferring role from `parent_thread_id` misses parentless reviews and guardians.
- Showing one bar per role doubles project-row height and weakens comparison.
- A single continuous bar with only a divider makes the first-level role split
  too easy to miss.
- Encoding role with another color conflicts with model color semantics.
- Showing every historical model in the visual legend becomes unreadable.
- Grouping independently per project assigns inconsistent colors and meanings.
- SQL-native aggregation duplicates effective-dated pricing and Python report
  logic without removing the existing range query.
- A hand-captured screenshot is easy to forget and hard to reproduce.

## Approved Outcome

The approved design is one absolute-scale horizontal row per project, two
adjacent role groups separated by neutral space, model-colored stacks inside
each group, a shared top-seven-plus-Other palette with Model Mix, explicit
schema-5 role persistence, and documentation led by a reproducible screenshot
of the finished feature.
