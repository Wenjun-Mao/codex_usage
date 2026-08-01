import ast
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPOSITORY_ROOT / "scripts/parser_equivalence_check.py"
NONCANONICAL_FIXTURE_NAMES = (
    "fixtures/000.jsonl:stream",
    "fixtures/CON.jsonl",
    "fixtures/NUL.jsonl",
    "fixtures/COM1.jsonl",
    "fixtures/000.jsonl.",
    "fixtures/000.jsonl ",
    r"C:fixtures\000.jsonl",
    r"C:\fixtures\000.jsonl",
    "C:/fixtures/000.jsonl",
    r"\\server\share\000.jsonl",
    "//server/share/000.jsonl",
    "../fixtures/000.jsonl",
    "fixtures/../fixtures/000.jsonl",
    "/fixtures/000.jsonl",
    "fixtures/001.jsonl",
    r"fixtures\000.jsonl",
    "fixtures//000.jsonl",
    "./fixtures/000.jsonl",
    "Fixtures/000.jsonl",
)


def load_tool_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "parser_equivalence_check_test_target",
        SCRIPT_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tool_module = load_tool_module()


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


def write_fake_parser_package(package_root: Path, sentinel: str) -> None:
    package = package_root / "codex_usage"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "parser.py").write_text(
        "from pathlib import Path\n\n"
        f"SENTINEL = {sentinel!r}\n\n"
        "def parse_session_file(path: Path) -> str:\n"
        "    return SENTINEL\n",
        encoding="utf-8",
    )


def digest_payload(
    *,
    version: object = 1,
    fixture: object = "fixtures/000.jsonl",
    size_bytes: object = 1,
    digest: object = "a" * 64,
) -> dict[str, object]:
    return {
        "version": version,
        "fixtures": [
            {
                "fixture": fixture,
                "size_bytes": size_bytes,
                "digest": digest,
            }
        ],
    }


def write_digest_payload(path: Path, payload: dict[str, object] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload or digest_payload()), encoding="utf-8")


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


def test_capture_rejects_jsonl_symlink_outside_source_root(tmp_path: Path) -> None:
    outside = tmp_path / "outside.jsonl"
    write_parser_fixture(outside, total_tokens=100, padding=0)
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "escape.jsonl").symlink_to(outside)
    evidence_root = tmp_path / "evidence"

    with pytest.raises(ValueError, match="path must remain under evidence root"):
        tool_module.capture(
            source_root, evidence_root, limit=5, max_file_bytes=10_000
        )
    assert not evidence_root.exists()


def test_capture_deduplicates_contained_resolved_candidates(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    source = source_root / "source.jsonl"
    write_parser_fixture(source, total_tokens=100, padding=0)
    (source_root / "alias.jsonl").symlink_to(source.name)
    evidence_root = tmp_path / "evidence"

    manifest_path = tool_module.capture(
        source_root, evidence_root, limit=5, max_file_bytes=10_000
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest == {
        "version": 1,
        "fixtures": [
            {"fixture": "fixtures/000.jsonl", "size_bytes": source.stat().st_size}
        ],
    }


def test_digest_uses_two_requested_package_roots_in_fresh_processes(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source"
    source = source_root / "source.jsonl"
    write_parser_fixture(source, total_tokens=100, padding=0)
    evidence_root = tmp_path / "evidence"
    manifest = tool_module.capture(
        source_root, evidence_root, limit=1, max_file_bytes=10_000
    )
    outputs: list[Path] = []
    sentinel_digests = (
        (
            "sentinel-one",
            "0d6fb56b5d68f056d1a81c89328f2594b4ef0479bea3f9a5738b8a80d63a1baa",
        ),
        (
            "sentinel-two",
            "29d009cafcae82e313e9a788111ee2f288bdcb13c7bab49ef4d515b1f2063afb",
        ),
    )
    for index, (sentinel, expected_digest) in enumerate(sentinel_digests):
        package_root = tmp_path / f"package-{index}"
        write_fake_parser_package(package_root, sentinel)
        output = evidence_root / f"digest-{index}.json"
        completed = subprocess.run(
            [
                sys.executable,
                "-I",
                str(SCRIPT_PATH),
                "digest",
                "--manifest",
                str(manifest),
                "--package-root",
                str(package_root),
                "--output",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        assert json.loads(completed.stdout) == {
            "byte_count": source.stat().st_size,
            "fixture_count": 1,
        }
        assert json.loads(output.read_text(encoding="utf-8")) == {
            "version": 1,
            "fixtures": [
                {
                    "fixture": "fixtures/000.jsonl",
                    "size_bytes": source.stat().st_size,
                    "digest": expected_digest,
                }
            ],
        }
        outputs.append(output)

    matching = evidence_root / "matching.json"
    matching.write_text(outputs[0].read_text(encoding="utf-8"), encoding="utf-8")
    assert tool_module.compare(outputs[0], matching) == 0
    assert tool_module.compare(outputs[0], outputs[1]) == 1


def test_loading_tool_module_does_not_change_sys_path() -> None:
    before = tuple(sys.path)
    load_tool_module()
    assert tuple(sys.path) == before


def test_digest_rejects_output_outside_manifest_evidence_root(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    write_five_parser_fixtures(source_root)
    evidence_root = tmp_path / "evidence"
    manifest = tool_module.capture(
        source_root, evidence_root, limit=5, max_file_bytes=10_000
    )
    with pytest.raises(ValueError, match="path must remain under evidence root"):
        tool_module.digest(manifest, REPOSITORY_ROOT / "src", tmp_path / "outside.json")


def test_digest_rejects_manifest_symlink_outside_evidence_root(tmp_path: Path) -> None:
    outside_manifest = tmp_path / "outside" / "manifest.json"
    outside_manifest.parent.mkdir()
    outside_manifest.write_text('{"version":1,"fixtures":[]}', encoding="utf-8")
    evidence_root = tmp_path / "evidence"
    evidence_root.mkdir()
    manifest = evidence_root / "manifest.json"
    manifest.symlink_to(outside_manifest)

    with pytest.raises(ValueError, match="path must remain under evidence root"):
        tool_module.digest(
            manifest,
            REPOSITORY_ROOT / "src",
            evidence_root / "current.json",
        )


def test_compare_rejects_fixture_symlink_outside_evidence_root(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.jsonl"
    outside.write_text("outside", encoding="utf-8")
    evidence_root = tmp_path / "evidence"
    fixtures_root = evidence_root / "fixtures"
    fixtures_root.mkdir(parents=True)
    (fixtures_root / "000.jsonl").symlink_to(outside)
    oracle = evidence_root / "oracle.json"
    current = evidence_root / "current.json"
    write_digest_payload(oracle)
    write_digest_payload(current)

    with pytest.raises(ValueError, match="invalid evidence payload"):
        tool_module.compare(oracle, current)


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


def test_compare_rejects_the_same_path(tmp_path: Path) -> None:
    digest_path = tmp_path / "evidence" / "digest.json"
    write_digest_payload(digest_path)

    with pytest.raises(ValueError, match="oracle and current must be distinct files"):
        tool_module.compare(digest_path, digest_path)


def test_compare_rejects_a_hardlink_alias(tmp_path: Path) -> None:
    oracle = tmp_path / "evidence" / "oracle.json"
    current = oracle.with_name("current.json")
    write_digest_payload(oracle)
    current.hardlink_to(oracle)

    with pytest.raises(ValueError, match="oracle and current must be distinct files"):
        tool_module.compare(oracle, current)


def test_compare_rejects_a_symlink_alias(tmp_path: Path) -> None:
    oracle = tmp_path / "evidence" / "oracle.json"
    current = oracle.with_name("current.json")
    write_digest_payload(oracle)
    current.symlink_to(oracle.name)

    with pytest.raises(ValueError, match="oracle and current must be distinct files"):
        tool_module.compare(oracle, current)


@pytest.mark.parametrize("fixture", NONCANONICAL_FIXTURE_NAMES)
def test_digest_rejects_noncanonical_manifest_fixture_names(
    tmp_path: Path,
    fixture: str,
) -> None:
    source_root = tmp_path / "source"
    source = source_root / "source.jsonl"
    write_parser_fixture(source, total_tokens=100, padding=0)
    evidence_root = tmp_path / "evidence"
    manifest = tool_module.capture(
        source_root, evidence_root, limit=1, max_file_bytes=10_000
    )
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["fixtures"][0]["fixture"] = fixture
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid evidence payload"):
        tool_module.digest(
            manifest,
            REPOSITORY_ROOT / "src",
            evidence_root / "current.json",
        )


@pytest.mark.parametrize("fixture", NONCANONICAL_FIXTURE_NAMES)
def test_compare_rejects_noncanonical_digest_fixture_names(
    tmp_path: Path,
    fixture: str,
) -> None:
    evidence_root = tmp_path / "evidence"
    oracle = evidence_root / "oracle.json"
    current = evidence_root / "current.json"
    write_digest_payload(oracle)
    write_digest_payload(current, digest_payload(fixture=fixture))

    with pytest.raises(ValueError, match="invalid evidence payload"):
        tool_module.compare(oracle, current)


@pytest.mark.parametrize(
    "fixture_names",
    (
        ("fixtures/001.jsonl", "fixtures/000.jsonl"),
        ("fixtures/000.jsonl", "fixtures/002.jsonl"),
        ("fixtures/000.jsonl", "fixtures/000.jsonl"),
    ),
    ids=("wrong-order", "skipped-name", "duplicate-name"),
)
def test_compare_rejects_noncanonical_digest_fixture_sequences(
    tmp_path: Path,
    fixture_names: tuple[str, ...],
) -> None:
    evidence_root = tmp_path / "evidence"
    oracle = evidence_root / "oracle.json"
    current = evidence_root / "current.json"
    write_digest_payload(oracle)
    payload = digest_payload()
    payload["fixtures"] = [
        {
            "fixture": fixture,
            "size_bytes": 1,
            "digest": "a" * 64,
        }
        for fixture in fixture_names
    ]
    write_digest_payload(current, payload)

    with pytest.raises(ValueError, match="invalid evidence payload"):
        tool_module.compare(oracle, current)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("version", True),
        ("version", 1.0),
        ("size_bytes", True),
        ("size_bytes", -1),
        ("size_bytes", 1.0),
        ("digest", "A" * 64),
        ("digest", "a" * 63),
        ("digest", "g" * 64),
    ),
)
def test_compare_rejects_malformed_digest_payloads(
    tmp_path: Path,
    field: str,
    value: object,
) -> None:
    evidence_root = tmp_path / "evidence"
    oracle = evidence_root / "oracle.json"
    current = evidence_root / "current.json"
    write_digest_payload(oracle)
    malformed = digest_payload()
    if field == "version":
        malformed[field] = value
    else:
        malformed["fixtures"][0][field] = value
    write_digest_payload(current, malformed)

    with pytest.raises(ValueError, match="invalid evidence payload"):
        tool_module.compare(oracle, current)


def test_import_is_lazy_and_guarded() -> None:
    code = (
        "import runpy,sys; "
        "runpy.run_path(sys.argv[1], run_name='parser_equivalence_import_test'); "
        "assert not any(name == 'codex_usage' or name.startswith('codex_usage.') "
        "for name in sys.modules)"
    )
    subprocess.run([sys.executable, "-I", "-c", code, str(SCRIPT_PATH)], check=True)
    assert_parser_script_guard(SCRIPT_PATH)
