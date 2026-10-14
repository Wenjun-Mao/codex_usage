# WebKit Temporal Probe Review Note

Date: 2026-10-13 (America/Toronto); checkpoint updated 2026-10-14.
Status: hosted capability preflight complete; privileged collection prototype held.
The owner also approved the autonomy bundle and
restarted the Goal without a wall-time constraint. Approval does not change the measurement
contract or authorize publication before the newly required owner UI review.

## Established Bound And Missing Evidence

At diagnostic source `1b6325af`, the unsampled run
[38501590699](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38501590699)
fails the original 250ms guard at 345.45ms. Same-renderer markers put about
342ms between the hidden baseline and style-expression entry; its synchronous
body reports 0ms at the available clock resolution. Input acknowledgement is
fast. This does not distinguish rendering, inspector preparation, waiting or
scheduling before expression entry.

The sampled control
[38501592271](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38501592271)
does not reproduce that failure. Its aggregate `sample` reports lack ordered
stacks and actual collection-completion bounds. More aggregation or nominal
window arithmetic cannot establish which work occupied the failed interval.
Both runs are terminal; there is no live job to await or rerun for acceptance.

## Newly Checked Feasibility Limits

- The installed `/usr/bin/sample` usage offers no temporal-output option.
  This is a local tool observation, not a claim about every macOS version.
- Local `xcrun xctrace help record` reports that the utility is unavailable.
  No local process was attached, and no installation or developer-directory
  change was made. This does not establish hosted availability.
- The sampled job's setup log identifies `macos-26-arm64`, image
  `20260907.0351.1`, macOS 26.6.2 (25G83). Its
  [pinned software inventory](https://github.com/actions/runner-images/blob/macos-26-arm64/20260907.0351/images/macos/macos-26-arm64-Readme.md)
  is the tool-discovery lead, not proof that tracing works in that job.
- Apple explains that
  [Time Profiler samples CPU execution](https://developer.apple.com/tutorials/instruments/determining-execution-frequency?changes=_9)
  and that
  [Thread State Trace is needed to investigate blocking](https://developer.apple.com/tutorials/instruments/getting-started-with-hang-analysis?language=objc%2Cobjc).
  A CPU-only trace may identify busy work; an absence of CPU samples cannot
  establish whether a thread was blocked or runnable but unscheduled.

## Proposed Batch Contract

Owner-approved batch: retain the existing maximum of two new five-minute jobs:
an unchanged unsampled control and one temporal-tracing arm at the same source.
Neither arm is qualification evidence. Preserve all 72 views, fixture hashes,
input history, scripts-disabled state and the original strict 250ms guard.

Preflight the hosted tool's actual version, templates, recording/export schema
and target-selection semantics before attaching. Verify that collection itself
is restricted to the kernel-identified owned processes, not merely filtered
after recording. Do not silently use all-process capture, elevated privileges,
security-setting changes, another runner, an SDK patch or a local user process.
Unavailable tools, unsupported process scope or insufficient temporal data must
produce an explicit unavailable result rather than a weaker substitute.

Retain actual tool readiness and collection start/end bounds, target PID/kernel
identity, binary digest, original protocol command IDs and renderer time origin.
Bound cleanup and export time as well as recording; preserve the original
observation failure if capture/export fails. Establish trace-to-host clock
alignment and uncertainty from tool-supported evidence before associating a
stack or thread state with an input interval. Do not subtract unrelated clocks.

Separate three possible findings: busy rendering/VM work, a blocked thread with
a supported wait reason, or runnable scheduling delay. A trace that omits the
failed interval, lacks readiness/alignment proof, or again suppresses the failure
is inconclusive. It does not qualify a passing run or justify a product fix.
The post-ACK rendering mechanism remains a hypothesis until temporal evidence
and a causal intervention support it.

The owner has approved this bounded extension. Tool privilege/system-wide scope
exceptions, additional batches and official toolchain updates are approved in
the [autonomy review](../plans/verification-and-release-efficiency.md#autonomy-approval-review),
subject to its boundaries. Stages B-F remain gated; `PROMOTION_ENABLED` remains false.

## Resumed Batch 1: Capability Before Collection

This batch first checks hosted `xctrace` location/version, recording/export help
and installed templates, with no attachment. Each command is bounded to ten
seconds and receives no repository/publisher token. Original input/style replay
remains unchanged. Missing tools or truncated help are explicitly unavailable,
not a reason to guess a trace schema or enable a broader instrument.
This feasibility dispatch consumes batch 1 of the three approved new batches;
its second slot need not be used. It cannot establish a causal correction.
The next collection/control pair will be prespecified at one source after
the tool output establishes a supported temporal collection contract.

## Capability Result And Collection Hold

Read-only capability run
[38507547887](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38507547887),
attempt 1, source `7d40d3c587bfd074c73f196a5a724cbfd53b3d4f`, completed successfully.
All five commands returned exit 0 with untruncated output. The host supplies
`/Applications/Xcode_26.6.app/Contents/Developer/usr/bin/xctrace`, version
`16.0 (17F113)`, including Time Profiler and System Trace templates. Original
72-view/648-observation replay passed; no process was attached. All eight fixture
hashes match the retained failed baseline. A passing capability replay does not
establish target ownership, readiness, clock alignment or a causal correction.

Artifact `11868880833`, `hover-input-diagnostic-r38507547887-a1`, digest
`sha256:a8d70673f2e6bbc3b1261cecbcd98a8aa679c01a4bbf4e1e08e50d4a9c431abf`
retains the capability report and replay. This used one job in batch 1 of the
three approved batches; no temporal collection/control pair has been dispatched.

Independent review rejected the uncommitted collection prototype: unprivileged
signals cannot reliably contain root-owned recorder/export descendants; bundle
affinity does not prove which reparented WebContent belongs to the fixture; and
raw cleanup failure can bypass independent export bounds. Preserve it only in
the isolated `temporal-trace-prototype` checkout with its hold note. Main has no
temporal attachment option. Owner approval of tool privilege does not fix these
implementation and ownership gaps.

The older optional aggregate sampler shared those ownership assumptions. Both
its context and direct monitor now refuse live work before filesystem, SDK or
process activity, even on the approved CI host. Selection excludes reparented
same-bundle services. Historical cleanup/identity tests remain; synthetic refusal
regressions cover both entrypoints. Its private ABI is explicitly labeled as
historical, not public. This is a temporary safety hold pending a reviewed public
identity/fixture-association contract, not a completed replacement. Default
unsampled replay and read-only capability discovery remain available.

The local macOS 26.5 SDK explicitly labels `libproc.h` private. Public Endpoint
Security responsibility tokens require an approved entitlement and Full Disk
Access beyond this scope. An external probe has no public handle to WebKit's
existing XPC connection. No approved supported association mechanism is yet
established; no security changes or private-interface fallback were made. This
limit is not evidence of a Playwright defect. The strict measurement contract
and source-disabled promotion remain unchanged; stages A-B are unresolved.

One separable diagnostic defect is corrected on main: evidence-write failure in
`finally` must not replace an original input assertion. A synthetic disk-failure
test checks both preservation of the original guard and rejection of a missing
evidence file after an otherwise successful replay. This preserves failure
identity; it does not repair or explain the WebKit delay.
