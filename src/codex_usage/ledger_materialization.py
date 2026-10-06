"""One captured-ledger materialization shared by HTML and structured queries."""
from dataclasses import dataclass
from datetime import tzinfo
import sqlite3

from codex_usage.aggregation import (
    ReportRange, ValuedUsageRecord, filter_records_by_project_keys, value_records,
)
from codex_usage.agent_activity import AgentActivity, build_agent_activity
from codex_usage.image_reporting import ImageReport, ImageReportCoverage, build_image_report
from codex_usage.ledger_queries import (
    LedgerStatus, query_ledger_image_operations, query_ledger_records,
    query_ledger_task_graph, query_ledger_transitions,
)
from codex_usage.parser import finalize_session_records
from codex_usage.project_transitions import apply_project_transitions


@dataclass(frozen=True, slots=True)
class LedgerMaterialization:
    valued: list[ValuedUsageRecord]
    activity: AgentActivity
    images: ImageReport
    transitions: list
    source_counts: dict[str, int]


def materialize_ledger(
    connection: sqlite3.Connection,
    report_range: ReportRange,
    project_keys: list[str],
    timezone: tzinfo,
    status: LedgerStatus,
    *,
    auto_transitions: bool,
) -> LedgerMaterialization:
    """Caller owns the read transaction and evaluation clock; no source I/O."""
    records = finalize_session_records([
        query_ledger_records(connection, bounds=report_range.bounds),
    ])
    transitions = query_ledger_transitions(connection) if auto_transitions else []
    if transitions:
        records = apply_project_transitions(records, transitions)
    records = filter_records_by_project_keys(records, project_keys)
    valued = value_records(records)
    images = build_image_report(
        query_ledger_image_operations(
            connection, bounds=report_range.bounds, project_keys=project_keys,
        ),
        coverage=ImageReportCoverage(
            complete=status.image_backfill.complete,
            artifacts_total=status.image_backfill.artifacts_total,
            tasks_total=status.image_backfill.tasks_total,
            tasks_completed=status.image_backfill.tasks_completed,
            tasks_unavailable=status.image_backfill.tasks_unavailable,
        ),
    )
    source_counts = connection.execute("""
        select count(*) total, sum(storage_state = 'archived') archived,
               sum(is_missing) missing from ledger_sources
    """).fetchone()
    return LedgerMaterialization(
        valued=valued,
        activity=build_agent_activity(records, query_ledger_task_graph(connection), timezone),
        images=images,
        transitions=transitions,
        source_counts={key: int(source_counts[key] or 0) for key in source_counts.keys()},
    )
