# Local Companion Checkpoint: 2026-10-06

## Scope

This is the dependent local implementation authorized while ChatGPT credential
setup is deferred. It is not the approved milestone's actual-host acceptance.
No live home, installed extension, OS service or live tunnel was used. No public
plugin, VS Code release, version bump, tag or PR was created.

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

- Resume synthetic actual-host and private organization/workspace-scope checks.
- Verify ChatGPT sidebar/panel/fullscreen and local Codex tool/UI capabilities,
  restart, disconnect, host approvals and end-to-end conversational selection.
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
