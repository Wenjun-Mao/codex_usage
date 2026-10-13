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
