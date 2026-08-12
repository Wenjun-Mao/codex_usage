# ADR 0028: Structured Subagent Replay Accounting

## Status

Accepted

## Context

Newer Codex structured subagent forks can begin with a replay of the parent
task's cumulative token history under the child task id. The child model and
own activity begin later at a `turn_context` followed by
`inter_agent_communication_metadata`.

The parser previously treated only the first cumulative snapshot as inherited.
It emitted every later replay delta as fresh subagent usage, before a model was
known. This duplicated parent usage and produced a large unpriced `unknown`
model bucket. A 2026-08-12 live-corpus audit found the same boundary pattern in
all 53 affected files. In a representative file, 333.2M replayed tokens were
removed while 11.6M actual subagent tokens remained attributed to
`gpt-5.6-sol`.

## Decision

For a structured subagent whose root metadata has `forked_from_id`, cumulative
token snapshots before `inter_agent_communication_metadata` establish the
delta baseline but do not emit usage records. The preceding `turn_context`
still captures the model, effort, turn, and collaboration mode for subsequent
own work.

The own-activity boundary is part of the serialized append checkpoint state so
full and tail-only parsing remain equivalent. Legacy structured subagents that
are not forks, user-visible root forks, and ordinary root tasks retain their
existing accounting behavior. Parser-cache version 6 rebuilds disposable
derived rows once so inflated version 5 records cannot survive the correction.

## Rejected Alternatives

- Relabeling `unknown` rows with the parent or eventual child model preserves
  duplicated usage and assigns a price to tokens that were not consumed again.
- Dropping every unknown-model record would hide legitimate future formats and
  unrelated missing evidence.
- Timestamp, path, or row-count heuristics are weaker than the explicit Codex
  relationship and inter-agent boundary.
- Correcting aggregates at report time leaves invalid cached usage available to
  CLI and other callers.

## Consequences And Guardrails

Parser fixtures cover replay removal, model attribution, legacy subagents, and
an append checkpoint immediately before the own-activity boundary. Full and
append parsing must produce the same records and checkpoint state. The bounded
row relevance classifier must retain the inter-agent boundary, and future
parser changes must continue updating replay snapshots as cumulative baselines
before discarding them from emitted usage.
