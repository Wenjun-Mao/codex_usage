import importlib.util
from pathlib import Path
from zipfile import ZipFile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify-vsix-archive.py"
SPEC = importlib.util.spec_from_file_location("verify_vsix_archive", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def make_vsix(path: Path, files: list[str]) -> None:
    with ZipFile(path, "w") as package:
        for name in files:
            package.writestr(name, "fixture")


def test_archive_requires_one_matching_collector_and_no_native_files(tmp_path: Path) -> None:
    archive = tmp_path / "companion.vsix"
    common = ["extension/package.json", "extension/out/extension.js"]
    mac = "extension/bin/darwin-arm64/codex-usage-agent"
    windows = "extension/bin/win32-x64/codex-usage-agent.exe"

    make_vsix(archive, common + [mac])
    MODULE.verify_archive(archive, "darwin-arm64")

    make_vsix(archive, common + [mac, windows])
    with pytest.raises(ValueError, match="collectors"):
        MODULE.verify_archive(archive, "darwin-arm64")

    make_vsix(archive, common + [mac, "extension/bin/win32-x64/other.exe"])
    with pytest.raises(ValueError, match="collectors"):
        MODULE.verify_archive(archive, "darwin-arm64")

    make_vsix(archive, common + [mac, "extension/apps/desktop/tauri.json"])
    with pytest.raises(ValueError, match="native_files"):
        MODULE.verify_archive(archive, "darwin-arm64")
