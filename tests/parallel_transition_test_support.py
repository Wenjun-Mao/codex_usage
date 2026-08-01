from __future__ import annotations

import json
import random
import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType
from typing import ClassVar, Self

from codex_usage.parallel.execution import resolve_worker_count
from codex_usage.parallel.transitions import TransitionScanRequest, TransitionScanResult


@dataclass(frozen=True, slots=True)
class TransitionCorpus:
    session_dirs: tuple[Path, ...]
    session_files: tuple[Path, ...]
    repeated_repo: Path


def write_transition_corpus(
    root: Path,
    *,
    repeat_same_path: bool = False,
) -> TransitionCorpus:
    codex_home = root / "codex-home"
    sessions = codex_home / "sessions"
    day = sessions / "2026" / "07" / "31"
    day.mkdir(parents=True, exist_ok=True)

    alpha_repo = root / "repos" / "alpha"
    beta_repo = root / "repos" / "beta"
    _write_git_config(alpha_repo, "https://github.com/example/alpha.git")
    _write_git_config(beta_repo, "https://github.com/example/beta.git")

    alpha_session = day / "000-alpha.jsonl"
    _write_mixed_jsonl(
        alpha_session,
        (
            _session_meta("thread-alpha", "2026-07-31T12:00:00Z"),
            _function_call("2026-07-31T12:00:01Z", alpha_repo),
            "{malformed json",
            _user_message("2026-07-31T12:00:02Z", beta_repo),
            _function_output("2026-07-31T12:00:03Z", beta_repo),
        ),
    )

    beta_rows: list[dict[str, object] | str] = [
        _session_meta("thread-beta", "2026-07-31T12:01:00Z"),
        _function_call("2026-07-31T12:01:01Z", beta_repo),
        _user_message("2026-07-31T12:01:02Z", alpha_repo),
        _function_output("2026-07-31T12:01:03Z", alpha_repo),
    ]
    if repeat_same_path:
        beta_rows.append(_function_call("2026-07-31T12:01:04Z", alpha_repo))
    beta_session = day / "001-beta.jsonl"
    _write_mixed_jsonl(beta_session, tuple(beta_rows))

    state_repo = alpha_repo if repeat_same_path else beta_repo
    with sqlite3.connect(codex_home / "state_5.sqlite") as connection:
        connection.execute(
            "create table threads (id text primary key, cwd text, updated_at integer)"
        )
        connection.execute(
            "insert into threads (id, cwd, updated_at) values (?, ?, ?)",
            ("thread-state", str(state_repo), 1785499380000),
        )
        connection.commit()

    return TransitionCorpus(
        session_dirs=(sessions,),
        session_files=(alpha_session, beta_session),
        repeated_repo=alpha_repo,
    )


class ShuffledTransitionResultMapper:
    seed: ClassVar[int] = 0
    observed_orders: ClassVar[list[tuple[int, ...]]] = []

    def __init__(
        self,
        worker: Callable[[TransitionScanRequest], TransitionScanResult],
        *,
        task_count: int,
        max_workers: int,
    ) -> None:
        self.worker = worker
        self.worker_count = resolve_worker_count(
            task_count, available_cpus=64, max_workers=max_workers
        )
        self.used_serial_fallback = False
        self.infrastructure_error = ""

    def map_batch(
        self, requests: Sequence[TransitionScanRequest]
    ) -> list[TransitionScanResult]:
        results = [self.worker(request) for request in requests]
        random.Random(self.seed + len(self.observed_orders)).shuffle(results)
        self.observed_orders.append(tuple(result.request.ordinal for result in results))
        return results

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        return None


def _write_git_config(repo: Path, origin_url: str) -> None:
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        f'[remote "origin"]\n\turl = {origin_url}\n',
        encoding="utf-8",
    )


def _write_mixed_jsonl(
    path: Path,
    rows: tuple[dict[str, object] | str, ...],
) -> None:
    encoded = b"".join(
        (row if isinstance(row, str) else json.dumps(row)).encode("utf-8") + b"\n"
        for row in rows
    )
    path.write_bytes(encoded + b"\xff\xfe\xfa\n")


def _session_meta(thread_id: str, timestamp: str) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "session_meta",
        "payload": {"id": thread_id},
    }


def _function_call(timestamp: str, workdir: Path) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "arguments": json.dumps(
                {"workdir": str(workdir), "command": "Get-Location"}
            ),
        },
    }


def _user_message(timestamp: str, mentioned_path: Path) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "message",
            "role": "user",
            "content": [
                {"type": "input_text", "text": f"Ignore path {mentioned_path}"}
            ],
        },
    }


def _function_output(timestamp: str, mentioned_path: Path) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "output": f"Ignored output path {mentioned_path}",
        },
    }
