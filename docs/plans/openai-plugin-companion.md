# OpenAI Plugin Companion

## Status

Implementation authorized by the user on 2026-10-06. Work is on the retained
checkout, starting with the synthetic actual-host feasibility gate. No public
publication or VS Code release is authorized by this companion plan.

The user wants the first milestone to be large enough to experience and test the
product's potential. A tool-only demo is not the intended deliverable.

The user selected a private ChatGPT plus Codex experience, including dashboard
UI, explicit Capture Usage, and selected-task storage analysis. Deletion, task
transfer, and settings changes remain excluded. On 2026-10-06 the user deferred
the ChatGPT runtime credential setup and authorized continuing local dependent
implementation. Actual-host acceptance is still required for milestone completion.

## Outcome

Deliver one complete private companion experience: explore the existing Usage
dashboard, ask questions about its underlying data, compare periods/projects/
models, inspect allowance and pace, and investigate task storage. Conversation
and dashboard should work together rather than behave as unrelated products.

Keep the VS Code extension, accounting semantics, captured ledger, and collector
lifecycle intact. This is an additional host integration, not a replacement app
or a cloud analytics service.

## Approaches

1. **Private ChatGPT plus Codex, with tools and MCP Apps UI (selected):**
   validates conversational analysis, sidebar/fullscreen navigation, and a panel
   beside a conversation. Requires private connectivity, account access, and
   explicit disclosure of the data returned to OpenAI. UI acceptance is required
   in ChatGPT; Codex tools are required, while its exact embedded UI support must
   be established in the host check rather than assumed.
2. **Codex-local first:** avoids hosted tunnel setup and public endpoints using
   supported local MCP transport. Full embedded dashboard support is a feasibility
   question; a headless success alone would not satisfy the requested milestone.
3. **Public ChatGPT service first:** could widen distribution but introduces
   public hosting, per-device access, authentication, operating cost, and public
   review before we have tested the product. Excluded from this milestone.

The shared directory does not guarantee identical transport or UI capabilities
across ChatGPT web, desktop, local Codex, and cloud execution.

## First Milestone Scope

### Interactive Dashboard

- Open Usage from a ChatGPT sidebar entrypoint and beside a conversation. The
  same component must handle fullscreen and constrained-panel presentation.
- Provide existing date presets, inclusive custom local-calendar ranges, project
  selection, Auto/Day/Night themes, and API-cost/token comparison controls.
- Cover the principal Usage sections: language totals and category economics,
  temporal activity, project/model/agent breakdowns, project economics, image
  activity with its separate pricing states, and account-wide Plan Allowance.
- Preserve existing presentation decisions: API cost default, remaining-quota
  meter fill, local reset time, compact pace wording, previous-window reference
  rules, disclosure of diagnostics, and single-day preset chart suppression.
- Include Task Storage inventory and explicit selected-tree analysis with job
  progress and cancellation. Never turn a storage lookup into a corpus analysis.
- Distinguish Reload (query current captured data) from Capture Usage (update the
  ledger through its existing writer). Include an explicit Capture Usage action
  so the private experience can be tested with fresh data; ordinary reads do not
  capture. Capture and selected-tree analysis are user-selected scope; exposing
  these actions does not authorize invoking them on live data during development.
- Show meaningful loading, empty, stale, collector-offline, incompatible-version,
  disconnected-tunnel, cancelled-job, and error states without fabricating data.
- Do not copy unsupported VS Code command links into the MCP component. Each
  included control must call the appropriate host bridge or shared backend API.

### Conversational Workflows

Expose a cohesive tool set, not one tool per table cell:

| Capability | Expected result |
| --- | --- |
| Usage summary | Selected-period language totals, category values, separate image results, and coverage |
| Usage breakdown | Project/model/agent/time slices with bounded drill-down and pagination |
| Usage comparison | Two explicit scopes with comparable units, values, changes, and coverage |
| Allowance status | Account-wide quota, observed credit balance, allowance reference, pace, reset and freshness |
| Storage inventory | Largest trees and missing-root/amplification evidence, without automatic analysis |
| Storage analysis | Explicit selected-tree job, progress, result, and cancellation |
| Capture usage | Explicit coalesced capture through the current collector |
| Open dashboard | Render a selected view and scope without attaching UI to every data query |

The implementation may choose precise names and split job polling/cancellation
as needed. Avoid arbitrary SQL, arbitrary paths, or an unrestricted command tool.

Queries should support questions such as:

- Which project had the highest API-equivalent cost this week, and which models
  contributed most?
- How did yesterday compare with the previous day, including cache behavior?
- What changed between the last two weeks for a selected project?
- At recent, daily, and cycle pace, how does exhaustion compare with reset?
- What is taking disk space, and what does analysis of this selected tree show?

The core computes all values and comparisons. The model explains observed
differences and identifies useful follow-ups; it does not invent prices, infer
billing from missing evidence, or claim causes from correlation alone.

### Conversation And UI Together

- A conversational request can open the dashboard at the same range, project,
  and relevant section used for its answer.
- A user can deliberately ask about the current dashboard selection. Share only
  the necessary selection context, not the entire report on every interaction.
- Query tools remain useful without UI. A focused render tool owns presentation.
- Preserve a view's filters during refresh/capture. Ignore superseded responses
  when rapid filter changes produce overlapping requests.
- Results disclose the actual scope, timezone, ledger revision, observation or
  last-capture time, price basis, coverage, and any truncation. Comparisons must
  use consistent snapshot evidence rather than silently mixing revisions.

## Architecture And Ownership

```text
Existing Codex files -> VS Code-owned collector -> existing SQLite ledger
                                  |
                         authenticated local API
                                  |
                         OpenAI MCP adapter
                          /              \
                structured tools     MCP Apps dashboard
                          \              /
                       private OpenAI connection
```

- Reuse existing aggregation, effective-dated pricing, allowance indexing/pace,
  image accounting, and storage jobs. Preserve raw observations and provenance.
- Add a versioned structured analytics boundary alongside the existing HTML
  report endpoint. Current `/v1/report` returns HTML and status, not a complete
  structured report. Do not scrape HTML or duplicate calculations in TypeScript.
- Keep shared query/materialization code cohesive and reusable by both report
  rendering and structured responses. Do not reorganize the repository into a
  new generic core/shared-UI framework merely to add this host.
- Retain the Python Usage renderer where practical. Add a host-specific MCP UI
  shell/bridge; reuse visual contracts and controlled report sections. Storage
  retains shared product semantics even where its host renderer differs.
- The collector remains the only writer of captured usage. The adapter must not
  start a competing writer, own another capture schedule, reset data, migrate a
  ledger on connection, or register an OS background service.
- Scheduled capture still depends on VS Code being open. If its collector is
  unavailable, report that state; do not silently launch a substitute. Freshness
  and capture-lifetime limits remain visible.
- Keep collector bearer credentials in the local adapter. They must not appear
  in model-readable results, component HTML, logs, or browser storage.
- Prefer existing caches and bounded queries. Warm UI/tool queries must not
  rescan rollouts, unnecessarily reprice events, or rebuild allowance history.

## Connection, Privacy, And Setup

- Proposed private ChatGPT route: keep the MCP server local and use Secure
  MCP Tunnel where available. Local Codex can connect directly over supported
  local MCP transport; a tunnel is not needed solely for that route.
- Verify actual account/organization/workspace permissions and host reachability
  before using live data. A runtime key, tunnel association, and running tunnel
  client are dependencies, not capabilities assumed to exist.
- Start the connectivity test with synthetic data. Confirm the chosen private
  connection is restricted to the intended test context before attaching a live
  collector. Ambiguous access scope must not expose live personal results.
- Explain that the ledger stays local but returned data travels to OpenAI and
  may enter model context. This integration is optional; the unchanged VS Code
  workflow retains its existing local-only behavior.
- Use allowlisted projections. Return required usage aggregates and selected
  labels, not raw conversations, rollout contents, prompts, images, filesystem
  credentials, absolute home paths, or unrestricted task metadata. Use opaque
  backend-resolved identifiers instead of exposing path-based project keys.
- Task titles and detail views require deliberate selection and a clear sharing
  boundary. UI-only metadata is not proof the data stayed on the computer.
- Provide one reproducible private setup path and a stop/disconnect path. Keep
  secrets outside the repository and tool outputs. No unattended OS service.
- Stopping or uninstalling the private integration leaves the VS Code collector,
  ledger, settings, services, and source tasks unchanged.
- Public MCP submission requires a stable reachable HTTPS endpoint; Secure MCP
  Tunnel alone is not a public-distribution backend. Public hosting, accounts,
  and directory submission are explicitly deferred.

## Likely Code Locations

Use the repository's existing layout rather than rename current directories:

- `src/codex_usage/agent_api.py`, `agent_reports.py`, `aggregation.py`,
  `report_breakdown.py`, `allowance_index.py`, `project_economics.py`, and image
  modules: discover/reuse existing calculations and expose structured results.
- New focused analytics/query-contract modules under `src/codex_usage/` and a
  small MCP adapter package there; avoid adding unrelated responsibilities to
  near-limit runtime/report modules.
- `extensions/openai/`: plugin manifest, skills, component shell, bridge code,
  private setup entrypoint, and host-specific tests.
- `tests/`: shared result parity, scope, privacy projection, collector ownership,
  compatibility, cache/I/O, and MCP contract tests.
- Existing VS Code tests and visual gates: regression coverage for the retained
  product, not a replacement release pipeline.

Record accepted host/data-sharing/structured-query contracts in an ADR during
implementation, following repository numbering. Link ADRs 0001, 0033, 0037,
0043, 0044, 0046, 0047, and 0049 as applicable; amend ADR 0047's distribution
scope only when an additional distribution route is actually accepted.

## Ordered Deliverables

Progress on 2026-10-06:

- Host feasibility is in progress. ChatGPT exposes custom MCP connections by
  Tunnel; Platform exposes tunnel creation. An empty private test tunnel was
  created and associated with the account's sole listed ChatGPT workspace.
  The workspace's personal/private mapping still needs verification before
  exposing live data.
- `extensions/openai/` contains an isolated synthetic-only MCP/UI probe. It has
  no collector connection or live data capability. Local protocol and bridge
  tests are preparation, not actual-host acceptance. Structured discovery and
  subprocess stdio checks pass. Chromium/WebKit/Firefox bridge checks pass for
  filters, context actions, response races, errors, and day/night layouts at
  1440/390/360 px. See ADR 0050 and the probe README.
- Runtime credential creation/entry is handed to the user. The local secret
  configuration is ignored by Git; no credential is stored in tracked files.
- ChatGPT credential setup is deferred at the user's request. Shared analytics
  and local adapter work can proceed against disposable fixtures. Required
  sidebar/panel, private access-scope, and Codex host checks remain outstanding.
- Shared captured-ledger materialization and schema-1 companion API are locally
  implemented with allowlisted projections, expiring pagination, snapshot
  comparison, allowance/pace, and selected-tree jobs. The single collector owns
  capture; blocked inventory work does not block polling/cancellation. ADR 0051
  records the reviewed contracts and guardrails.
- The isolated adapter exposes twelve tools and a Usage/Storage MCP Apps UI.
  Local core/HTTP/protocol tests and the three-browser bridge harness validate
  fixture behavior. This is a candidate, not actual-host acceptance. All live
  sharing remains off; project/task labels are anonymized, so name-based querying
  and private plugin connection/package wiring remain handoff work.
- Disabled stdio setup and a conversational skill are prepared, not installed.
  No VS Code version bump, plugin publication or live-data capture is part of
  this checkpoint.
- [Local checkpoint evidence](../../extensions/openai/VERIFICATION.md) records
  tests, disposable timing, reviewed fixes and remaining actual-host gates.

The read-only API/privacy review identified that current HTML and storage
exports contain paths and task metadata. Reusing them directly is not safe:
the structured boundary must apply allowlisted projections before tool/UI
serialization, and comparisons/pagination must preserve one snapshot. Storage
inventory has its own observation identity rather than the usage revision.

1. **Host and connection feasibility:** demonstrate a synthetic tool and real
   embedded interactive component in the chosen host, including required sidebar
   and panel entrypoints. Establish Codex tool availability and exact UI support.
   Test private access scope, connection restart, and disconnect. If a required
   host capability is unavailable, return with evidence and revise the plan;
   do not silently downgrade the milestone to a tool-only demo.
2. **Shared structured analytics:** define scope/result schemas, add bounded
   query and comparison support, preserve existing calculation/cache paths, and
   prove parity with current reports on synthetic and disposable ledger data.
3. **MCP workflows and skills:** expose the scoped tools, freshness/coverage,
   errors, capture/analysis confirmation boundaries, and headless workflows.
   Connect to the existing collector without creating another writer.
4. **Complete dashboard experience:** implement host controls and rendering,
   Usage/Storage views, conversation-to-view context, capture/analysis progress,
   themes, accessible interactions, and responsive panel/fullscreen layouts.
5. **Private acceptance and handoff:** package the private integration, document
   setup/disconnect and privacy boundaries, validate in the real selected hosts,
   benchmark core/adapter/transport/UI separately, and present for review before
   any publication or public release decision.

Default to serial implementation on the retained checkout. No new task, worktree,
parallel writer, PR, public server, version bump, or publish is implied by this
plan. Commit/push decisions follow the user's applicable authorization; review
the actual candidate before any release.

## Observable Acceptance

The first user-facing milestone is complete only when:

1. ChatGPT opens the real dashboard through its sidebar and conversation panel,
   including fullscreen presentation. Local Codex conversational tools work,
   and its tested embedded UI capabilities and limits are documented. A
   standalone localhost preview is insufficient host evidence.
2. A user can change ranges/projects/themes, inspect the principal Usage and
   Storage views, and run explicit capture and selected-tree analysis.
3. The sample conversational questions above work, including a follow-up drill
   down and a dashboard opened at the same scope. Headless tools also work.
4. All displayed monetary/token/credit/image/allowance values match the existing
   core oracle on identical revisions, including partial/unpriced evidence.
5. Concurrent VS Code and plugin use retains one collector and the same ledger;
   reconnecting/restarting/disconnecting does not duplicate events or captures.
6. Query, opening UI, and Reload read captured data without capture or JSONL
   rescans. Explicit actions reuse coalescing and the existing heavy-I/O lane.
7. Stale readings, reset/credit transitions, missing data, offline collector,
   connection loss, incompatible collector, invalid scope, and cancelled jobs
   produce accurate, recoverable states.
8. Privacy tests prove excluded fields and secrets cannot leak through tools,
   UI resources, model context updates, or normal logs.
9. Browser checks cover Day/Night, keyboard use, focus, tooltips, constrained
   conversation-panel widths and fullscreen; actual-host checks confirm bridge,
   entrypoints, and context behavior beyond screenshots.
10. Benchmarks report warm/cold core time, adapter overhead, transport, UI render,
    payload size, and capture concurrency separately. Warm-path work counters
    remain bounded and VS Code baseline performance does not regress materially;
    unexplained regressions are investigated before calling the milestone done.
11. Existing Python/Ruff/VS Code checks and relevant platform package smoke gates
    pass. Real personal-host acceptance starts on this Mac; Windows host support
    is not claimed from package tests alone.
12. Setup and stop/disconnect are repeatable and preserve the existing VS Code
    installation and all live data. No account-wide adoption or public release
    readiness is inferred from this private acceptance.

## Exclusions

- No replacement standalone app, cloud ledger sync, telemetry/adoption tracking,
  public backend, commercial account system, or public directory submission.
- No task deletion, cleanup automation, transfer/import/export of tasks, ledger
  rebuild/reset, service handoff, or capture-schedule/settings mutation.
- No raw rollout exploration, generic SQL/shell/file access, new usage pricing,
  reconstructed missing billing evidence, or forecast methodology changes.
- No claim that every VS Code feature must be ported before evaluating the
  companion, or that a shared listing gives identical UI on every surface.

## Sources And Technical Dependencies

Official documentation read during planning:

- https://developers.openai.com/plugins/concepts/plugins
- https://developers.openai.com/plugins/build/plugins
- https://developers.openai.com/plugins/build/extensions
- https://developers.openai.com/plugins/build/chatgpt-ui
- https://developers.openai.com/api/docs/guides/secure-mcp-tunnels
- https://learn.chatgpt.com/docs/extend/mcp

Product scope is settled by the user's two selections above. Transport access,
private connection permissions, actual-host UI support, and compatible collector
availability are early technical investigations. If these prevent the selected
experience, present the evidence and revised options before reducing scope.
Neither a saved plan nor a synthetic connection test establishes that the
complete experience has already been validated.
