from pathlib import Path

from release_tooling_support import load_tool


ROOT = Path(__file__).resolve().parents[1]


def test_experiment_is_manual_nonpublishing_and_both_native_targets():
    text = (ROOT / ".github/workflows/collector-runtime-evaluation.yml").read_text()
    assert "workflow_dispatch:" in text and "  push:" not in text
    assert "contents: read" in text and "contents: write" not in text
    for denied in ("VSCE_PAT", "secrets.", "publication_journal", "promote-vsix", "private-input", "--ledger-snapshot"):
        assert denied not in text
    assert "[macos-26, windows-2025]" in text
    assert "[current313, common313, common315]" in text
    assert "max-parallel: 2" in text and "timeout-minutes: 15" in text
    assert "if: always()" in text and "output/runtime-experiment/*.json" in text
    assert '"$PY" experiments/collector-runtime/check.py' in text
    assert "PYTHONPATH: ${{ github.workspace }}/src" in text


def test_default_package_dependencies_remain_unchanged():
    import tomllib
    packages = {item["name"]: item["version"] for item in tomllib.loads((ROOT / "uv.lock").read_text())["package"]}
    assert packages["pyinstaller"] == "6.20.0"
    assert packages["pydantic-core"] == "2.46.3"
    assert (ROOT / ".python-version").read_text().strip() == "3.13"


def test_runtime_check_refuses_non_ci_before_any_collector_run(tmp_path, monkeypatch):
    import importlib.util
    import sys
    import pytest
    spec = importlib.util.spec_from_file_location("runtime_experiment", ROOT / "experiments/collector-runtime/check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    monkeypatch.setattr(sys, "argv", ["check", "--output", str(tmp_path / "output")])
    with pytest.raises(RuntimeError, match="fresh CI"):
        module.main()


def test_empty_ci_host_accepts_unresolved_fallback_but_rejects_real_cli(monkeypatch):
    import importlib.util
    import pytest
    spec = importlib.util.spec_from_file_location("runtime_guard", ROOT / "experiments/collector-runtime/check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    monkeypatch.setattr("codex_usage.codex_runtime.discover_codex_executables", lambda: ("codex",))
    monkeypatch.setattr(module.shutil, "which", lambda candidate: None)
    module.require_disposable_host()
    monkeypatch.setattr(module.shutil, "which", lambda candidate: "/installed/codex")
    with pytest.raises(RuntimeError, match="account CLI"):
        module.require_disposable_host()


def test_cold_proof_requires_actual_byte_progress():
    policy = load_tool("release.policy")
    assert "collector_smoke_owner.py" in " ".join(policy.contract_files())
