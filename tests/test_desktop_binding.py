from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_usage.desktop_binding import (
    DesktopProjectBindingError,
    bind_desktop_tasks,
    desktop_state_path,
    preflight_desktop_binding,
)


def test_missing_desktop_state_is_not_applicable(tmp_path: Path) -> None:
    destination = tmp_path / "project"
    destination.mkdir()

    plan = preflight_desktop_binding(
        tmp_path / ".codex",
        destination,
        ["task-1"],
        process_probe=lambda: "unknown",
    )

    assert plan.mode == "not-applicable"


def test_binding_assigns_only_registered_tasks_and_preserves_unrelated_state(
    tmp_path: Path,
) -> None:
    home, destination, state_path = _desktop_fixture(tmp_path)
    plan = preflight_desktop_binding(
        home, destination, ["task-1", "task-2"], process_probe=lambda: "closed"
    )

    result = bind_desktop_tasks(
        plan, ["task-1"], process_probe=lambda: "closed"
    )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert result["status"] == "bound"
    assert state["thread-project-assignments"]["task-1"] == {
        "projectKind": "local",
        "projectId": "project-1",
        "cwd": str(destination),
        "pendingCoreUpdate": False,
    }
    assert "task-1" not in state["projectless-thread-ids"]
    assert state["thread-project-assignments"].get("task-2") is None
    assert state["unrelated"] == {"keep": True}
    assert Path(str(result["backup_path"])).is_file()


def test_running_desktop_blocks_preflight_before_mutation(tmp_path: Path) -> None:
    home, destination, state_path = _desktop_fixture(tmp_path)
    before = state_path.read_bytes()

    with pytest.raises(DesktopProjectBindingError, match="Quit Codex Desktop") as error:
        preflight_desktop_binding(
            home, destination, ["task-1"], process_probe=lambda: "running"
        )

    assert error.value.code == "desktop-running"
    assert state_path.read_bytes() == before


def test_concurrent_state_change_rejects_binding(tmp_path: Path) -> None:
    home, destination, state_path = _desktop_fixture(tmp_path)
    plan = preflight_desktop_binding(
        home, destination, ["task-1"], process_probe=lambda: "closed"
    )
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["concurrent"] = True
    state_path.write_text(json.dumps(state), encoding="utf-8")

    with pytest.raises(DesktopProjectBindingError) as error:
        bind_desktop_tasks(plan, ["task-1"], process_probe=lambda: "closed")

    assert error.value.code == "state-changed"
    assert not list(home.glob("*.bak"))


def _desktop_fixture(tmp_path: Path) -> tuple[Path, Path, Path]:
    home = tmp_path / ".codex"
    home.mkdir()
    destination = tmp_path / "project"
    destination.mkdir()
    state_path = desktop_state_path(home)
    state_path.write_text(
        json.dumps(
            {
                "local-projects": {
                    "project-1": {
                        "id": "project-1",
                        "rootPaths": [str(destination)],
                    }
                },
                "thread-project-assignments": {},
                "projectless-thread-ids": ["task-1", "other"],
                "thread-projectless-output-directories": {
                    "task-1": "/tmp/task-1",
                    "other": "/tmp/other",
                },
                "unrelated": {"keep": True},
            }
        ),
        encoding="utf-8",
    )
    return home, destination.resolve(), state_path
