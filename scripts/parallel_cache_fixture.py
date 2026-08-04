"""Create a disposable session corpus for cache acceptance checks."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FixtureCorpus:
    """Paths and sizes owned by a synthetic cache-acceptance corpus."""

    sessions_dir: Path
    files: tuple[Path, ...]
    transition_target: Path
    changed_file: Path

    @property
    def byte_count(self) -> int:
        return sum(path.stat().st_size for path in self.files)


def write_parallel_cache_fixture(
    root: Path,
    *,
    file_count: int = 10,
    minimum_file_bytes: int = 2 * 1024 * 1024,
) -> FixtureCorpus:
    """Write an isolated corpus that exercises usage and transition parsing."""
    if file_count < 2:
        raise ValueError("parallel cache fixture requires at least two files")
    if minimum_file_bytes < 1:
        raise ValueError("parallel cache fixture files must be nonempty")

    sessions_dir = root / "sessions"
    day = sessions_dir / "2026" / "07" / "31"
    day.mkdir(parents=True, exist_ok=True)
    transition_target = _write_transition_target(root / "transition-target")
    files = tuple(
        day / f"parallel-{index:02d}.jsonl" for index in range(file_count)
    )
    for index, path in enumerate(files):
        _write_large_session(
            path,
            index=index,
            transition_target=transition_target,
            minimum_file_bytes=minimum_file_bytes,
        )
    return FixtureCorpus(
        sessions_dir=sessions_dir,
        files=files,
        transition_target=transition_target,
        changed_file=files[0],
    )


def append_incremental_change(corpus: FixtureCorpus) -> Path:
    """Append one usage event and one workdir event to exactly one fixture file."""
    with corpus.changed_file.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(
            _json_lines(
                {
                    "timestamp": "2026-07-31T12:03:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "arguments": json.dumps(
                            {"workdir": str(corpus.transition_target)}
                        ),
                    },
                },
                _token_count_row(
                    "2026-07-31T12:04:00Z",
                    {
                        "input_tokens": 150,
                        "cached_input_tokens": 30,
                        "cache_write_input_tokens": 0,
                        "output_tokens": 20,
                        "reasoning_output_tokens": 8,
                        "total_tokens": 170,
                    },
                ),
            )
        )
    return corpus.changed_file


def _write_transition_target(path: Path) -> Path:
    git_dir = path / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        '[remote "origin"]\n'
        "    url = https://github.com/example/packaged-parallel-target.git\n",
        encoding="utf-8",
    )
    return path


def _write_large_session(
    path: Path,
    *,
    index: int,
    transition_target: Path,
    minimum_file_bytes: int,
) -> None:
    timestamp = f"2026-07-31T12:00:{index:02d}Z"
    prefix = _json_lines(
        {
            "timestamp": timestamp,
            "type": "session_meta",
            "payload": {
                "id": f"packaged-parallel-{index:02d}",
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
    rows = [_token_count_row(timestamp, initial_usage)]
    if index == 0:
        rows.extend(
            (
                {
                    "timestamp": "2026-07-31T12:01:00Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "arguments": json.dumps({"workdir": str(transition_target)}),
                    },
                },
                _token_count_row("2026-07-31T12:02:00Z", final_usage),
            )
        )
    suffix = _json_lines(*rows)
    repetitions = max(0, minimum_file_bytes - len(prefix) - len(suffix))
    padding = filler * ((repetitions + len(filler) - 1) // len(filler))
    path.write_text(prefix + padding + suffix, encoding="utf-8")


def _json_lines(*rows: dict[str, object]) -> str:
    return "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows)


def _token_count_row(timestamp: str, usage: dict[str, int]) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "event_msg",
        "payload": {"type": "token_count", "info": {"total_token_usage": usage}},
    }
