import json
from datetime import UTC, datetime
from pathlib import Path

from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.project_transitions import (
    RepoPathObservation,
    apply_project_transitions,
    collect_repo_path_observations,
    infer_project_transitions,
)


def test_collect_infer_and_apply_transitions_from_function_call_workdir(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    source_repo = tmp_path / "signoz-stack"
    target_repo = tmp_path / "ops-board"
    _write_git_config(source_repo, "https://github.com/example/signoz-stack.git")
    _write_git_config(target_repo, "https://github.com/example/ops-board.git")
    session_path = sessions / "2026" / "05" / "23" / "thread-1.jsonl"
    session_path.parent.mkdir(parents=True)
    session_path.write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {
                    "timestamp": "2026-05-23T21:00:00Z",
                    "type": "session_meta",
                    "payload": {
                        "id": "thread-1",
                        "cwd": str(source_repo),
                        "git": {"repository_url": "https://github.com/example/signoz-stack.git"},
                    },
                },
                {
                    "timestamp": "2026-05-23T21:06:45Z",
                    "type": "response_item",
                    "payload": {
                        "type": "function_call",
                        "arguments": json.dumps({"workdir": str(target_repo), "command": "Get-Location"}),
                    },
                },
            ]
        ),
        encoding="utf-8",
    )
    before = _usage_record(
        tmp_path,
        timestamp=datetime(2026, 5, 23, 21, 0, tzinfo=UTC),
        session_id="thread-1",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )
    after = _usage_record(
        tmp_path,
        timestamp=datetime(2026, 5, 23, 21, 7, tzinfo=UTC),
        session_id="thread-1",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[session_path])
    transitions = infer_project_transitions([before, after], observations)
    rewritten = apply_project_transitions([before, after], transitions)

    assert len(transitions) == 1
    assert transitions[0].source_key == "https://github.com/example/signoz-stack"
    assert transitions[0].target_key == "https://github.com/example/ops-board"
    assert [record.project_key for record in rewritten] == [
        "https://github.com/example/signoz-stack",
        "https://github.com/example/ops-board",
    ]


def test_collect_infer_and_apply_transitions_from_sqlite_cwd_uses_updated_at(tmp_path: Path) -> None:
    codex_home = tmp_path / "codex"
    sessions = codex_home / "sessions"
    sessions.mkdir(parents=True)
    source_repo = tmp_path / "signoz-stack"
    target_repo = tmp_path / "ops-board"
    _write_git_config(source_repo, "https://github.com/example/signoz-stack.git")
    _write_git_config(target_repo, "https://github.com/example/ops-board.git")
    _write_thread_db(codex_home, cwd=str(target_repo), created_at=1779570000000, updated_at=1779570405000)
    before = _usage_record(
        tmp_path,
        timestamp=datetime(2026, 5, 23, 21, 5, tzinfo=UTC),
        session_id="thread-1",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )
    after = _usage_record(
        tmp_path,
        timestamp=datetime(2026, 5, 23, 21, 7, tzinfo=UTC),
        session_id="thread-1",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )

    observations = collect_repo_path_observations(session_dirs=[sessions], session_files=[])
    transitions = infer_project_transitions([before, after], observations)
    rewritten = apply_project_transitions([before, after], transitions)

    assert len(transitions) == 1
    assert transitions[0].effective_from == datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC)
    assert [record.project_key for record in rewritten] == [
        "https://github.com/example/signoz-stack",
        "https://github.com/example/ops-board",
    ]


def test_infer_project_transitions_from_verified_repo_observation(tmp_path: Path) -> None:
    observed_at = datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC)
    record = _usage_record(
        tmp_path,
        timestamp=datetime(2026, 5, 23, 21, 0, tzinfo=UTC),
        session_id="thread-1",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )
    observation = _repo_observation(
        timestamp=observed_at,
        thread_id="thread-1",
        project_key="https://github.com/example/ops-board",
        project_label="ops-board",
        source="jsonl:response_item",
    )

    transitions = infer_project_transitions([record], [observation])

    assert len(transitions) == 1
    transition = transitions[0]
    assert transition.source_key == "https://github.com/example/signoz-stack"
    assert transition.source_label == "signoz-stack"
    assert transition.target_key == "https://github.com/example/ops-board"
    assert transition.target_label == "ops-board"
    assert transition.effective_from == observed_at
    assert transition.confidence == 100
    assert observation.to_evidence_text() in transition.evidence
    assert transition.thread_ids == ("thread-1",)


def test_infer_project_transitions_ignores_observation_for_current_project(tmp_path: Path) -> None:
    record = _usage_record(
        tmp_path,
        timestamp=datetime(2026, 5, 23, 21, 0, tzinfo=UTC),
        session_id="thread-1",
        project_key="https://github.com/example/ops-board",
        project_label="ops-board",
    )
    observation = _repo_observation(
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        thread_id="thread-1",
        project_key="https://github.com/example/ops-board",
        project_label="ops-board",
    )

    transitions = infer_project_transitions([record], [observation])

    assert transitions == []


def test_infer_project_transitions_ignores_previous_project_alias_reverse_transition(
    tmp_path: Path,
) -> None:
    record = _usage_record(
        tmp_path,
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        session_id="thread-1",
        project_key="https://github.com/example/ops-board",
        project_label="ops-board",
        project_aliases=("https://github.com/example/signoz-stack",),
        project_previous_key="https://github.com/example/signoz-stack",
        project_previous_label="signoz-stack",
    )
    observation = _repo_observation(
        timestamp=datetime(2026, 5, 23, 21, 7, tzinfo=UTC),
        thread_id="thread-1",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )

    transitions = infer_project_transitions([record], [observation])

    assert transitions == []


def test_infer_project_transitions_ignores_observation_before_source_usage(tmp_path: Path) -> None:
    record = _usage_record(
        tmp_path,
        timestamp=datetime(2026, 5, 23, 21, 6, 46, tzinfo=UTC),
        session_id="thread-1",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )
    observation = _repo_observation(
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        thread_id="thread-1",
        project_key="https://github.com/example/ops-board",
        project_label="ops-board",
    )

    transitions = infer_project_transitions([record], [observation])

    assert transitions == []


def test_infer_project_transitions_ignores_observation_without_existing_thread(tmp_path: Path) -> None:
    record = _usage_record(
        tmp_path,
        timestamp=datetime(2026, 5, 23, 21, 0, tzinfo=UTC),
        session_id="thread-1",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )
    observation = _repo_observation(
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        thread_id="thread-2",
        project_key="https://github.com/example/ops-board",
        project_label="ops-board",
    )

    transitions = infer_project_transitions([record], [observation])

    assert transitions == []


def test_infer_project_transitions_dedupes_same_source_thread_target_to_earliest(
    tmp_path: Path,
) -> None:
    record = _usage_record(
        tmp_path,
        timestamp=datetime(2026, 5, 23, 21, 0, tzinfo=UTC),
        session_id="thread-1",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )
    later = _repo_observation(
        timestamp=datetime(2026, 5, 23, 21, 8, tzinfo=UTC),
        thread_id="thread-1",
        project_key="https://github.com/example/ops-board",
        project_label="ops-board",
        source="state_5.sqlite:threads",
    )
    earlier = _repo_observation(
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        thread_id="thread-1",
        project_key="https://github.com/example/ops-board",
        project_label="ops-board",
        source="jsonl:response_item",
    )

    transitions = infer_project_transitions([record], [later, earlier])

    assert len(transitions) == 1
    assert transitions[0].effective_from == earlier.timestamp
    assert transitions[0].evidence == (earlier.to_evidence_text(),)
    assert transitions[0].thread_ids == ("thread-1",)


def _write_git_config(repo: Path, url: str) -> None:
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(f'[remote "origin"]\n\turl = {url}\n', encoding="utf-8")


def _write_thread_db(codex_home: Path, *, cwd: str, created_at: int, updated_at: int) -> None:
    import sqlite3

    con = sqlite3.connect(codex_home / "state_5.sqlite")
    try:
        con.execute("create table threads (id text primary key, created_at integer, updated_at integer, cwd text)")
        con.execute("insert into threads values (?, ?, ?, ?)", ("thread-1", created_at, updated_at, cwd))
        con.commit()
    finally:
        con.close()


def _usage_record(
    tmp_path: Path,
    *,
    timestamp: datetime,
    session_id: str,
    project_key: str,
    project_label: str,
    project_aliases: tuple[str, ...] = (),
    project_previous_key: str = "",
    project_previous_label: str = "",
) -> UsageRecord:
    return UsageRecord(
        timestamp=timestamp,
        usage=TokenUsage(total_tokens=100, input_tokens=100),
        session_id=session_id,
        file_path=tmp_path / f"{session_id}.jsonl",
        project_key=project_key,
        project_label=project_label,
        project_aliases=project_aliases,
        project_previous_key=project_previous_key,
        project_previous_label=project_previous_label,
    )


def _repo_observation(
    *,
    timestamp: datetime,
    thread_id: str,
    project_key: str,
    project_label: str,
    source: str = "jsonl:response_item",
) -> RepoPathObservation:
    return RepoPathObservation(
        raw_path=f"D:\\Projects\\{project_label}",
        resolved_path=f"D:\\Projects\\{project_label}",
        project_key=project_key,
        project_label=project_label,
        timestamp=timestamp,
        thread_id=thread_id,
        source=source,
    )
