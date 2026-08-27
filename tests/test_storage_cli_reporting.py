from __future__ import annotations

from argparse import Namespace
from dataclasses import dataclass
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_usage import cli
from codex_usage.storage_insights import TaskStorageInsights, TaskStorageTree


@dataclass(frozen=True)
class FakeRoot:
    path: Path
    storage_state: str
    exists: bool
    jsonl_count: int
    total_bytes: int


def test_storage_snapshot_cli_uses_storage_context_and_emits_schema_four_json(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    snapshot = _snapshot(tmp_path)
    context = SimpleNamespace(insights=snapshot)
    args = Namespace(
        json=True,
        project_key=["Repo"],
        no_auto_transitions=False,
        parallel_audit=None,
    )

    monkeypatch.setattr(cli, "find_session_dirs", lambda: [tmp_path])
    monkeypatch.setattr(cli, "load_storage_context", lambda **kwargs: context)

    assert cli.handle_storage_snapshot(args) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["schema_version"] == 4
    assert payload["totals"]["total_bytes"] == 13 * 1024**3 + 30
    assert payload["thresholds"]["high_inherited_root_bytes"] == 1024**3
    assert payload["roots"][0]["path"] == str(tmp_path / "sessions")
    assert [tree["root_task_id"] for tree in payload["task_trees"]] == ["large", "small"]
    assert payload["task_trees"][0]["total_bytes"] == 13 * 1024**3
    assert payload["task_trees"][0]["project_aliases"] == ["repo-alias"]
    assert payload["task_trees"][0]["share"] == pytest.approx(1.0)
    assert payload["task_trees"][0]["duplicate_file_count"] == 2
    assert "recovery_ready" not in payload["task_trees"][0]
    assert "analysis_complete" not in payload["task_trees"][0]
    assert "can_prepare_rollover" not in payload["task_trees"][0]


def test_storage_snapshot_terminal_uses_human_readable_iec_sizes(
    monkeypatch, tmp_path: Path
) -> None:
    payload = cli.storage_snapshot_payload(_snapshot(tmp_path))

    terminal = cli.render_storage_terminal(payload)

    assert "Codex task storage snapshot" in terminal
    assert "Corpus: 13.00 GiB" in terminal
    assert "Roots:" in terminal
    assert "Task trees:" in terminal
    assert "13.00 GiB total" in terminal
    assert "high inherited root" in terminal
    assert "large task tree" in terminal


def test_storage_snapshot_parser_accepts_project_filter() -> None:
    args = cli.build_parser().parse_args(
        ["storage", "snapshot", "--project-key", "Repo", "--project-key", "other"]
    )

    assert args.project_key == ["Repo", "other"]


def test_storage_parser_exposes_only_snapshot_and_analyze() -> None:
    parser = cli.build_parser()

    snapshot = parser.parse_args(["storage", "snapshot"])
    analyze = parser.parse_args(["storage", "analyze", "--tree-id", "root"])

    assert snapshot.storage_command == "snapshot"
    assert analyze.storage_command == "analyze"
    for removed in ("backup", "verify", "rollover"):
        with pytest.raises(SystemExit) as error:
            parser.parse_args(["storage", removed])
        assert error.value.code == 2


def _snapshot(tmp_path: Path) -> TaskStorageInsights:
    return TaskStorageInsights(
        task_trees=(
            TaskStorageTree(
                root_task_id="small",
                title="Small",
                project_key="repo",
                project_label="Repo",
                project_aliases=(),
                root_bytes=10,
                descendant_bytes=20,
                descendant_count=1,
                total_bytes=30,
                share=0.0,
                active_file_count=2,
                archived_file_count=0,
                active_bytes=30,
                archived_bytes=0,
                physical_file_count=2,
                has_missing_root=False,
                has_relationship_cycle=False,
                duplicate_file_count=0,
                metadata_diagnostics=(),
                is_large_root=False,
                is_large_tree=False,
            ),
            TaskStorageTree(
                root_task_id="large",
                title="Large",
                project_key="repo",
                project_label="Repo",
                project_aliases=("repo-alias",),
                root_bytes=2 * 1024**3,
                descendant_bytes=11 * 1024**3,
                descendant_count=20,
                total_bytes=13 * 1024**3,
                share=1.0,
                active_file_count=20,
                archived_file_count=3,
                active_bytes=10 * 1024**3,
                archived_bytes=3 * 1024**3,
                physical_file_count=23,
                has_missing_root=False,
                has_relationship_cycle=False,
                duplicate_file_count=2,
                metadata_diagnostics=(),
                is_large_root=True,
                is_large_tree=True,
            ),
        ),
        corpus_bytes=13 * 1024**3 + 30,
        root_bytes=2 * 1024**3 + 10,
        descendant_bytes=11 * 1024**3 + 20,
        active_bytes=10 * 1024**3 + 30,
        archived_bytes=3 * 1024**3,
        physical_file_count=25,
        task_tree_count=2,
        roots=(FakeRoot(tmp_path / "sessions", "active", True, 2, 13 * 1024**3 + 30),),
    )
