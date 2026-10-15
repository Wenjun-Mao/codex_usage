# ADR 0068: Ledger Writer Compatibility And Quiescent Upgrades

Status: Implemented; private repair and release qualification pending.

## Problem

New parser semantics do not prevent an older collector or raw parser connection
from overwriting corrected worksets. A ledger-backed parser mismatch could also
take the disposable-cache reset path. A runtime feature check alone cannot fence
independent connections, and SQLite DML triggers cannot prevent arbitrary DDL.

## Decision

Advance the ledger schema to 7, retain parser/cache versions 8/11, and persist
writer epoch 1. New writable connections register a connection-local deterministic
epoch function. INSERT, UPDATE and DELETE guards cover the fixed authoritative,
workset and derived tables listed in `ledger_writer_contract.PROTECTED_TABLES`.
Missing functions and wrong epochs fail before mutation, including connections
opened before upgrade. Guard SQL and epoch metadata must match exactly on reopen;
missing or changed guards are an error, not permission to reinstall them silently.
This is compatibility enforcement for supported writers, not a secret or identity.

The collector advertises `physical-lineage-accounting-v2`; the extension refuses
V1 preview collectors explicitly under ADR 0066. Read-only inspection remains
available. Standalone parser/staging and storage-diagnostic databases retain their
existing contracts. Ledger-backed cache refresh and image backfill use authorized
connections. Future, malformed or missing ledger metadata fails closed, and no
ledger-backed parser mismatch can trigger a destructive disposable-cache reset.

## Migration Admission

Acquire the home-agent lock, then the database's parser-refresh lock, without
waiting. A busy owner produces a bounded refusal; no existing service is stopped.
Startup may borrow only its already-held matching `FileLock`. Canonical managed
paths identify the home; database/parent/sidecar symlinks are refused before
privacy operations or writable connection setup. Privacy cleanup does not chmod
alias targets; POSIX chmod uses a no-follow file descriptor. This does not claim
protection against an adversarial filesystem owner racing directory replacement.
Cleanup failures annotate an active primary refusal rather than replacing it;
after a successful operation they remain surfaced failures, not silent warnings.

Before changing accounting/schema state, create a unique private backup directory
and a coherent SQLite snapshot with hash, integrity, revision and count checks.
The backup page-copy operation has a 300-second execution deadline; failed partial
artifacts remain distinct from a verified receipt and are never overwritten.
Hold the maintenance locks throughout backup and installation. Record the current
connection's `data_version` before backup. After `BEGIN IMMEDIATE`, recheck backup
facts and that data version, catching even a late unrevisioned legacy commit.
Keep the write lock until schema, epoch and guards commit. Do not reset the
data-version guard after a mismatch or retry an unexplained change into acceptance.

Supported additive parser migration borrows this transaction and the verified
whole-ledger backup; it cannot commit independently or back up its own write
transaction. Journal-mode conversion occurs after the guarded migration commits,
since converting DELETE to WAL itself changes SQLite's observed data version.
Failed installation rolls back parser changes, schema, epoch and guards together.
A later connection-configuration failure does not undo a committed contract;
inspect the persisted version before deciding whether migration occurred.

## Accounting And Boundaries

Schema 7 means writer compatibility, not completed historical repair. Migration
marks weak legacy checkpoints pending for bounded discovery, flags their coverage
stale and advances the report revision without rewriting captured usage or quota
facts. Strong captures preserve their existing accounting. Actual corrections
still require the source-bound staged repairs in ADRs 0064 and 0067.

Older schema-aware ledger code refuses version 7. The SQL guards fence ordinary
old DML but cannot stop an arbitrary connection from dropping tables/triggers or
recreating the database. Such destructive SQL, manual guard removal, unsupported
old reset-only CLI paths and a malicious database owner are outside the guarantee.
Do not run old collector/CLI tools against the migrated live ledger. Schema 7 is
not permission to perform the approved live repair: private-snapshot validation,
fresh backup/source checks, rollback and owner UI/release gates remain required.

Regression gates cover every protected table/operation, preexisting and wrong-
epoch connections, future/damaged contracts, parser-reset refusal, lock ordering,
backup failure, late commits, transactional rollback, privacy aliases, legacy
migrations, preserved financial facts and the V1-preview client refusal.

Development measurement on 5,000 synthetic responses (three alternating pairs)
increased median capture from 1.7282 to 1.9048 seconds with guards. This is a local
compatibility-cost observation, not a production latency claim; monetary and
bounded-work gates remain unchanged. Full-candidate performance still requires
the release qualification path.
