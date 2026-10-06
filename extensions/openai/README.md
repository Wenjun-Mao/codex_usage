# Private OpenAI Companion: Feasibility Probe

This directory currently contains the **synthetic-only host feasibility probe**,
not the complete companion. Its two tools and dashboard have no collector,
ledger, task-storage, capture, or deletion access. The product scope remains in
[the approved plan](../../docs/plans/openai-plugin-companion.md).

## Local Checks

From this directory:

```sh
uv sync --frozen
npm --prefix web ci
npm --prefix web run build
uv run pytest -q
uv run ruff check .
```

The isolated dependencies do not change the production collector or VS Code
package. Tool outputs are typed structured results with an explicitly synthetic
source; the UI uses the official MCP Apps SDK. External resource, connection,
and frame domains are empty. Tests exercise in-memory and subprocess stdio
transports. Build the UI before running the server or tests.

## Private Tunnel

Use the official [OpenAI tunnel client](https://github.com/openai/tunnel-client/releases).
The prepared macOS ARM64 client is version 0.0.15; its ZIP SHA-256 is
`b2cae3aa9df45b4c2fe9b1d700ebacce39f9feb6a6b46b86e6499f9a51bf72ff`,
verified against the official release asset digest. It resides in the ignored
`output/openai-plugin/tunnel-client/v0.0.15/` directory. Other installations can
pass their own verified binary with `--client`.

Create a private tunnel using Platform, associated only with the intended
ChatGPT test workspace. The runtime-key principal requires Tunnels Read + Use;
tunnel management requires Read + Manage. See the official
[Secure MCP Tunnels guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
The user must create/enter the runtime credential locally. Never paste it into
chat, commit it, or put it in a CLI argument. The `.env.example` shows the two
configuration fields; `.env` is Git-ignored. Restrict `.env` to the current user
on macOS (`chmod 600 .env`). It is not an encrypted credential store.

```sh
uv run python -m probe.tunnel init
uv run python -m probe.tunnel doctor
uv run python -m probe.tunnel run
```

`init` creates only the ignored, named synthetic profile, with a loopback-only
ephemeral health port. It does not overwrite an existing profile. `doctor` and
`run` load the runtime key through an environment reference, not profile text.
The launcher does not inherit unrelated tunnel/Harpoon/debug settings.
`run` is foreground only: no OS service, background collector, or unattended
startup is registered. Stop with Ctrl-C. The health URL is written to the
ignored `output/openai-plugin/health.url`; check `/readyz` before discovery.

While the tunnel is healthy, use ChatGPT Plugins -> Add custom MCP server ->
Tunnel. Select this test tunnel and only its intended workspace. Verify actual
sidebar/global and thread/panel entrypoints, filter interaction, fullscreen,
theme, selection context, restart, and disconnect. These tests are still
pending; local protocol tests do not establish ChatGPT/Codex host support.

Stopping the probe leaves the VS Code collector and live data unchanged.
Removing its custom plugin disconnects the private host. No public listing,
cloud ledger, model API calls, or billing operations are part of this probe.

## Browser Harness

`node web/build-test-host.mjs` builds an additional local SDK bridge harness in
`web/dist/test-host.html`. It reuses fixtures from the Python probe and is not
advertised as an MCP resource. Its mock host can check UI controls, race/error
states, and responsive layouts. It is test infrastructure, not evidence of the
required actual-host milestone.

Serve `web/dist/` on loopback, then from the repository root run
`uv run python extensions/openai/tests/check_ui.py http://127.0.0.1:PORT/test-host.html`.
This uses the repository's existing Playwright verification environment. Checks
cover Chromium, WebKit, and Firefox, day/night themes, widths 1440/390/360,
meter semantics, filter/metric controls, context actions, error recovery, and
superseded responses. Screenshots go to `output/playwright/openai-probe/`.
