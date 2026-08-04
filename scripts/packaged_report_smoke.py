"""Prove the frozen executable renders project role/model report charts."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from pathlib import Path

from codex_usage.process_tree import run_process_tree

_REPORT_MARKERS = (
    "<h2>Project Breakdown</h2>",
    "<h2>Model Mix</h2>",
    'class="project-role-group"',
    'class="model-segment',
    "Root tasks",
    "Subagents",
)
_COMMAND_TIMEOUT_SECONDS = 120


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify the packaged project role/model report contract."
    )
    parser.add_argument("--executable", required=True, type=Path)
    args = parser.parse_args(argv)
    executable = args.executable.resolve()
    if not executable.is_file():
        raise RuntimeError(f"packaged executable does not exist: {executable}")

    with tempfile.TemporaryDirectory(prefix="codex-usage-packaged-report-") as directory:
        root = Path(directory)
        home = root / "codex-home"
        _write_synthetic_home(home)
        report = root / "report.html"
        completed = _run_report(executable, home, root / "cache", report)
        if completed.returncode != 0:
            raise RuntimeError(
                "packaged report command failed "
                f"with code {completed.returncode}\nstdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
            )
        report_html = report.read_text(encoding="utf-8")
        _validate_report(report_html)
        print(
            json.dumps(
                {
                    "report_bytes": len(report_html.encode()),
                    "required_markers": len(_REPORT_MARKERS),
                    "synthetic_sessions": 2,
                },
                sort_keys=True,
            )
        )
    return 0


def _run_report(
    executable: Path,
    home: Path,
    cache_dir: Path,
    report: Path,
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "CODEX_HOME": str(home),
            "CODEX_USAGE_CACHE_DIR": str(cache_dir),
            "CODEX_USAGE_TIMEZONE": "UTC",
            "PYTHONNOUSERSITE": "1",
        }
    )
    environment.pop("PYTHONPATH", None)
    try:
        return run_process_tree(
            [str(executable), "report", "--range", "all", "--theme", "night", "--output", str(report)],
            environment=environment,
            cwd=home,
            timeout_seconds=_COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise RuntimeError("packaged report command exceeded timeout") from error


def _write_synthetic_home(home: Path) -> None:
    sessions = home / "sessions" / "2026" / "08" / "04"
    sessions.mkdir(parents=True)
    _write_session(
        sessions / "root.jsonl",
        session_id="packaged-root",
        source="cli",
        models=(("gpt-5.6-sol", 1_000), ("gpt-5.5", 1_600)),
    )
    _write_session(
        sessions / "subagent.jsonl",
        session_id="packaged-subagent",
        source={"subagent": {"thread_spawn": {"parent_thread_id": "packaged-root"}}},
        models=(("gpt-5.4", 900), ("gpt-5.3-codex", 1_400)),
    )


def _write_session(
    path: Path,
    *,
    session_id: str,
    source: object,
    models: tuple[tuple[str, int], ...],
) -> None:
    rows: list[dict[str, object]] = [
        {
            "timestamp": "2026-08-04T12:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": "/synthetic/project",
                "git": {
                    "repository_url": "https://github.com/example/packaged-report.git",
                    "branch": "main",
                },
                "source": source,
            },
        }
    ]
    for index, (model, total_tokens) in enumerate(models, start=1):
        timestamp = f"2026-08-04T12:00:{index:02d}Z"
        rows.extend(
            (
                {"timestamp": timestamp, "type": "turn_context", "payload": {"model": model}},
                {
                    "timestamp": timestamp,
                    "type": "event_msg",
                    "payload": {
                        "type": "token_count",
                        "info": {
                            "total_token_usage": {
                                "input_tokens": total_tokens * 3 // 4,
                                "cached_input_tokens": total_tokens // 5,
                                "cache_write_input_tokens": total_tokens // 20,
                                "output_tokens": total_tokens // 4,
                                "reasoning_output_tokens": total_tokens // 25,
                                "total_tokens": total_tokens,
                            }
                        },
                    },
                },
            )
        )
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _validate_report(report_html: str) -> None:
    missing = [marker for marker in _REPORT_MARKERS if marker not in report_html]
    if missing:
        raise RuntimeError(f"packaged report is missing required markers: {missing!r}")


if __name__ == "__main__":
    raise SystemExit(main())
