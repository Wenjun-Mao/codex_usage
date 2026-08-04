# ADR 0020: Disposable Versioned Usage Cache

## Status

Accepted

## Context

The usage cache is derived entirely from Codex source data. Preserving rows
across internal schema changes adds migration branches and can retain data that
no longer satisfies the current parser and transition contracts.

## Decision

Schema 4 is the only supported internal cache format and uses
`usage-cache-v4.sqlite3`. A cache whose schema, parser, or transition version
does not match is reset in one immediate transaction by dropping only known
plugin-cache objects and recreating the schema. No schema-3 rows are migrated.

After schema 4 opens, the CLI best-effort removes the legacy database and its
WAL sidecars. Cleanup retries `OSError` failures three times, never removes the
new database, and reports exhausted paths through cache statistics.

## Alternatives Rejected

- Snapshot and restore compatible columns: this preserves unsupported state
  and creates an implicit migration contract.
- Read both schema versions: this doubles storage behavior and test scope for
  disposable data.

## Consequences

The first load after upgrade reparses source files. Schema rollback tests,
exact SQLite shape fixtures, versioned-path tests, and cleanup retry tests guard
the contract.
