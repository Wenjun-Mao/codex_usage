# ADR 0066: Accounting Compatibility Is Separate From API Availability

Status: Implemented; release qualification pending.

## Problem

API 1 predates paginated physical-lineage accounting and retained-replica
selection. A healthy older collector could therefore supply reports or capture
usage for the new extension without implementing ADRs 0064 and 0065. Treating
that collector as unavailable would also permit startup and settings controls.

## Decision

Keep the transport API at version 1. The runtime advertises the versioned
`physical-lineage-accounting-v1` capability in authenticated health/status.
The extension requires that exact capability in a string array, API 1, and
boolean `ok: true` before returning a discovered client. Descriptor metadata and
process ownership cannot substitute for this runtime check.
Structurally valid descriptors declaring another API are also incompatible, not
an unavailable-writer fallback; no request is sent using an unsupported protocol.

Represent healthy incompatibility with `AgentIncompatibleError`, independent of
`AgentUnavailableError`. Existing supervisor fallbacks handle only unavailability:
incompatibility propagates without retry, automatic replacement, home change or
shutdown of the discovered collector. A startup race can already have launched a
child before an incompatible collector appears; it must not claim that collector
or continue retrying. Ownership checks still govern shutdown separately.
Home changes preflight a discovered destination before stopping an owned current
collector or persisting settings. This is not an atomic cross-home reservation:
a later replacement is still checked during acquisition and refused, but cannot
undo controls already completed before that race.

Read-only retry validates a replacement descriptor through a separate client
before adopting it. Failed validation must not leave that descriptor installed
for a later write. POST requests are still never replayed.

## Boundaries And Alternatives

- This proves runtime feature compatibility, not that historical accounting has
  been repaired, the ledger is complete, or a writer migration is safe.
- It does not fence independent older CLI/parser/database connections. Row-level
  SQL triggers alone are insufficient: an old parser can drop cache tables.
  Quiescent cutover and mixed-writer protection remain separate implementation
  and disposable-repair gates; no schema migration is activated by this ADR.
- A transport-version bump would unnecessarily couple accounting semantics to
  unrelated API consumers. A release-number comparison would not directly bind
  the feature contract. Neither grants authority to stop an older service.
- Guardrails cover malformed/missing/versioned capabilities, authenticated
  descriptor replacement, strict boolean readiness, supervisor startup races,
  configuration refusal and ownership-preserving shutdown refusal.
