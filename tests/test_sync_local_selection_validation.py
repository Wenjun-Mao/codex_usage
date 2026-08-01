from __future__ import annotations

import json
from pathlib import Path

import pytest

from codex_usage.sync import (
    LocalTransferProbe,
    directional_preflight,
    load_local_transfer_probe,
    push_sync,
)


def test_push_blocks_selected_root_replaced_by_subagent_after_browse(
    tmp_path: Path,
) -> None:
    probe, path, project_key = _probed_root(tmp_path)
    _replace_metadata(
        path,
        source={"subagent": {"thread_spawn": {"parent_thread_id": "parent"}}},
    )

    result = push_sync(
        local=probe.inventory,
        sync_dir=tmp_path / "sync",
        thread_ids=["root"],
        machine_id="machine-a",
        project_key=project_key,
    )

    assert result.outcome == "issue"
    assert result.pushed == ()
    assert any(
        issue.code == "subagent_not_transferable" and issue.thread_id == "root"
        for issue in result.issues
    )
    assert not (tmp_path / "sync" / "tasks" / "root.jsonl").exists()


def test_push_blocks_current_byte_thread_id_mismatch(tmp_path: Path) -> None:
    probe, path, project_key = _probed_root(tmp_path)
    _replace_metadata(path, id="different-root")

    result = push_sync(
        local=probe.inventory,
        sync_dir=tmp_path / "sync",
        thread_ids=["root"],
        machine_id="machine-a",
        project_key=project_key,
    )

    assert result.outcome == "issue"
    assert result.pushed == ()
    assert any(
        issue.code == "local_session_identity_mismatch" and issue.thread_id == "root"
        for issue in result.issues
    )
    assert not (tmp_path / "sync" / "tasks" / "root.jsonl").exists()


def test_push_blocks_current_byte_project_identity_mismatch(tmp_path: Path) -> None:
    probe, path, project_key = _probed_root(tmp_path)
    replacement_project = tmp_path / "replacement-project"
    replacement_project.mkdir()
    _replace_metadata(path, cwd=str(replacement_project))

    result = push_sync(
        local=probe.inventory,
        sync_dir=tmp_path / "sync",
        thread_ids=["root"],
        machine_id="machine-a",
        project_key=project_key,
    )

    assert result.outcome == "issue"
    assert result.pushed == ()
    assert any(
        issue.code == "local_project_identity_mismatch" and issue.thread_id == "root"
        for issue in result.issues
    )
    assert not (tmp_path / "sync" / "tasks" / "root.jsonl").exists()


def test_push_detects_change_after_selected_local_snapshot_materialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe, path, project_key = _probed_root(tmp_path)
    original_build_plan = directional_preflight.build_sync_plan
    mutations = 0

    def mutate_before_plan(*args: object, **kwargs: object):
        nonlocal mutations
        mutations += 1
        with path.open("a", encoding="utf-8") as handle:
            handle.write(
                "\n"
                + json.dumps(
                    {
                        "timestamp": f"2026-07-31T12:00:0{mutations}Z",
                        "type": "event_msg",
                        "payload": {"type": "user_message", "message": "changed"},
                    }
                )
            )
        return original_build_plan(*args, **kwargs)

    monkeypatch.setattr(
        directional_preflight,
        "build_sync_plan",
        mutate_before_plan,
    )

    result = push_sync(
        local=probe.inventory,
        sync_dir=tmp_path / "sync",
        thread_ids=["root"],
        machine_id="machine-a",
        project_key=project_key,
    )

    assert mutations >= 1
    assert result.outcome == "issue"
    assert result.pushed == ()
    assert result.issues[-1].code == "concurrent_local_change"
    assert not (tmp_path / "sync" / "tasks" / "root.jsonl").exists()


def _probed_root(tmp_path: Path) -> tuple[LocalTransferProbe, Path, str]:
    sessions = tmp_path / ".codex" / "sessions"
    sessions.mkdir(parents=True)
    project = tmp_path / "project"
    project.mkdir()
    path = sessions / "root.jsonl"
    path.write_text(
        json.dumps(
            {
                "timestamp": "2026-07-31T12:00:00Z",
                "type": "session_meta",
                "payload": {
                    "id": "root",
                    "timestamp": "2026-07-31T12:00:00Z",
                    "cwd": str(project),
                    "source": "cli",
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    probe = load_local_transfer_probe([sessions])
    project_key = probe.inventory.threads["root"].project_key
    return probe, path, project_key


def _replace_metadata(path: Path, **updates: object) -> None:
    rows = path.read_text(encoding="utf-8").splitlines()
    metadata = json.loads(rows[0])
    metadata["payload"].update(updates)
    rows[0] = json.dumps(metadata)
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
