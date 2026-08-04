#!/usr/bin/env python3
"""Prove packaged combined cache workers through the frozen executable."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import cast

from codex_usage.parallel_audit import ExpectedTarget, validate_target_architecture
from codex_usage.process_tree import run_process_tree

SCRIPT_DIRECTORY = str(Path(__file__).parent)
if SCRIPT_DIRECTORY not in sys.path:
    sys.path.insert(0, SCRIPT_DIRECTORY)

from parallel_cache_fixture import (
    append_incremental_change,
    write_parallel_cache_fixture,
)

FILE_COUNT = 10
EXPECTED_RECORD_COUNT = FILE_COUNT + 1
EXPECTED_CHANGED_RECORD_COUNT = EXPECTED_RECORD_COUNT + 1
MINIMUM_FILE_BYTES = 2 * 1024 * 1024
COMMAND_TIMEOUT_SECONDS = 120
AUDIT_FIELDS = (
    "version",
    "parent_pid",
    "sys_platform",
    "machine",
    "usage_run",
    "transition_run",
)
RUN_FIELDS = (
    "resolved_worker_count",
    "worker_pids",
    "max_concurrency",
    "used_serial_fallback",
    "infrastructure_error",
    "span_count",
    "file_error_count",
)
EXPECTED_USAGE = {
    "input_tokens": 1_045,
    "cached_input_tokens": 200,
    "cache_write_input_tokens": 0,
    "uncached_input_tokens": 845,
    "ordinary_input_tokens": 845,
    "output_tokens": 145,
    "reasoning_output_tokens": 50,
    "total_tokens": 1_190,
}
EXPECTED_CHANGED_USAGE = {
    "input_tokens": 1_095,
    "cached_input_tokens": 210,
    "cache_write_input_tokens": 0,
    "uncached_input_tokens": 885,
    "ordinary_input_tokens": 885,
    "output_tokens": 155,
    "reasoning_output_tokens": 53,
    "total_tokens": 1_250,
}
TRANSITION_FIELDS = (
    "source_key",
    "source_label",
    "target_key",
    "target_label",
    "effective_from",
    "confidence",
    "evidence",
    "thread_ids",
)
EXPECTED_STABLE_TRANSITION = {
    "source_key": "https://github.com/example/source-00",
    "source_label": "source-00",
    "target_key": "https://github.com/example/packaged-parallel-target",
    "target_label": "packaged-parallel-target",
    "effective_from": "2026-07-31T12:01:00+00:00",
    "confidence": 100,
    "thread_ids": ["packaged-parallel-00"],
}
TRANSITION_EVIDENCE_PREFIX = "verified repo path "
TRANSITION_EVIDENCE_SUFFIX = (
    " -> https://github.com/example/packaged-parallel-target "
    "(thread packaged-parallel-00, "
    "source jsonl:response_item:function_call_workdir)"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Exercise packaged parallel cache refresh and audit output."
    )
    parser.add_argument("--executable", required=True, type=Path)
    parser.add_argument(
        "--expected-target",
        required=True,
        choices=("darwin-arm64", "win32-x64"),
    )
    args = parser.parse_args(argv)

    expected_target = cast(ExpectedTarget, args.expected_target)
    validate_target_architecture(
        expected_target,
        sys_platform=sys.platform,
        machine=platform.machine(),
    )
    executable = args.executable.resolve()
    if not executable.is_file():
        raise RuntimeError(f"packaged executable does not exist: {executable}")

    with tempfile.TemporaryDirectory(
        prefix="codex-usage-packaged-parallel-"
    ) as directory:
        root = Path(directory)
        corpus = write_parallel_cache_fixture(
            root / "codex-home",
            file_count=FILE_COUNT,
            minimum_file_bytes=MINIMUM_FILE_BYTES,
        )
        cache_dir = root / "cache"
        cold = _run_summary_with_audit(
            executable, corpus.sessions_dir.parent, cache_dir, root / "cold-audit.json"
        )
        _validate_summary(cold[0])
        cold_evidence = _validate_audit(cold[1], expected_target)

        warm = _run_summary_with_audit(
            executable, corpus.sessions_dir.parent, cache_dir, root / "warm-audit.json"
        )
        _validate_summary(warm[0])
        warm_evidence = _validate_audit(
            warm[1], expected_target, usage_must_be_parallel=False
        )
        if _stable_summary(cold[0]) != _stable_summary(warm[0]):
            raise RuntimeError("packaged warm summary payload differs from cold payload")

        changed_file = append_incremental_change(corpus)
        changed = _run_summary_with_audit(
            executable, corpus.sessions_dir.parent, cache_dir, root / "changed-audit.json"
        )
        _validate_summary(
            changed[0],
            expected_record_count=EXPECTED_CHANGED_RECORD_COUNT,
            expected_usage=EXPECTED_CHANGED_USAGE,
        )
        changed_evidence = _validate_audit(
            changed[1], expected_target, expected_usage_span_count=1
        )

        oracle = _run_summary(
            executable, corpus.sessions_dir.parent, root / "cold-oracle-cache"
        )
        _validate_summary(
            oracle,
            expected_record_count=EXPECTED_CHANGED_RECORD_COUNT,
            expected_usage=EXPECTED_CHANGED_USAGE,
        )
        if _stable_summary(changed[0]) != _stable_summary(oracle):
            raise RuntimeError("packaged incremental summary differs from cold oracle")

        payload = {
            "expected_target": expected_target,
            "sys_platform": sys.platform,
            "machine": platform.machine(),
            "corpus": {
                "file_count": len(corpus.files),
                "byte_count": corpus.byte_count,
                "minimum_file_bytes": min(path.stat().st_size for path in corpus.files),
            },
            "cold": {"summary_sha256": _json_digest(_stable_summary(cold[0])), **cold_evidence},
            "warm": warm_evidence,
            "changed": {
                "summary_sha256": _json_digest(_stable_summary(changed[0])),
                "source_bytes_eligible": changed_file.stat().st_size,
                **changed_evidence,
            },
        }
        print(json.dumps(payload, sort_keys=True))
    return 0


def _run_summary_with_audit(
    executable: Path,
    codex_home: Path,
    cache_dir: Path,
    audit_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    return _run_summary(executable, codex_home, cache_dir, audit_path=audit_path), _read_json_object(
        audit_path, "parallel audit"
    )


def _run_summary(
    executable: Path,
    codex_home: Path,
    cache_dir: Path,
    *,
    audit_path: Path | None = None,
) -> dict[str, object]:
    command = [str(executable), "summary", "--range", "all", "--json"]
    if audit_path is not None:
        command.extend(["--parallel-audit", str(audit_path)])
    environment = os.environ.copy()
    environment.update(
        {
            "CODEX_HOME": str(codex_home),
            "CODEX_USAGE_CACHE_DIR": str(cache_dir),
            "CODEX_USAGE_AUTO_PROJECT_TRANSITIONS": "true",
            "CODEX_USAGE_TIMEZONE": "UTC",
            "PYTHONNOUSERSITE": "1",
        }
    )
    environment.pop("PYTHONPATH", None)
    try:
        completed = run_process_tree(
            command,
            environment=environment,
            cwd=codex_home,
            timeout_seconds=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("packaged command exceeded recursion deadlock guard") from error
    if completed.returncode != 0:
        raise RuntimeError(
            f"packaged command exited with code {completed.returncode}\n"
            f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
        )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError("packaged command stdout was not one JSON object") from error
    if not isinstance(payload, dict):
        raise TypeError("packaged command stdout was not a JSON object")
    return payload


def _validate_summary(
    payload: dict[str, object],
    *,
    expected_record_count: int = EXPECTED_RECORD_COUNT,
    expected_usage: dict[str, int] = EXPECTED_USAGE,
) -> None:
    if payload.get("files_scanned") != FILE_COUNT:
        raise RuntimeError("packaged summary scanned an unexpected file count")
    total = payload.get("total")
    if not isinstance(total, dict) or total.get("record_count") != expected_record_count:
        raise RuntimeError("packaged summary returned an unexpected record count")
    if total.get("usage") != expected_usage:
        raise RuntimeError("packaged summary returned unexpected usage totals")
    transitions = payload.get("project_transitions")
    if not isinstance(transitions, list) or len(transitions) != 1:
        raise RuntimeError("packaged summary did not retain deterministic transition evidence")
    transition = transitions[0]
    if not isinstance(transition, dict) or set(transition) != set(TRANSITION_FIELDS):
        raise RuntimeError("packaged summary returned an invalid deterministic transition")
    stable_transition = {key: transition.get(key) for key in EXPECTED_STABLE_TRANSITION}
    if stable_transition != EXPECTED_STABLE_TRANSITION:
        raise RuntimeError("packaged summary returned an invalid deterministic transition")
    _validate_transition_evidence(transition.get("evidence"))


def _validate_transition_evidence(evidence: object) -> None:
    if not isinstance(evidence, list) or len(evidence) != 1:
        raise RuntimeError("packaged summary returned invalid transition evidence")
    text = evidence[0]
    if not isinstance(text, str):
        raise TypeError("packaged summary returned invalid transition evidence")
    if not text.startswith(TRANSITION_EVIDENCE_PREFIX) or not text.endswith(
        TRANSITION_EVIDENCE_SUFFIX
    ):
        raise RuntimeError("packaged summary returned invalid transition evidence")
    path_text = text[len(TRANSITION_EVIDENCE_PREFIX) : -len(TRANSITION_EVIDENCE_SUFFIX)]
    if not path_text or not Path(path_text).is_absolute():
        raise RuntimeError("packaged summary returned invalid transition evidence")


def _validate_audit(
    audit: dict[str, object],
    expected_target: ExpectedTarget,
    *,
    usage_must_be_parallel: bool = True,
    expected_usage_span_count: int | None = None,
) -> dict[str, dict[str, object]]:
    if (
        tuple(audit) != AUDIT_FIELDS
        or type(audit.get("version")) is not int
        or audit["version"] != 1
    ):
        raise RuntimeError("packaged audit fields or version are invalid")
    parent_pid = audit.get("parent_pid")
    audit_platform = audit.get("sys_platform")
    audit_machine = audit.get("machine")
    if type(parent_pid) is not int or parent_pid <= 0:
        raise RuntimeError("packaged audit parent PID is invalid")
    if not isinstance(audit_platform, str) or not isinstance(audit_machine, str):
        raise TypeError("packaged audit architecture fields are invalid")
    validate_target_architecture(
        expected_target, sys_platform=audit_platform, machine=audit_machine
    )
    if audit_platform != sys.platform or audit_machine.casefold() != platform.machine().casefold():
        raise RuntimeError("packaged audit architecture differs from smoke host")

    usage_run = _audit_run(audit, "usage_run", "usage")
    transition_run = _audit_run(audit, "transition_run", "transition")
    if expected_usage_span_count is not None:
        _require_exact_usage_span_count(
            usage_run,
            expected_span_count=expected_usage_span_count,
        )
    elif usage_must_be_parallel:
        _require_actual_parallel_audit(usage_run, parent_pid=parent_pid, label="usage")
    else:
        _require_idle_audit(usage_run, "warm usage")
    _require_idle_audit(transition_run, "transition")
    return {"usage_run": usage_run, "transition_run": transition_run}


def _audit_run(
    audit: dict[str, object], key: str, label: str
) -> dict[str, object]:
    value = audit.get(key)
    if not isinstance(value, dict):
        raise TypeError(f"{label}: packaged audit run is not an object")
    return value


def _require_actual_parallel_audit(
    run: dict[str, object], *, parent_pid: int, label: str
) -> None:
    worker_pids = run.get("worker_pids")
    valid_pids = (
        isinstance(worker_pids, list)
        and all(type(pid) is int and pid > 0 for pid in worker_pids)
        and len(set(worker_pids)) >= 2
        and parent_pid not in worker_pids
    )
    actual_parallel = (
        tuple(run) == RUN_FIELDS
        and type(run.get("resolved_worker_count")) is int
        and run["resolved_worker_count"] > 1
        and valid_pids
        and type(run.get("max_concurrency")) is int
        and run["max_concurrency"] >= 2
        and run.get("used_serial_fallback") is False
        and run.get("infrastructure_error") == ""
        and type(run.get("span_count")) is int
        and run["span_count"] >= 2
        and type(run.get("file_error_count")) is int
        and run["file_error_count"] == 0
    )
    if not actual_parallel:
        raise RuntimeError(f"{label}: actual process parallelism not observed")


def _require_idle_audit(run: dict[str, object], label: str) -> None:
    idle = (
        tuple(run) == RUN_FIELDS
        and run.get("resolved_worker_count") == 0
        and run.get("worker_pids") == []
        and run.get("max_concurrency") == 0
        and run.get("used_serial_fallback") is False
        and run.get("infrastructure_error") == ""
        and run.get("span_count") == 0
        and run.get("file_error_count") == 0
    )
    if not idle:
        raise RuntimeError(f"{label}: unexpected worker spans")


def _require_exact_usage_span_count(
    run: dict[str, object],
    *,
    expected_span_count: int,
) -> None:
    worker_pids = run.get("worker_pids")
    exact = (
        expected_span_count == 1
        and tuple(run) == RUN_FIELDS
        and type(run.get("resolved_worker_count")) is int
        and run["resolved_worker_count"] == 1
        and isinstance(worker_pids, list)
        and len(worker_pids) == 1
        and type(worker_pids[0]) is int
        and worker_pids[0] > 0
        and type(run.get("max_concurrency")) is int
        and run["max_concurrency"] == 1
        and run.get("used_serial_fallback") is False
        and run.get("infrastructure_error") == ""
        and type(run.get("span_count")) is int
        and run["span_count"] == expected_span_count
        and type(run.get("file_error_count")) is int
        and run["file_error_count"] == 0
    )
    if not exact:
        raise RuntimeError("changed usage: expected one combined worker span")


def _read_json_object(path: Path, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"could not read {label}") from error
    if not isinstance(value, dict):
        raise TypeError(f"{label} was not a JSON object")
    return value


def _stable_summary(payload: dict[str, object]) -> dict[str, object]:
    stable = dict(payload)
    stable.pop("generated_at", None)
    return stable


def _json_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
