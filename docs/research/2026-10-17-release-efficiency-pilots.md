# Release Efficiency Implementation And Pilots

Date: 2026-10-17 (America/Toronto). Status: implemented and nonpublishing-qualified.
All hosted evidence below is October 17 EDT / October 18 UTC.

The [approved plan](../plans/verification-and-release-efficiency.md) is complete
within its two-qualification/one-dry-run budget. No production tag, upload,
production journal write, installed-extension change or live-data operation was
performed. The 30-day dashboard loading investigation remains deferred.

## Source And Proof

Both fresh qualifications used source
`8b1226a0ec4911134cb15d1f051a78c41375401d`, contract
`eb9f27e502e86b3157084c84ae083adbe1748f95422e81c649ef392f5485bcc8`:

- [First qualification, attempt 1](https://github.com/Wenjun-Mao/codex_usage/actions/runs/39090001226).
- [Predeclared timing repeat, attempt 1](https://github.com/Wenjun-Mao/codex_usage/actions/runs/39090610712).
- [Credential-free dry-run, attempt 1](https://github.com/Wenjun-Mao/codex_usage/actions/runs/39091175485), selecting the first qualification.

These are nonpublishing 2.12.5 measurement packages, not replacement public bytes.
The published `v2.12.5` tag remains at
`dd6406930ea41d26af8f280032cc8e6bc3e290ef`. Product/extension source and runtime
lockfiles have no diff from that tag. A future release needs an unused version,
fresh exact-source qualification and explicit owner publication authority.

## Measured Results

The baseline is the successful [2.12.5 qualification](https://github.com/Wenjun-Mao/codex_usage/actions/runs/39085426094)
and its [wall-time profile](2026-10-17-release-2.12.5-profile.md). This is a
historical comparison, not a controlled same-host experiment. No failed run was
retried, and no timing/assertion policy changed.

| Measure | Historical Two Slots | Three Slots, First | Three Slots, Repeat |
| --- | ---: | ---: | ---: |
| Qualification elapsed | 12m19s | 9m12s | 8m28s |
| Visual eligibility to final completion | 8m49s | 5m56s | 5m26s |
| Sum of concurrent runner execution | 29m11s | 28m09s | 24m57s |
| Breakdown eligibility wait | 2m43s | 7s | 8s |
| Completion to local inspection start | About 67s | 10.9s | 11.4s |
| Independent local inspection | 27.8s | 28.2s | 28.1s |

Qualification improved by 3m07s and 3m51s, or 25-31%; the mean was 8m50s versus
12m19s, about 28% faster. Earlier breakdown scheduling is directly visible, but
individual job times also varied. Do not attribute the entire difference solely
to the concurrency cap. Runner execution is not elapsed time or an exact billing
measure; neither sample showed increased summed runner execution.

The hosted dry-run took **47s**, versus the historical **29s**. Its proof step
took 31s versus 14s previously. Independent local inspection still costs about
28s. These reads were intentionally retained; this work does not establish a
dry-run transport improvement. No extra attempt was used to seek a faster result.

## Local Preflight

Shared release/workflow changes conservatively selected all five existing suites.
The complete local pass covered 1,329 cases: 15 screenshot, 252 allowance,
18 economics, 162 speed, 720 breakdown, 90 overlay and 72 hover cases. Engines
remained serial, with the existing local timing limits and full raw inventories.

Serial harness durations summed to 300.2s, roughly five minutes, excluding command
startup/build/final environment-check overhead. This cold preflight is real extra
preparation work, not a free saving. Both prepare commands reused its unchanged
complete evidence in **2.0s / 2.4s**, including browser/environment verification.
Changed inputs, missing cases or changed environments invalidate reuse. Hosted
qualification always reruns every gate; local evidence is never publication proof.

## Coordination And Resume

The first prepare dispatched UUID `6db8aa21-7dbd-4abf-b319-a226954e3929` once.
After the run was discovered, only the local observer was interrupted with
Ctrl-C. Progress retained run `39090001226`; generic resume observed that same
run through independent inspection. The hosted workflow was not canceled or
redispatched. The API inventory contains exactly the two planned qualifications
for this source; the second used UUID `913f0e7b-add4-4977-ac47-6a10205a41af`.

The sole dry-run used UUID `a2e98bea-52ff-4a1a-bce1-e63c6af80bc6`. Its validator
succeeded and **Publish qualified packages was skipped**. Downloaded hosted
`qualified.json` was byte-identical to the independent local inspection, SHA-256
`264be3ca4b9a112f92dd9bb06eee69fc503ac71aafb6d211cd466e3f0e213feb`.
No tag or actual promotion operation exists in either pilot's process state.

## Verification And Boundaries

- Complete local Python run: 3,280 passed, one existing skip; subsequent focused
  tests and both final-source hosted full suites passed.
- Extension tests: 86 passed; Ruff, frozen monetary parity and bounded-work checks
  passed. Monetary snapshot hash remained
  `58c434d278baaa4a0f6d8acc660475f67dd6cba0fc5f8eb638f8327336fd588e`.
- Both hosted qualifications passed all original inventories, platform package
  bindings, archive/disposable handoff checks and exact-package native macOS.
  Native Windows UI acceptance remains the existing untested surface.
- Existing `hosted-webkit-observed` policy was retained, not represented as a
  resolution of the underlying hosted observation delay.
- Focused coordinator tests cover ambiguity/no redelivery, candidate/attempt
  mismatch, failed proof, partial publication, locking, symlink confinement and
  receipt idempotence. Fourteen receipt tests passed in 0.07s; this is synthetic
  validation, not a measured live post-publication closeout.
- An attended read-only GPT-6.1 Sol / High safety review was collected and closed.
  Lock/intent scope, stable verification timestamps, post-upload status and
  canonical-file confinement findings were fixed and re-reviewed before commit.

Evidence is retained privately under ignored
`output/performance/release-efficiency/`: `local-preflight/preflight.json`, raw
suite inventories, `baseline.json`, and each pilot's process/timings/inspection
records. `run-evidence.json` preserves run/job timestamps; the first pilot also
retains `dry-run-evidence.json` and the matching `dry-run-qualified.json`.

The [coordinator guide](../release/qualified-promotion.md#on-demand-coordinator)
documents normal use and the manual fallback. Actual tag/publication/public-byte
verification and receipt generation are implemented with synthetic fault coverage,
but no live automated publishing canary was authorized. The earlier 22-25 minute
end-to-end target therefore remains unverified. No claim is made that Marketplace
propagation, proof/journal transport or dashboard loading is faster.
