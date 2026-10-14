# Qualification Pilot Receipt

Date: 2026-10-13. Status: journal pilot passes; prior normal/dry-run evidence is
retained. Current source qualification is held by hosted WebKit input latency.
This receipt is nonpublishing evidence, not release approval. No new tag,
Marketplace upload, credential/settings change or existing-version replacement.
Production promotion remains source-disabled.

## Source And Authority

- Implementation: `108e92c7` on retained `main`.
- Pinned candidate: `b01aa9c8d000d5192971b931f9ec49187e2164dc`.
- Corrected qualified source: `dc79adb616601959748480f8fac118fd9455e69f`.
- Transport correction: `b2814244bfa7d64d5bfdd0285cb5991e32c37095`.
- Guarded observation source: `8f6eb9d0e41822f362fe96ec1dbe2d7efbb690d3`.
- Owner approved the durable Git journal, scoped commits/pushes and nonpublishing
  normal, controlled-failure/retry and dry-run pilots.
- Unrelated untracked `apps/` is untouched and uncommitted.

## Retained Journal

Repository `Wenjun-Mao/codex_usage`, numeric ID `1224749210`.

| Domain | Fixed Ref | Pinned Orphan Genesis | Workflow ID |
| --- | --- | --- | --- |
| Production | `refs/heads/codex/publication-receipts` | `309d26365bea01b99c1570c9e624932522ab6212` | `383496116` |
| Synthetic pilot | `refs/heads/codex/publication-journal-pilot` | `53cfc38734eb431201bf313ac391353853e0627e` | `383496114` |

Bootstrap and independent readback verified exact origin JSON, one canonical
blob per tree, repository/workflow identity, empty parents and pinned roots.
Production cutover is 2.12.3; this is not retrospective proof of older uploads.
Never bootstrap again or force/reset these refs.

[Hosted journal pilot, attempt 1](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38441695598)
passed on the pinned candidate. GitHub rejected the stale sibling ref update;
the retained chain rejected replay. Readback found exactly two pilot entries:

- Sequence 1: `d39696b47c8b4bee5069028ed143ef4395e2928a`, synthetic darwin-arm64.
- Sequence 2: `413cd9a5f70fc0a393e82adb503429a7d08576c5`, synthetic win32-x64.

The pilot reported zero publication calls and zero production-journal writes.
Independent production readback remains at its genesis with zero events.
Ignored raw evidence: `output/releases/journal-*-origin.json` and
`output/qualification/hosted-journal-pilot/`.

## Qualification Gates

- Complete local Python suite after hosted fixes: 2,101 passed, one approved
  non-Windows skip, 65.96 seconds; all 2,102 identities reconcile with raw JUnit.
- Focused pinned-journal/workflow/artifact tests: 111 passed.
- [Normal hosted run](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38441697737):
  early metadata passed; core and Windows setup contracts failed as described below.
- [Corrected normal qualification, attempt 1](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38442424276):
  all eleven required jobs pass, including exact-VSIX native replay and unchanged
  250ms hover guards. Local inspection reports `qualified-not-published`.
- [Dry-run promotion](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38444551516):
  validation passes, publish skipped, no build/upload; its inspection equals local
  inspection. Qualification source/contract is unchanged.
- [Controlled failure/retry pilot](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38443928239):
  first attempt fails only its selected hover case; aggregation/native skip.
  Second attempt passes hover/aggregation and validates unchanged original
  package proofs, but native replay fails its 250ms observation guard at 273ms
  with the tooltip visible. That attempt is not qualified.
- Native Windows UI remains a coverage gap; Windows archive/collector/handoff
  checks are required and are not replaced by native macOS proof.

Workflow success, exact-byte qualification and a publicly verified release are
distinct states. New process acceptance does not itself authorize publication.

## First Hosted Findings

The first full pilot is not qualified. Node's custom reporter loader rejected a
Windows drive-letter path as an unsupported URL scheme. The owning runner now
uses `pathToFileURL`, with a guard exercising the real runner's emitted arguments.
The complete local extension run still passes all 48 cases.

The full Linux Python suite passed, but frozen monetary parity could not archive
its historical baseline from the new shallow core checkout. The owning job now
fetches complete Git history; the baseline and comparison remain unchanged, and
the workflow regression guard requires that history dependency.

These are source changes requiring a fresh qualification, not permission to reuse
old proofs or weaken assertions. Focused reporter/workflow/history tests pass 40
cases after the fixes. Original failed runs/artifacts remain retained.

The first run also captured a WebKit focus-tooltip visibility-observation timeout
after 24 completed cases. Later visible DOM is not within-deadline evidence.
Bounded local sidecar probes do not reproduce it; exact root cause is unresolved.
The separately qualified run passes unchanged guards, not a claimed flake repair.

The native retry failure is a separate whole-CDP-round-trip measurement, not proof
of a 273ms renderer delay. A dedicated read-only `native-hover-probe.yml` compares
plain and traced native replay of the original normal-qualified package. Its
protocol timestamps add no DOM/style reads, script injection or deadline changes;
instrumentation overhead is uncalibrated. Diagnostic output never produces
qualification or publication receipts. Original failure evidence remains retained.

## Exact Qualified Bytes

Version 2.12.2 is a nonpublishing process candidate only: the already published
tag is not moved or republished. Production journal eligibility begins at 2.12.3.
Hosted manifest SHA-256:
`5bc6b9338494e895845265c94c0189193588af7542115d5aa4fcc29d8793ab6c`.

| Target | VSIX SHA-256 | Embedded Collector SHA-256 |
| --- | --- | --- |
| darwin-arm64 | `a568eb74c18572631255d7d5d54e4226779a38606a739043dbf71992ab71fb40` | `94dfe4b3b6245154e93e0ef715e24e59b077f880402a2f3eda7c122e51e2d1e5` |
| win32-x64 | `de8971e8d653184c8e1781b73595e211f4571ae27e1a142120183f03c6d226f4` | `832f6bf05076dbb2df6a5d7640cd6e782d72a7242e0d31d7df9cba49daddd294` |

Each package has 25 individually verified shipped assets. Original native proof:
job `115457883772`, receipt artifact `11837082612`, originating attempt 1.
Its uploaded archive SHA-256 is
`c1250e9b76286d96452455ab8eeb8a41458b1b9ce85d90136e697d9622dbb60e`.

See the [measured profile](../research/2026-10-13-verification-and-release-profile.md)
for queue, execution-span and summed-runner-work boundaries.

## Native Transport Follow-Up

[Read-only plain/traced diagnostic](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38447513798)
passed both fresh-host samples using the original normal-qualified package.
Plain hover observations were 32/43ms and traced observations 35/73ms. These are
observer timings on different hosts; no overhead subtraction or causal speed claim.
The trace adds no style reads and does not supersede the failed retry.

Review confirmed fixed-delay reply polling and incomplete whole-command timeout
coverage. [ADR 0062](../adr/0062-native-observation-transport.md) defines the public
async event/Future correction. Reply/ACK order, correlation, expired stored replies,
closure, cancellation and pending-state cleanup are regression guarded. The exact
250ms input-to-observation guard and all real inputs remain unchanged.

Current local verification: 2,118 passed and one approved skip in 64.01 seconds;
all 2,119 collected identities reconcile. Focused native checks pass 51 cases.
A real Chromium CDP round trip and isolated local pinned-Code replay pass; the
latter exercises 21 inputs with script execution disabled and 13/15ms hover.
It uses revalidated historical package bytes for diagnostic purposes, not hosted
authority for the changed source contract. Monetary parity/work and Ruff pass.
The read-only review has no remaining correctness findings and is collected,
closed and unregistered. Standalone speed-main cancellation cleanup has existing
unconditional cleanup but is not newly exercised through a full speed-main fixture.

Fresh source-bound pilots:

- [Normal](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38450968712): failed WebKit focus observation.
- [Controlled failure/retry](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38450970364): cancelled before execution.
- Fresh dry-run promotion: pending successful normal qualification.

The new transport changes the execution-closure fingerprint. Earlier receipts
remain historical evidence, not qualification for this candidate. Renderer root
cause and general hosted flake reliability are not claimed solved.

## Current Held Gate

The owning observation contract now pre-resolves a stable tooltip handle and
starts one strict `<250ms` budget before real input. Keyboard setup uses the
verified preceding legend/usage target; no corrective focus follows real Tab.
[ADR 0063](../adr/0063-real-input-observation-budget.md) records the contract.

- [Normal source `8f6eb9d0`](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38455041352):
  attempt 1 failed WebKit keyboard/style observation at 453ms. One bounded
  failed-job rerun failed at 310ms inside locator hover before any style read.
- [Controlled failure/retry](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38455044042):
  attempt 1 failed exactly its requested first hover case; aggregation/native
  skipped. Attempt 2 reused the eight healthy gates but failed a WebKit keyboard
  call at 472ms before the first style read. It is not qualified.
- Pointer readiness has been separated from physical motion: original locator
  actionability remains through `hover(trial=True)` and the exact rendered
  coordinate must pass hit testing. Since the pinned driver moves during trial,
  pointer/focus reset and an explicit hidden baseline are required afterward.
  The same physical input budget remains. The 310ms observation covers the
  combined locator path, not proven readiness-only time.
  This fixes a measurement conflation, not the unexplained keyboard stall.
- Complete local verification of that correction passed 2,133 tests with one
  approved skip in 63.87 seconds; raw JUnit and collection reconcile all 2,134
  unique identities. All 72 script-disabled hover views pass. These results
  precede the hidden-baseline correction and do not prove fresh transitions;
  fresh full-suite/matrix evidence is required below.
- A separate bounded `hover-input-probe.yml` records SDK send/reply timing for
  the original inputs. It is read-only, runs no publisher/producer step, keeps
  failed evidence, and cannot qualify a candidate. Its debug overhead is not
  calibrated; results cannot justify subtracting time from the deadline.

Both failed runs are terminal. No repeated runs until green, engine removal,
timeout relaxation or product CSS patch is accepted without causal evidence.
Current-source full hosted/native qualification and fresh dry-run promotion
remain open. Production journal readback is still its empty pinned genesis;
no tag, publication, live data or secret/settings change was made.

## Fresh Hidden-Baseline Verification

Read-only GPT-6.1 Sol / High review found the pinned driver's trial-hover priming;
effective model settings were unverified. A script-disabled runtime probe
confirmed priming and pointer-away reset in Chromium, WebKit and Firefox.
The corrected fixture retains actionability/hit checks and requires hidden,
unfocused, non-hovered state immediately before each timed visibility input.

Fresh complete local verification passes 2,143 cases with the one approved
non-Windows junction skip in 64.55 seconds. Independent raw JUnit/collection
validation reconciles all 2,144 unique identities. All 72 browser views pass;
Ruff, frozen monetary parity and bounded-work guards pass. Raw evidence is
`output/qualification/hidden-baseline-final-core/` and
`output/qualification/hidden-baseline-hover/`.

Review found no blocking correctness issues after correction. Added regressions
exercise the real 250ms/472ms action-only rejection before a timed style read,
preserve original diagnostic failures, and restore both the module and `argv`.
The reviewer is collected, closed and unregistered; no workers remain.

The bounded `hover_input_latency.py` wrapper marks existing input/style calls
without adding DOM reads or inputs. The separate workflow records SDK protocol
timestamps. Both keep original failures and the unchanged guard; debug-marker
overhead remains charged and uncalibrated. Fresh hosted diagnosis/qualification
is still pending, not inferred from these local passes.

## Hosted Input Diagnostic

[Bounded diagnostic at `63c032c7`, attempt 1](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38461396621)
is terminal and failed the unchanged guard at 310ms in WebKit's first view after
24 completed Chromium cases. Original input markers report 3.16ms for mouse
motion and 306.98ms for the style-query round trip. The baseline was hidden;
the returned state was visible, late, and correctly rejected.

The raw protocol independently correlates page-proxy 7 input command 365 with
its 2ms reply. Style command 366 was sent through outer command 367 at
20:16:32.365 UTC; the outer ACK returned immediately, but the correlated target
reply arrived at 20:16:32.671 UTC. This localizes this sample to the target
style-query round trip, not pointer delivery or Python post-reply polling.
It does not separate CSS computation from browser/IPC scheduling or establish
visibility onset/paint timing. Marker/debug overhead is uncalibrated.

Raw retained evidence: `output/qualification/hosted-input-diagnostic/`.
No rerun until green is planned. One targeted diagnostic revision added renderer
performance-clock markers around the original style expression; it makes no
extra DOM/input calls, keeps product scripts disabled, declares test-side
evaluation instrumentation, and cannot produce qualification/publication proof.
Its completed result follows; current-source qualification is held.

Local verification of the renderer-clock diagnostic passes all 72 views with
648 unchanged observation calls and 1,080 original baseline/style reads.
Recorded renderer expression times are 0ms median and 1ms maximum, subject to
browser clock resolution; this is not paint timing or hosted evidence.
The full suite passes 2,146 cases plus the approved skip in 63.62 seconds;
all 2,147 unique identities reconcile. Ruff and focused diagnostic guards pass.
Raw evidence is `output/qualification/renderer-clock-local/` and
`output/qualification/renderer-clock-core/`.

[Targeted renderer-clock diagnostic at `7f690510`, attempt 1](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38462435683)
is terminal and fails the unchanged guard at 379ms in the same WebKit case.
Mouse input takes 1.73ms and the style round trip 377.21ms. Both baseline and
visible-state expression clocks report 0ms at the browser's available resolution;
the returned visible state remains late and rejected. Protocol command 366's
immediate outer ACK arrives at 20:24:27.168 UTC and target reply at 27.543 UTC,
independently retaining the 375ms target-response interval.

This sample excludes expensive execution of the synchronous style expression
as the source of that measured round trip. It does not locate the delay before
versus after expression execution, prove paint timing, or explain all earlier
keyboard stalls. Browser/IPC scheduling and observer delivery need further
causal investigation; no product CSS change or deadline relaxation is justified.
Debug/clock instrumentation overhead is uncalibrated and not subtracted.
Raw evidence: `output/qualification/hosted-renderer-clock-diagnostic/`.

Both bounded diagnostic runs and all qualification pilots are terminal. Current
source is not fully hosted/native-qualified, and no fresh dry-run promotion is
borrowed from older receipts. The pinned production journal remains empty;
source promotion remains false. No workers, tags, uploads or live-data changes.

## Prespecified Non-DOM Control Batch

The next investigation batch is two new, five-minute diagnostic dispatches:
one scalar control and one five-boolean object control, each immediately before
the unchanged real style read. Controls never replace style results, execute
only after the real input, and remain inside the original strict 250ms budget.
Document visibility/focus/readiness is sampled in untimed setup. Marker/clock
overhead is uncalibrated and never subtracted. No producer or publication proof
is emitted. Stop after each original failure, with no passing rerun.

Hypotheses: a delayed scalar followed by fast style would exclude DOM/style work
as necessary for the stall, but not distinguish target scheduling from transport
delivery. Consistently fast scalar versus delayed object in equivalent history
would support a serialization hypothesis; command position and host provenance
must be checked before inferring causality or changing the owning observer.
Actual launch logs will be correlated with the configured binary-tree digest,
SDK manifest, runner OS and viewport; configured identity alone is not loaded
process attestation. Independent Sol/High read-only review caught and corrected
timed document introspection and acceptance of a missing launcher before dispatch.
Combined control/clock tests reject exact-250ms overruns; missing and dangling
launchers are explicitly unavailable. All later qualification gates stay held.

Pre-dispatch verification: 2,155 core tests pass with the one approved skip in
65.36s; independent raw result/collection validation reconciles 2,156 identities.
The corrected scalar diagnostic passes all 72 views and 648 observations locally,
with a 14.25ms maximum including diagnostic overhead. No timed extra DOM reads
remain. Ruff, frozen monetary parity and bounded-work guards pass. Raw evidence
is `output/qualification/control-probe-core/` and
`output/qualification/control-scalar-corrected-local/`. These local diagnostic
passes are not hosted correction or release acceptance.

### Hosted Control Results

Both prespecified runs at `32b7b510` are terminal, with no retries:
[scalar 38498780902](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38498780902)
fails at 362.45ms; [object 38498782946](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38498782946)
passes all 72 views but reaches 228.68ms at the same second usage bucket in the
first WebKit view, after 24 Chromium cases. The scalar control itself takes
356.84ms, followed by a 3.17ms real style query (renderer expression 1ms). The
object control takes 217.20ms, followed by 5.14ms real style (renderer 0ms).
No passing diagnostic is adopted as qualification.

Protocol correlation retains scalar input 379 at 02:01:46.986/.987 UTC, control
380 through outer 381 at .988 with outer ACK .989 and target reply 47.343;
style 382 through 383 at 47.345 with target reply .347. The delay follows the
first post-input query, even when it has no DOM access and returns a scalar.
CSS computation and object serialization are therefore not necessary for this
observed stall; JSON-string conversion is not an evidence-backed correction.
Before-input snapshots are visible/focused/complete in both arms. This does not
exclude OS process throttling or separate execution scheduling from reply delivery.

Both SDKs are 1.62.0, browser version 26.5, macOS 26.6.2 arm64, and launch logs
use the inventoried `webkit-2336/pw_run.sh`. Their configured WebKit-tree digest
`2e7611d2510e3215fcb38883a5c88a2ea50f06e8c055a0f6b147e61e9698d5ee`
also equals the local tree. This excludes different bundled tree bytes, not all
environment or loaded-library differences. Raw artifacts are retained in
`output/qualification/hosted-scalar-control/` and
`output/qualification/hosted-object-control/`. The two-dispatch batch is exhausted;
any further probe needs a new causal hypothesis and control before dispatch.
Production journal/tag refs are unchanged; promotion remains source-disabled.

### Next Clock-Entry Discriminator

New two-dispatch batch: stamped original style without a control, and a stamped
non-DOM clock control before real style. The existing wrapper retains execution
duration and adds expression-entry `performance.now()`/`timeOrigin`; no timed DOM
read, event listener, extra input or post-observation RPC is added. Page URL is
recorded before timing. The strict original failure/result remains unchanged.

Hypotheses: a large same-renderer baseline-to-query-entry gap with fast baseline
and input protocol replies supports waiting before expression entry. A short
entry gap with a long correlated query round trip supports a post-entry delay.
The clock-control-to-real-style-entry interval can additionally bound the latter,
but includes delivery/driver work and following-query scheduling. Compare stamps
only when time origin, page/frame/context and original history agree in raw
protocol; missing/reset clocks stop interpretation. No cross-process subtraction,
paint conclusion, shape-based fix or passing-run adoption is permitted.

Pre-dispatch: all 72 local clock-control views and 648 observations pass;
33 focused probe/provenance/workflow tests plus Ruff and diff checks pass.
Baseline exclusion and exact-250ms overrun tests include the clock arm. Read-only
review found no implementation defect after those coverage additions. The
earlier 2,155-test full result belongs to the preceding scalar/object revision;
fresh complete qualification remains necessary after any causal correction.

Both stamped runs at `b3d5a48d` are terminal:
[direct style 38499551235](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38499551235)
and [clock control 38499552504](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38499552504)
each pass all 72 views/648 observations, at maximum 91.24ms and 150.89ms.
The original affected bucket is now 8.89ms/15.49ms, not a reproduced failure.
Those greens establish no causal correction. All eight document digests agree
across both batches, and bundled WebKit-tree digests agree.

The clock arm's longest interval is WebKit keyboard observation 278: baseline
entry 765ms, control entry 838ms and style entry 913ms share time origin
1791943862342. The host control round trip is 138.45ms and real style 4.95ms.
Delay appears on both sides of control entry in this shorter sample; it does not
uniquely locate the process or explain the earlier 357ms failure. Protocol/frame
correlation is still required before stronger attribution. Debug instrumentation
can perturb startup/scheduling, and the failure was not reproduced in this batch.

Fresh full core verification of the stamped source passes 2,158 cases plus the
approved skip in 66.85s, with 2,159 independently reconciled identities. Raw
local evidence is `output/qualification/renderer-entry-core/`; hosted evidence
is `output/qualification/hosted-stamped-style/` and
`output/qualification/hosted-clock-control/`. Owning-layer correction, cold/warm
acceptance and fresh release qualification are still held.

### Prespecified External Sampling Batch

Hypothesis: identifiable CPU work, blocking, or pipe/driver delivery work in the
owned driver/browser/WebContent path explains delayed intervals beyond the DOM
expression. Next batch has two five-minute jobs at one source: direct stamped
style with no sampler, and the same harness with a background OS sampler. No
observer callback or DOM primer starts collection. Sampler work/overhead cannot
count as qualification or be subtracted from the original 250ms guard.

Sampling is restricted to the GitHub-hosted macOS main diagnostic job. Discover
the owner's bundled WebKit process by ancestry, then bind reparented XPC services
by that verified executable-root affinity; sample only the owner's installed
driver. Retain executable hashes and loaded-image paths, recheck PID identity
before attachment, and capture each process once for eight seconds at 2ms.
The monitor is bounded to 90s and all sampler children are collected. Local/user
process sampling is refused. Sampler failure cannot mask the original observer
exception. Empty/missing samples and an absent reproduced stall are inconclusive.

CPU-active rendering/GC/JIT, lock/synchronous-wait or pipe-writer stacks will
guide the next owning-layer intervention; idle stacks alone do not establish
causality. The matched unsampled arm checks profiler perturbation. No activation,
SDK patch, runner change, waiting primer or timeout relaxation is introduced.

Pre-dispatch review corrected shared cleanup deadlines/process-group containment,
preservation of original failures across cleanup errors, and exact revision-2336
XPC `.Development` executable mapping. Kernel BSD creation timestamps, parent
and canonical executable paths are rechecked along with binary hashes before
attachment; the final PID-only attachment race remains a diagnostic limitation.
Fifty-three focused tests and Ruff pass. Full core passes 2,178 plus the approved
skip in 68.10s; 2,179 raw identities reconcile independently. Local unsampled
replay passes all 72 views. Monetary parity/work guards pass. Evidence is
`output/qualification/process-probe-final-core/` and
`output/qualification/process-probe-unsampled-local/`. No user/local process was
sampled; a self-only libproc ABI read verified the installed 136-byte structure.

### External Sampling Results

Both runs at `1b6325af` are terminal:
[unsampled 38501590699](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38501590699)
fails the original guard at 345.45ms in the same second WebKit usage bucket;
[sampled 38501592271](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38501592271)
passes all 72 views/648 observations, at maximum 150.80ms. No run is retried or
adopted as a correction. Document digests and bundled tree identities agree.

The failing renderer stamps are baseline 578ms and style entry 920ms in time
origin 1791945229105; expression duration is 0ms at clock resolution. Protocol
baseline 371 returns at 02:33:49.684 UTC, mouse 373 sends .686/returns .687,
style 374 through outer 375 sends/ACKs .688 and its target reply arrives 50.029.
This localizes this sample before expression entry, not to its synchronous body
or exclusively post-expression reply delivery. It does not identify preceding
input/render work, inspector dispatch/VM work or scheduling individually.
The nearby network-idle event at .690 is correlation, not a cause.

Four collected reports have successful exits/nonempty output and kernel-bound
identities: owned Node driver, Playwright UI process, Networking and WebContent.
Actual executable paths/hashes are retained in `samples/processes.json`. Loaded
WebKit, JavaScriptCore and WebCore UUIDs in both browser-process reports match
the same hashed local/pinned bundle, verified with `dwarfdump --uuid`.
The sampled affected hover is only 7.79ms input-to-observation; its later keyboard
sample is 146.41ms, not the original >250ms failure. Aggregate reports cannot
identify the culprit from a missing reproduced failure. UI/driver nominal
eight-second windows cover earlier startup; WebContent covers the affected view.
No individual stack is attributed to the failed unsampled run.

Raw evidence is `output/qualification/hosted-unsampled-process-control/` and
`output/qualification/hosted-sampled-process-control/`. The batch is exhausted.
Owning-layer correction, cold/warm qualification and stages C-F remain held.
Promotion is still false; pinned production journal and v2.12.2 tag are unchanged,
and v2.12.3 remains absent. Unrelated `apps/` and user windows/data are untouched.

Independent Sol/High review is collected, closed and unregistered; effective
settings remain unverified. It confirms the pre-expression bound and incomplete
temporal sampling, with no B correction established. Image paths are redacted;
matching loaded UUIDs do not independently attest exact loaded paths. No GPU
sample was captured. Missing completion timestamps and aggregate teardown stacks
prevent attribution to a particular interval.

A reviewed next hypothesis is post-ACK WebContent rendering/transaction work:
pinned [WebPage finalization](https://raw.githubusercontent.com/WebKit/WebKit/343e13bf22dca9d0ec227801419aab0f9001a32f/Source/WebKit/WebProcess/WebPage/WebPage.cpp)
flushes deferred hover acknowledgement before the later transaction/backing-store
work in the [drawing area](https://raw.githubusercontent.com/WebKit/WebKit/343e13bf22dca9d0ec227801419aab0f9001a32f/Source/WebKit/WebProcess/WebPage/RemoteLayerTree/RemoteLayerTreeDrawingArea.mm).
That is a source-supported mechanism, not attribution of the observed failure.
The next diagnostic refinement needs actual capture start/end bounds and
failure-aligned temporal evidence separating rendering, compilation/GC and
waiting, without DOM primers or measurement changes. A prearmed normal-world
JavaScript listener/rAF is not substituted for the script-disabled fixture;
script enablement, private-world use or runner redesign needs owner review.
No further dispatch or requirement relaxation is inferred from this checkpoint.
