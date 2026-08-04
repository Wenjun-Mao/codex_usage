from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]


def _load_script(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"_task_7_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def test_synthetic_acceptance_renders_a_bounded_warm_cached_report(
    capsys: object,
) -> None:
    source = _load_script(ROOT / "scripts" / "parallel_cache_acceptance.py")

    assert source.main(["--synthetic"]) == 0
    payload = json.loads(capsys.readouterr().out)

    warm_report = payload["warm_report"]
    assert warm_report["range_record_count"] < warm_report["unbounded_record_count"]
    assert warm_report["source_jsonl_read_attempts"] == 0
    assert warm_report["stats"]["files_parsed"] == 0
    assert warm_report["usage_run"]["span_count"] == 0
    assert warm_report["project_count"] > 0
    assert warm_report["model_count"] > 0


def test_packaged_report_smoke_is_a_shared_native_build_gate() -> None:
    smoke = ROOT / "scripts" / "packaged_report_smoke.py"
    assert smoke.is_file()
    text = smoke.read_text(encoding="utf-8")
    assert '"--executable"' in text
    assert "Project Breakdown" in text
    assert "Root tasks" in text
    assert "Subagents" in text
    assert "model-segment" in text

    for name in ("build-macos-arm64-exe.sh", "build-windows-exe.ps1"):
        build = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "packaged_report_smoke.py" in build
        assert build.index("packaged_parallel_cache_smoke.py") < build.index(
            "packaged_report_smoke.py"
        ) < build.index("smoke-test-packaged-sync.py")


def test_direct_script_bootstrap_imports_use_inline_e402_suppressions() -> None:
    for name in ("parallel_cache_acceptance.py", "packaged_parallel_cache_smoke.py"):
        text = (ROOT / "scripts" / name).read_text(encoding="utf-8")
        assert "from parallel_cache_fixture import (  # noqa: E402" in text

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "per-file-ignores" not in pyproject
