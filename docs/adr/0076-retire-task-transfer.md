# ADR 0076: Retire Task Transfer

Date: 2026-10-22. Status: accepted; implementation candidate for 2.13.0.

## Problem

Task Transfer grew from portable file transport into registration and private
desktop project binding. Imported local chats can remain intact while later
Codex changes expose stale same-ID remote copies. Validating the import cannot
guarantee future sidebar membership. The October 22 recovery confirmed missing
server-owned membership beside compatible legacy assignments; the owner then
confirmed the repaired sidebar and approved retirement.

## Decision

Remove Task Transfer from the extension and collector, including Import, Export,
Review Status, setup, CLI/API routes, transfer engine, registration/binding and
transfer-only packaging/tests. No hidden fallback importer or export-only feature
remains. Removed HTTP paths return the ordinary unknown-route response; removed
CLI commands fail parsing. Surviving transport/accounting contracts are unchanged.

Keep chat logs, indexes, Codex databases/global state, exports, transfer folders
and paired state untouched. Preserve the legacy `transfer_folder` settings value
without editing it or accessing its path. Retirement triggers no migration,
registration, cleanup, handoff or data rollback. Previously repaired assignments
are not undone. Existing cached byte-estimate fields remain readable for cache
compatibility; the unused transfer estimate is removed from thread-list output.

Move unchanged Codex executable discovery and owned process-tree cleanup into
`codex_runtime.py`, retaining their allowance-probe/RPC users and tests. Ledger
synchronization, usage-cache migration and legacy-service handoff are not Task
Transfer and remain supported.

Point users to Codex-owned native host handoff, with its connected-host and
matching Git-project requirements. Do not promise offline/non-Git recovery or
future resumability of old exports through a retired version.

## Alternatives And Consequences

Rejected another private-state compatibility patch: its ongoing ownership is
outside usage reporting. Hiding only the UI leaves risky hidden import paths;
export-only leaves a format without a supported continuation path. Full removal
reduces maintenance and qualification scope, not a claimed dashboard speed gain.
Preserved files can still be used in a separately scoped recovery investigation.

Historical ADRs, changelogs and release receipts remain historical evidence.
This supersedes active transfer behavior in ADRs 0014, 0016, 0017, 0018 and 0029,
and Task Transfer-specific portions of other decisions, not their surviving
parser, usage, storage or distribution contracts.

## Guardrails

Synthetic upgrade/startup/settings tests must preserve chat/transfer byte hashes
and reject access to saved legacy paths. Retired commands/routes cannot enqueue
work or register chats. Shared runtime probes and Usage/Storage/CSV remain tested.
Review every retired required test identity; pin new retirement/verifier cases
and preserve all unrelated requirements. No broad skips or weakened proof gates.
Required identities must be deterministic across independent collections; use
fixed representative parameter data and semantic IDs. Validate the complete local
JUnit/collection evidence with the hosted validator before requesting CI.
Both target packages require fresh source-bound qualification and exact-artifact
promotion; no live data, automatic installation or chat operations for release.
