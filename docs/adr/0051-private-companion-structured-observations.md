# ADR 0051: Private Companion Structured Observations

## Status

Accepted on 2026-10-06 for local implementation. Extends ADR 0050. Actual-host
acceptance and live data sharing remain deferred, not established by these tests.

## Context

Existing HTML and storage exports contain paths, titles, unrestricted errors and
local command links. Forwarding those exports would create an unsafe sharing
boundary. Queries must also preserve accounting and evidence when capture,
pagination, analysis and cancellation overlap.

## Decision

- Add capability `private-companion-v1` and schema 1 on dedicated authenticated
  loopback routes. Share captured-ledger materialization with HTML, using one
  read transaction and evaluation clock. Preserve the existing warm HTML path.
- The collector computes prices, Standard credit estimates, image states,
  economics, allowance and pace. The isolated MCP adapter has no database,
  source-file, collector-start or schedule implementation. It is sharing-disabled
  by default and refuses incompatible or non-VS-Code-owned collectors.
- Outgoing projections allowlist aggregate fields. Process-local keyed opaque
  handles resolve selections; project, agent and tree labels are anonymized.
  Human labels require a future explicit sharing decision. No raw status/errors,
  prompts, task titles, paths, images, bearer token or provenance leave this API.
- Query pages retain scope, revision, timezone and pricing basis. Cursors bind
  kind, dimension and snapshot; they do not read a newer revision. Stores expire
  after ten minutes, hold at most eight snapshots/32 MiB and cap page sizes at 100.
  Expired/oversized scopes fail explicitly. Comparisons use one read transaction.
  The replayable request `scope` stays separate from `resolved_range` calendar
  dates; preset results must not form an invalid preset-plus-custom-date request.
- The UI rejects mixed-revision loading and superseded requests, and shares only
  selected scope/view when deliberately asking a conversational question.
- Capture reuses the existing coalesced writer only on explicit request. The
  adapter never retries an action after an uncertain transport outcome.
- Storage has its own metadata observation, separate from ledger revision. Bind
  analysis to selected-tree membership and project scope, revalidate before
  content scanning, and freeze completed findings against that analysis inventory.
  A later refresh cannot replace findings or change the scoped share denominator.
- Blocking heavy-I/O waits occur outside control locks so queued inventory reads
  cannot block job progress/cancellation. Only companion-started job IDs can be
  controlled. Cancellation is cooperative, not diagnostic-cache rollback.

## Rejected Alternatives

Scraping HTML, copying monetary calculations into JavaScript, raw storage export,
and a second collector each violate existing ownership or sharing contracts.
Rebuilding pages from current data would silently mix revisions. Reconstructing
completed findings from later inventory would change the meaning of the result.
Holding one lock across I/O makes cancellation depend on the work it must stop.

## Consequences And Guardrails

Generic labels limit name-based exploration until the user approves specific
label sharing. Cold scopes materialize captured history; warm queries reuse
projected aggregates. Snapshot bounds can require a narrower request. Inventory
can update the existing metadata cache; explicit analysis can update diagnostics,
but neither changes task files. No deletion/transfer/settings tools are exposed.

Regression tests cover core parity, fixed clocks, zero source reads, warm pricing,
snapshot pagination, HTTP authentication and safe errors, membership change,
scope-preserving frozen findings, and cancellation during a waiting inventory.
The official SDK bridge harness covers interactions and layouts, not real host
entrypoints, access scope, transport latency or end-to-end predictive accuracy.
