# Qualification Pilot Receipt

Date: 2026-10-13. Status: journal pilot passed; full qualification in progress.
This receipt is nonpublishing evidence, not release approval. No new tag,
Marketplace upload, credential/settings change or existing-version replacement.
Production promotion remains source-disabled.

## Source And Authority

- Implementation: `108e92c7` on retained `main`.
- Pinned candidate: `b01aa9c8d000d5192971b931f9ec49187e2164dc`.
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

- Complete local Python suite: 2,100 passed, one approved non-Windows skip,
  69.62 seconds; all 2,101 collected identities reconcile with raw JUnit.
- Focused pinned-journal/workflow/artifact tests: 111 passed.
- [Normal hosted run](https://github.com/Wenjun-Mao/codex_usage/actions/runs/38441697737):
  early metadata passed; core and Windows setup contracts failed as described below.
- Controlled failure/retry and dry-run promotion: pending normal qualification.
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
