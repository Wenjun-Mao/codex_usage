from __future__ import annotations

import hashlib
import html
import json
import sqlite3
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic

from codex_usage import __version__
from codex_usage.aggregation import (
    aggregate_valued_records,
    filter_records_by_project_keys,
    resolve_range_bounds,
    resolve_timezone,
    summarize_valued_records,
    value_records,
)
from codex_usage.agent_paths import ledger_database_path
from codex_usage.ledger_queries import (
    LedgerStatus,
    query_ledger_records,
    query_ledger_status,
    query_ledger_transitions,
)
from codex_usage.ledger_schema import ledger_revision, open_ledger
from codex_usage.parser import finalize_session_records
from codex_usage.pricing import PRICING_AS_OF
from codex_usage.project_transitions import apply_project_transitions
from codex_usage.report_breakdown import build_report_breakdown_from_valued
from codex_usage.reporting import render_html_report


PRICING_REVISION = f"{PRICING_AS_OF}:{__version__}"


@dataclass(frozen=True, slots=True)
class RenderedLedgerReport:
    html: str
    ledger_revision: int
    cache_hit: bool
    elapsed_seconds: float
    status: LedgerStatus

    def to_dict(self) -> dict[str, object]:
        return {
            "html": self.html,
            "ledger_revision": self.ledger_revision,
            "cache_hit": self.cache_hit,
            "elapsed_seconds": self.elapsed_seconds,
            "status": self.status.to_dict(),
        }


def render_ledger_report(
    codex_home: Path,
    *,
    range_name: str,
    project_keys: list[str] | None,
    theme: str,
    timezone_name: str | None,
    auto_transitions: bool = True,
) -> RenderedLedgerReport:
    started = monotonic()
    ledger_path = ledger_database_path(codex_home)
    timezone = resolve_timezone(timezone_name)
    normalized_keys = sorted({key for key in project_keys or [] if key})
    bounds = resolve_range_bounds(range_name, timezone)
    with open_ledger(ledger_path, read_only=True) as connection:
        connection.execute("begin")
        status = query_ledger_status(connection)
        cache_key = _report_cache_key(
            status.revision,
            range_name,
            normalized_keys,
            theme,
            str(timezone),
            auto_transitions,
        )
        cached = _load_cached_report(connection, cache_key)
        if cached is not None:
            return RenderedLedgerReport(
                html=cached,
                ledger_revision=status.revision,
                cache_hit=True,
                elapsed_seconds=monotonic() - started,
                status=status,
            )

        records = finalize_session_records(
            [query_ledger_records(connection, bounds=bounds)]
        )
        transitions = (
            query_ledger_transitions(connection) if auto_transitions else []
        )
        source_counts = connection.execute(
            """
            select count(*) total,
                   sum(storage_state = 'archived') archived,
                   sum(is_missing) missing
            from ledger_sources
            """
        ).fetchone()
    if transitions:
        records = apply_project_transitions(records, transitions)
    records = filter_records_by_project_keys(records, normalized_keys)
    valued = value_records(records)
    with tempfile.TemporaryDirectory(prefix="codex-usage-report-") as directory:
        output_path = Path(directory) / "report.html"
        render_html_report(
            output_path=output_path,
            generated_at=datetime.now(timezone),
            range_name=range_name,
            total=summarize_valued_records(valued),
            daily_rows=aggregate_valued_records(valued, "day", timezone),
            hourly_rows=aggregate_valued_records(valued, "hour", timezone),
            breakdown=build_report_breakdown_from_valued(valued),
            sessions_dirs=[],
            files_scanned=int(source_counts["total"] or 0),
            files_archived=int(source_counts["archived"] or 0),
            files_retained_missing=int(source_counts["missing"] or 0),
            project_keys=normalized_keys,
            project_transitions=[transition.to_dict() for transition in transitions],
            storage_snapshot=None,
            theme=theme,
            data_status_html=_status_banner(status),
            embedded_usage_only=True,
        )
        rendered = output_path.read_text(encoding="utf-8")
    _store_cached_report(ledger_path, cache_key, status.revision, rendered)
    return RenderedLedgerReport(
        html=rendered,
        ledger_revision=status.revision,
        cache_hit=False,
        elapsed_seconds=monotonic() - started,
        status=status,
    )


def _status_banner(status: LedgerStatus) -> str:
    if status.coverage.complete:
        return ""
    percentage = status.coverage.fraction * 100
    detail = (
        f"Baseline capture is {percentage:.1f}% complete. Totals shown below are partial; "
        f"{status.coverage.pending_files:,} source files and "
        f"{status.coverage.pending_bytes:,} bytes remain."
    )
    return (
        '<div class="notice warning" role="status">'
        f"<strong>Incomplete usage baseline.</strong> {html.escape(detail)}"
        "</div>"
    )


def _report_cache_key(
    revision: int,
    range_name: str,
    project_keys: list[str],
    theme: str,
    timezone: str,
    auto_transitions: bool,
) -> str:
    payload = json.dumps(
        {
            "ledger_revision": revision,
            "pricing_revision": PRICING_REVISION,
            "range": range_name,
            "project_keys": project_keys,
            "theme": theme,
            "timezone": timezone,
            "auto_transitions": auto_transitions,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _load_cached_report(
    connection: sqlite3.Connection,
    cache_key: str,
) -> str | None:
    row = connection.execute(
        "select html from rendered_reports where cache_key = ?", (cache_key,)
    ).fetchone()
    return str(row["html"]) if row is not None else None


def _store_cached_report(
    ledger_path: Path,
    cache_key: str,
    revision: int,
    rendered: str,
) -> None:
    with open_ledger(ledger_path) as connection:
        current_revision = ledger_revision(connection)
        if current_revision != revision:
            return
        connection.execute(
            """
            insert or replace into rendered_reports (
                cache_key, ledger_revision, pricing_revision, created_at, html
            ) values (?, ?, ?, ?, ?)
            """,
            (
                cache_key,
                revision,
                PRICING_REVISION,
                datetime.now().astimezone().isoformat(),
                rendered,
            ),
        )
        connection.execute("delete from rendered_reports where ledger_revision < ?", (revision,))
        connection.commit()
