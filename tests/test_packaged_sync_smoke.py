from __future__ import annotations

import ast
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from packaged_sync_smoke_support import (
    PACKAGED_SYNC_SMOKE,
    PACKAGED_SYNC_VALIDATION,
    PackagedCommandDouble,
    copied_rows,
    encode_rows,
    inventory_payload,
    load_packaged_sync_smoke,
    matching_metadata,
    multi_record_rows,
    run_main,
    sync_result,
)


PRIVATE_STATE_FILENAMES = {
    ".codex-global-state.json",
    "state_5.sqlite",
    "state_5.sqlite-wal",
    "state_5.sqlite-shm",
}


def _forbidden_private_state_writes(source: str) -> list[str]:
    write_calls: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        segment = ast.get_source_segment(source, node) or ""
        function = node.func
        name = function.attr if isinstance(function, ast.Attribute) else getattr(function, "id", "")
        if name in {"open", "touch", "write_bytes", "write_text"} and any(
            filename in segment for filename in PRIVATE_STATE_FILENAMES
        ):
            write_calls.append(segment)
    return write_calls


def test_packaged_smoke_is_v3_and_static_guard_rejects_private_state_writes() -> None:
    assert PACKAGED_SYNC_VALIDATION.is_file()
    source = PACKAGED_SYNC_SMOKE.read_text(encoding="utf-8")
    validation = PACKAGED_SYNC_VALIDATION.read_text(encoding="utf-8")
    combined = source + validation

    assert "INVENTORY_VERSION = 2" in combined
    assert "REMOTE_TRANSFER_FORMAT_VERSION = 3" in combined
    assert "SYNC_FORMAT_VERSION" not in combined
    assert 'TASKS_DIRNAME = "tasks"' in combined
    assert '"--candidate-project-root"' in source
    assert all(filename in combined for filename in PRIVATE_STATE_FILENAMES)
    assert not _forbidden_private_state_writes(combined)
    probe = '(target / ".codex-global-state.json").write_text("{}")'
    assert _forbidden_private_state_writes(probe)


def test_packaged_smoke_modules_stay_below_500_lines() -> None:
    assert PACKAGED_SYNC_SMOKE.read_text(encoding="utf-8").count("\n") < 500
    assert PACKAGED_SYNC_VALIDATION.read_text(encoding="utf-8").count("\n") < 500


def test_source_fixture_has_selective_multi_record_project_metadata(tmp_path: Path) -> None:
    smoke = load_packaged_sync_smoke()
    source_jsonl = smoke._write_source_home(tmp_path / "home", tmp_path / "source-project")
    rows = [json.loads(line) for line in source_jsonl.read_bytes().splitlines()]
    matching = [row for row in rows if matching_metadata(row, smoke.PROJECT_KEY)]
    unrelated = [
        row
        for row in rows
        if row.get("type") == "session_meta" and not matching_metadata(row, smoke.PROJECT_KEY)
    ]

    assert len(matching) >= 2
    assert len(unrelated) >= 1
    assert rows[0] in matching
    assert len([row for row in rows if row.get("type") != "session_meta"]) >= 2


def test_cross_project_task_is_added_after_the_initial_source_fixture(tmp_path: Path) -> None:
    smoke = load_packaged_sync_smoke()
    source_home = tmp_path / "home"

    smoke._write_source_home(source_home, tmp_path / "source-project")

    unrelated_jsonl = source_home / "sessions" / smoke.UNRELATED_SESSION_RELATIVE_PATH
    assert not unrelated_jsonl.exists()
    smoke._write_unrelated_source_task(source_home)
    assert unrelated_jsonl.is_file()


def test_cross_project_selection_accepts_the_native_issue_exit_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = load_packaged_sync_smoke()
    payload = {
        "outcome": "issue",
        "issues": [{"code": "cross_project_selection", "message": "blocked", "thread_id": ""}],
    }
    completed = subprocess.CompletedProcess([], 2, json.dumps(payload), "")
    monkeypatch.setattr(smoke, "subprocess", SimpleNamespace(run=lambda *args, **kwargs: completed))

    assert smoke._run_sync(
        tmp_path / "codex-usage",
        tmp_path / "codex-home",
        tmp_path / "sync",
        "push",
        thread_ids=(smoke.THREAD_ID, smoke.UNRELATED_THREAD_ID),
        allow_issue=True,
    ) == payload


def test_rejected_cross_project_extra_remote_task_write_fails_native_smoke(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = load_packaged_sync_smoke()
    command_double = PackagedCommandDouble(smoke)
    original_run = command_double.run

    def write_extra_remote_task(
        command: list[str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        completed = original_run(command, **kwargs)
        if len(command_double.calls) == 5:
            sync_dir = Path(command[4])
            (sync_dir / "tasks" / f"{smoke.UNRELATED_THREAD_ID}.jsonl").write_bytes(b"unexpected\n")
        return completed

    monkeypatch.setattr(command_double, "run", write_extra_remote_task)

    with pytest.raises(RuntimeError, match="cross-project remote task-file isolation"):
        run_main(smoke, command_double, tmp_path, monkeypatch)


def test_packaged_sync_smoke_orchestrates_exact_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    smoke = load_packaged_sync_smoke()
    command_double = PackagedCommandDouble(smoke)

    assert run_main(smoke, command_double, tmp_path, monkeypatch) == 0

    calls = command_double.calls
    source_home = calls[0][0]
    target_home = calls[2][0]
    assert source_home != target_home
    assert [call[0] for call in calls] == [
        source_home,
        source_home,
        target_home,
        target_home,
        source_home,
        target_home,
    ]
    assert [call[1][1] for call in calls] == [
        "inventory",
        "push",
        "inventory",
        "pull",
        "push",
        "status",
    ]
    assert all("--project-key" in calls[index][1] for index in (1, 3))
    assert all("--candidate-project-root" in calls[index][1] for index in (2, 3, 5))
    rejected_selection = calls[4][1]
    assert rejected_selection[:2] == ("sync", "push")
    assert rejected_selection.count("--thread-id") == 2
    assert rejected_selection.count("--project-key") == 1
    assert smoke.UNRELATED_THREAD_ID in rejected_selection
    for codex_home, _, environment in calls:
        expected_cache = codex_home.parent / "tool-cache" / codex_home.name
        assert environment["CODEX_USAGE_CACHE_DIR"] == str(expected_cache)
        assert codex_home not in expected_cache.parents
    assert capsys.readouterr().out.strip().endswith("status=up-to-date format_version=3")


@pytest.mark.parametrize("stage", ("inventory", "pull", "status"))
def test_destination_private_state_mutation_fails_native_smoke(
    stage: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    smoke = load_packaged_sync_smoke()
    command_double = PackagedCommandDouble(smoke, mutate_stage=stage)

    with pytest.raises(RuntimeError, match=rf"destination {stage}.*unexpected"):
        run_main(smoke, command_double, tmp_path, monkeypatch)


@pytest.mark.parametrize("mode", ("first_only", "rewrite_unrelated"))
def test_imported_task_rejects_nonselective_metadata_rewrites(
    mode: str,
    tmp_path: Path,
) -> None:
    smoke = load_packaged_sync_smoke()
    destination = tmp_path / "Destination Spelling"
    rows = multi_record_rows(smoke, tmp_path / "source")
    imported = copied_rows(rows)
    matching = [
        index for index, row in enumerate(rows) if matching_metadata(row, smoke.PROJECT_KEY)
    ]
    if mode == "first_only":
        imported[matching[0]]["payload"]["cwd"] = str(destination)
    else:
        for row in imported:
            if row.get("type") == "session_meta":
                row["payload"]["cwd"] = str(destination)
    imported_path = tmp_path / "imported.jsonl"
    imported_path.write_bytes(encode_rows(imported))

    with pytest.raises(RuntimeError, match="imported task"):
        smoke._validate_imported_task(imported_path, encode_rows(rows), destination)


@pytest.mark.parametrize(
    ("case", "message"),
    (
        ("missing_timings", "result fields"),
        ("missing_threads", "result fields"),
        ("malformed_threads", "threads"),
        ("extra_result_key", "result fields"),
        ("missing_timing_key", "timings"),
        ("negative_timing", "timings"),
        ("unsafe_timing", "timings"),
        ("missing_plan_field", "plan item fields"),
        ("extra_plan_field", "plan item fields"),
        ("bad_plan_field", "memory_database_rows"),
        ("unsafe_plan_field", "memory_database_rows"),
        ("wrong_action", "action"),
        ("wrong_local_path", "local_path"),
        ("wrong_local_hash", "local_sha256"),
        ("wrong_remote_hash", "remote_sha256"),
        ("wrong_pushed", "pushed thread ids"),
        ("wrong_count", "counts"),
        ("unsafe_count", "counts"),
    ),
)
def test_sync_result_validation_rejects_protocol_contract_mismatches(
    case: str,
    message: str,
    tmp_path: Path,
) -> None:
    smoke = load_packaged_sync_smoke()
    payload = sync_result("push", tmp_path / "local.jsonl", tmp_path / "remote.jsonl", b"task")
    if case == "missing_timings":
        payload.pop("timings_ms")
    elif case == "missing_threads":
        payload.pop("threads")
    elif case == "malformed_threads":
        payload["threads"] = {}
    elif case == "extra_result_key":
        payload["extra"] = True
    elif case == "missing_timing_key":
        payload["timings_ms"].pop("planning")
    elif case == "negative_timing":
        payload["timings_ms"]["total"] = -1
    elif case == "unsafe_timing":
        payload["timings_ms"]["total"] = 2**53
    elif case == "missing_plan_field":
        payload["threads"][0].pop("reason")
    elif case == "extra_plan_field":
        payload["threads"][0]["extra"] = "no"
    elif case == "bad_plan_field":
        payload["threads"][0]["memory_database_rows"] = -1
    elif case == "unsafe_plan_field":
        payload["threads"][0]["memory_database_rows"] = 2**53
    elif case == "wrong_action":
        payload["threads"][0]["action"] = "pull"
    elif case == "wrong_local_path":
        payload["threads"][0]["local_path"] = "/wrong/local.jsonl"
    elif case == "wrong_local_hash":
        payload["threads"][0]["local_sha256"] = "wrong"
    elif case == "wrong_remote_hash":
        payload["threads"][0]["remote_sha256"] = "wrong"
    elif case == "wrong_pushed":
        payload["pushed"] = ["wrong-thread"]
    elif case == "wrong_count":
        payload["counts"]["pushed"] = 2
    else:
        payload["counts"]["pushed"] = 2**53

    with pytest.raises(RuntimeError, match=message):
        smoke._validate_sync_result(
            payload,
            "push",
            local_jsonl=tmp_path / "local.jsonl",
            remote_jsonl=tmp_path / "remote.jsonl",
            source_bytes=b"task",
        )


def test_sync_result_validation_requires_directional_file_context(tmp_path: Path) -> None:
    smoke = load_packaged_sync_smoke()
    payload = sync_result(
        "push",
        tmp_path / "local.jsonl",
        tmp_path / "remote.jsonl",
        b"task",
    )

    with pytest.raises(TypeError):
        smoke._validate_sync_result(payload, "push")


@pytest.mark.parametrize("direction", ("push", "pull"))
def test_sync_result_validation_accepts_exact_directional_contract(
    direction: str,
    tmp_path: Path,
) -> None:
    smoke = load_packaged_sync_smoke()
    local_jsonl = tmp_path / "local.jsonl"
    remote_jsonl = tmp_path / "remote.jsonl"
    source_bytes = b"task"
    payload = sync_result(direction, local_jsonl, remote_jsonl, source_bytes)

    smoke._validate_sync_result(
        payload,
        direction,
        local_jsonl=local_jsonl,
        remote_jsonl=remote_jsonl,
        source_bytes=source_bytes,
    )


@pytest.mark.parametrize(
    ("payload", "availability", "message"),
    (
        ({**inventory_payload("local"), "inventory_version": 1}, "local", "inventory_version"),
        ({**inventory_payload("local"), "issues": [{"code": "issue"}]}, "local", "issues"),
        (inventory_payload("local", thread_id="wrong-thread"), "local", "thread id"),
        (inventory_payload("both"), "local", "availability"),
    ),
)
def test_inventory_validation_rejects_contract_mismatches(
    payload: dict[str, object],
    availability: str,
    message: str,
) -> None:
    smoke = load_packaged_sync_smoke()

    with pytest.raises(RuntimeError, match=message):
        smoke._validate_inventory(payload, availability, 498)


@pytest.mark.parametrize(
    ("completed", "message"),
    (
        (subprocess.CompletedProcess([], 7, "stdout", "stderr"), "exited with code 7"),
        (subprocess.CompletedProcess([], 0, "not-json", ""), "not one JSON object"),
        (subprocess.CompletedProcess([], 0, "[]", ""), "non-object JSON"),
    ),
)
def test_json_runner_rejects_command_and_payload_errors(
    monkeypatch: pytest.MonkeyPatch,
    completed: subprocess.CompletedProcess[str],
    message: str,
) -> None:
    smoke = load_packaged_sync_smoke()
    monkeypatch.setattr(smoke, "subprocess", SimpleNamespace(run=lambda *args, **kwargs: completed))

    with pytest.raises(RuntimeError, match=message):
        smoke._run_json(Path("codex-usage"), Path("codex-home"), ["sync", "inventory"])


def test_packaged_smoke_modules_have_no_optimization_sensitive_asserts() -> None:
    for path in (PACKAGED_SYNC_SMOKE, PACKAGED_SYNC_VALIDATION):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        assert not [node for node in ast.walk(tree) if isinstance(node, ast.Assert)]
