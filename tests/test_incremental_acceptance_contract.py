from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_acceptance_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_explicit_sessions_runner_reuses_every_unchanged_fixture_file(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    fixture = load_script_module(ROOT / "scripts/parallel_cache_fixture.py")
    source = load_script_module(ROOT / "scripts/parallel_cache_acceptance.py")
    corpus = fixture.write_parallel_cache_fixture(tmp_path / "codex")

    assert source.main(
        [
            "--sessions-dir",
            str(corpus.sessions_dir),
            "--cache-dir",
            str(tmp_path / "cache"),
        ]
    ) == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["changed"]["stats"]["files_reused"] == (
        payload["corpus"]["file_count"] - 1
    )
