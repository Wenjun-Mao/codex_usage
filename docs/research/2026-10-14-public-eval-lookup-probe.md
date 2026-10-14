# Public Eval Lookup Probe

Status: final approved two-job batch completed at `c1ac6983`; both arms pass but
do not reproduce the retained stall. No correction or qualification is claimed.

## New Discriminating Boundary

Batch 2 delays a handle-free literal as well as the original state expression.
The delay is therefore not specific to the tooltip handle or supplied function.
Public session/AX checks cannot identify a distinct renderer for safe attachment;
script-disabled native event listeners emit no usable input marker. Those held
prototypes remain outside main's runnable collection path.

A local synthetic capability check shows that public `page.evaluate` can install
an accessor on the configurable public `eval` property with product scripts
disabled. It timestamps property lookup and returns the unchanged original native
function. The pinned [Playwright evaluator](https://github.com/microsoft/playwright/blob/v1.62.0/packages/injected/src/utilityScript.ts#L60-L76)
reconstructs arguments before this lookup, then evaluates the expression and calls
the supplied function. This boundary is not target receipt, UtilityScript entry,
VM dispatch, input delivery, visibility onset or paint.

## Prespecified Batch 3

Two new standard macOS jobs, at the same frozen main SHA, maximum five minutes
each. Both use the existing renderer-body stamp, unchanged fixture bytes, browser
pins, all 72 case identities, genuine inputs, hidden baselines, strict `<250ms`
guard and fresh navigation. No process collection, privilege, timed control query,
SDK patch, readiness wait, product JavaScript or publication receipt.

| Arm | Per-document public setup | Timed observation |
| --- | --- | --- |
| Descriptor control | Save and redefine the unchanged data descriptor | Original style query plus existing body stamp and marker integrity readback |
| Lookup clock | Save descriptor; accessor stamps `performance.now()` and returns original function | Same query/body stamp, with lookup mark in the same returned value |

Setup occurs before original case preparation, cleanup after the case. Both arms
have two additional untimed queries per WebKit document. Other engines are not
instrumented. Cleanup restores only the still-owned descriptor, never a replacement.
Failures in marker validation/cleanup cannot replace the original timing failure.
Every output is diagnostic-only; no producer receipt or qualified package exists.

If the clock arm reproduces the delay, compare lookup-to-body time in its same
monotonic domain. A large gap narrows delay to work after property lookup and before
the supplied body. A small gap leaves pre-lookup dispatch/reconstruction/scheduling
and post-body return work unresolved; host stage timings are separate evidence,
never subtracted from renderer clocks. The matched control checks whether redefining
the descriptor itself changes the observed fault. Different runner durations alone
are not an effect estimate. If either arm loses the fault, preserve the outcome as
potential perturbation/non-discrimination, not a correction. No green-seeking rerun.

## Clock-Domain Root Cause

The initial final local clock replay completed 46 cases and then rejected valid
marks because raw `performance.timeOrigin` alternated by one millisecond with the
same document token. The original input guard was fast. Failed evidence is retained
under `output/qualification/eval-lookup-final-clock/`; it is not overwritten.

Pinned [Performance.cpp](https://github.com/WebKit/WebKit/blob/343e13bf22dca9d0ec227801419aab0f9001a32f/Source/WebCore/page/Performance.cpp#L97-L115)
uses a fixed monotonic origin for `now()` but reprojects the epoch origin through
approximate wall time on each read. Raw epoch equality was the wrong realm model,
not evidence of navigation. The fix belongs to this diagnostic's identity contract:
unique nonce, exact Performance object/`now` method identities, bound page/frame/URL,
fresh sequence and finite nonnegative relative timestamps. Epoch origin is sampled
once only as an immutable label. There is no one-millisecond tolerance, changed
deadline or cross-process clock arithmetic. Actual-JS regression tests vary epoch
readings while retaining the same Performance object and verify exact restoration.

The accessor can perturb reflection/JIT/recording. This uncertainty is explicit;
local capability and source inspection do not calibrate it or make it production
behavior. Requested GPT-6.1 Sol / High independent read-only review is collected
before source freeze; effective settings remain unverified. The reviewer found
no remaining source blocker, was collected, closed and Relay unregistered.

## Final Local Verification

Final source passes 2,234 core tests with one approved native-Windows-only skip;
all 2,235 collected/JUnit identities reconcile against the preserved baseline.
Focused marker/observation/probe/workflow checks pass 89 tests. Full Ruff and diff
checks pass. Monetary parity retains digest
`58c434d278baaa4a0f6d8acc660475f67dd6cba0fc5f8eb638f8327336fd588e`;
speed work guards retain zero quota-only language repricing/recovery revision drift.

Both instrumented arms and the normal uninstrumented path pass all 72 inventory-
bound local views. Each arm completes 648 original observations, 360 same-return
WebKit marker reads and 24 exact descriptor restorations. All eight HTML hashes
match the retained failed hosted batch-2 fixtures. The configured browser-tree
digest stays `2e7611d2510e3215fcb38883a5c88a2ea50f06e8c055a0f6b147e61e9698d5ee`.
Ring drops are explicit metadata; the latest mark for each observed query remains
fresh and attributable. These are preparation facts, not hosted reliability proof.

Evidence directories: `output/qualification/eval-lookup-final-core/`,
`eval-lookup-release-default/`, `eval-lookup-release-descriptor/`,
`eval-lookup-release-clock/`, `eval-lookup-final-parity/`, `eval-lookup-final-work/`.
The separate capability-only logging/eval source is preserved locally at
`e0acec9` in the held worktree, not merged/pushed. Its five focused tests and Ruff
pass; empty logging still does not establish propagation or absence of collection.

## Hosted Batch 3 Result

Both runs are terminal, attempt 1, workflow-dispatch on main, exact source
`c1ac6983f5becd47e3e47430621e3e6e74a9f728`, standard macOS 26.6.2 ARM64.
No extra timed control, process sampling, profiler preflight, privilege, producer
receipt, SDK/runner change or publication occurred.

| Arm | Run / job | Job duration | Outcome |
| --- | --- | --- | --- |
| Descriptor | [38541865502](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38541865502) / 115778309012 | 1m50s | 72 views / 648 observations pass |
| Clock | [38541867765](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38541867765) / 115778318891 | 2m22s | 72 views / 648 observations pass |

Observation 219, the retained failing second usage hover in the first WebKit
view, now has a trace span of 5.906ms / 22.016ms respectively. These trace spans
include baseline/diagnostic work and are not replacements for the strict guard.
The maximum trace spans across all original observations are 62.027ms / 60.680ms.
The clock arm provides 360 attributable WebKit reads; lookup-to-body gaps range
from 0 to 1ms at clock resolution. There is no failed interval to localize.
Same-protocol-clock setup roundtrips range 0-6ms / 0-14ms at log resolution;
there is no observed hundreds-of-milliseconds stall relocated into installation.
This does not exclude warming, changed evaluation shape, recording perturbation
or runner variation, and does not identify their effects.

Downloaded ZIP digests were independently recomputed and match GitHub metadata:

- Descriptor artifact `11882468134`, 13,290,227 bytes,
  `sha256:bebb7593942c0ae0ccd9e7bdc88154b2f05fd750cf3b5f1338f818a369fd3043`.
- Clock artifact `11881999801`, 13,354,536 bytes,
  `sha256:6f87102930b362df1e3bf1bb353243fabae401f6980ac09550e99cbf42654750`.

Both are nonexpired at collection, retained for 14 days. Local expanded directories
are approximately 80.2 / 80.8MiB, below 100MiB. Retained ZIPs and unpacked evidence:
`output/qualification/hosted-eval-lookup-{descriptor,clock}.zip` and corresponding
directories. The prior failed uninstrumented/literal artifacts remain intact.

Requested GPT-6 Luna / Max read-only audit independently validates the 72-case/
10-assertion inventories, eight file hashes, source/attempt/browser provenance,
24 exact restorations and 360 same-return reads (24 document tokens, 15 each).
Clock sequences are fresh and increasing per token; timestamp/domain/anchor
checks pass, with no validation failures. Final document readbacks disclose four
dropped historical ring records each; latest timed marks remain present. The
manager verifies artifact digests and interprets timing/protocol separately.
Reviewer collected, closed and Relay unregistered; effective settings unverified.

Both arms add document setup and change the diagnostic returned expression.
Their passing result cannot qualify the setup-free production path or establish
a causal correction. The final approved batch is spent; further hosted diagnostic
dispatch needs revised authority and a prespecified discriminating design.
Stages A-B remain unresolved, dependent C-F gates remain unachieved, promotion
stays disabled, and U awaits owner review in a full-dashboard Local Preview.
