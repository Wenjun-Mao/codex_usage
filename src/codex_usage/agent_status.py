"""Public collector status and versioned feature declarations."""
from __future__ import annotations

import os
from pathlib import Path

from codex_usage.agent_paths import ledger_database_path
from codex_usage.agent_protocol import ACCOUNTING_CAPABILITY, AgentDescriptor
from codex_usage.ledger_queries import load_ledger_status


def runtime_status_payload(
    codex_home: Path,
    descriptor: AgentDescriptor,
    *,
    capture_running: bool,
    next_capture_seconds: float | None,
    dirty_paths: int,
) -> dict[str, object]:
    status = load_ledger_status(ledger_database_path(codex_home)).to_dict()
    status.update(
        {
            "agent_pid": os.getpid(),
            "api_version": descriptor.api_version,
            "codex_home": str(codex_home),
            "capture_running": capture_running,
            "next_capture_seconds": next_capture_seconds,
            "dirty_paths": dirty_paths,
            "capabilities": [
                ACCOUNTING_CAPABILITY,
                "custom-report-range",
                "agent-activity",
                "image-generation-accounting",
                "observed-output-speed-v1",
                "usage-allowance-breakdown-v1",
                "on-demand-allowance-history-v1",
                "plan-allowance",
                "private-companion-v1",
            ],
        }
    )
    return status
