from __future__ import annotations

import json
import os
import sqlite3
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.ledger_schema import open_ledger
from codex_usage.ledger_sync import synchronize_parser_workset
from codex_usage.ledger_migration_source import (
    is_schema_eight,
    legacy_cache_digest,
    verified_legacy_cache,
)
from codex_usage.ledger_migration_history import (
    GenerationHistory,
    compare_generation_history,
    load_generation_history,
)
from codex_usage.session_cache import CACHE_DB_NAME


_GENERATION_TABLES = (
    "usage_records",
    "session_metadata",
    "parser_checkpoints",
    "transition_candidates",
)


@dataclass(frozen=True, slots=True)
class LegacyCacheCandidate:
    path: Path
    digest: str
    source_kind: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": str(self.path),
            "digest": self.digest,
            "source_kind": self.source_kind,
        }


@dataclass(frozen=True, slots=True)
class MigrationConflict:
    file_key: str
    sources: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, object]:
        return {
            "file_key": self.file_key,
            "sources": list(self.sources),
            "reason": self.reason,
        }


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    candidates: tuple[LegacyCacheCandidate, ...]
    conflicts: tuple[MigrationConflict, ...]
    importable_generations: int
    identical_generations: int
    superseding_generations: int

    def to_dict(self) -> dict[str, object]:
        return {
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "conflicts": [conflict.to_dict() for conflict in self.conflicts],
            "importable_generations": self.importable_generations,
            "identical_generations": self.identical_generations,
            "superseding_generations": self.superseding_generations,
            "requires_precedence": bool(self.conflicts),
        }


def discover_legacy_caches(codex_home: Path) -> tuple[LegacyCacheCandidate, ...]:
    paths: list[tuple[Path, str]] = []
    override = os.environ.get("CODEX_USAGE_LEGACY_CACHE_PATHS", "").strip()
    if override:
        paths.extend((Path(value), "override") for value in override.split(os.pathsep))
    paths.append(
        (
            codex_home / ".codex-usage-cache" / CACHE_DB_NAME,
            "codex-home",
        )
    )
    for product, root in _editor_data_roots():
        paths.append(
            (
                root
                / "User"
                / "globalStorage"
                / "wenjun-mao.codex-usage-dashboard"
                / "cache"
                / CACHE_DB_NAME,
                product,
            )
        )
    selected: list[LegacyCacheCandidate] = []
    seen: set[str] = set()
    for raw_path, kind in paths:
        path = raw_path.expanduser().resolve()
        key = os.path.normcase(str(path))
        if key in seen or not path.is_file() or not is_schema_eight(path):
            continue
        seen.add(key)
        selected.append(
            LegacyCacheCandidate(path, legacy_cache_digest(path), kind)
        )
    return tuple(sorted(selected, key=lambda item: str(item.path).casefold()))


def plan_legacy_migration(
    ledger_path: Path,
    candidates: tuple[LegacyCacheCandidate, ...],
) -> MigrationPlan:
    importable = 0
    identical = 0
    superseding = 0
    conflicts: list[MigrationConflict] = []
    histories: dict[str, GenerationHistory] = {}
    sources_by_key: dict[str, list[str]] = {}
    conflicting_keys: set[str] = set()
    with open_ledger(ledger_path, read_only=True) as destination:
        for row in destination.execute("select file_key from files"):
            key = str(row["file_key"])
            histories[key] = load_generation_history(destination, key)
            sources_by_key[key] = [str(ledger_path)]
    for candidate in candidates:
        with verified_legacy_cache(candidate.path, candidate.digest) as source:
            for row in source.execute("select file_key from files order by file_key"):
                key = str(row["file_key"])
                candidate_source = str(candidate.path)
                sources_by_key.setdefault(key, []).append(candidate_source)
                incoming = load_generation_history(source, key)
                existing = histories.get(key)
                if existing is None:
                    histories[key] = incoming
                    importable += 1
                    continue
                relation = compare_generation_history(existing, incoming)
                if relation == "identical":
                    identical += 1
                elif relation == "extends":
                    histories[key] = incoming
                    superseding += 1
                elif relation == "prefix":
                    identical += 1
                else:
                    conflicting_keys.add(key)
    for key in sorted(conflicting_keys):
        conflicts.append(
            MigrationConflict(
                file_key=key,
                sources=tuple(dict.fromkeys(sources_by_key[key])),
                reason=(
                    "task histories disagree on usage context, metadata, "
                    "or repository-transition evidence"
                ),
            )
        )
    return MigrationPlan(
        candidates=candidates,
        conflicts=tuple(conflicts),
        importable_generations=importable,
        identical_generations=identical,
        superseding_generations=superseding,
    )


def migrate_legacy_caches(
    ledger_path: Path,
    candidates: tuple[LegacyCacheCandidate, ...],
    *,
    precedence: dict[str, str] | None = None,
) -> dict[str, object]:
    precedence = precedence or {}
    plan = plan_legacy_migration(ledger_path, candidates)
    unresolved = [
        conflict
        for conflict in plan.conflicts
        if precedence.get(conflict.file_key) not in set(conflict.sources)
    ]
    if unresolved:
        raise ValueError(
            "migration has divergent histories that require explicit cache precedence"
        )
    imported = 0
    skipped = 0
    with open_ledger(ledger_path) as destination:
        _prune_unselected_transitions(destination, precedence, str(ledger_path))
        for candidate in candidates:
            if _migration_completed(destination, candidate):
                skipped += 1
                continue
            started = datetime.now(UTC).isoformat()
            audit_id = _start_audit(destination, candidate, started)
            try:
                with verified_legacy_cache(candidate.path, candidate.digest) as source:
                    counts = _merge_cache(
                        destination,
                        source,
                        candidate.path,
                        precedence,
                    )
                _finish_audit(destination, audit_id, "completed", counts)
                destination.commit()
                imported += 1
            except BaseException as exc:
                destination.rollback()
                with open_ledger(ledger_path) as audit_connection:
                    failed_id = _start_audit(audit_connection, candidate, started)
                    _finish_audit(
                        audit_connection,
                        failed_id,
                        "failed",
                        {"error": f"{type(exc).__name__}: {exc}"},
                    )
                    audit_connection.commit()
                raise
    revision, changed = synchronize_parser_workset(ledger_path)
    return {
        "imported_caches": imported,
        "skipped_caches": skipped,
        "ledger_revision": revision,
        "ledger_changed": changed,
        "plan": plan.to_dict(),
    }


def _merge_cache(
    destination: sqlite3.Connection,
    source: sqlite3.Connection,
    source_path: Path,
    precedence: dict[str, str],
) -> dict[str, int]:
    counts = {"imported": 0, "replaced": 0, "skipped": 0}
    for row in source.execute("select file_key from files order by file_key"):
        key = str(row["file_key"])
        incoming = load_generation_history(source, key)
        existing_row = destination.execute(
            "select 1 from files where file_key = ?", (key,)
        ).fetchone()
        selected_source = precedence.get(key)
        if selected_source is not None and selected_source != str(source_path):
            counts["skipped"] += 1
            continue
        if existing_row is None:
            _copy_generation(destination, source, key)
            counts["imported"] += 1
            continue
        if selected_source == str(source_path):
            _delete_generation(destination, key)
            _copy_generation(destination, source, key)
            counts["replaced"] += 1
            continue
        existing = load_generation_history(destination, key)
        relation = compare_generation_history(existing, incoming)
        if relation in {"identical", "prefix"}:
            counts["skipped"] += 1
            continue
        use_candidate = relation == "extends"
        if not use_candidate:
            raise ValueError(f"unresolved migration conflict for {key}")
        _delete_generation(destination, key)
        _copy_generation(destination, source, key)
        counts["replaced"] += 1
    _merge_transition_rows(destination, source, str(source_path), precedence)
    return counts


def _copy_generation(
    destination: sqlite3.Connection,
    source: sqlite3.Connection,
    file_key: str,
) -> None:
    _copy_filtered_rows(destination, source, "files", "file_key", file_key)
    for table in _GENERATION_TABLES:
        _copy_filtered_rows(destination, source, table, "file_key", file_key)


def _delete_generation(connection: sqlite3.Connection, file_key: str) -> None:
    for table in _GENERATION_TABLES:
        connection.execute(f"delete from {table} where file_key = ?", (file_key,))
    connection.execute("delete from files where file_key = ?", (file_key,))


def _copy_filtered_rows(
    destination: sqlite3.Connection,
    source: sqlite3.Connection,
    table: str,
    key_column: str,
    key: str,
) -> None:
    columns = _common_columns(destination, source, table)
    if not columns:
        return
    placeholders = ", ".join("?" for _ in columns)
    column_list = ", ".join(columns)
    rows = source.execute(
        f"select {column_list} from {table} where {key_column} = ?", (key,)
    ).fetchall()
    destination.executemany(
        f"insert into {table} ({column_list}) values ({placeholders})",
        [tuple(row[column] for column in columns) for row in rows],
    )


def _merge_transition_rows(
    destination: sqlite3.Connection,
    source: sqlite3.Connection,
    source_path: str,
    precedence: dict[str, str],
) -> None:
    columns = _common_columns(destination, source, "project_transitions")
    if not columns:
        return
    existing = {
        tuple(row[column] for column in columns)
        for row in destination.execute(
            f"select {', '.join(columns)} from project_transitions"
        )
    }
    for row in source.execute(
        f"select {', '.join(columns)} from project_transitions"
    ):
        if not _transition_matches_source(row, source_path, precedence):
            continue
        values = tuple(row[column] for column in columns)
        if values in existing:
            continue
        destination.execute(
            f"insert into project_transitions ({', '.join(columns)}) values "
            f"({', '.join('?' for _ in columns)})",
            values,
        )
        existing.add(values)


def _prune_unselected_transitions(
    connection: sqlite3.Connection,
    precedence: dict[str, str],
    source_path: str,
) -> None:
    rows = connection.execute(
        "select rowid as migration_rowid, * from project_transitions"
    ).fetchall()
    for row in rows:
        if _transition_matches_source(row, source_path, precedence):
            continue
        connection.execute(
            "delete from project_transitions where rowid = ?",
            (int(row["migration_rowid"]),),
        )


def _transition_matches_source(
    row: sqlite3.Row,
    source_path: str,
    precedence: dict[str, str],
) -> bool:
    task_ids = {str(row["owner_thread_id"])}
    related = json.loads(str(row["thread_ids_json"] or "[]"))
    if not isinstance(related, list) or not all(
        isinstance(task_id, str) for task_id in related
    ):
        raise ValueError("legacy project transition has invalid task IDs")
    task_ids.update(related)
    selected_sources = {
        precedence[task_id] for task_id in task_ids if task_id in precedence
    }
    return not selected_sources or selected_sources == {source_path}


def _common_columns(
    destination: sqlite3.Connection,
    source: sqlite3.Connection,
    table: str,
) -> tuple[str, ...]:
    destination_columns = {
        str(row["name"]) for row in destination.execute(f"pragma table_info({table})")
    }
    return tuple(
        str(row["name"])
        for row in source.execute(f"pragma table_info({table})")
        if str(row["name"]) in destination_columns
    )


def _start_audit(
    connection: sqlite3.Connection,
    candidate: LegacyCacheCandidate,
    started_at: str,
) -> int:
    connection.execute(
        """
        insert into migration_audit (
            source_path, source_digest, started_at, outcome, detail_json
        ) values (?, ?, ?, 'running', '{}')
        on conflict(source_path, source_digest) do update set
            started_at = excluded.started_at, completed_at = null,
            outcome = 'running', detail_json = '{}'
        """,
        (str(candidate.path), candidate.digest, started_at),
    )
    row = connection.execute(
        """
        select migration_id from migration_audit
        where source_path = ? and source_digest = ?
        """,
        (str(candidate.path), candidate.digest),
    ).fetchone()
    return int(row["migration_id"])


def _finish_audit(
    connection: sqlite3.Connection,
    audit_id: int,
    outcome: str,
    detail: dict[str, object],
) -> None:
    connection.execute(
        """
        update migration_audit
        set completed_at = ?, outcome = ?, detail_json = ?
        where migration_id = ?
        """,
        (
            datetime.now(UTC).isoformat(),
            outcome,
            json.dumps(detail, sort_keys=True),
            audit_id,
        ),
    )


def _migration_completed(
    connection: sqlite3.Connection, candidate: LegacyCacheCandidate
) -> bool:
    return connection.execute(
        """
        select 1 from migration_audit
        where source_path = ? and source_digest = ? and outcome = 'completed'
        """,
        (str(candidate.path), candidate.digest),
    ).fetchone() is not None


def _editor_data_roots() -> tuple[tuple[str, Path], ...]:
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
        return tuple(
            (label, base / directory)
            for label, directory in (
                ("VS Code", "Code"),
                ("VS Code Insiders", "Code - Insiders"),
                ("VSCodium", "VSCodium"),
            )
        )
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return tuple(
            (label, base / directory)
            for label, directory in (
                ("VS Code", "Code"),
                ("VS Code Insiders", "Code - Insiders"),
                ("VSCodium", "VSCodium"),
            )
        )
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return (("VS Code", base / "Code"), ("VSCodium", base / "VSCodium"))
