# ADR 0050: Private Companion Integration Boundary

## Status

Accepted on 2026-10-06 for the integration boundary and feasibility workflow.
Actual ChatGPT/Codex host acceptance and the complete companion remain pending.
Extends ADRs 0033, 0037, and 0047 without changing VS Code distribution.

## Context

The user approved a private ChatGPT and Codex companion with dashboard UI,
conversational queries, explicit capture, and selected-task storage analysis.
The current HTML and storage exports contain filesystem paths and task metadata;
HTML escaping does not establish a data-sharing boundary. Host transport and
embedded UI capabilities also need actual-host verification. The user deferred
runtime credential setup on 2026-10-06 and authorized local implementation while
keeping that acceptance gate open.

## Decision

- Establish private connection and required dashboard entrypoints with a
  synthetic-only probe first. Local SDK tests are preparation, not actual-host
  acceptance. Do not silently replace the approved experience with headless tools.
  With the approved credential deferral, dependent local implementation may use
  synthetic/disposable fixtures; this does not authorize live connection or count
  as actual-host acceptance.
- Keep this probe isolated under `extensions/openai/`, with pinned SDKs and a
  typed synthetic result. It cannot attach a collector, read usage/tasks, capture,
  delete, migrate, or register a background service. Its browser UI has no external
  connection/resource/frame domain permissions.
- Use the official outbound tunnel client for private ChatGPT testing. Verify
  organization/workspace scope before live access. Runtime credentials remain
  local, excluded from Git and CLI arguments; user credential creation/entry is
  a handoff. The prepared launcher is foreground-only with loopback health access
  and does not inherit unrelated tunnel targets or unsafe debug settings.
- The eventual adapter connects to the existing authenticated local collector
  API. VS Code retains capture scheduling and the sole captured-ledger writer.
  Ordinary companion reads do not capture, rescan, migrate, or launch a substitute.
- Add allowlisted, versioned structured results before exposing real data. Do not
  scrape existing HTML or forward unrestricted storage/task exports. Returned
  results and UI metadata travel to OpenAI even though the ledger stays local.
- Comparison and pagination preserve snapshot identity; storage inventory has
  its own observation identity. Backend computations remain authoritative for
  pricing, coverage, allowance, and pace.
- The component paints its themed content surface explicitly, independent of
  the iframe body's background. Actual ChatGPT rendering made the body transparent
  over a dark host; body-only Day styling produced unreadable dark text. Both UI
  harnesses simulate this host condition and check the main surface in each theme.
  UI resource revisions advance when changing the probe bundle, with visual
  verification after tool refresh; host cache behavior is not assumed.

## Rejected Alternatives

Forwarding existing reports directly would leak excluded paths/metadata. A second
collector would violate capture ownership. Public inbound hosting introduces
deployment and access scope beyond the approved private milestone. A tool-only
or localhost-only demonstration cannot establish required host UI support.

## Consequences And Guardrails

Feasibility can stop at an account/credential dependency without claiming product
completion. The production collector, ledger, installed extension, and release
version remain unchanged during this probe. Do not connect live data until the
host/access and sharing boundaries are verified and the user approves the
specific data/destination. Document setup, shutdown, and outstanding actual-host
checks alongside the probe; test structured output, stdio, narrow layouts,
superseded responses, credential handling, and recoverable connection errors.
