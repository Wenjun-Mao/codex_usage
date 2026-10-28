"""The trusted release contract includes the native-runtime build closure."""
from pathlib import Path

from release_tooling_support import load_tool


policy = load_tool("release.policy")
ROOT = Path(__file__).resolve().parents[1]
RUNTIME_FILES = (
    "scripts/build_sqlite_runtime.py", "scripts/build_sqlite_runtime_windows.py",
    "scripts/runtime_sources.py", "scripts/runtime_windows_sources.py",
    "scripts/check_sqlite_runtime.py", "scripts/macos-package-runtime.sh",
    "scripts/windows-build-toolchain.ps1", "scripts/test-windows-build-toolchain.ps1",
    "src/codex_usage/sqlite_runtime.py",
)


def test_runtime_build_closure_is_part_of_the_qualification_contract():
    actual = policy.contract_files(ROOT)
    assert set(RUNTIME_FILES) <= set(actual)
    assert len(actual) == len(set(actual))
    assert all((ROOT / name).is_file() for name in actual)


def test_each_runtime_helper_changes_the_contract_identity(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "contract_files", lambda root: list(RUNTIME_FILES))
    for name in RUNTIME_FILES:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((ROOT / name).read_bytes())
    original = policy.contract_identity(tmp_path)
    for name in RUNTIME_FILES:
        path = tmp_path / name
        data = path.read_bytes()
        path.write_bytes(data + b"\n# changed build input\n")
        assert policy.contract_identity(tmp_path) != original, name
        path.write_bytes(data)
        assert policy.contract_identity(tmp_path) == original
