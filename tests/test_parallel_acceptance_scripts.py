from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import sys
from datetime import UTC, datetime, tzinfo
from pathlib import Path
from types import ModuleType
from typing import Any, cast

import pytest
from parallel_cache_test_support import write_usage_corpus

import codex_usage.cli as cli_module
from codex_usage.parallel.execution import ParallelRunReport, WorkerSpan
from codex_usage.parallel_audit import (
    require_actual_parallel,
    validate_target_architecture,
    write_parallel_audit,
)
from codex_usage.session_cache import load_cached_session_data

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_AUDIT_KEY_FRAGMENTS = (
    "path",
    "session",
    "thread",
    "project",
    "token",
    "timestamp",
    "event",
)


def load_script_module(path: Path) -> ModuleType:
    module_name = f"_parallel_plan_test_{path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def call_name(call: ast.Call) -> str:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name):
        return f"{call.func.value.id}.{call.func.attr}"
    return ""


def assert_importable_guard(path: Path, *, requires_freeze_support: bool) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    guards = [
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and ast.unparse(node.test) == "__name__ == '__main__'"
    ]
    assert len(guards) == 1
    guarded_calls = [
        (node.lineno, call_name(node))
        for node in ast.walk(guards[0])
        if isinstance(node, ast.Call)
    ]
    main_lines = [line for line, name in guarded_calls if name == "main"]
    assert len(main_lines) == 1
    freeze_lines = [
        line for line, name in guarded_calls if name == "multiprocessing.freeze_support"
    ]
    if requires_freeze_support:
        assert len(freeze_lines) == 1
        assert freeze_lines[0] < main_lines[0]
    else:
        assert freeze_lines == []
    forbidden_top_level = {
        "main",
        "load_cached_session_data",
        "subprocess.run",
        "subprocess.Popen",
    }
    for node in tree.body:
        if node is guards[0] or isinstance(
            node, (ast.Import, ast.ImportFrom, ast.FunctionDef, ast.ClassDef)
        ):
            continue
        assert all(
            call_name(call) not in forbidden_top_level
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
        )


def assert_no_sensitive_audit_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            folded = str(key).casefold()
            assert not any(
                fragment in folded for fragment in SENSITIVE_AUDIT_KEY_FRAGMENTS
            )
            assert_no_sensitive_audit_keys(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_sensitive_audit_keys(child)


class FixedDateTime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> FixedDateTime:
        value = cls(2026, 7, 31, 12, 0, tzinfo=UTC)
        return value.replace(tzinfo=None) if tz is None else value.astimezone(tz)


def packaged_transition_payload() -> dict[str, object]:
    return {
        "confidence": 100,
        "effective_from": "2026-07-31T12:01:00+00:00",
        "evidence": [
            (
                "verified repo path /private/tmp/transition-target -> "
                "https://github.com/example/packaged-parallel-target "
                "(thread packaged-parallel-00, "
                "source jsonl:response_item:function_call_workdir)"
            )
        ],
        "source_key": "https://github.com/example/source-00",
        "source_label": "source-00",
        "target_key": "https://github.com/example/packaged-parallel-target",
        "target_label": "packaged-parallel-target",
        "thread_ids": ["packaged-parallel-00"],
    }


def packaged_summary_payload(module: ModuleType) -> dict[str, object]:
    return {
        "files_scanned": module.FILE_COUNT,
        "total": {
            "record_count": module.EXPECTED_RECORD_COUNT,
            "usage": dict(module.EXPECTED_USAGE),
        },
        "project_transitions": [packaged_transition_payload()],
    }


def packaged_audit_run() -> dict[str, object]:
    return {
        "resolved_worker_count": 2,
        "worker_pids": [901, 902],
        "max_concurrency": 2,
        "used_serial_fallback": False,
        "infrastructure_error": "",
        "span_count": 2,
        "file_error_count": 0,
    }


def packaged_audit_payload() -> dict[str, object]:
    return {
        "version": 1,
        "parent_pid": 900,
        "sys_platform": "darwin",
        "machine": "arm64",
        "usage_run": packaged_audit_run(),
        "transition_run": packaged_audit_run(),
    }


@pytest.mark.parametrize(
    ("relative_path", "requires_freeze_support"),
    [
        ("scripts/parallel_cache_acceptance.py", True),
        ("scripts/packaged_parallel_cache_smoke.py", True),
    ],
)
def test_acceptance_scripts_are_importable_and_guarded(
    relative_path: str,
    requires_freeze_support: bool,
) -> None:
    path = REPOSITORY_ROOT / relative_path
    module = load_script_module(path)
    assert callable(module.main)
    assert inspect.signature(module.main).return_annotation in {"int", int}
    assert_importable_guard(path, requires_freeze_support=requires_freeze_support)


def test_frozen_main_calls_freeze_support_before_cli_import() -> None:
    path = REPOSITORY_ROOT / "src/codex_usage/__main__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    guards = [node for node in tree.body if isinstance(node, ast.If)]
    assert len(guards) == 1
    freeze_line = next(
        node.lineno
        for node in ast.walk(guards[0])
        if isinstance(node, ast.Call)
        and call_name(node) == "multiprocessing.freeze_support"
    )
    cli_import_line = next(
        node.lineno
        for node in ast.walk(guards[0])
        if isinstance(node, ast.ImportFrom) and node.module == "codex_usage.cli"
    )
    assert freeze_line < cli_import_line
    assert not any(
        isinstance(node, ast.ImportFrom) and node.module == "codex_usage.cli"
        for node in tree.body
    )


def test_packaged_corpus_represents_both_sides_of_transition(
    tmp_path: Path,
) -> None:
    module = load_script_module(
        REPOSITORY_ROOT / "scripts/packaged_parallel_cache_smoke.py"
    )
    sessions = tmp_path / "codex" / "sessions"
    day = sessions / "2026" / "07" / "31"
    day.mkdir(parents=True)
    target_repo = tmp_path / "transition-target"
    git_dir = target_repo / ".git"
    git_dir.mkdir(parents=True)
    (git_dir / "config").write_text(
        '[remote "origin"]\n'
        "    url = https://github.com/example/packaged-parallel-target.git\n",
        encoding="utf-8",
    )
    module._write_large_session(
        day / "parallel-00.jsonl",
        index=0,
        transition_target=target_repo,
    )

    data = load_cached_session_data(
        [sessions],
        cache_dir=tmp_path / "cache",
        auto_transitions=True,
        max_workers=1,
    )
    assert len(data.project_transitions) == 1
    assert {record.project_key for record in data.records} == {
        "https://github.com/example/source-00",
        "https://github.com/example/packaged-parallel-target",
    }


def test_parallel_audit_does_not_change_summary_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    codex_home = tmp_path / "codex"
    write_usage_corpus(codex_home)
    monkeypatch.setenv("CODEX_HOME", str(codex_home))
    monkeypatch.setenv("CODEX_USAGE_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(cli_module, "datetime", FixedDateTime)
    assert cli_module.main(["summary", "--range", "all", "--json"]) == 0
    without_audit = json.loads(capsys.readouterr().out)
    audit_path = tmp_path / "audit.json"
    assert (
        cli_module.main(
            ["summary", "--range", "all", "--json", "--parallel-audit", str(audit_path)]
        )
        == 0
    )
    with_audit = json.loads(capsys.readouterr().out)
    assert with_audit == without_audit

    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert tuple(audit) == (
        "version",
        "parent_pid",
        "sys_platform",
        "machine",
        "usage_run",
        "transition_run",
    )
    for run_key in ("usage_run", "transition_run"):
        assert tuple(audit[run_key]) == (
            "resolved_worker_count",
            "worker_pids",
            "max_concurrency",
            "used_serial_fallback",
            "infrastructure_error",
            "span_count",
            "file_error_count",
        )
    assert_no_sensitive_audit_keys(audit)


@pytest.mark.parametrize(
    "sensitive_error",
    [
        "session_token_timestamp_event",
        "OSError: /Users/alice/private-project/session.jsonl",
    ],
)
def test_parallel_audit_serializes_only_fixed_infrastructure_error_sentinel(
    sensitive_error: str,
    tmp_path: Path,
) -> None:
    report = ParallelRunReport(
        resolved_worker_count=2,
        worker_spans=(WorkerSpan(901, 0, 20), WorkerSpan(902, 5, 15)),
        used_serial_fallback=True,
        infrastructure_error=sensitive_error,
        file_error_count=0,
    )
    audit_path = write_parallel_audit(
        tmp_path / "audit.json",
        parent_pid=900,
        usage_run=report,
        transition_run=report,
    )

    serialized = audit_path.read_text(encoding="utf-8")
    audit = json.loads(serialized)
    assert audit["usage_run"]["infrastructure_error"] == "present"
    assert audit["transition_run"]["infrastructure_error"] == "present"
    assert sensitive_error not in serialized


def test_actual_parallel_validator_rejects_every_disguised_serial_shape() -> None:
    parent_pid = 900
    overlap = (WorkerSpan(901, 0, 20), WorkerSpan(902, 5, 15))
    invalid = (
        ParallelRunReport(1, overlap, False, "", 0),
        ParallelRunReport(2, overlap, True, "OSError: failed", 0),
        ParallelRunReport(
            2, (WorkerSpan(parent_pid, 0, 20), WorkerSpan(902, 5, 15)), False, "", 0
        ),
        ParallelRunReport(
            2, (WorkerSpan(901, 0, 20), WorkerSpan(901, 5, 15)), False, "", 0
        ),
        ParallelRunReport(
            2,
            (
                WorkerSpan(901, 0, 20),
                WorkerSpan(901, 5, 15),
                WorkerSpan(902, 21, 30),
            ),
            False,
            "",
            0,
        ),
        ParallelRunReport(
            2, (WorkerSpan(901, 0, 5), WorkerSpan(902, 5, 10)), False, "", 0
        ),
    )
    for report in invalid:
        with pytest.raises(
            RuntimeError, match="cold usage: actual process parallelism not observed"
        ):
            require_actual_parallel(report, parent_pid=parent_pid, label="cold usage")
    require_actual_parallel(
        ParallelRunReport(2, overlap, False, "", 0),
        parent_pid=parent_pid,
        label="cold usage",
    )


def test_target_architecture_validator_is_exact() -> None:
    validate_target_architecture("darwin-arm64", sys_platform="darwin", machine="arm64")
    validate_target_architecture("win32-x64", sys_platform="win32", machine="AMD64")
    validate_target_architecture("win32-x64", sys_platform="win32", machine="x86_64")
    for target, sys_platform, machine in (
        ("darwin-arm64", "linux", "arm64"),
        ("darwin-arm64", "darwin", "x86_64"),
        ("win32-x64", "win32", "arm64"),
        ("win32-x64", "darwin", "x86_64"),
        ("linux-x64", "linux", "x86_64"),
    ):
        with pytest.raises(RuntimeError, match="unsupported target architecture"):
            validate_target_architecture(
                cast(Any, target), sys_platform=sys_platform, machine=machine
            )


def test_packaged_summary_accepts_expected_transition_in_json_key_order() -> None:
    module = load_script_module(
        REPOSITORY_ROOT / "scripts/packaged_parallel_cache_smoke.py"
    )

    module._validate_summary(packaged_summary_payload(module))


@pytest.mark.parametrize(
    ("field", "wrong_value"),
    [
        ("source_key", "https://github.com/example/wrong-source"),
        ("source_label", "wrong-source"),
        ("target_key", "https://github.com/example/wrong-target"),
        ("target_label", "wrong-target"),
        ("effective_from", "2026-07-31T12:01:01+00:00"),
        ("confidence", 99),
        ("thread_ids", ["packaged-parallel-09"]),
    ],
)
def test_packaged_summary_rejects_changed_stable_transition_fields(
    field: str,
    wrong_value: object,
) -> None:
    module = load_script_module(
        REPOSITORY_ROOT / "scripts/packaged_parallel_cache_smoke.py"
    )
    payload = packaged_summary_payload(module)
    transition = cast(list[dict[str, object]], payload["project_transitions"])[0]
    transition[field] = wrong_value

    with pytest.raises(RuntimeError, match="deterministic transition"):
        module._validate_summary(payload)


@pytest.mark.parametrize(
    ("evidence", "error_type"),
    [
        ([], RuntimeError),
        ([1], TypeError),
        (["unverified transition"], RuntimeError),
        (
            [
                (
                    "verified repo path /tmp/one -> "
                    "https://github.com/example/packaged-parallel-target "
                    "(thread packaged-parallel-00, "
                    "source jsonl:response_item:function_call_workdir)"
                ),
                "extra evidence",
            ],
            RuntimeError,
        ),
    ],
)
def test_packaged_summary_structurally_validates_dynamic_transition_evidence(
    evidence: list[object],
    error_type: type[Exception],
) -> None:
    module = load_script_module(
        REPOSITORY_ROOT / "scripts/packaged_parallel_cache_smoke.py"
    )
    payload = packaged_summary_payload(module)
    transition = cast(list[dict[str, object]], payload["project_transitions"])[0]
    transition["evidence"] = evidence

    with pytest.raises(error_type, match="transition evidence"):
        module._validate_summary(payload)


def test_packaged_audit_rejects_bool_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_script_module(
        REPOSITORY_ROOT / "scripts/packaged_parallel_cache_smoke.py"
    )
    audit = packaged_audit_payload()
    audit["version"] = True
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.platform, "machine", lambda: "arm64")

    with pytest.raises(RuntimeError, match="fields or version"):
        module._validate_audit(audit, "darwin-arm64")


@pytest.mark.parametrize(
    "field",
    [
        "resolved_worker_count",
        "max_concurrency",
        "span_count",
        "file_error_count",
    ],
)
def test_packaged_audit_rejects_bool_integer_counts(
    field: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_script_module(
        REPOSITORY_ROOT / "scripts/packaged_parallel_cache_smoke.py"
    )
    audit = packaged_audit_payload()
    cast(dict[str, object], audit["usage_run"])[field] = False
    monkeypatch.setattr(module.sys, "platform", "darwin")
    monkeypatch.setattr(module.platform, "machine", lambda: "arm64")

    with pytest.raises(RuntimeError, match="actual process parallelism"):
        module._validate_audit(audit, "darwin-arm64")
