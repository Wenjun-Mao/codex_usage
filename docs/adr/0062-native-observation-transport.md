# ADR 0062: Native Observation Transport

Status: implementation candidate, 2026-10-13. Fresh hosted qualification required.

## Context

The normal exact-VSIX native pilot passed, but a controlled-retry native run failed
its strict 250ms hover-observation guard at 273ms. The tooltip was visible in a
subsequent read. That is an observation failure, not renderer-delay proof.
Separate plain/traced samples of the same package passed; instrumentation is not
timing-neutral and those samples do not supersede the original failed attempt.

The owning native harness has two concrete transport defects: nested replies
are delivered through a fixed 10ms page-timer polling loop, and its five-second
command timeout starts after the outer acknowledgment. A stored response can
bypass that timeout. The trace shows callback-to-return delay, but repeated JSON
parsing and uncalibrated instrumentation prevent attributing all of it to polling.

## Decision

Use public async Playwright CDP events with one pending Future per command ID and
attached session. Register before sending, accept either reply/ACK order, and
bound both by one absolute command deadline. Reject expired commands even when
their reply is already stored. Errors, cancellation, target detachment and session
closure retire pending state and cancel in-flight waiters. No timer polling for
protocol replies; native helpers and both native entrypoints use the async API
consistently rather than mixing sync/async clients or adding a background bridge.

Keep OOPIF attachment, exact DOM-derived input/hit testing, script-disabled
webviews, real mouse/Enter/Tab, isolated profiles/in-memory credentials and the
original hover style-read sequence. The strict `<250ms` guard still starts before
real input and includes all input/observation transport. Do not subtract timings,
start the clock after ACK, relax thresholds or retry into passing receipts.

Rejected: shorter fixed polls/busy pings; they retain the flawed waiting contract.
Rejected: private Playwright internals, extra raw socket dependencies and threaded
sync bridges; the supported async event API provides the needed lifecycle.
Renderer latency is not inferred from Python-side protocol timestamps.

## Consequences And Guards

This changes the fingerprinted qualification execution closure; old qualified
artifacts are retained as historical evidence, not reused for the changed contract.
Production remains source-disabled. Fresh full qualification, controlled failure/
retry and dry-run promotion must pass before accepting this candidate.

Tests preserve every existing rendered-input invariant and cover reply ordering,
ID/session correlation, outer/protocol errors, missing replies, slow ACK, expired
stored replies, close/detach, cancellation and pending-state cleanup. Host suitability
and performance remain hosted gates; a passing sample is not proof of flake removal.

Primary API: [Playwright CDPSession](https://playwright.dev/python/docs/api/class-cdpsession).
