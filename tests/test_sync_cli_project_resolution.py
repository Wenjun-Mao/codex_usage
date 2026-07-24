from pathlib import Path
from types import SimpleNamespace

import pytest

import codex_usage.cli as cli_module
import codex_usage.sync_cli as sync_cli
from codex_usage.sync import ProjectBinding, ProjectResolutionRequest


def test_inventory_cli_passes_only_candidate_project_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[Path, ...]] = []
    monkeypatch.setattr(
        sync_cli, "_sync_session_dirs", lambda *, create: [tmp_path / "sessions"]
    )
    monkeypatch.setattr(
        sync_cli,
        "load_sync_selection_inventory",
        lambda data, sync_dir, *, candidate_roots: (
            calls.append(candidate_roots)
            or SimpleNamespace(
                to_dict=lambda: {
                    "inventory_version": 2,
                    "projects": [],
                    "issues": [],
                }
            )
        ),
    )

    exit_code = cli_module.main(
        [
            "sync",
            "inventory",
            "--sync-dir",
            str(tmp_path / "transfer"),
            "--candidate-project-root",
            str(tmp_path / "first"),
            "--candidate-project-root",
            str(tmp_path / "second"),
            "--json",
        ]
    )

    assert exit_code == 0
    assert calls == [(tmp_path / "first", tmp_path / "second")]
    capsys.readouterr()


def test_status_cli_passes_candidate_project_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        sync_cli, "_sync_session_dirs", lambda *, create: [tmp_path / "sessions"]
    )
    monkeypatch.setattr(
        sync_cli,
        "sync_status",
        lambda **kwargs: calls.append(kwargs)
        or SimpleNamespace(to_dict=lambda: {"threads": [], "issues": []}),
    )

    exit_code = cli_module.main(
        [
            "sync",
            "status",
            "--sync-dir",
            str(tmp_path / "transfer"),
            "--thread-id",
            "task-1",
            "--candidate-project-root",
            str(tmp_path / "workspace"),
            "--project-binding",
            "/source/plain",
            str(tmp_path / "workspace"),
            "--confirm-unverified-project",
            "/source/plain",
            "--json",
        ]
    )

    assert exit_code == 0
    assert calls[0]["project_resolution"] == ProjectResolutionRequest(
        candidate_roots=(tmp_path / "workspace",),
        bindings=(
            ProjectBinding("/source/plain", tmp_path / "workspace", True),
        ),
    )
    capsys.readouterr()


def test_pull_cli_passes_transient_project_resolution_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        sync_cli, "_sync_session_dirs", lambda *, create: [tmp_path / "sessions"]
    )
    monkeypatch.setattr(
        sync_cli,
        "pull_sync",
        lambda **kwargs: calls.append(kwargs) or _completed_result(),
    )

    exit_code = cli_module.main(
        [
            "sync",
            "pull",
            "--sync-dir",
            str(tmp_path / "transfer"),
            "--thread-id",
            "task-1",
            "--project-key",
            "https://github.com/example/repo",
            "--candidate-project-root",
            str(tmp_path / "workspace"),
            "--project-binding",
            "https://github.com/example/repo",
            str(tmp_path / "workspace"),
            "--project-binding",
            "/source/non-git",
            str(tmp_path / "workspace"),
            "--confirm-unverified-project",
            "/source/non-git",
            "--json",
        ]
    )

    assert exit_code == 0
    assert calls[0]["project_key"] == "https://github.com/example/repo"
    request = calls[0]["project_resolution"]
    assert isinstance(request, ProjectResolutionRequest)
    assert request.candidate_roots == (tmp_path / "workspace",)
    assert request.bindings == (
        ProjectBinding(
            "https://github.com/example/repo", tmp_path / "workspace", False
        ),
        ProjectBinding("/source/non-git", tmp_path / "workspace", True),
    )
    capsys.readouterr()


def test_conflicting_project_bindings_fail_before_session_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    discovery_calls: list[bool] = []
    monkeypatch.setattr(
        sync_cli,
        "_sync_session_dirs",
        lambda *, create: discovery_calls.append(create),
    )

    exit_code = cli_module.main(
        [
            "sync",
            "pull",
            "--sync-dir",
            str(tmp_path / "transfer"),
            "--thread-id",
            "task-1",
            "--project-key",
            "repo-key",
            "--project-binding",
            "repo-key",
            str(tmp_path / "first"),
            "--project-binding",
            "repo-key",
            str(tmp_path / "second"),
            "--json",
        ]
    )

    assert exit_code == 2
    assert discovery_calls == []
    assert "Conflicting project bindings for 'repo-key'" in capsys.readouterr().err


def _completed_result() -> SimpleNamespace:
    return SimpleNamespace(
        outcome="completed",
        to_dict=lambda: {"outcome": "completed", "counts": {}},
    )
