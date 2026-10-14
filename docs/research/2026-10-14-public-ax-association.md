# Public Accessibility Fixture Association

Status: local capability evidence, not renderer association, causal diagnosis or
qualification. Stage A remains unresolved. No profiler attachment, new hosted
diagnostic job, permission prompt, trust/security change or publication occurred.
One approved two-job diagnostic batch remains unused.

## Question And Boundary

The previous literal-query pair retained a long pre-expression wait even without
a tooltip handle. Failure-aligned renderer tracing still needs a supported way
to associate the actual renderer with the owned fixture. Public kernel creation
identity is not ownership, and same-bundle affinity is insufficient.

The public `AXUIElementGetPid` API reports a PID associated with an AX object.
WebKit's internal remote-tree registration suggests that fixture-specific AX
traversal is worth testing; it does not establish public renderer-PID semantics.
The check uses only public SDK declarations, not WebKit remote-token APIs.

## Isolated Implementation

Retained checkout: `/Users/wjmao/.codex/worktrees/temporal-trace-prototype/codex_usage`,
branch `codex/held-temporal-trace-prototype`, retained prototype checkpoint
`cbf003a6155cb7d89629d0ddfa399a67e56348d3`. The branch remains local/unpublished.

- `scripts/probes/public_ax_fixture.c` accepts a PID only after typed public
  `sysctl(KERN_PROC_PID)` metadata proves a stable ancestry chain to its own
  controller. Complete kernel responses and creation times are required.
- It checks existing Accessibility trust without prompting or changing it. It
  creates only an owned application AX root and starts traversal at that root's
  public Windows attribute, then follows children beneath those windows.
- The helper reads roles, associated PIDs and exact synthetic URL equality. It
  prints counts/booleans, kernel start fields and API error codes, not UI titles,
  text, values, raw kernel buffers, environment, arguments or URL contents.
- Traversal limits are 64 nodes, depth 16, ancestry depth 16 and a 50ms timeout
  on each AX element. A three-second elapsed check runs between nodes; the
  controller separately caps each helper subprocess at four seconds or the
  remaining phase deadline. Partial/changed arrays and URL-read errors refuse
  complete traversal instead of being treated as negative matches.
- `scripts/probes/check_public_ax_fixture.py` launches its own headless WebKit
  through the public Playwright API, with product scripts disabled and a unique
  synthetic file URI. Descendant discovery uses only `pgrep -P` on the controller
  and discovered owned branches, capped at 16 PIDs.
- Two snapshots are explicitly recorded: initial AX access and a second after
  a fixed 250ms initialization interval. AX initialization is potentially
  perturbing; this is not an uninstrumented acceptance replay or a hover priming
  fix. Actual start/end intervals and cross-snapshot creation identity remain
  inspectable. `attachment_allowed` is always false.

The 20-second deadline covers launch/navigation/discovery/helper phases, not a
hard end-to-end controller limit. Playwright startup, context creation and
teardown are not independently supervised. The evidence explicitly records
`controller_hard_deadline: false`; do not dispatch this as a bounded collector.

## Observed Result

Fresh reviewed run: macOS 27.0.1 ARM64, Playwright 1.62.0, helper compiled against
the installed public macOS 26.5 SDK with:

```sh
clang -std=c11 -Wall -Wextra -Werror \
  -isysroot /Library/Developer/CommandLineTools/SDKs/MacOSX26.5.sdk \
  -framework ApplicationServices scripts/probes/public_ax_fixture.c \
  -o output/diagnostic/public-metadata/ax-fixture-check
env PYTHONPATH=scripts uv run python -m probes.check_public_ax_fixture \
  --helper output/diagnostic/public-metadata/ax-fixture-check \
  --output output/diagnostic/public-ax-fixture-reviewed
```

The owned UI candidate was PID 70567, kernel creation time
`1791961498.904205`. Its initial snapshot visited three nodes, no WebArea, and
completed without an AX error. The recorded second snapshot visited eight nodes
at maximum depth seven and found exactly one WebArea with the unique fixture URI.
Both UI creation fields were unchanged; ancestry remained stable. The matched
WebArea's public associated PID was **70567, the same UI PID**, not a distinct
WebContent PID. Total observed controller duration was 1.436 seconds.

Other owned driver/launcher candidates returned `kAXErrorCannotComplete` (-25204)
for role access; these did not become valid fixture matches. Initial broad
application-child traversal reached menu-tree resource bounds. Narrowing the
entrypoint to owned windows addressed the discovery-layer scope, not the original
hover delay; no acceptance assertion changed.

Evidence in that held checkout:

| File | SHA-256 |
| --- | --- |
| C helper source | `6632a14effe3850493554205d52aa0ed607a76e8ea0829fd69cb5abb5b8eefdb` |
| Controller source | `9649ba747ac08f2082c791d0006f12723ab114f9aeb2745f36ca44c0055a47a0` |
| Compiled helper | `812abcd61638bcf3e6df0f764e8cc73001ab29dce5d154d0d9b37dbb61cac5c5` |
| `output/diagnostic/public-ax-fixture-reviewed/metadata.json` | `8761c2fbff21b2702bcbbd4ab3971c14ab5c23cd0e43755e49bda1896b6ed147` |

## Review And Guardrails

Attended read-only reviewer: requested GPT-6.1 Sol / Medium, effective settings
unverified. The reviewer corrected its initial renderer-association suggestion
after the observed UI PID result. Its final was collected and the agent closed
and unregistered. The parent independently inspected the public declarations,
pinned source and actual evidence.

Review found a short-array out-of-bounds risk, conflated URL error/nonmatch,
missing snapshot timing/start identity, and an overstated controller deadline.
The helper now refuses changed arrays before iteration, separates URL validity
from equality, and records timing/start fields. The remaining end-to-end bound is
explicitly disclosed, not claimed solved. Ten focused helper/controller tests
pass, including a real public-SDK compile and refusal of the controller PID
before any AX operation.

The separate temporal prototype now unconditionally refuses enabled collection
at context, preparation and finish entrypoints. Regression tests verify refusal
before SDK/selector/process/file work. Mock-only tests bypass that guard solely
to inspect retained unready mechanics, never to authorize dispatch.

The prototype's export checks now run before XML parsing and independently of
raw-package deletion, with a regression for an oversized export plus failed raw
cleanup. This is partial hardening, not collector qualification: privileged
descendant containment, complete artifact/stream limits and safe raw-writer
termination remain unresolved. All 52 focused helper/temporal/notification/hover
tests and Ruff pass. No main runtime or release proof was changed by this work.

## Interpretation And Next Boundary

This route establishes point-in-time fixture identity through the owned UI AX
tree on the tested build/host. It **does not identify the actual renderer**. Do
not promote the UI PID into a WebContent target, infer renderer ownership from a
role/URL alone, or interpret the result as universal AX impossibility.

UI/driver-only tracing would be a different measurement target and could not
substitute for renderer evidence. It still needs its own reviewed identity,
containment and payload/clock/resource contracts before any collection. Existing
bounded tracing approval is not proof that those technical conditions are met.

Do not spend the remaining hosted batch on this unresolved attachment route,
upgrade the SDK without an identified owning defect, weaken the 250ms guard,
enable product scripts or call private APIs. Stages B-F remain gated; U's full
dashboard owner review remains the publication gate.

## Primary Source Pointers

- Public macOS 26.5 SDK: `HIServices/AXUIElement.h` lines 133-185 (bounded attribute
  reads), 356-402 (application roots, associated PID and per-element timeout);
  `AXAttributeConstants.h` lines 1191-1200 (read-only URL);
  `AppKit/NSAccessibilityConstants.h` line 555 (public WebArea role).
- Public typed kernel declarations: SDK `sys/sysctl.h` lines 437, 472-498 and 800;
  `sys/proc.h` lines 97-101 (creation time). No private libproc ABI is used here.
- [Pinned WebKit remote AX setup and demand initialization](https://github.com/WebKit/WebKit/blob/343e13bf22dca9d0ec227801419aab0f9001a32f/Source/WebKit/UIProcess/mac/WebViewImpl.mm#L3928-L4071).
  Implementation evidence only, not callable public ownership APIs.
- [Pinned headless WebKit window construction](https://github.com/microsoft/playwright/blob/v1.62.0/browser_patches/webkit/embedder/Playwright/mac/AppDelegate.m#L326-L352).
  Headless does not necessarily mean no AX window; it does not guarantee a
  publicly identifiable renderer.
