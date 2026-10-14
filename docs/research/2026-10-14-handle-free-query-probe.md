# Handle-Free Query Probe

Status: batch 2 completed at `352895d6`; both arms reproduced the original late
observation. No causal correction, qualification or publication is claimed.

## Evidence That Changes The Next Probe

Independent read-only audit, requested GPT-6.1 Sol / Medium (effective settings
unverified), examined the retained failed and passing logs at source `4c0bad1c`.
The manager independently checked the affected log lines and installed SDK source;
the reviewer was collected, closed and Relay unregistered.

| Run | Mouse ID / ACK | Affected inner / outer evaluation | Logged send to inner result |
| --- | --- | --- | --- |
| Unsampled `38501590699` | 373 / 02:33:49.687 UTC | 374 / 375 | .688 to 02:33:50.029: 341 ms |
| Scalar `38498780902` | 379 / 02:01:46.987 UTC | 380 / 381 | .988 to 02:01:47.343: 355 ms |
| Passing capability `38507547887` | 373 / 03:43:01.559 UTC | 374 / 375 | .560 to .565: 5 ms |

Within each run, page proxy 7, target page-8, context 3 and the adopted tooltip
handle stay stable from baseline through the affected query. The baseline and
style parameter objects are identical in the unsampled run. Adoption finished
before pointer preparation. Host preparation cannot explain hundreds of ms
before a send logged one ms after the mouse ACK. A send log precedes transport
send, however, and the outer routing ACK does not prove inner target receipt.

The scalar control is `tooltip.evaluate("() => 1")`, not a handle-free query:
its arguments still include the tooltip handle. Installed Playwright 1.62.0's
UtilityScript deserializes arguments and evaluates the expression before calling
the supplied function and reaching its clock marker. That work is untimed in
the renderer-body figures. Its actual duration remains unknown.

Evidence pointers: `output/qualification/hosted-unsampled-process-control/protocol.log`
lines 21617-21625; `hosted-scalar-control/protocol.log` lines 22058-22068;
`hosted-profiler-capability/protocol.log` lines 21644-21651. Installed
`coreBundle.js` generated UtilityScript is at line 19118, WebKit send at 45728.
These are run-local identities, not objects shared across runs.

## Batch 2 Contract

Two fresh, five-minute maximum jobs at one immutable source: unchanged unsampled
stamped-style replay (`control=none`) and `control=page-scalar`. Keep all 72 views,
fixture hashes, real inputs, hidden baselines, product scripts disabled, and the
strict input-through-observation `<250ms` check. No process sampling or profiler
attachment, privilege, SDK patch, runner change or extra readiness wait.

The new control calls the public `page.evaluate("1")` once after the original
input and before the original style read. It is a literal, takes no tooltip
handle or supplied function, and reads no DOM. Its whole latency remains inside
the original absolute budget; a late constant result cannot count as success.
This still uses Playwright UtilityScript and Inspector evaluation. Do not call
it raw protocol evaluation or claim that it eliminates all target preparation.

Preserve original failures, command/session IDs, HTML/binary identities and
actual sent argument shape. A delayed literal query narrows the cause away from
tooltip-handle/supplied-function work, but cannot distinguish IPC, dispatch,
common UtilityScript, VM work or scheduling. A passing arm without the retained
delay is inconclusive, not a fix. No repeat solely for green; review the two
results before deciding whether the last approved batch has a distinct purpose.

## Built-In Logging Feasibility

[WebKit's logging guide](https://docs.webkit.org/Build%20%26%20Debug/Logging.html)
documents JSC GC logging and distinguishes macOS defaults from Linux environment
channels. No defaults, security settings or user browser processes were changed.
One local synthetic 72-view replay requested `JSC_logGC=1` with browser logging;
it passed but emitted no GC records. Its visual inventory is retained under
`output/qualification/jsc-gc-feasibility-local/`. This lacks a positive telemetry
control and proves neither option propagation nor absence of GC. It is not a
hosted batch or qualification result. No GC logging arm is dispatched from this
negative feasibility observation.

Pinned source
[Options.cpp](https://raw.githubusercontent.com/WebKit/WebKit/343e13bf22dca9d0ec227801419aab0f9001a32f/Source/JavaScriptCore/runtime/Options.cpp)
parses JSC-prefixed options on Cocoa; the configured JSC binary contains the
GC logging strings. Those facts do not establish what reaches WebContent.
The [Heap implementation](https://raw.githubusercontent.com/WebKit/WebKit/343e13bf22dca9d0ec227801419aab0f9001a32f/Source/JavaScriptCore/heap/Heap.cpp)
emits pause/cycle durations, but no failed-interval telemetry was obtained.

Stages A-B remain unresolved; all C-F gates and owner UI acceptance remain intact.

## Local Preparation

At the uncommitted diagnostic candidate over `4c0bad1c`, the original 72-view
replay with the new control passes all 648 observations. Structured protocol
inspection finds 216 WebKit literal calls: expression `1`, six arguments,
argument-count value 1 with the API's null argument, and no non-UtilityScript
object handle. The literal remains in the main execution context. Original
monetary parity/work guards and Ruff pass; focused probe/workflow/sampler and
inventory checks pass 71 cases. Complete core passes 2,196 cases plus the one
approved skip in 68.12 seconds; all 2,197 collected/JUnit identities reconcile
against the preserved baseline before dispatch.

Evidence: `output/qualification/page-scalar-first-local/`; protocol 80,512,214
bytes, SHA-256 `c04b32c3c71748b676ae6ceac5950f28ad5d683e55a379719da895cbe33222e9`.
The configured browser-tree SHA-256 remains
`2e7611d2510e3215fcb38883a5c88a2ea50f06e8c055a0f6b147e61e9698d5ee`.
These are local preparation facts, not hosted qualification or a correction.

## Hosted Batch 2 Result

Both jobs are terminal, attempt 1, source
`352895d6dc5031c27a4dc3ef953901828a531fdf`, standard macOS 26.6.2 ARM64. No
sampling, profiler attachment, privilege or producer receipt was enabled.

| Arm | Run / job | Job duration | Original failure |
| --- | --- | --- | --- |
| Unchanged stamped style | [38519190750](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38519190750) / 115704739146 | 1m38s | 605.852 ms |
| Page literal | [38519192481](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38519192481) / 115704744610 | 1m22s | 482.973 ms |

Both preserve all 24 completed Chromium cases and fail observation index 219,
the second usage target in WebKit's first `single-day/night/1440` view. The
late state is genuinely visible/hovered but rejected by the unchanged guard.
All eight HTML hashes and complete recorded browser provenance match the old
unsampled failure. Parent and a requested GPT-6 Luna / Max read-only reviewer
(effective settings unverified) checked the retained bytes; reviewer collected,
context association clarified, closed and Relay unregistered.

The literal arm spends 475.840 ms in its extra query; subsequent real style read
is 2.865 ms, reporting 0 ms inside its renderer body. Its actual literal request
is inner 380 / outer 381: logged send 05:55:57.680 UTC, outer ACK .681, inner
number-1 result 05:55:58.155. No tooltip handle, supplied function or DOM read is
present in that literal's arguments. It still calls through UtilityScript.
The unchanged arm's style round trip is 603.279 ms, with a 0 ms renderer body;
same-origin entry clocks advance 943 to 1546 ms. Do not subtract these renderer
and host clocks to amend the acceptance duration.

Literal execution context is established by the creation chain, not by equating
injected-script and context IDs: `Runtime.evaluate` inner 79 explicitly targets
normal/main context 3 and returns UtilityScript object `3:1`; literal 380 uses
that object. `DOM.resolveNode` 297 explicitly adopts the tooltip into context 3
as `3:9`. The separate utility world is context 4. References in the literal
protocol: context events 21577-21578, creation 21599-21601, adoption 21962-21968,
literal 22107-22109 and real style 22110-22112.

Artifact 11873605443, unchanged arm, digest
`sha256:03da1699a415ef690c20aa771a6e2f78aad7ea1df31c857debacecad21add5ca`,
5,708,159 compressed bytes; retained directory
`output/qualification/hosted-literal-pair-unsampled/`, 30,050,627 bytes.
Artifact 11872559228, literal arm, digest
`sha256:f49c2e09a134076a3913d35afe20265cada5fdcd642339158d7c3510f322ef78`,
5,717,148 compressed bytes; retained directory
`output/qualification/hosted-page-scalar-control/`, 30,225,084 bytes. Both are
nonexpired at collection; workflow retention is 14 days.

This discrimination narrows the delay away from work specific to the tooltip
argument and supplied state function. It does not exonerate rendering triggered
by hover, or identify IPC, common UtilityScript work, VM or scheduling as cause.
Do not compare two different runners' durations as a speedup or causal effect.
One approved two-job batch remains; do not spend it without a new distinct probe.

## Further Nonattaching Feasibility

Ordinary public `BrowserType.launch(args=...)` rejects the documented Cocoa
key/value spelling before launching because the value looks like a page argument.
One capability-only attempt with the public explicit-argument mode retained the
three original flags (`--inspector-pipe`, `--headless`, `--no-startup-window`) and
added the same logging keys. It launched an owned script-disabled synthetic page,
but produced no Layout/MouseHandling telemetry. Retain both outcomes under
`output/qualification/cocoa-logging-feasibility-local/`; no SDK or preference
change was made. Neither this mode nor logging output is qualified or added to
the hosted observation path.

A separate self-only helper in the held prototype compiles against public SDK
`sysctl.h`/`AXUIElement.h`, checks complete `KERN_PROC_PID` metadata for its own
PID/parent/start time, and calls nonprompting `AXIsProcessTrusted`. Local execution
returned complete self metadata and trust=true without permission changes.
It queries no other PID or Accessibility element and proves no renderer
association. It is not wired into main or dispatched. A supported public
Accessibility association to the owned fixture remains a named feasibility
question; the privileged prototype's containment/export findings remain open.
