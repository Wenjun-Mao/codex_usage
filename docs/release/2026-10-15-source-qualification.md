# Source-Only Qualification Receipt

Date: 2026-10-15. C/D passes at the disabled source below. This is not a
publication, owner UI acceptance, live-ledger repair or qualification of later
Stage E edits. This work has not stopped the old live collector or applied live
ledger maintenance; ordinary captures may continue. The owner leaves an active
source's targeted repair pending. No release tag was created.

## Frozen Source And Journal

- Retained/pushed main: `f376c2739cab89914cf216208b5862c3ab98052c`.
- Source version: 2.12.2, nonpublishing only; the published version is immutable.
- Contract: `be4970336abd67f502df03b654a5b72b316130a953033f85dae8da965a19b570`.
- First approved D4 binding: `ba93c29417e114155612f5ef8db514c3961e43fa` in
  `refs/heads/codex/publication-receipts`, independently read back from the pinned
  genesis. Its purpose is nonpublishing; it reserves 2.12.3 with the approved
  immutable scope and four-binding ceiling. No possible-upload intent exists.
- Hosted WebKit's 216 observations remain `deferred-known-latency`; all 648
  observations and 72 cases are retained. Other-engine/local/native guards stay
  strict. This is the owner's one-release disposition, not a root-cause fix.

## Normal Qualification

[Run 38742478655, attempt 1](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38742478655)
passes all eleven required jobs: metadata, core, both platform packages, all
five visual units, hosted aggregation and exact-VSIX native macOS replay.
Local `qualification.py inspect` independently validates original receipts,
artifact digests, raw hover evidence, source closure and native package/host
identity, returning `qualified-not-published`.

| Target | VSIX SHA-256 | Embedded Collector SHA-256 |
| --- | --- | --- |
| darwin-arm64 | `98a3f660be239fbc71e65c18eaa8b09b39c62affd369a141699fc358ec6bc713` | `c426a1638e76031139116e35e1786a165123711d077d74e0a2490ff55c74c4ea` |
| win32-x64 | `f148b5224548c4f1bee0b10c63270c6724f45eee6f3d8fbee4ab2f2b1c380b12` | `95ab46d25a98a1ea6a332b491cffe38c42cd6187104294ac95fbe77f932c1e82` |

Normal native receipt artifact: `11976517113`, original job `116452227743`,
attempt 1. Its uploaded receipt archive digest is
`ae21a82421a1a4d2863be3c70447f699258a11474c0bd4a628c2dc51104b04de`.
Native Windows UI is still an explicit gap; Windows package/smoke/archive/handoff
gates pass and are not replaced by the macOS replay.

Local current-source checks pass 2,939 Python cases plus the one approved
non-Windows junction skip, 83 extension cases, Ruff, frozen monetary parity and
bounded-work guards. Raw JUnit and independent case inventories reconcile.
The added held-lock migration/refresh tests retain caller ownership, competing
writer exclusion, transactional rollback and pre-filesystem invalid-handle refusal.

## Controlled Failure And Retry

[Run 38744799790](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38744799790)
attempt 1 fails only `chromium/single-day/night/1440` with the explicit requested
synthetic assertion, zero completed hover cases and retained bounded diagnostics.
The eight other producers pass; aggregation/native skip and emit no receipts.

One failed-job rerun disables injection. Attempt 2 passes hover, aggregation and
native replay. Independent reconciliation verifies:

- All eight healthy producers retain the exact original attempt-1 receipt IDs,
  archive digests, original-job markers and execution timestamps.
- Both packages retain exact VSIX, collector and asset identities across the
  probe's own attempts, with their payload bytes revalidated.
- Hover, hosted aggregation and native receipts originate from attempt 2.
  Their artifacts are `11978322534`, `11980325585`, and `11979476371` respectively.
- Fresh native hover observations are approximately 119 ms and 25 ms, both
  satisfying the unchanged 250 ms guard.
- The normal inspector explicitly refuses this successful probe as a release
  candidate. No probe package can be selected for publication.

[Earlier operator-input probe 38744299963](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38744299963)
selected Day instead of the documented first Night case. It was cancelled while
hover remained queued and is permanently nonqualifying. This consumes one of the
two approved corrective pilot iterations; one remains. No source/binding changed,
no unexplained failure was retried, and the normal proof was unaffected.

## Dry-Run Promotion

[Run 38744418804, attempt 1](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38744418804)
selects the normal run/attempt on main. Validation succeeds; the publisher job is
skipped, with no build, PAT-bearing step or upload. Its downloaded inspection
JSON equals the independent local inspection exactly, including package hashes,
native reference, frozen manifest and current D4 binding.

## Measurements And Next Gate

Normal run creation to final job completion is 735 s; API completion/update is
736 s (12m16s). Summed job runtime is 1,635 s, including each job's setup/post.
The longest visual job is breakdown at 336 s. These are one hosted sample of a
larger combined candidate, not a controlled speedup percentage. Dependency waits
and runner-queue delays are not separable from these job timestamps alone.

Stage E prepares 2.12.3 source activation with explicit disabled/enabled guard
coverage and no real publication effects. That changes version/contract/source,
so this receipt becomes historical: freeze the reviewed source, append its
approved release-purpose binding, then repeat complete C/D qualification.
Full live P completion and owner full-dashboard acceptance still gate F;
source activation or a release-purpose binding cannot waive either requirement.

Ignored inspectable evidence: `output/qualification/c-f376c273/`,
`output/qualification/maintenance-locks/`, and `output/qualification/d4-prepared/`.
