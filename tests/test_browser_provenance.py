"""Configured WebKit tree capture cannot confuse a missing executable with proof."""
import pytest

from release_tooling_support import load_tool

provenance = load_tool("probes.browser_provenance")


def test_browser_tree_changes_when_a_framework_binary_changes(tmp_path):
    root = tmp_path / "webkit-2336"
    root.mkdir()
    executable = root / "pw_run.sh"
    executable.write_text("synthetic wrapper")
    binary = root / "MiniBrowser"
    binary.write_bytes(b"synthetic binary")
    first = provenance.binary_inventory(executable)
    assert first["status"] == "captured" and len(first["files"]) == 2
    binary.write_bytes(b"different synthetic binary")
    second = provenance.binary_inventory(executable)
    assert first["tree_sha256"] != second["tree_sha256"]
    assert first["files"]["pw_run.sh"] == second["files"]["pw_run.sh"]


def test_missing_browser_root_is_explicitly_unavailable(tmp_path):
    assert provenance.binary_inventory(tmp_path / "missing")["status"] == "unavailable"


@pytest.mark.parametrize("dangling", (False, True))
def test_existing_browser_root_with_missing_launcher_is_unavailable(tmp_path, dangling):
    root = tmp_path / "webkit-2336"
    root.mkdir()
    executable = root / "pw_run.sh"
    if dangling:
        executable.symlink_to("absent-wrapper")
    assert provenance.binary_inventory(executable)["status"] == "unavailable"


def test_browser_tree_identity_includes_framework_symlink_targets(tmp_path):
    root = tmp_path / "webkit-2336"
    root.mkdir()
    executable = root / "pw_run.sh"
    executable.write_text("synthetic wrapper")
    link = root / "Current"
    link.symlink_to("A")
    first = provenance.binary_inventory(executable)
    link.unlink()
    link.symlink_to("B")
    second = provenance.binary_inventory(executable)
    assert first["files"] == second["files"]
    assert first["symlinks"] == {"Current": "A"}
    assert first["tree_sha256"] != second["tree_sha256"]
