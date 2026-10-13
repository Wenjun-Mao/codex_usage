# ADR 0061: Qualified Artifact Promotion

Status: Accepted for implementation on 2026-10-13; local implementation and
qualification in progress, production promotion disabled, not released. Owner selected explicit promotion; see the
[implementation plan](../plans/verification-and-release-efficiency.md).

## Context

The current process qualifies a nonpublishing candidate, then rebuilds and
retests that source on its release tag. The 2.12.2 tag workflow took 17m 49s.
Its macOS VSIX and embedded collector hashes differed from preflight, requiring
fresh native proof. Source equality is not artifact equality. The visual gate
also couples otherwise independent checks and loses case diagnostics on failure.
See the [measured profile](../research/2026-10-13-verification-and-release-profile.md).

## Proposed Decision

Build each supported platform VSIX once per candidate qualification. Separate
early metadata checks, complete core checks, platform packaging, and independently
required visual suites. A receipt is qualified only when the explicitly expected
gate and case inventories pass; missing or skipped mandatory gates cannot pass
through an empty-list success check. Partial diagnostics are never qualification.

Promote the exact immutable qualified VSIX bytes, rather than rebuilding at the
release tag. Preserve both targets, archive/smoke/handoff checks, frozen monetary
parity, bounded-work guards, cross-browser/painted-meter/screenshot behavior,
native macOS evidence, and official public catalog/download hash verification.
Native Windows coverage limits remain disclosed.

A versioned receipt binds:

- Repository identity, source commit, package version, supported targets and
  trusted qualification event/workflow identity plus its contract revision.
- The allowlisted required gate IDs and complete case inventories/results,
  dependency/environment identities, and immutable evidence artifact identities.
- Qualification run and each originating attempt/job, including verified reuse
  on failed-job reruns; reused proof must cover unchanged source and dependencies.
- Each platform artifact ID and archive digest, VSIX SHA-256/size, embedded
  collector SHA-256, and packaged extension asset identities. Transport archive
  digests and inner VSIX digests are different values and checked separately.
- Trusted native replay evidence bound to that VSIX, collector, shipped assets
  and source; known acceptance-harness-only differences are explicit.

Caller inputs select proof, not authority. Validate receipt contents against
GitHub's trusted repository/run/job/artifact records and the approved gate
contract. An arbitrary uploaded JSON, artifact name, overall green run, or
source SHA alone is insufficient. Unknown receipt contracts, ambiguous rerun
provenance, unavailable/expired artifacts and stale native proof fail closed.
Resolve artifact-attempt association and the native receipt trust path through
nonpublishing probes before implementing dependent promotion behavior.

Promotion requires a matching version tag whose peeled commit is the qualified
source and is contained in main. Restrict publisher credentials to the trusted
promotion path after proof validation; untrusted fork/PR evidence cannot gain
publication authority. Do not increase permissions beyond necessary scoped
artifact reads and existing authorized Marketplace publication.

Use an explicitly dispatched promotion workflow on the matching release tag,
with qualification run/attempt selection and complete proof validation. Creating
a tag alone does not publish or rebuild. Owner selected this interface over
automatic tag discovery, avoiding ambiguous receipt selection and making the
publication action explicit. Creating a plan does not authorize publication.

Publication records uploaded targets separately from public validation. Poll
the official catalog and compare each downloaded package's SHA-256 with both
the qualification receipt and declared Marketplace hash. A partial publication
can resume only when already occupied target/version hashes match. Catalog
delay is pending validation, not a reason to re-upload or replace a version.

## Alternatives And Consequences

Keeping full preflight and tag qualification preserves today's flow but repeats
most work and native proof when builds differ. Qualifying only at the tag is
simpler but removes prepublication candidate proof. Reproducible builds alone
would not remove repeated tests and are not established for these packages.
Trusting names or one run ID is simpler but cannot establish complete proof.

Exact promotion eliminates the duplicate pass, but introduces provenance,
retention and native-proof responsibilities. Expired artifacts require fresh
qualification, not relaxed validation. Suite isolation increases runner setup
and queue/cost exposure; bounded concurrency and measured pilots choose limits.
Browser batching changes test transport only; assertion inventories and real
interaction/pixel checks must remain equivalent. Latency guards are unchanged.

## Verification And Rollback

Negative tests reject wrong source/version/tag/repository/target/trust context,
missing or unsuccessful gates/cases, unknown contracts, ambiguous reruns,
expired/swapped artifacts, stale native proof and mismatching bytes. Synthetic
controlled failures prove case diagnostics and isolated retry behavior; dry-run
promotion receives no publisher credentials and makes no Marketplace changes.

All current gates remain required. A separately authorized publishing canary
must prove official bytes equal qualification bytes for both targets. Timings
are measured separately for qualification, native replay, promotion, queueing
and public propagation. Before activation retain/revert to current full
qualification if trust probes fail. Published tags/versions are immutable;
corrections require a newly approved version, not replacement or silent rebuild.

## Implementation Guardrails

GitHub's copied attempt records are not new executions. Producer artifacts use
attempt-qualified names; immutable receipt outputs are stamped in the original
job log. Validation checks those original logs and the selected attempt's matching
execution, never reconstructing origin from timestamps alone. Missing association
requires fresh qualification. Producers require tracked, unchanged Git inputs.
Text contract fingerprints use POSIX paths and normalize checkout CRLF to LF;
other byte changes invalidate proof. Payload, VSIX, collector and asset hashes
remain byte-exact, including the VSIX XML publication identity.

Native replay extracts the qualified VSIX. Its only declared metadata patch is
removing activation events, plus the approved acceptance harness; shipped runtime
assets remain identical. Hosted replay uses a hash-pinned, disposable VS Code
1.141.0 ARM64 download, not a user's profile. A trusted hosted receipt, rather
than locally uploaded JSON, is the selected native-proof path pending a hosted pilot.

Source authority is independently checked against GitHub's actual source Git
tree, not a claimed digest. Both promotion jobs use one frozen trusted publisher
revision; its complete execution closure includes CLI entrypoints. Producer
checkout HEAD and tracked inputs must match the declared source. Raw GitHub ZIP/
log reads allow escape bytes without printing them; ANSI is stripped only before
structured log-marker parsing, not from package bytes.

Core and metadata results reconcile every unique collected case with raw JUnit
and an independent 2.12.2 case registry. Only the exact non-Windows native-junction
skip is allowed. Extension packaging reconciles every named test with structured
Node test events and successful cumulative completion, rejecting TODOs, skips,
cancellation and missing collection/results. Renderer
inventories retain their independent tuple/assertion contracts.

Both public targets are preflighted before any upload. Each possible upload gets
an immutable, original-job-stamped intent before its credential-bearing step.
All prior promotion attempts for the release are inspected, including failed
publisher jobs. Missing/expired intent history or unexplained executions block
automatic retries. A previously attempted but catalog-invisible target remains
pending until validated public bytes establish safe reuse; absence is not proof
that an upload never happened. Intent/outcome recording uses no publisher secret.

Surviving run-number continuity can detect missing historical records, but cannot
prove a later deleted run never existed when an older run is retried. Consequently
production `validate-publication` and `check-files` are source-disabled before
network/credential exposure until independent history authority is implemented
and qualified. There is no environment/input override. Resetting an existing
publication directory is also forbidden; cached preflight history cannot erase
its `possibly-uploaded` state.

Promotion validation binds both the current peeled tag and the immutable dispatch
SHA/ref/attempt. Prior same-tag source drift is rejected, not filtered out. Copied
validation/publisher rows resolve original log-bearing executions; original
markers and execution closure, not timestamps alone, establish authority.

### Independent Publication History

Owner approved the durable journal and scoped commit/push/nonpublishing pilots
on 2026-10-13. A fixed Git branch retains self-contained possible-upload events
outside the Actions-run lifecycle. The independently pinned orphan genesis binds
repository ID, numeric workflow ID, namespace and minimum eligible version.
Production begins at 2.12.3; 2.12.2 is already published and is not reopened.
This is an explicit trusted cutover, not retroactive proof of older uploads.

Each linear commit contains one canonical event blob with parent/sequence and a
random invocation ID. Verify the complete bounded chain to the pinned origin,
reject duplicate release/target events, and require anchored reachability before
issuing local upload authority. Distinct sibling commits use non-forced Git ref
updates: only one can advance the current history. This is restricted append
concurrency control, not a general expected-old-SHA CAS API. A lost response stops
the caller and leaves retained uncertainty; no force, rebase or automatic reset.

Retries consult this journal without requiring surviving Actions logs/artifacts.
Same-version source/package conflicts stop; a catalog-invisible recorded target
is never re-uploaded. Current qualification and original completion still use
trusted Actions proof. Missing or malformed journal history fails closed and can
only be initialized through a separately authorized explicit bootstrap.

The publisher job has Contents-write permission, which is repository/job-scoped,
not technically ref-scoped. Our narrow Git adapter permits only journal object
creation and non-forced updates to its fixed ref. The token is supplied to journal
steps only; these receive no Marketplace PAT. All other qualification/validation
jobs remain read-only. The separate synthetic pilot has its own fixed ref,
workflow ID, genesis and event kind, and cannot produce publication authority.

Trust includes approved repository maintainers and unchanged trusted publisher
code. It does not claim protection against a privileged administrator deliberately
rewriting trusted code, secrets or journal refs. Do not force, delete or manually
rewind journal refs; protection-policy changes are outside this authorization.
Local tests pass. Both origins are bootstrapped and pinned; the hosted synthetic
append/conflict/replay pilot passed, with independent Git readback confirming no
production events. See the [pilot receipt](../release/2026-10-13-qualification-pilot.md).
Production remains source-disabled until a separately approved release.

Marketplace captures retain their original browser scripting setting because the
driver waits for two animation frames before painted capture. A bounded probe
confirmed disabled scripting prevents those callbacks, causing a collected
promise. Captures still reject script elements and retain the product CSP; the
other visual matrices and native webview explicitly disable product scripts.
This is the existing capture contract, not a product/runtime exception.

## Source Contracts

GitHub's [upload-artifact v6 contract](https://github.com/actions/upload-artifact/blob/v6/README.md)
provides immutable artifact IDs and SHA-256 digests; replacement creates a new
ID. The [artifact REST API](https://docs.github.com/en/rest/actions/artifacts)
provides run/source identity and expiry metadata. These support byte selection,
not an assumption that an artifact passed every required job or native replay.
GitHub documents [per-job reruns](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/re-run-workflows-and-jobs?tool=cli)
and [attempt-specific job queries](https://docs.github.com/en/rest/actions/workflow-jobs#list-jobs-for-a-workflow-run-attempt).
Artifact-to-attempt association remains a required probe, not a documented
guarantee inferred from these separate APIs. Validate digests explicitly with
failing assertions; default downloader warnings are not release authority.

The [Node test runner contract](https://nodejs.org/download/release/v24.18.0/docs/api/test.html#test-reporters)
provides structured test events; human-readable reporter output is not a stable
machine interface. GitHub's [workflow counters](https://docs.github.com/en/actions/reference/workflows-and-actions/variables)
describe increasing run numbers, not an independently retained lifetime high-water
mark. Neither REST counts of surviving runs nor counters close deleted-suffix gaps.
