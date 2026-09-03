from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from codex_usage import agent_transfer


class _TransferResult:
    def __init__(
        self,
        *,
        outcome: str = "completed",
        pulled: tuple[str, ...] = (),
    ) -> None:
        self.outcome = outcome
        self.pulled = pulled
        self.counts = SimpleNamespace(pulled=len(pulled))

    def to_dict(self) -> dict[str, object]:
        return {
            "outcome": self.outcome,
            "pulled": list(self.pulled),
            "counts": {"pulled": self.counts.pulled},
        }


class _RegistrationResult:
    def __init__(self, task_ids: tuple[str, ...]) -> None:
        self.registered_task_ids = task_ids

    def to_dict(self) -> dict[str, object]:
        return {"registered_task_ids": list(self.registered_task_ids)}


def test_import_preflights_before_copy_and_binds_only_registered_tasks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    codex_home, sync_dir, destination = _folders(tmp_path)
    selected = ("task-one", "task-two")
    binding_plan = object()
    calls: list[object] = []
    monkeypatch.setattr(
        agent_transfer,
        "load_local_transfer_probe",
        lambda _roots: SimpleNamespace(inventory="local-inventory"),
    )

    def preflight(home: Path, project: Path, task_ids: tuple[str, ...]):
        calls.append(("preflight", home, project, task_ids))
        return binding_plan

    def pull_sync(**kwargs):
        calls.append(("copy", kwargs["thread_ids"]))
        return _TransferResult(pulled=selected)

    def register(task_ids: tuple[str, ...], *, codex_home: Path):
        calls.append(("register", task_ids, codex_home))
        return _RegistrationResult(("task-two",))

    def bind(plan, task_ids: tuple[str, ...]):
        calls.append(("bind", plan, task_ids))
        return {"assigned_task_ids": list(task_ids)}

    monkeypatch.setattr(agent_transfer, "preflight_desktop_binding", preflight)
    monkeypatch.setattr(agent_transfer, "pull_sync", pull_sync)
    monkeypatch.setattr(agent_transfer, "register_codex_tasks", register)
    monkeypatch.setattr(agent_transfer, "bind_desktop_tasks", bind)

    response = agent_transfer.execute_task_transfer(
        codex_home,
        "import",
        _import_payload(sync_dir, destination, selected),
    )

    assert [call[0] for call in calls] == ["preflight", "copy", "register", "bind"]
    assert calls[-1] == ("bind", binding_plan, ("task-two",))
    assert response["integration"] == {
        "registration": {"registered_task_ids": ["task-two"]},
        "binding": {"assigned_task_ids": ["task-two"]},
    }


def test_import_preflight_failure_copies_no_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    codex_home, sync_dir, destination = _folders(tmp_path)
    copied = False
    monkeypatch.setattr(
        agent_transfer,
        "load_local_transfer_probe",
        lambda _roots: SimpleNamespace(inventory="local-inventory"),
    )

    def preflight(*_args):
        raise RuntimeError("Codex Desktop must be closed")

    def pull_sync(**_kwargs):
        nonlocal copied
        copied = True
        return _TransferResult()

    monkeypatch.setattr(agent_transfer, "preflight_desktop_binding", preflight)
    monkeypatch.setattr(agent_transfer, "pull_sync", pull_sync)

    with pytest.raises(RuntimeError, match="must be closed"):
        agent_transfer.execute_task_transfer(
            codex_home,
            "import",
            _import_payload(sync_dir, destination, ("task-one",)),
        )

    assert copied is False


def test_partial_import_registers_and_binds_only_certified_pulled_tasks(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    codex_home, sync_dir, destination = _folders(tmp_path)
    selected = ("task-one", "task-two")
    registered: list[tuple[str, ...]] = []
    bound: list[tuple[str, ...]] = []
    monkeypatch.setattr(
        agent_transfer,
        "load_local_transfer_probe",
        lambda _roots: SimpleNamespace(inventory="local-inventory"),
    )
    monkeypatch.setattr(
        agent_transfer,
        "preflight_desktop_binding",
        lambda *_args: object(),
    )
    monkeypatch.setattr(
        agent_transfer,
        "pull_sync",
        lambda **_kwargs: _TransferResult(outcome="issue", pulled=("task-one",)),
    )

    def register(task_ids: tuple[str, ...], *, codex_home: Path):
        registered.append(task_ids)
        return _RegistrationResult(task_ids)

    def bind(_plan, task_ids: tuple[str, ...]):
        bound.append(task_ids)
        return {"assigned_task_ids": list(task_ids)}

    monkeypatch.setattr(agent_transfer, "register_codex_tasks", register)
    monkeypatch.setattr(agent_transfer, "bind_desktop_tasks", bind)

    agent_transfer.execute_task_transfer(
        codex_home,
        "import",
        _import_payload(sync_dir, destination, selected),
    )

    assert registered == [("task-one",)]
    assert bound == [("task-one",)]


def _folders(tmp_path: Path) -> tuple[Path, Path, Path]:
    codex_home = tmp_path / ".codex"
    sync_dir = tmp_path / "transfer"
    destination = tmp_path / "project"
    (codex_home / "sessions").mkdir(parents=True)
    sync_dir.mkdir()
    destination.mkdir()
    return codex_home, sync_dir, destination


def _import_payload(
    sync_dir: Path,
    destination: Path,
    task_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "sync_dir": str(sync_dir),
        "project_key": "project-key",
        "task_ids": list(task_ids),
        "destination_path": str(destination),
        "candidate_roots": [],
    }
