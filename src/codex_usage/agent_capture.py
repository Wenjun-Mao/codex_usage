from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import monotonic

from codex_usage.agent_paths import ledger_database_path
from codex_usage.ledger_queries import LedgerStatus, load_ledger_status
from codex_usage.ledger_schema import ledger_revision, open_ledger
from codex_usage.ledger_sync import synchronize_parser_workset
from codex_usage.session_cache import refresh_cached_session_data
from codex_usage.session_cache_models import CacheStats


CAPTURE_SLICE_BYTES = 64 * 1024 * 1024
CAPTURE_FILE_QUANTUM_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class CaptureResult:
    run_id: int
    request_kind: str
    outcome: str
    elapsed_seconds: float
    status: LedgerStatus
    stats: CacheStats
    error: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "request_kind": self.request_kind,
            "outcome": self.outcome,
            "elapsed_seconds": self.elapsed_seconds,
            "status": self.status.to_dict(),
            "stats": asdict(self.stats),
            "error": self.error,
        }


def session_dirs_for_home(codex_home: Path) -> list[Path]:
    candidates = [codex_home / "sessions", codex_home / "archived_sessions"]
    selected = [path for path in candidates if path.is_dir()]
    if not selected:
        raise FileNotFoundError(
            f"No Codex sessions directory found under {codex_home}"
        )
    return selected


def recover_interrupted_capture_runs(ledger_path: Path) -> int:
    with open_ledger(ledger_path) as connection:
        now = datetime.now(UTC).isoformat()
        cursor = connection.execute(
            """
            update capture_runs
            set completed_at = ?, outcome = 'interrupted',
                error = 'agent stopped before capture completed'
            where outcome = 'running'
            """,
            (now,),
        )
        connection.commit()
        return cursor.rowcount


def capture_once(
    codex_home: Path,
    *,
    request_kind: str,
    max_workers: int | None = None,
    auto_transitions: bool = True,
    preferred_paths: tuple[str, ...] = (),
) -> CaptureResult:
    ledger_path = ledger_database_path(codex_home)
    started = monotonic()
    run_id = _begin_capture(ledger_path, request_kind)
    stats = CacheStats()
    try:
        outcome = refresh_cached_session_data(
            session_dirs_for_home(codex_home),
            cache_database_path=ledger_path,
            auto_transitions=auto_transitions,
            max_workers=max_workers,
            max_parse_bytes=CAPTURE_FILE_QUANTUM_BYTES,
            max_total_parse_bytes=CAPTURE_SLICE_BYTES,
            refresh_storage_metadata=False,
            defer_full_fallback=True,
            preferred_paths=preferred_paths,
        )
        stats = outcome.stats
        revision, _ = synchronize_parser_workset(ledger_path)
        status = load_ledger_status(ledger_path)
        _complete_capture(
            ledger_path,
            run_id,
            outcome="success",
            revision=revision,
            stats=stats,
            status=status,
        )
        status = load_ledger_status(ledger_path)
        return CaptureResult(
            run_id=run_id,
            request_kind=request_kind,
            outcome="success",
            elapsed_seconds=monotonic() - started,
            status=status,
            stats=stats,
        )
    except BaseException as exc:
        error = f"{type(exc).__name__}: {exc}"
        _fail_capture(ledger_path, run_id, error, stats)
        status = load_ledger_status(ledger_path)
        return CaptureResult(
            run_id=run_id,
            request_kind=request_kind,
            outcome="failed",
            elapsed_seconds=monotonic() - started,
            status=status,
            stats=stats,
            error=error,
        )


def _begin_capture(ledger_path: Path, request_kind: str) -> int:
    with open_ledger(ledger_path) as connection:
        cursor = connection.execute(
            """
            insert into capture_runs (
                request_kind, started_at, outcome, ledger_revision, stats_json, error
            ) values (?, ?, 'running', ?, '{}', '')
            """,
            (
                request_kind,
                datetime.now(UTC).isoformat(),
                ledger_revision(connection),
            ),
        )
        connection.commit()
        return int(cursor.lastrowid)


def _complete_capture(
    ledger_path: Path,
    run_id: int,
    *,
    outcome: str,
    revision: int,
    stats: CacheStats,
    status: LedgerStatus,
) -> None:
    with open_ledger(ledger_path) as connection:
        connection.execute(
            """
            update capture_runs set
                completed_at = ?, outcome = ?, ledger_revision = ?,
                files_total = ?, files_parsed = ?, pending_files = ?,
                pending_bytes = ?, source_bytes_read = ?, stats_json = ?, error = ''
            where run_id = ?
            """,
            (
                datetime.now(UTC).isoformat(),
                outcome,
                revision,
                stats.files_total,
                stats.files_parsed,
                status.coverage.pending_files,
                status.coverage.pending_bytes,
                stats.source_bytes_read,
                json.dumps(asdict(stats), sort_keys=True),
                run_id,
            ),
        )
        connection.commit()


def _fail_capture(
    ledger_path: Path,
    run_id: int,
    error: str,
    stats: CacheStats,
) -> None:
    with open_ledger(ledger_path) as connection:
        connection.execute(
            """
            update capture_runs set
                completed_at = ?, outcome = 'failed', ledger_revision = ?,
                files_total = ?, files_parsed = ?, source_bytes_read = ?,
                stats_json = ?, error = ?
            where run_id = ?
            """,
            (
                datetime.now(UTC).isoformat(),
                ledger_revision(connection),
                stats.files_total,
                stats.files_parsed,
                stats.source_bytes_read,
                json.dumps(asdict(stats), sort_keys=True),
                error,
                run_id,
            ),
        )
        connection.commit()
