# Local Companion Checkpoint: 2026-10-06

## Scope

This records the dependent local implementation and the resumed synthetic host
probe after the user configured the runtime key locally. It is not acceptance
of the complete companion or live-data sharing. No live home, installed VS Code
extension or OS service was changed. A foreground synthetic tunnel and private
ChatGPT test plugin were used; no public plugin, VS Code release, version bump,
tag or PR was created. The tunnel and local browser-test server are stopped.

The candidate contains shared captured-ledger analytics, an authenticated
allowlisted API, isolated sharing-disabled MCP adapter, Usage/Storage UI,
conversational workflow and disabled stdio example. ADRs 0050/0051 and the
approved plan record the connection and observation contracts.

## Checks

| Check | Result |
| --- | --- |
| Root Python suite | 1,498 passed, 1 Windows-only skip |
| Isolated probe/adapter Python suite | 27 passed |
| Root and isolated Ruff | Passed |
| VS Code tests/build | 28 passed |
| Skill validator | Passed, with isolated PyYAML 6.0.3 |
| Companion browser harness | Chromium/WebKit/Firefox interactions, Day/Night, 1440/390/360 px; 18 screenshots |
| Synthetic feasibility browser harness | Same browsers/themes/widths; 18 screenshots |
| Whitespace checks | Passed |

Core tests verify monetary/token/credit parity, deterministic dates, replayable
scopes versus resolved calendar ranges, exact bounded breakdowns, one-transaction
comparison, zero source-file reads, warm-query zero repricing, original-revision
cursor pages after a committed revision change, expiry, opaque selections and
excluded metadata. A real loopback HTTP adapter test uses a disposable captured
ledger; it verifies core parity, compatibility/authentication, offline state and
safe errors. Protocol checks include in-memory and subprocess stdio transports.

Storage tests cover selected scope, changed membership before a content scan,
frozen results after a later inventory change, foreign-job rejection, and polling
or cancellation while another query waits behind heavy I/O. Read-only review
found the broad-lock cancellation failure and the filtered-share denominator
error; both were fixed at their owning contract and regression-tested.

Bridge tests cover incoming selection, period/group/metric switches, API cost
default, remaining-quota semantics, ask/fullscreen context, action confirmation,
job cancellation, offline recovery, mixed-revision rejection and superseded
requests. Wide Day and narrow Night screenshots were visually inspected.
The action bridge uses synthetic receipts/jobs; actual analysis behavior is
covered separately by disposable core tests.

## Actual Synthetic Host Probe

On 2026-10-06, the user entered `CONTROL_PLANE_API_KEY` in the ignored local
configuration. Its value was not printed, entered into the plugin form, passed
in CLI arguments or included in Git. Launcher doctor checks passed; the running
tunnel fetched authenticated remote metadata and returned ready on its loopback
health endpoint. Doctor alone is not proof of remote authentication.

`Codex Usage Test` is installed as a private development plugin. ChatGPT showed
the Personal context and Platform showed one associated ChatGPT workspace for
the intended organization. This is useful positive scope evidence, not an
independent audit of workspace membership or every possible authorized reader.

| Actual check | Observed result |
| --- | --- |
| Connection and discovery | Exactly `probe_usage` and `open_probe_dashboard`, both read-only |
| Global plugin entrypoint | Rendered 7-day/all synthetic cost $120.40 and 133M tokens |
| Dashboard queries | Today/all $17.20; Today/Demo Alpha $12.40 and 11M tokens |
| Conversation context | Ask generated a correct synthetic project comparison and identified it as synthetic |
| Conversation render tool | Today/Demo Alpha opened inline with matching scope and values |
| Panel and fullscreen | Component expansion opened a workspace side panel; the host fullscreen control expanded it, preserving scope |
| Themes | Day and Auto/dark inspected in Safari; local three-browser matrices passed |
| Restart | Remote query succeeded after server restart; reopening recovered after one stalled Safari reload |
| Codex remote tools | Synthetic Today/Demo Alpha and Yesterday/Demo Beta queries succeeded in this chat |
| Codex embedded UI / local stdio | Not accepted; render tool output is not evidence of an embedded component |
| Tunnel shutdown | Foreground process exited cleanly; Reload remained Loading during the bounded observation, so disconnected UI acceptance is still open |

The host rendered the iframe with a transparent body over a dark surface. Day
theme originally painted only the body, leaving dark text unreadable. The shared
component now paints `main` with its theme background. Both harnesses simulate
the transparent-body/dark-host combination; the new assertion failed before
the fix and passed afterward. The corrected Day surface was also visually
verified in Safari after advancing the probe UI resource to v2, restarting and
refreshing tool discovery. Refresh alone had retained the prior rendering;
this does not establish a general host caching guarantee.

ChatGPT displayed **CSP off** in its development UI. No host security setting or
tool approval was weakened by this work; the declared empty resource CSP is not
proof the host enforced it. Resolve and retest that gate before sharing live data.
The plugin remains installed for further private tests; the tunnel is not running.

The generated test conversations used ChatGPT Work. After the user raised its
allowance impact, no additional model prompts were sent. Official documentation
states that [plugins work in Chat and Work](https://learn.chatgpt.com/docs/plugins),
and that [Work shares Codex usage](https://learn.chatgpt.com/docs/pricing).
Prefer ordinary Chat for lightweight conversational testing and direct component
interaction for UI checks. Exact private-plugin behavior in ordinary Chat and
the billing treatment of component-only calls have not been measured; do not
claim they are token-free.

## Synthetic Timing

Reproduce from the repository root:

```sh
uv run python extensions/openai/tests/benchmark_companion.py
```

One local run, four disposable tasks and 4,000 trusted events:

| Measurement | Time |
| --- | ---: |
| Fixture capture | 255 ms |
| Cold structured materialization | 321 ms |
| Warm structured query, median of seven | 0.44 ms |
| Adapter handshake plus warm query | 2.25 ms |
| Adapter + loopback warm query, median of seven | 1.08 ms |
| Cold HTML report | 307 ms |
| Warm HTML report, median of seven | 0.53 ms |

The summary was 4,367 bytes; the HTML report was 96,718 bytes. These are different
payloads, **not a before/after benchmark**. The fixture has no quota or image
history. It cannot establish performance on the user's large ledger, real
ChatGPT transport, VS Code transport, host rendering or predictive accuracy.
The UI currently loads several bounded tools sequentially; actual-host latency
must be measured before deciding whether a combined snapshot read is needed.

## Remaining Acceptance

- Complete private organization/workspace-access review and enforced-CSP checks.
- Verify bounded disconnect/recovery, host approvals, ordinary Chat, and local
  Codex stdio/UI capabilities. The synthetic probe's ChatGPT entrypoint results
  do not accept the complete Usage/Storage candidate.
- Settle deliberate sharing of human project/task labels; this candidate uses
  anonymized labels and cannot select projects by their real names.
- Prepare/install reviewed collector and private plugin connection wiring only
  after those gates and the specific sharing decision. Published 2.10.4 has no
  companion capability; the example configuration remains disabled/uninstalled.
- Measure large-ledger cold/warm/concurrent capture, real adapter/transport/UI
  time and result sizes separately. No real-host or Windows-host support is
  inferred from local checks.
- Run applicable platform package/smoke gates on the exact host-test candidate.

No completion or release decision follows from this local checkpoint alone.
