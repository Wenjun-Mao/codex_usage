# Public Observability Capability Checks

Status: local diagnostics and source review, not causal correction or release
qualification. The original hosted delay remains after native input acknowledgment
and before style-expression entry. The final approved two-job batch remains unused.
Held source checkpoint: `2faef82fab86c1b1880a89d2a69cf1c4d18264f1` on local
`codex/held-temporal-trace-prototype`; it is not merged or pushed to a public ref.

## Owned Session Membership

The public AX route identifies the fixture through the owned UI app but returns
the UI PID. Public `ps -L` has no responsible-process or coalition keyword. Public
`getsid`/`getpgid` and `ps -g` provide a separate bounded namespace hypothesis,
without private libproc, argument/environment reads or an all-process scan.

The pinned SDK starts its browser launcher as a session/group leader; the actual
UI app can be a child rather than that leader. The updated held C helper checks
that the session leader occurs in the independently kernel-verified UI ancestry
to its controller, and records both UI and leader creation identity. It does not
adopt a session merely because a numeric group matches.

The controller first requires one unique fixture match and stable UI identity,
then rechecks identity before querying exactly that owned group with:

```sh
/bin/ps -g <verified-session-leader> -o pid=,ppid=,pgid=
```

Every returned candidate must share the verified session via public `getsid`.
Output is capped at 2048 characters and 16 members; duplicate, malformed, missing,
foreign-session and over-budget data refuse. No process name, command arguments,
environment, credentials or memory contents are read into the evidence. A second
AX/kernel check validates UI and leader creation fields after enumeration; changed
identity discards the returned membership. This remains capability-only and no
profiler target is selected.

Local macOS 27.0.1 / Playwright 1.62.0 / WebKit 26.5 result:

| Member | Parent | Group/Session | Role established by this probe |
| --- | --- | --- | --- |
| 80810 | 80797 | 80810 | Owned launcher ancestor, session leader |
| 80816 | 80810 | 80810 | Owned UI app, exact fixture AX match |

UI creation `1791962806.140677` and leader creation `1791962806.128097` were
unchanged before/after the query. No distinct renderer candidate was exposed by
this namespace. This does not establish that no renderer exists or that every
WebKit build uses the same namespace. Expanding to another/global session or
same-bundle affinity is not a permitted fallback.

Evidence in the held checkout:
`output/diagnostic/public-session-membership-ancestor/metadata.json`, SHA-256
`af2d17658906a49f5492504784a179e2927c2df44afef2037d2596f60ef18180`.
Observed run duration: 1.609s. This is not the controller's guaranteed end-to-end
bound; startup/context creation/teardown remain outside independent supervision.

The updated controller runs as a module because it imports the cohesive session
helper. Run the current session capability with:

```sh
env PYTHONPATH=scripts uv run python -m probes.check_public_ax_fixture \
  --helper output/diagnostic/public-metadata/ax-fixture-session-check \
  --output output/diagnostic/public-session-membership-ancestor --session-metadata
```

For the earlier AX-only checkpoint, use the module entrypoint with its original
helper and omit `--session-metadata`. That checkpoint does not accept the new flag;
its original helper remains required for reproducing its retained hash.

## Native DOM Event Stamp Liveness

A different hypothesis was to stamp trusted input delivery within the renderer
without selecting a PID. `check_dom_event_stamps.py` uses the original synthetic
single-day/night fixture at width 1440 and original pointer preparation and strict
observation helper, with `java_script_enabled=False` throughout. A test-side API
evaluation registers bounded metadata-only event listeners: type, trust flag,
handler entry, time origin and event timestamp, at most eight records. It retains
no key, target, text or coordinate data and does not prevent/redirect events.

The listener installation reported success. Real pointer input made the CSS
tooltip visible in 5.657ms, but the recorded event array was empty. The probe
explicitly reports `trusted_mouse_event_observed: false` and
`qualification_eligible: false`. Empty stamps do not locate an input delay or
prove a missing DOM event. They mean this listener was not an available stage
marker under the tested scripts-disabled setting.

Pinned WebKit `JSEventListener::handleEvent` checks script execution before calling
the handler; this is consistent with the observed lack of callbacks. Do not
enable scripts, synthesize JavaScript input, poll an injected promise or infer
native event timing from the empty array to make this probe usable.

The fixture SHA is
`e033b67c506b0e4b21f99acfa3fb83c37d2f77fc82ed3cab293780489734c901`.
Evidence: `output/diagnostic/dom-event-stamp-capability/capability.json`, SHA-256
`e8e69c1e0501a6abd3979c72fde21994c3a1c4de553f3d318541b72c5bd0c4d5`.
Observed controller duration: 1.106s. Tests retain scripts-disabled behavior,
unavailable-stamp semantics and the original guard even if evidence writing fails.

## Readiness Intervention Review

An attended, read-only GPT-6.1 Sol / High reviewer inspected the original artifacts
and pinned source; effective settings were unverified. The final was collected,
the agent closed and its Relay route removed. The parent checked the capability
results and reviewed the cited script, screenshot and receipt/source paths.

The affected second bucket is not the page's first interaction: trial/reset/
hidden/hit preparation and the first bucket's hover/hide/keyboard plus real Tab
already precede it. Both hosted arms record visible, focused, ready=complete for
the first four observations; those facts do not guarantee compositor completion.

The pinned mouse path defers receipt until core/backend rendering finalization,
and Playwright reports input success when the UI mouse queue drains. The retained
stall occurs **after** that acknowledgment, so deferred acknowledgment alone does
not explain it. Rendering can still occupy a later interval, but its extent is
not measured by the current clocks.

A public screenshot was considered as a readiness intervention, not implemented.
Its WebKit preparation enables stylesheet synchronization, forces geometry and
waits for fonts; snapshot creation paints into an image buffer. It is not a neutral
presentation-completion barrier. A passing screenshot arm could reflect elapsed
time, evaluation, stylesheet/layout/font work or painting/queue changes. Without
a source-backed stage marker and discriminating control, it would not establish
an omitted readiness precondition or an owning-layer fix. A relocated untimed
wait or passing diagnostic replay is not qualification.

## Retained Boundary

The held prototype still rejects collection entrypoints unconditionally. No
hosted job, new diagnostic batch, native attachment, SDK update, product change,
security/trust change, release tag or publication occurred in this checkpoint.
All 81 focused capability/temporal/notification/hover tests, Ruff and diff checks
pass; mock-only tests are not collection or release authority.

Stage A remains unresolved: no safe renderer association or usable native input
stamp was supplied by these routes, and no causal readiness correction was
established. This is a limitation of the tested paths and approved measurement
contract, not a proof that public observability is universally impossible. Keep
the remaining batch for a hypothesis/control that can change the delayed stage;
do not consume it on warm-up, tolerance or unsupported-interface experiments.
Stages B-F remain unachieved; U still awaits owner full-dashboard acceptance.

## Primary Sources

- Installed `ps(1)`, `getsid(2)` and `getpgid(2)` manuals; `ps -L` keyword inventory.
- [Pinned launcher isolation](https://github.com/microsoft/playwright/blob/v1.62.0/packages/playwright-core/src/server/utils/processLauncher.ts).
- [Pinned native event script-execution guard](https://github.com/WebKit/WebKit/blob/343e13bf22dca9d0ec227801419aab0f9001a32f/Source/WebCore/bindings/js/JSEventListener.cpp#L133-L170).
- [Pinned mouse receipt/rendering path](https://github.com/WebKit/WebKit/blob/343e13bf22dca9d0ec227801419aab0f9001a32f/Source/WebKit/WebProcess/WebPage/WebPage.cpp#L3788-L3819)
  and [finalization](https://github.com/WebKit/WebKit/blob/343e13bf22dca9d0ec227801419aab0f9001a32f/Source/WebKit/WebProcess/WebPage/WebPage.cpp#L5264-L5279).
- [Pinned input-success patch](https://github.com/microsoft/playwright/blob/v1.62.0/browser_patches/webkit/patches/bootstrap.diff#L14163-L14169).
- [WebKit screenshot preparation](https://github.com/microsoft/playwright/blob/v1.62.0/packages/playwright-core/src/server/webkit/wkPage.ts#L1258)
  and [preparation helpers](https://github.com/microsoft/playwright/blob/v1.62.0/packages/playwright-core/src/server/screenshotter.ts#L251-L269).
- [Image-buffer snapshot creation](https://github.com/WebKit/WebKit/blob/343e13bf22dca9d0ec227801419aab0f9001a32f/Source/WebCore/page/FrameSnapshotting.cpp#L83-L152).
