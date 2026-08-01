from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
from pathlib import Path
from typing import Literal

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from codex_usage.parallel.execution import ParallelRunReport

type ExpectedTarget = Literal["darwin-arm64", "win32-x64"]


def write_parallel_audit(
    path: Path,
    *,
    parent_pid: int,
    usage_run: ParallelRunReport,
    transition_run: ParallelRunReport,
) -> Path:
    if parent_pid <= 0:
        raise ValueError("parent_pid must be greater than zero")
    payload = {
        "version": 1,
        "parent_pid": parent_pid,
        "sys_platform": sys.platform,
        "machine": platform.machine(),
        "usage_run": _audit_run(usage_run),
        "transition_run": _audit_run(transition_run),
    }
    _atomic_write(path, json.dumps(payload, indent=2) + "\n")
    return path


def require_actual_parallel(
    report: ParallelRunReport,
    *,
    parent_pid: int,
    label: str,
) -> None:
    if parent_pid in report.worker_pids or not report.actually_parallel(parent_pid):
        raise RuntimeError(f"{label}: actual process parallelism not observed")


def validate_target_architecture(
    expected_target: ExpectedTarget,
    *,
    sys_platform: str,
    machine: str,
) -> None:
    normalized_machine = machine.casefold()
    matches = (
        expected_target == "darwin-arm64"
        and sys_platform == "darwin"
        and normalized_machine == "arm64"
    ) or (
        expected_target == "win32-x64"
        and sys_platform == "win32"
        and normalized_machine in {"amd64", "x86_64"}
    )
    if not matches:
        raise RuntimeError(
            "unsupported target architecture: "
            f"expected {expected_target}, got {sys_platform}-{machine}"
        )


def _audit_run(report: ParallelRunReport) -> dict[str, object]:
    return {
        "resolved_worker_count": report.resolved_worker_count,
        "worker_pids": list(report.worker_pids),
        "max_concurrency": report.max_concurrency,
        "used_serial_fallback": report.used_serial_fallback,
        "infrastructure_error": _error_kind(report.infrastructure_error),
        "span_count": len(report.worker_spans),
        "file_error_count": report.file_error_count,
    }


def _error_kind(error: str) -> str:
    if not error:
        return ""
    candidate = error.partition(":")[0].strip()
    return candidate if candidate.isidentifier() else "error"


@retry(
    retry=retry_if_exception_type(OSError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.05, min=0.05, max=0.2),
    reraise=True,
)
def _atomic_write(path: Path, contents: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(contents)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
