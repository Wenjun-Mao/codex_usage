# Private OpenAI Companion

Local implementation candidate, **not an installed or accepted host integration**.
The user deferred ChatGPT credential setup; real sidebar/panel/fullscreen,
private workspace access, and Codex host acceptance remain pending. Nothing here
publishes a plugin, changes the installed VS Code extension, or enables sharing.
See the [approved plan](../../docs/plans/openai-plugin-companion.md) and
[structured observation contract](../../docs/adr/0051-private-companion-structured-observations.md).
[Local verification and remaining acceptance](VERIFICATION.md) record this checkpoint.

## Entry Points

- `probe/`: synthetic-only host feasibility server. No collector, ledger, task
  storage or capture access. Use this first for actual-host/access verification.
- `companion/`: sharing-disabled-by-default MCP adapter for the existing
  VS Code-owned collector. Twelve structured query/action/render tools plus a
  local Usage/Storage dashboard candidate, using core calculations.
- `web/`: official MCP Apps bridge, UI resources and local test harnesses.
- `skills/inspect-usage/`: prepared conversational workflow, not installed.
- `config.example.toml`: disabled local Codex stdio example, not installed.

The dashboard includes scopes/themes, category economics, daily/hourly activity,
project/model/agent breakdowns, project turn metrics, separate image activity,
allowance/pace/history, comparison, and explicit capture/selected-tree jobs.
Projects, agents and trees currently have anonymized labels; name-based selection
is not yet available. This limits real-world usability until an explicit label
sharing policy is settled. No deletion, transfer, settings, reset or migration
tools exist. Bridge checks do not prove identical UI support in actual hosts.

## Local Verification

From this directory:

```sh
uv sync --frozen
npm --prefix web ci
npm --prefix web run build
uv run pytest -q
uv run ruff check .
```

From the repository root, run the existing Python and VS Code suites too:

```sh
uv run pytest -q
uv run ruff check .
npm --prefix extensions/vscode test
```

The isolated pinned MCP SDK dependencies do not enter the bundled collector.
Build the UI before starting either MCP server. The adapter's disabled mode
can be exercised with `uv run python -m companion.server` over stdio; it does
not connect to the collector without explicit enablement.

## Sharing And Ownership

The ledger stays local, but returned aggregates and UI metadata travel to OpenAI.
The dedicated collector API projects only aggregate fields, safe model labels,
opaque selections and bounded evidence. It excludes raw conversations, prompts,
task titles, paths, image content, provenance, collector credentials and errors.
Bearer credentials are used only on authenticated `127.0.0.1` requests and never
forwarded to MCP clients, the component, browser storage or normal logs.

The adapter does not open SQLite, source tasks, start a collector or configure
a schedule. VS Code remains the single capture owner. Reload is a read; Capture
Usage is an explicit action through the existing coalesced writer. Analysis reads
only a selected tree and can update its existing diagnostic cache, not task files.
Cancellation is cooperative, not rollback. Transport loss after an action is an
uncertain outcome: check status before retrying.

Paged results bind scope/revision/timezone to expiring snapshots. Storage has its
own observation identity and revalidates tree membership before scanning. Query
errors are fixed codes, not raw local exception text. A stopped/incompatible
collector is reported rather than replaced with another writer.

## Deferred Local Codex Setup

The [official Codex MCP configuration](https://developers.openai.com/codex/mcp)
supports local stdio; this route needs no ChatGPT tunnel credential. The prepared
`config.example.toml` has both the MCP server and sharing disabled. Do not install
or enable it during the deferred host gate. Before a future live test:

1. Complete synthetic actual-host checks and review the intended data/destination.
2. Install a reviewed collector containing `private-companion-v1`; the currently
   published 2.10.4 collector does not contain this unreleased capability.
3. Deliberately configure the reviewed stdio example and selected `CODEX_HOME`.
   Enabling requires `enabled = true` and `CODEX_USAGE_COMPANION_ENABLED = "1"`.
   Tool policy prompts for non-read-only capture/analysis/cancellation actions.
4. Test status, scoped queries and disconnect before explicitly testing live actions.

No local Codex configuration, skills, marketplace catalog or plugin has been
installed by this work. Portable plugin/registered-server wiring is a later host
handoff, not a fabricated mapping to an uncreated ChatGPT connection.

To stop a future stdio integration, disable/remove its MCP configuration and
restart the host connection. This does not stop the VS Code-owned collector,
change the ledger/settings/services, or remove task files.

## Deferred Private ChatGPT Tunnel

Use the official [OpenAI tunnel client](https://github.com/openai/tunnel-client/releases)
and [Secure MCP Tunnels guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
The prepared macOS ARM64 client is 0.0.15; ZIP SHA-256:
`b2cae3aa9df45b4c2fe9b1d700ebacce39f9feb6a6b46b86e6499f9a51bf72ff`.
It lives under ignored `output/openai-plugin/tunnel-client/v0.0.15/`.

The empty private test tunnel exists, but its personal/private workspace mapping
is unverified. **No runtime key exists and no tunnel is running.** The launcher
still targets the synthetic probe only; it cannot expose live collector results.
Credential setup is deferred at the user's request, not required for local work.

When resumed, create/enter the runtime credential locally, never in chat, Git or
CLI arguments. `.env.example` contains field names; `.env` is ignored and should
be restricted to the current user (`chmod 600 .env` on macOS). It is not encrypted.

```sh
uv run python -m probe.tunnel init
uv run python -m probe.tunnel doctor
uv run python -m probe.tunnel run
```

`init` creates only the named ignored synthetic profile. The launcher passes the
credential via environment, excludes unrelated tunnel/debug targets and runs in
the foreground. Ctrl-C stops it; no service or startup hook is registered.
The ignored `output/openai-plugin/health.url` identifies loopback `/readyz`.

Verify private scope, synthetic tools, sidebar/global and thread/panel entrypoints,
fullscreen/themes, conversation context, restart and disconnect in ChatGPT before
live sharing. Remove the custom host plugin to disconnect it. Public directory,
public HTTPS hosting, account setup and deployment remain excluded.

## Browser Harnesses

```sh
node web/build-test-host.mjs
node web/build-companion-test-host.mjs
```

Serve `web/dist/` on loopback. From the repository root:

```sh
uv run python extensions/openai/tests/check_ui.py http://127.0.0.1:PORT/test-host.html
uv run python extensions/openai/tests/check_companion_ui.py http://127.0.0.1:PORT/companion-test-host.html
```

The companion harness exports fixtures from disposable captured data; its action
buttons use synthetic receipts/jobs, not the live collector. Both harnesses use
the official SDK bridge, Chromium/WebKit/Firefox and Day/Night at 1440/390/360 px.
They check scopes, remaining meter, action confirmation/cancellation, context,
races, consistency errors and layouts. Screenshots are ignored under
`output/playwright/openai-probe/` and `output/playwright/openai-companion/`.

These are local interaction checks, not host acceptance or real tunnel/UI latency
measurements. Use `tests/benchmark_companion.py` from the root for a disposable
synthetic core/HTTP timing record; its fixture scale and limitations are explicit.
