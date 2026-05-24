from datetime import UTC, datetime
from pathlib import Path

import codex_usage.project_transition_evidence as project_transition_evidence
from codex_usage.models import TokenUsage, UsageRecord
from codex_usage.project_transitions import (
    ProjectTransition,
    apply_project_transitions,
    extract_windows_paths,
    verified_repo_observation_from_path,
)


def test_extract_windows_paths_from_text() -> None:
    text = (
        "Work in repo `D:\\MyDocuments\\03-PythonProjects\\HU\\ops-board` and "
        "ignore C:\\Users\\mkof6\\.codex\\sessions."
    )

    paths = extract_windows_paths(text)

    assert paths == [
        "D:\\MyDocuments\\03-PythonProjects\\HU\\ops-board",
        "C:\\Users\\mkof6\\.codex\\sessions",
    ]


def test_extract_windows_paths_from_forward_slash_text() -> None:
    text = (
        "Work in repo `D:/MyDocuments/03-PythonProjects/HU/ops-board` and "
        "ignore C:/Users/mkof6/.codex/sessions."
    )

    paths = extract_windows_paths(text)

    assert paths == [
        "D:/MyDocuments/03-PythonProjects/HU/ops-board",
        "C:/Users/mkof6/.codex/sessions",
    ]


def test_extract_windows_paths_stops_bare_path_at_prose_boundary() -> None:
    text = "Work in D:\\MyDocuments\\03-PythonProjects\\utility_projects\\codex_usage before continuing."

    paths = extract_windows_paths(text)

    assert paths == ["D:\\MyDocuments\\03-PythonProjects\\utility_projects\\codex_usage"]


def test_extract_windows_paths_preserves_delimited_trailing_parenthesis() -> None:
    text = "Open `C:\\My Projects\\Foo (2026)` next."

    paths = extract_windows_paths(text)

    assert paths == ["C:\\My Projects\\Foo (2026)"]


def test_extract_windows_paths_does_not_use_single_quote_as_delimiter() -> None:
    text = "Open 'C:\\Projects\\Foo' next 'other'."

    paths = extract_windows_paths(text)

    assert paths == ["C:\\Projects\\Foo"]


def test_extract_windows_paths_preserves_delimited_trailing_bracket() -> None:
    text = 'Open "C:\\Projects\\Foo [test]" next.'

    paths = extract_windows_paths(text)

    assert paths == ["C:\\Projects\\Foo [test]"]


def test_verified_repo_observation_from_path_resolves_git_origin(tmp_path: Path) -> None:
    repo = tmp_path / "ops-board"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/Wenjun-Mao/ops-board.git\n',
        encoding="utf-8",
    )
    timestamp = datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC)

    observation = verified_repo_observation_from_path(
        str(repo),
        timestamp=timestamp,
        thread_id="thread-1",
        source="user-message",
    )

    assert observation is not None
    assert observation.raw_path == str(repo)
    assert observation.resolved_path == str(repo.resolve())
    assert observation.project_key == "https://github.com/wenjun-mao/ops-board"
    assert observation.project_label == "ops-board"
    assert observation.timestamp == timestamp
    assert observation.thread_id == "thread-1"
    assert observation.source == "user-message"
    assert observation.to_evidence_text() == (
        f"verified repo path {repo.resolve()} -> https://github.com/wenjun-mao/ops-board "
        "(thread thread-1, source user-message)"
    )


def test_verified_repo_observation_from_path_returns_none_for_missing_path(tmp_path: Path) -> None:
    observation = verified_repo_observation_from_path(
        str(tmp_path / "missing"),
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        thread_id="thread-1",
        source="user-message",
    )

    assert observation is None


def test_verified_repo_observation_from_path_returns_none_for_malformed_origin(tmp_path: Path) -> None:
    repo = tmp_path / "bad-origin"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = http://[broken\n',
        encoding="utf-8",
    )

    observation = verified_repo_observation_from_path(
        str(repo),
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        thread_id="thread-1",
        source="user-message",
    )

    assert observation is None


def test_verified_repo_observation_from_path_returns_none_when_path_check_raises(monkeypatch) -> None:
    def raise_os_error(self: Path) -> bool:
        raise OSError("permission denied")

    monkeypatch.setattr(project_transition_evidence.Path, "exists", raise_os_error)

    observation = verified_repo_observation_from_path(
        "C:\\inaccessible\\repo",
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        thread_id="thread-1",
        source="user-message",
    )

    assert observation is None


def test_verified_repo_observation_from_path_returns_none_when_normalization_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    repo = tmp_path / "ops-board"
    repo.mkdir()

    def raise_runtime_error(value: str) -> str:
        raise RuntimeError(f"cannot normalize {value}")

    monkeypatch.setattr(project_transition_evidence, "normalize_project_key", raise_runtime_error)

    observation = verified_repo_observation_from_path(
        str(repo),
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        thread_id="thread-1",
        source="user-message",
    )

    assert observation is None


def test_verified_repo_observation_from_path_accepts_forward_slash_windows_path(tmp_path: Path) -> None:
    repo = tmp_path / "MixedCaseRepo"
    git_dir = repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        '[remote "origin"]\n\turl = https://github.com/Wenjun-Mao/MixedCaseRepo.git\n',
        encoding="utf-8",
    )
    raw_path = str(repo).replace("\\", "/")

    observation = verified_repo_observation_from_path(
        raw_path,
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        thread_id="thread-1",
        source="user-message",
    )

    assert "/" in raw_path
    assert "\\" not in raw_path
    assert observation is not None
    assert observation.raw_path == raw_path
    assert observation.resolved_path == str(repo.resolve())
    assert observation.project_key == "https://github.com/wenjun-mao/mixedcaserepo"
    assert observation.project_label == "mixedcaserepo"


def test_apply_project_transitions_splits_records_at_effective_timestamp(tmp_path: Path) -> None:
    before = UsageRecord(
        timestamp=datetime(2026, 5, 23, 21, 6, 44, tzinfo=UTC),
        usage=TokenUsage(total_tokens=100, input_tokens=100),
        session_id="thread-1",
        file_path=tmp_path / "thread.jsonl",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )
    after = UsageRecord(
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        usage=TokenUsage(total_tokens=200, input_tokens=200),
        session_id="thread-1",
        file_path=tmp_path / "thread.jsonl",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )
    transition = ProjectTransition(
        source_key="https://github.com/example/signoz-stack",
        source_label="signoz-stack",
        target_key="https://github.com/example/ops-board",
        target_label="ops-board",
        effective_from=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        confidence=100,
        evidence=("verified local repo path",),
        thread_ids=("thread-1",),
    )

    records = apply_project_transitions([before, after], [transition])

    assert [record.project_key for record in records] == [
        "https://github.com/example/signoz-stack",
        "https://github.com/example/ops-board",
    ]
    assert records[1].project_previous_key == "https://github.com/example/signoz-stack"
    assert records[1].project_transition_effective_from == "2026-05-23T21:06:45+00:00"


def test_apply_project_transitions_only_rewrites_transition_threads(tmp_path: Path) -> None:
    included = UsageRecord(
        timestamp=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        usage=TokenUsage(total_tokens=200, input_tokens=200),
        session_id="thread-1",
        file_path=tmp_path / "thread-1.jsonl",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )
    excluded = UsageRecord(
        timestamp=datetime(2026, 5, 23, 21, 6, 46, tzinfo=UTC),
        usage=TokenUsage(total_tokens=300, input_tokens=300),
        session_id="thread-2",
        file_path=tmp_path / "thread-2.jsonl",
        project_key="https://github.com/example/signoz-stack",
        project_label="signoz-stack",
    )
    transition = ProjectTransition(
        source_key="https://github.com/example/signoz-stack",
        source_label="signoz-stack",
        target_key="https://github.com/example/ops-board",
        target_label="ops-board",
        effective_from=datetime(2026, 5, 23, 21, 6, 45, tzinfo=UTC),
        confidence=100,
        evidence=("verified local repo path",),
        thread_ids=("thread-1",),
    )

    records = apply_project_transitions([included, excluded], [transition])

    assert [record.project_key for record in records] == [
        "https://github.com/example/ops-board",
        "https://github.com/example/signoz-stack",
    ]
    assert records[1].project_previous_key == ""
