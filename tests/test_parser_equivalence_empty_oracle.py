from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts/parser_equivalence_check.py"


def _load_tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_empty_oracle_tool", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool = _load_tool()


def _write_empty_payload(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"version":1,"fixtures":[]}\n', encoding="utf-8")


def test_capture_rejects_empty_corpus_before_creating_evidence(tmp_path: Path) -> None:
    source_root = tmp_path / "private-source"
    source_root.mkdir()
    evidence_root = tmp_path / "evidence"

    with pytest.raises(ValueError, match="eligible fixtures"):
        tool.capture(source_root, evidence_root, limit=5, max_file_bytes=10_000)

    assert not evidence_root.exists()


@pytest.mark.parametrize("require_digest", (False, True))
def test_payload_validation_rejects_empty_fixture_lists(
    tmp_path: Path,
    require_digest: bool,
) -> None:
    payload_path = tmp_path / "evidence" / "payload.json"
    _write_empty_payload(payload_path)

    with pytest.raises(ValueError, match="invalid evidence payload"):
        tool._read_payload(payload_path, require_digest=require_digest)


def test_compare_never_reports_empty_payloads_equivalent(tmp_path: Path) -> None:
    evidence_root = tmp_path / "evidence"
    oracle = evidence_root / "oracle.json"
    current = evidence_root / "current.json"
    _write_empty_payload(oracle)
    _write_empty_payload(current)

    with pytest.raises(ValueError, match="invalid evidence payload"):
        tool.compare(oracle, current)


def _run_cli(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *command],
        check=False,
        capture_output=True,
        text=True,
    )


def test_empty_capture_cli_reports_only_aggregate_error(tmp_path: Path) -> None:
    source_root = tmp_path / "private-source"
    source_root.mkdir()
    evidence_root = tmp_path / "private-evidence"

    completed = _run_cli(
        [
            "capture",
            "--source-root",
            str(source_root),
            "--evidence-root",
            str(evidence_root),
            "--limit",
            "5",
            "--max-file-bytes",
            "10000",
        ]
    )

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == '{"error":true}\n'
    assert str(source_root) not in completed.stderr
    assert not evidence_root.exists()


@pytest.mark.parametrize("command_name", ("digest", "compare"))
def test_empty_digest_cli_paths_report_only_aggregate_error(
    tmp_path: Path,
    command_name: str,
) -> None:
    evidence_root = tmp_path / "private-evidence"
    oracle = evidence_root / "oracle.json"
    current = evidence_root / "current.json"
    _write_empty_payload(oracle)
    if command_name == "digest":
        command = [
            "digest",
            "--manifest",
            str(oracle),
            "--package-root",
            str(REPOSITORY_ROOT / "src"),
            "--output",
            str(current),
        ]
    else:
        _write_empty_payload(current)
        command = [
            "compare",
            "--oracle",
            str(oracle),
            "--current",
            str(current),
        ]

    completed = _run_cli(command)

    assert completed.returncode == 2
    assert completed.stdout == ""
    assert completed.stderr == '{"error":true}\n'
    assert str(evidence_root) not in completed.stderr
