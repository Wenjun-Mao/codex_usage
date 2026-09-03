from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.aggregation import RangeBounds
from codex_usage.ledger_schema import ledger_revision, open_ledger
from codex_usage.models import TokenUsage, UsageRecord, parse_usage_role
from codex_usage.parser import parse_timestamp
from codex_usage.project_transitions import ProjectTransition


@dataclass(frozen=True, slots=True)
class LedgerCoverage:
    total_sources: int
    captured_sources: int
    stale_sources: int
    pending_files: int
    pending_bytes: int
    total_bytes: int
    captured_bytes: int

    @property
    def complete(self) -> bool:
        return (
            self.total_sources == self.captured_sources
            and self.stale_sources == 0
            and self.pending_files == 0
        )

    @property
    def fraction(self) -> float:
        if self.total_bytes <= 0:
            return 1.0 if self.complete else 0.0
        return min(1.0, self.captured_bytes / self.total_bytes)

    def to_dict(self) -> dict[str, object]:
        return {
            "complete": self.complete,
            "fraction": self.fraction,
            "total_sources": self.total_sources,
            "captured_sources": self.captured_sources,
            "stale_sources": self.stale_sources,
            "pending_files": self.pending_files,
            "pending_bytes": self.pending_bytes,
            "total_bytes": self.total_bytes,
            "captured_bytes": self.captured_bytes,
        }


@dataclass(frozen=True, slots=True)
class LedgerStatus:
    revision: int
    last_capture_at: str
    last_capture_outcome: str
    last_capture_error: str
    coverage: LedgerCoverage

    def to_dict(self) -> dict[str, object]:
        return {
            "ledger_revision": self.revision,
            "last_capture_at": self.last_capture_at,
            "last_capture_outcome": self.last_capture_outcome,
            "last_capture_error": self.last_capture_error,
            "coverage": self.coverage.to_dict(),
        }


def load_ledger_records(
    ledger_path: Path,
    *,
    bounds: RangeBounds | None = None,
    project_keys: list[str] | None = None,
) -> list[UsageRecord]:
    with open_ledger(ledger_path, read_only=True) as connection:
        return query_ledger_records(
            connection,
            bounds=bounds,
            project_keys=project_keys,
        )


def query_ledger_records(
    connection: sqlite3.Connection,
    *,
    bounds: RangeBounds | None = None,
    project_keys: list[str] | None = None,
) -> list[UsageRecord]:
    clauses = ["ledger_generations.status = 'trusted'"]
    parameters: list[object] = []
    if bounds is not None and bounds.start_us is not None:
        clauses.append("ledger_usage_events.timestamp_us >= ?")
        parameters.append(bounds.start_us)
    if bounds is not None and bounds.end_us is not None:
        clauses.append("ledger_usage_events.timestamp_us < ?")
        parameters.append(bounds.end_us)
    query = f"""
        select ledger_usage_events.*, ledger_models.model_key,
               ledger_projects.project_key, ledger_projects.label as project_label,
               ledger_contexts.project_aliases_json, ledger_contexts.cwd,
               ledger_contexts.repository_url, ledger_contexts.git_branch,
               ledger_contexts.effort, ledger_contexts.collaboration_mode,
               ledger_sources.path as file_path
        from ledger_usage_events
        join ledger_generations using (generation_id)
        join ledger_sources using (source_id)
        join ledger_models using (model_id)
        join ledger_contexts using (context_id)
        join ledger_projects on ledger_projects.project_id = ledger_contexts.project_id
        where {' and '.join(clauses)}
        order by ledger_sources.source_key, ledger_usage_events.source_record_index
    """
    selected = {key for key in project_keys or [] if key}
    rows = connection.execute(query, parameters).fetchall()
    records = [_row_to_usage_record(row) for row in rows]
    if not selected:
        return records
    return [
        record
        for record in records
        if record.project_key in selected
        or selected.intersection(record.project_aliases)
    ]


def load_ledger_transitions(ledger_path: Path) -> list[ProjectTransition]:
    with open_ledger(ledger_path, read_only=True) as connection:
        return query_ledger_transitions(connection)


def query_ledger_transitions(
    connection: sqlite3.Connection,
) -> list[ProjectTransition]:
    rows = connection.execute(
        """
        select * from ledger_transitions
        order by effective_from, source_key, target_key
        """
    ).fetchall()
    transitions: list[ProjectTransition] = []
    for row in rows:
        effective_from = parse_timestamp(row["effective_from"])
        if effective_from is None:
            continue
        transitions.append(
            ProjectTransition(
                source_key=str(row["source_key"]),
                source_label=str(row["source_label"]),
                target_key=str(row["target_key"]),
                target_label=str(row["target_label"]),
                effective_from=effective_from,
                confidence=int(row["confidence"]),
                evidence=tuple(json.loads(row["evidence_json"] or "[]")),
                thread_ids=tuple(json.loads(row["task_ids_json"] or "[]")),
            )
        )
    return transitions


def load_ledger_status(ledger_path: Path) -> LedgerStatus:
    with open_ledger(ledger_path, read_only=True) as connection:
        return query_ledger_status(connection)


def query_ledger_status(connection: sqlite3.Connection) -> LedgerStatus:
    coverage = _coverage(connection)
    capture = connection.execute(
        """
        select completed_at, outcome, error from capture_runs
        where completed_at is not null order by run_id desc limit 1
        """
    ).fetchone()
    return LedgerStatus(
        revision=ledger_revision(connection),
        last_capture_at=str(capture["completed_at"] or "") if capture else "",
        last_capture_outcome=str(capture["outcome"]) if capture else "never",
        last_capture_error=str(capture["error"] or "") if capture else "",
        coverage=coverage,
    )


def load_projects(ledger_path: Path) -> list[dict[str, object]]:
    with open_ledger(ledger_path, read_only=True) as connection:
        rows = connection.execute(
            """
            select ledger_projects.project_key, ledger_projects.label,
                   ledger_projects.aliases_json, count(distinct ledger_tasks.task_id) task_count
            from ledger_projects
            left join ledger_tasks using (project_id)
            group by ledger_projects.project_id
            order by lower(ledger_projects.label), ledger_projects.project_key
            """
        ).fetchall()
    return [
        {
            "project_key": str(row["project_key"]),
            "project_label": str(row["label"]),
            "project_aliases": json.loads(row["aliases_json"] or "[]"),
            "task_count": int(row["task_count"]),
        }
        for row in rows
    ]


def load_tasks(
    ledger_path: Path,
    *,
    project_key: str | None = None,
) -> list[dict[str, object]]:
    clause = "where ledger_projects.project_key = ?" if project_key else ""
    parameters = (project_key,) if project_key else ()
    with open_ledger(ledger_path, read_only=True) as connection:
        rows = connection.execute(
            f"""
            select ledger_tasks.*, ledger_projects.project_key,
                   ledger_projects.label as project_label
            from ledger_tasks
            left join ledger_projects using (project_id)
            {clause}
            order by ledger_tasks.last_seen_at desc, ledger_tasks.task_id
            """,
            parameters,
        ).fetchall()
    return [dict(row) for row in rows]


def _coverage(connection: sqlite3.Connection) -> LedgerCoverage:
    row = connection.execute(
        """
        select count(*) as total_sources,
               sum(case when ledger_generations.generation_id is not null then 1 else 0 end) captured_sources,
               sum(ledger_sources.is_stale) stale_sources,
               sum(case when ledger_sources.is_missing = 0 and
                    coalesce(ledger_generations.captured_size, 0) < ledger_sources.size_bytes
                    then 1 else 0 end) pending_files,
               sum(case when ledger_sources.is_missing = 0 then
                    max(0, ledger_sources.size_bytes - coalesce(ledger_generations.captured_size, 0))
                    else 0 end) pending_bytes,
               sum(case when ledger_sources.is_missing = 0 then ledger_sources.size_bytes else 0 end) total_bytes,
               sum(case when ledger_sources.is_missing = 0 then
                    min(ledger_sources.size_bytes, coalesce(ledger_generations.captured_size, 0))
                    else 0 end) captured_bytes
        from ledger_sources
        left join ledger_generations on ledger_generations.source_id = ledger_sources.source_id
          and ledger_generations.status = 'trusted'
        """
    ).fetchone()
    return LedgerCoverage(
        total_sources=int(row["total_sources"] or 0),
        captured_sources=int(row["captured_sources"] or 0),
        stale_sources=int(row["stale_sources"] or 0),
        pending_files=int(row["pending_files"] or 0),
        pending_bytes=int(row["pending_bytes"] or 0),
        total_bytes=int(row["total_bytes"] or 0),
        captured_bytes=int(row["captured_bytes"] or 0),
    )


def _row_to_usage_record(row: sqlite3.Row) -> UsageRecord:
    timestamp = parse_timestamp(row["timestamp"])
    return UsageRecord(
        timestamp=timestamp or datetime.fromtimestamp(0, tz=UTC),
        usage=TokenUsage(
            input_tokens=int(row["input_tokens"]),
            cached_input_tokens=int(row["cached_input_tokens"]),
            cache_write_input_tokens=int(row["cache_write_input_tokens"]),
            output_tokens=int(row["output_tokens"]),
            reasoning_output_tokens=int(row["reasoning_output_tokens"]),
            total_tokens=int(row["total_tokens"]),
        ),
        session_id=str(row["task_id"]),
        file_path=Path(row["file_path"]),
        usage_role=parse_usage_role(row["usage_role"]),
        model=str(row["model_key"]),
        turn_id=str(row["turn_id"]),
        effort=str(row["effort"]),
        collaboration_mode=str(row["collaboration_mode"]),
        project_key=str(row["project_key"]),
        project_label=str(row["project_label"]),
        project_aliases=tuple(json.loads(row["project_aliases_json"] or "[]")),
        cwd=str(row["cwd"]),
        git_repository_url=str(row["repository_url"]),
        git_branch=str(row["git_branch"]),
        parent_thread_id=str(row["parent_task_id"]),
    )
