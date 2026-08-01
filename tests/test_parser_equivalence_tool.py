import ast
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts import parser_equivalence_check as tool_module


SCRIPT_PATH = REPOSITORY_ROOT / "scripts/parser_equivalence_check.py"


def write_parser_fixture(path: Path, *, total_tokens: int, padding: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        {
            "timestamp": "2026-07-31T10:00:00Z",
            "type": "session_meta",
            "payload": {
                "id": path.stem,
                "timestamp": "2026-07-31T10:00:00Z",
                "cwd": "/repo/parser-equivalence",
            },
        },
        {"type": "ignored_padding", "payload": {"value": "x" * padding}},
        {
            "timestamp": "2026-07-31T10:00:01Z",
            "type": "event_msg",
            "payload": {
                "type": "token_count",
                "info": {
                    "total_token_usage": {
                        "input_tokens": total_tokens,
                        "cached_input_tokens": 0,
                        "cache_write_input_tokens": 0,
                        "output_tokens": 0,
                        "reasoning_output_tokens": 0,
                        "total_tokens": total_tokens,
                    }
                },
            },
        },
    ]
    path.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8"
    )


def write_five_parser_fixtures(source_root: Path) -> tuple[Path, ...]:
    paths = tuple(source_root / f"{index}.jsonl" for index in range(5))
    for index, path in enumerate(paths):
        write_parser_fixture(path, total_tokens=100 + index, padding=50 * index)
    return paths


def assert_parser_script_guard(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    guards = [
        node
        for node in tree.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and ast.unparse(node.test) == "__name__ == '__main__'"
    ]
    assert len(guards) == 1
    guarded_main_calls = [
        node
        for node in ast.walk(guards[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "main"
    ]
    assert len(guarded_main_calls) == 1
    for node in tree.body:
        if isinstance(node, ast.Import):
            assert all(not alias.name.startswith("codex_usage") for alias in node.names)
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("codex_usage")


def test_capture_copies_rounded_bounded_sample_without_private_paths(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "private-source"
    paths = write_five_parser_fixtures(source_root)
    sizes = tuple(path.stat().st_size for path in paths)
    evidence_root = tmp_path / "evidence"
    manifest_path = tool_module.capture(
        source_root, evidence_root, limit=3, max_file_bytes=10_000
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest == {
        "version": 1,
        "fixtures": [
            {"fixture": "fixtures/000.jsonl", "size_bytes": sizes[0]},
            {"fixture": "fixtures/001.jsonl", "size_bytes": sizes[2]},
            {"fixture": "fixtures/002.jsonl", "size_bytes": sizes[4]},
        ],
    }
    serialized = json.dumps(manifest, sort_keys=True)
    assert str(source_root) not in serialized
    assert sorted(
        path.relative_to(evidence_root).as_posix()
        for path in evidence_root.rglob("*")
        if path.is_file()
    ) == [
        "fixtures/000.jsonl",
        "fixtures/001.jsonl",
        "fixtures/002.jsonl",
        "manifest.json",
    ]


def test_digest_and_compare_use_requested_package_root(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    write_five_parser_fixtures(source_root)
    evidence_root = tmp_path / "evidence"
    manifest = tool_module.capture(
        source_root, evidence_root, limit=5, max_file_bytes=10_000
    )
    current = tool_module.digest(
        manifest, REPOSITORY_ROOT / "src", evidence_root / "current.json"
    )
    payload = json.loads(current.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert all(
        tuple(row) == ("fixture", "size_bytes", "digest")
        for row in payload["fixtures"]
    )
    oracle = evidence_root / "oracle.json"
    shutil.copyfile(current, oracle)
    assert tool_module.compare(oracle, current) == 0
    payload["fixtures"][0]["digest"] = "0" * 64
    current.write_text(json.dumps(payload), encoding="utf-8")
    assert tool_module.compare(oracle, current) == 1


def test_digest_rejects_output_outside_manifest_evidence_root(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    write_five_parser_fixtures(source_root)
    evidence_root = tmp_path / "evidence"
    manifest = tool_module.capture(
        source_root, evidence_root, limit=5, max_file_bytes=10_000
    )
    with pytest.raises(ValueError, match="path must remain under evidence root"):
        tool_module.digest(manifest, REPOSITORY_ROOT / "src", tmp_path / "outside.json")


def test_compare_requires_oracle_and_current_in_one_evidence_root(
    tmp_path: Path,
) -> None:
    left = tmp_path / "left" / "oracle.json"
    right = tmp_path / "right" / "current.json"
    left.parent.mkdir()
    right.parent.mkdir()
    left.write_text('{"version": 1, "fixtures": []}', encoding="utf-8")
    right.write_text('{"version": 1, "fixtures": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="path must remain under evidence root"):
        tool_module.compare(left, right)


def test_import_is_lazy_and_guarded() -> None:
    code = (
        "import runpy,sys; "
        "runpy.run_path(sys.argv[1], run_name='parser_equivalence_import_test'); "
        "assert not any(name == 'codex_usage' or name.startswith('codex_usage.') "
        "for name in sys.modules)"
    )
    subprocess.run([sys.executable, "-I", "-c", code, str(SCRIPT_PATH)], check=True)
    assert_parser_script_guard(SCRIPT_PATH)
