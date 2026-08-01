#!/usr/bin/env python3
"""Prove spawned cache workers through the frozen command-line executable."""

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
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from codex_usage.parallel_audit import ExpectedTarget, validate_target_architecture

FILE_COUNT = 10
EXPECTED_RECORD_COUNT = FILE_COUNT + 1
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


@dataclass(frozen=True, slots=True)
class CorpusMetrics:
    file_count: int
    byte_count: int
    minimum_file_bytes: int


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
        codex_home = root / "codex-home"
        cache_dir = root / "cache"
        audit_path = root / "cold-audit.json"
        corpus = _write_corpus(codex_home)

        cold = _run_summary(executable, codex_home, cache_dir, audit_path=audit_path)
        _validate_summary(cold)
        audit = _read_json_object(audit_path, "parallel audit")
        evidence = _validate_audit(audit, expected_target)

        warm = _run_summary(executable, codex_home, cache_dir)
        _validate_summary(warm)
        if _stable_summary(cold) != _stable_summary(warm):
            raise RuntimeError(
                "packaged warm summary payload differs from cold payload"
            )

        payload = {
            "expected_target": expected_target,
            "sys_platform": sys.platform,
            "machine": platform.machine(),
            "corpus": {
                "file_count": corpus.file_count,
                "byte_count": corpus.byte_count,
                "minimum_file_bytes": corpus.minimum_file_bytes,
            },
            "record_count": EXPECTED_RECORD_COUNT,
            "total_tokens": EXPECTED_USAGE["total_tokens"],
            "summary_sha256": _json_digest(_stable_summary(cold)),
            "usage_run": evidence["usage_run"],
            "transition_run": evidence["transition_run"],
        }
        print(json.dumps(payload, sort_keys=True))
    return 0


def _write_corpus(codex_home: Path) -> CorpusMetrics:
    day = codex_home / "sessions" / "2026" / "07" / "31"
    day.mkdir(parents=True, exist_ok=True)
    target_repo = codex_home.parent / "transition-target"
    git_dir = target_repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        '[remote "origin"]\n'
        "    url = https://github.com/example/packaged-parallel-target.git\n",
        encoding="utf-8",
    )

    sizes: list[int] = []
    for index in range(FILE_COUNT):
        path = day / f"parallel-{index:02d}.jsonl"
        _write_large_session(path, index=index, transition_target=target_repo)
        sizes.append(path.stat().st_size)
    if min(sizes) < MINIMUM_FILE_BYTES:
        raise RuntimeError("packaged smoke corpus files are smaller than required")
    return CorpusMetrics(FILE_COUNT, sum(sizes), min(sizes))


def _write_large_session(
    path: Path,
    *,
    index: int,
    transition_target: Path,
) -> None:
    session_id = f"packaged-parallel-{index:02d}"
    timestamp = f"2026-07-31T12:00:{index:02d}Z"
    prefix = _json_lines(
        {
            "timestamp": timestamp,
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "timestamp": timestamp,
                "cwd": f"/source/project/{index:02d}",
                "source": "cli",
                "git": {
                    "repository_url": f"https://github.com/example/source-{index:02d}.git",
                    "branch": "main",
                },
            },
        },
        {
            "timestamp": timestamp,
            "type": "turn_context",
            "payload": {"model": "gpt-5", "turn_id": f"turn-{index:02d}"},
        },
    )
    filler = _json_lines(
        {
            "timestamp": timestamp,
            "type": "event_msg",
            "payload": {
                "type": "task_started",
                "turn_id": f"turn-{index:02d}",
                "padding": "x" * 896,
            },
        }
    )
    final_usage = {
        "input_tokens": 100 + index,
        "cached_input_tokens": 20,
        "cache_write_input_tokens": 0,
        "output_tokens": 10 + index,
        "reasoning_output_tokens": 5,
        "total_tokens": 110 + (2 * index),
    }
    initial_usage = (
        {
            "input_tokens": 50,
            "cached_input_tokens": 10,
            "cache_write_input_tokens": 0,
            "output_tokens": 5,
            "reasoning_output_tokens": 2,
            "total_tokens": 55,
        }
        if index == 0
        else final_usage
    )
    suffix_rows = [_token_count_row(timestamp, initial_usage)]
    if index == 0:
        suffix_rows.extend(
            [
                {
                    "timestamp": "2026-07-31T12:01:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "arguments": json.dumps({"workdir": str(transition_target)}),
                    },
                },
                _token_count_row("2026-07-31T12:02:00Z", final_usage),
            ]
        )
    suffix = _json_lines(*suffix_rows)
    missing_bytes = max(0, MINIMUM_FILE_BYTES - len(prefix) - len(suffix))
    repetitions = (missing_bytes + len(filler) - 1) // len(filler)
    path.write_text(prefix + (filler * repetitions) + suffix, encoding="utf-8")


def _json_lines(*rows: dict[str, object]) -> str:
    return "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)


def _token_count_row(
    timestamp: str,
    usage: dict[str, int],
) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {
            "type": "token_count",
            "info": {"total_token_usage": usage},
        },
    }


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
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=environment,
            cwd=codex_home,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError(
            "packaged command exceeded recursion deadlock guard"
        ) from error
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


def _validate_summary(payload: dict[str, object]) -> None:
    if payload.get("files_scanned") != FILE_COUNT:
        raise RuntimeError("packaged summary scanned an unexpected file count")
    total = payload.get("total")
    if (
        not isinstance(total, dict)
        or total.get("record_count") != EXPECTED_RECORD_COUNT
    ):
        raise RuntimeError("packaged summary returned an unexpected record count")
    if total.get("usage") != EXPECTED_USAGE:
        raise RuntimeError("packaged summary returned unexpected usage totals")
    transitions = payload.get("project_transitions")
    if not isinstance(transitions, list) or len(transitions) != 1:
        raise RuntimeError(
            "packaged summary did not retain deterministic transition evidence"
        )


def _validate_audit(
    audit: dict[str, object],
    expected_target: ExpectedTarget,
) -> dict[str, dict[str, object]]:
    if tuple(audit) != AUDIT_FIELDS or audit.get("version") != 1:
        raise RuntimeError("packaged audit fields or version are invalid")
    parent_pid = audit.get("parent_pid")
    audit_platform = audit.get("sys_platform")
    audit_machine = audit.get("machine")
    if type(parent_pid) is not int or parent_pid <= 0:
        raise RuntimeError("packaged audit parent PID is invalid")
    if not isinstance(audit_platform, str) or not isinstance(audit_machine, str):
        raise TypeError("packaged audit architecture fields are invalid")
    validate_target_architecture(
        expected_target,
        sys_platform=audit_platform,
        machine=audit_machine,
    )
    if (
        audit_platform != sys.platform
        or audit_machine.casefold() != platform.machine().casefold()
    ):
        raise RuntimeError("packaged audit architecture differs from smoke host")

    evidence: dict[str, dict[str, object]] = {}
    for key, label in (
        ("usage_run", "cold usage"),
        ("transition_run", "cold transition"),
    ):
        value = audit.get(key)
        if not isinstance(value, dict):
            raise TypeError(f"{label}: packaged audit run is not an object")
        _require_actual_parallel_audit(value, parent_pid=parent_pid, label=label)
        evidence[key] = value
    return evidence


def _require_actual_parallel_audit(
    run: dict[str, object],
    *,
    parent_pid: int,
    label: str,
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
        and run.get("file_error_count") == 0
    )
    if not actual_parallel:
        raise RuntimeError(f"{label}: actual process parallelism not observed")


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
