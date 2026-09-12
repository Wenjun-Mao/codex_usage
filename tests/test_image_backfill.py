from __future__ import annotations

import json
import os
import sqlite3
import struct
from pathlib import Path

import pytest

from image_capture_test_support import session_meta, token_count, turn_context

from codex_usage import agent_capture, image_backfill
from codex_usage.agent_capture import capture_once
from codex_usage.agent_paths import ledger_database_path
from codex_usage.image_backfill import (
    IMAGE_BACKFILL_CAPTURE_BYTES,
    IMAGE_BACKFILL_SLICE_COUNT,
    IMAGE_BACKFILL_SLICE_BYTES,
    ImageBackfillResult,
    run_image_backfill_slice,
)
from codex_usage.image_capture_payloads import kind_from_mapping
from codex_usage.ledger_schema import open_ledger
from codex_usage.image_capture_payloads import has_reference_inputs
from codex_usage.image_models import ImageOperationKind


def test_null_reference_options_remain_fresh_generation() -> None:
    assert not has_reference_inputs(
        {
            "referenced_image_paths": None,
            "num_last_images_to_include": None,
        }
    )


def test_live_sample_shape_reconciles_six_fresh_and_four_reference_edits() -> None:
    fixture = [
        {},
        {},
        {"referenced_image_paths": None, "num_last_images_to_include": None},
        {"referenced_image_paths": None, "num_last_images_to_include": None},
        {"referenced_image_paths": None, "num_last_images_to_include": None},
        {"referenced_image_paths": None, "num_last_images_to_include": None},
        {"num_last_images_to_include": 1},
        {"num_last_images_to_include": 1},
        {"referenced_image_paths": [True]},
        {"referenced_image_paths": [True]},
    ]

    kinds = [kind_from_mapping(arguments) for arguments in fixture]

    assert kinds.count(ImageOperationKind.GENERATE) == 6
    assert kinds.count(ImageOperationKind.EDIT_REFERENCE) == 4


def test_scheduled_artifact_first_backfill_preserves_language_ledger(
    tmp_path: Path,
) -> None:
    home = tmp_path / ".codex"
    directory = home / "sessions" / "2026" / "09" / "12"
    directory.mkdir(parents=True)
    task_id = "07b936fd-4c91-4430-b953-677e7abaafe7"
    path = directory / f"rollout-{task_id}.jsonl"
    artifact_name = "exec-f1d4d3db-0e01-4588-8d00-f151f42a9ec3.png"
    artifacts = home / "generated_images" / task_id
    artifacts.mkdir(parents=True)
    (artifacts / artifact_name).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", 1024, 1024)
        + b"\x08\x06\x00\x00\x00"
        + b"c2pa.actions.v2 c2pa.signature softwareAgent name gpt-image version 2.0"
    )
    rows = [
        session_meta(task_id),
        turn_context(),
        token_count(125),
        {
            "timestamp": "2026-09-12T10:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "call-backfill",
                "input": "await tools.image_gen__imagegen({prompt: 'private'});",
            },
        },
        {
            "timestamp": "2026-09-12T10:00:03Z",
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "Extension",
                    "kind": "image_gen.generation",
                    "id": artifact_name.removesuffix(".png"),
                    "status": "completed",
                    "failure": None,
                },
            },
        },
    ]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")
    assert capture_once(home, request_kind="manual", max_workers=1).outcome == "success"
    ledger = ledger_database_path(home)
    with sqlite3.connect(ledger) as connection:
        language_before = connection.execute(
            "select * from ledger_usage_events"
        ).fetchall()
        connection.execute("delete from image_operations")
        connection.execute("delete from ledger_image_events")
        connection.execute(
            "delete from ledger_meta where key = 'image_backfill_state_v1'"
        )
        connection.commit()

    result = capture_once(home, request_kind="scheduled", max_workers=1)

    assert result.outcome == "success"
    assert result.stats.source_bytes_read == 0
    assert result.status.image_backfill.complete
    with sqlite3.connect(ledger) as connection:
        assert (
            connection.execute("select * from ledger_usage_events").fetchall()
            == language_before
        )
        assert connection.execute(
            "select tool_call_id, outcome, output_count from ledger_image_events"
        ).fetchall() == [("call-backfill", "succeeded", 1)]


def test_image_ledger_migration_creates_a_pre_migration_backup(tmp_path: Path) -> None:
    ledger = tmp_path / "usage-ledger.sqlite3"
    with open_ledger(ledger):
        pass
    with sqlite3.connect(ledger) as connection:
        connection.execute("drop table ledger_image_events")
        connection.execute(
            "update ledger_meta set value = '1' where key = 'schema_version'"
        )
        connection.commit()

    with open_ledger(ledger) as connection:
        version = connection.execute(
            "select value from ledger_meta where key = 'schema_version'"
        ).fetchone()[0]
        assert (
            connection.execute(
                "select 1 from sqlite_master where type = 'table' and name = 'ledger_image_events'"
            ).fetchone()
            is not None
        )

    backups = list(tmp_path.glob("usage-ledger.sqlite3.schema-1-backup-*"))
    assert version == "2"
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert (
            connection.execute(
                "select value from ledger_meta where key = 'schema_version'"
            ).fetchone()[0]
            == "1"
        )
        assert (
            connection.execute(
                "select 1 from sqlite_master where type = 'table' and name = 'ledger_image_events'"
            ).fetchone()
            is None
        )


def test_artifact_first_backfill_never_opens_an_unrelated_rollout(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / ".codex"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    task_id = "07b936fd-4c91-4430-b953-677e7abaafe7"
    owning = sessions / f"rollout-{task_id}.jsonl"
    owning.write_text(
        "".join(
            f"{json.dumps(row)}\n" for row in (session_meta(task_id), turn_context())
        ),
        encoding="utf-8",
    )
    unrelated = sessions / "rollout-unrelated.jsonl"
    unrelated.write_text("private unrelated source", encoding="utf-8")
    artifact_name = "exec-f1d4d3db-0e01-4588-8d00-f151f42a9ec3.png"
    artifacts = home / "generated_images" / task_id
    artifacts.mkdir(parents=True)
    (artifacts / artifact_name).write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", 1024, 1024)
        + b"\x08\x06\x00\x00\x00"
    )
    ledger = ledger_database_path(home)
    with open_ledger(ledger):
        pass
    original_open = Path.open

    def guarded_open(path: Path, *args, **kwargs):
        if path == unrelated:
            raise AssertionError("backfill opened an unrelated rollout")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)

    result = run_image_backfill_slice(home, ledger)

    assert result.status == "complete"


def test_unavailable_candidate_falls_through_to_a_valid_owner(tmp_path: Path) -> None:
    home = tmp_path / ".codex"
    sessions = home / "sessions"
    sessions.mkdir(parents=True)
    unavailable_task = "07b936fd-4c91-4430-b953-677e7abaafe7"
    valid_task = "f1d4d3db-0e01-4588-8d00-f151f42a9ec3"
    unavailable_artifact = _write_artifact(home, unavailable_task)
    _write_artifact(home, valid_task)
    # The unavailable artifact is newer, so it is selected first and must not
    # consume the valid owner's parser slice.
    os.utime(unavailable_artifact, ns=(2_000_000_000, 2_000_000_000))
    os.utime(
        home / "generated_images" / valid_task / unavailable_artifact.name,
        ns=(1_000_000_000, 1_000_000_000),
    )
    artifact_name = unavailable_artifact.name
    path = sessions / f"rollout-{valid_task}.jsonl"
    rows = [
        session_meta(valid_task),
        turn_context(),
        {
            "timestamp": "2026-09-12T10:00:02Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "name": "exec",
                "call_id": "call-valid",
                "input": "await tools.image_gen__imagegen({prompt: 'private'});",
            },
        },
        {
            "timestamp": "2026-09-12T10:00:03Z",
            "type": "event_msg",
            "payload": {
                "type": "item_completed",
                "item": {
                    "type": "Extension",
                    "kind": "image_gen.generation",
                    "id": artifact_name.removesuffix(".png"),
                    "status": "completed",
                    "failure": None,
                },
            },
        },
    ]
    path.write_text("".join(f"{json.dumps(row)}\n" for row in rows), encoding="utf-8")
    ledger = ledger_database_path(home)
    with open_ledger(ledger):
        pass

    result = run_image_backfill_slice(home, ledger)

    assert result.status == "partial"
    assert result.tasks_unavailable == 1
    assert result.tasks_completed == 1
    with sqlite3.connect(ledger) as connection:
        assert connection.execute(
            "select tool_call_id from image_operations"
        ).fetchall() == [("call-valid",)]


def test_backfill_scheduler_is_capped_at_four_slices(monkeypatch, tmp_path: Path) -> None:
    calls = 0

    def pending_slice(_home: Path, _ledger: Path) -> ImageBackfillResult:
        nonlocal calls
        calls += 1
        return ImageBackfillResult(True, "pending", 1, 1, 0, 0, 1)

    monkeypatch.setattr(image_backfill, "run_image_backfill_slice", pending_slice)

    result = image_backfill.run_image_backfill(tmp_path, tmp_path / "ledger.sqlite3")

    assert IMAGE_BACKFILL_SLICE_COUNT == 4
    assert IMAGE_BACKFILL_SLICE_BYTES == 16 * 1024 * 1024
    assert IMAGE_BACKFILL_CAPTURE_BYTES == 64 * 1024 * 1024
    assert calls == IMAGE_BACKFILL_SLICE_COUNT
    assert result.changed is True


def test_scheduler_prefers_recent_then_least_recently_served() -> None:
    older_task = "07b936fd-4c91-4430-b953-677e7abaafe7"
    newer_task = "f1d4d3db-0e01-4588-8d00-f151f42a9ec3"
    artifacts = {
        older_task: image_backfill._ArtifactTask(1, 1),
        newer_task: image_backfill._ArtifactTask(1, 2),
    }

    assert (
        image_backfill._select_next_task({older_task, newer_task}, artifacts, {})
        == newer_task
    )
    assert (
        image_backfill._select_next_task(
            {older_task, newer_task}, artifacts, {older_task: 4, newer_task: 9}
        )
        == older_task
    )


def test_scheduler_breaks_equal_priority_ties_deterministically() -> None:
    lower_task = "11111111-1111-1111-1111-111111111111"
    higher_task = "22222222-2222-2222-2222-222222222222"
    artifacts = {
        lower_task: image_backfill._ArtifactTask(1, 1),
        higher_task: image_backfill._ArtifactTask(1, 1),
    }

    assert (
        image_backfill._select_next_task({lower_task, higher_task}, artifacts, {})
        == higher_task
    )
    assert (
        image_backfill._select_next_task(
            {lower_task, higher_task},
            artifacts,
            {lower_task: 4, higher_task: 4},
        )
        == lower_task
    )


@pytest.mark.parametrize("request_kind", ("startup", "scheduled", "manual"))
def test_every_capture_kind_runs_the_bounded_backfill(
    monkeypatch, tmp_path: Path, request_kind: str
) -> None:
    home = tmp_path / ".codex"
    (home / "sessions").mkdir(parents=True)
    calls: list[tuple[Path, Path]] = []

    def observed_backfill(codex_home: Path, ledger_path: Path) -> ImageBackfillResult:
        calls.append((codex_home, ledger_path))
        return ImageBackfillResult(False, "complete", 0, 0, 0, 0, 0)

    monkeypatch.setattr(agent_capture, "run_image_backfill", observed_backfill)

    result = agent_capture.capture_once(
        home, request_kind=request_kind, max_workers=1
    )

    assert result.outcome == "success"
    assert calls == [(home, ledger_database_path(home))]


def _write_artifact(home: Path, task_id: str) -> Path:
    artifact = home / "generated_images" / task_id / (
        "exec-f1d4d3db-0e01-4588-8d00-f151f42a9ec3.png"
    )
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", 1024, 1024)
        + b"\x08\x06\x00\x00\x00"
    )
    return artifact
