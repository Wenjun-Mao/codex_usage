"""Capture-only orchestration; report code never imports the probe or recovery."""
from datetime import UTC, datetime

from codex_usage.allowance_probe import QuotaRead, probe_allowance
from codex_usage.allowance_recovery import recover_allowance
from codex_usage.allowance_store import store_read, synchronize_quota_cache
from codex_usage.ledger_schema import increment_ledger_revision, open_ledger


def capture_quota_read(codex_home, ledger_path, run_id):
    try:
        read = probe_allowance(codex_home)
    except Exception:
        # Transport failures must not discard an otherwise successful capture.
        # Never persist the exception text, which may contain private values.
        read = QuotaRead(datetime.now(UTC).isoformat(), diagnostics="probe_failed")
    with open_ledger(ledger_path) as connection:
        store_read(connection, read, run_id)
        revision = increment_ledger_revision(connection)
        connection.commit()
    return revision


def recover_captured_allowance(ledger_path):
    with open_ledger(ledger_path) as connection:
        synchronize_quota_cache(connection)
        recover_allowance(connection)
        revision = increment_ledger_revision(connection)
        connection.commit()
    return revision
