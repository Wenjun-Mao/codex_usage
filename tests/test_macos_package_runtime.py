"""Portable shell/mock tests: never compile Python or run a packaged application."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts/macos-package-runtime.sh"
ENTRYPOINTS = ("build-agent-macos-arm64.sh", "build-macos-arm64-exe.sh")


def invoke_helper(tmp_path, *, verified=False, failure=0, symlink=False):
    repository = tmp_path / "repo with spaces"
    repository.mkdir()
    build = repository / "build"
    build.mkdir()
    if verified:
        cached = build / "sqlite-runtime-verified"
        cached.mkdir()
        (cached / "manifest.json").write_text("must be checked by builder")
    if symlink:
        (build / "package-venv-macos-arm64").symlink_to(tmp_path, target_is_directory=True)
    script = r'''
set -euo pipefail
source "$HELPER"
UV_CALLS=0
uv() {
  UV_CALLS=$((UV_CALLS + 1))
  printf 'CALL:%s\n' "${UV_PROJECT_ENVIRONMENT-<unset>}"
  printf 'ARG:%s\n' "$@"
  printf 'END\n'
  if [[ "$UV_CALLS" == "$FAILURE" ]]; then return 41; fi
}
cc() { :; }
make() { :; }
ar() { :; }
perl() { :; }
prepare_macos_package_runtime "$REPOSITORY"
printf 'AFTER:%s\n' "$UV_PROJECT_ENVIRONMENT"
'''
    result = subprocess.run(["bash", "-c", script], cwd=repository, capture_output=True, text=True,
                            env={**os.environ, "HELPER": str(HELPER), "REPOSITORY": str(repository),
                                 "FAILURE": str(failure), "UV_PROJECT_ENVIRONMENT": "caller-original"})
    return repository, result


@pytest.mark.parametrize("verified", [False, True])
def test_clean_or_cached_runtime_is_prepared_before_private_sync(tmp_path, verified):
    repository, result = invoke_helper(tmp_path, verified=verified)
    assert result.returncode == 0, result.stderr
    calls = result.stdout.split("END\n")
    assert len(calls) == 5
    runtime = repository / "build" / (
        "sqlite-runtime-verified" if verified else "sqlite-runtime-macos-arm64-py31316")
    assert "ARG:--isolated\nARG:--no-project\nARG:--no-python-downloads\nARG:--python\nARG:3.13" in calls[0]
    assert f"ARG:{repository}/scripts/build_sqlite_runtime.py\nARG:--output\nARG:{runtime}" in calls[0]
    assert "CALL:caller-original" in calls[0]
    for call in calls[1:4]:
        assert f"CALL:{repository}/build/package-venv-macos-arm64" in call
    assert f"ARG:sync\nARG:--locked\nARG:--python\nARG:{runtime}/install/bin/python3.13" in calls[1]
    assert "sys.base_prefix" in calls[2]
    assert f"ARG:{runtime}/install" in calls[2]
    assert f"ARG:{repository}/scripts/check_sqlite_runtime.py" in calls[3]
    assert calls[4] == "AFTER:caller-original\n"
    assert not (repository / ".venv").exists()


@pytest.mark.parametrize("failure", [1, 2, 3, 4])
def test_every_preparation_failure_stops_before_next_step(tmp_path, failure):
    _, result = invoke_helper(tmp_path, failure=failure)
    assert result.returncode == 41
    assert result.stdout.count("END\n") == failure
    assert "AFTER:" not in result.stdout


def test_private_environment_symlink_is_rejected_before_uv(tmp_path):
    _, result = invoke_helper(tmp_path, symlink=True)
    assert result.returncode != 0
    assert "must not be a symlink" in result.stderr
    assert "CALL:" not in result.stdout


@pytest.mark.parametrize("filename", ENTRYPOINTS)
def test_entrypoint_prepares_before_output_deletion_and_keeps_downstream_no_sync(filename):
    source = (ROOT / "scripts" / filename).read_text()
    assert 'source "$repo_root/scripts/macos-package-runtime.sh"' in source
    assert source.index('prepare_macos_package_runtime "$repo_root"') < source.index("rm -f")
    assert source.index('prepare_macos_package_runtime "$repo_root"') < source.index("mkdir -p")
    assert "macos_package_uv run --no-sync pyinstaller" in source
    assert not any(line.lstrip().startswith("uv run ") for line in source.splitlines())
    assert all("--no-sync" in line for line in source.splitlines() if "macos_package_uv run " in line)


@pytest.mark.parametrize("filename", (*ENTRYPOINTS, HELPER.name))
def test_shell_syntax(filename):
    subprocess.run(["bash", "-n", str(ROOT / "scripts" / filename)], check=True,
                   capture_output=True, text=True)


@pytest.mark.parametrize("filename,output", [
    ("build-agent-macos-arm64.sh", "build/packaged-agent/aarch64-apple-darwin/codex-usage-agent-aarch64-apple-darwin"),
    ("build-macos-arm64-exe.sh", "extensions/vscode/bin/darwin-arm64/codex-usage"),
])
def test_failed_bootstrap_preserves_old_binary_in_real_shell_entrypoint(tmp_path, filename, output):
    repository = tmp_path / "repository"
    scripts = repository / "scripts"
    scripts.mkdir(parents=True)
    for name in (filename, HELPER.name):
        (scripts / name).write_text((ROOT / "scripts" / name).read_text())
    old_binary = repository / output
    old_binary.parent.mkdir(parents=True)
    old_binary.write_bytes(b"previous qualified binary")
    tools = tmp_path / "tools"
    tools.mkdir()
    mocks = {"uname": 'if [[ "$1" == "-s" ]]; then echo Darwin; else echo arm64; fi',
             "uv": "exit 71", "cc": ":", "make": ":", "ar": ":", "perl": ":"}
    for name, body in mocks.items():
        path = tools / name
        path.write_text("#!/bin/bash\n" + body + "\n")
        path.chmod(0o755)
    result = subprocess.run(["bash", str(scripts / filename)], capture_output=True, text=True,
                            env={**os.environ, "PATH": str(tools) + os.pathsep + os.environ["PATH"]})
    assert result.returncode == 71
    assert old_binary.read_bytes() == b"previous qualified binary"
    assert not (repository / ".venv").exists()


def test_bootstrap_is_stdlib_only_and_does_not_touch_existing_project(tmp_path):
    uv = shutil.which("uv")
    assert uv is not None, "uv is a required repository qualification tool"
    (tmp_path / "pyproject.toml").write_text('[project]\nname="do-not-sync"\nversion="0.0.0"\n')
    venv = tmp_path / ".venv"
    venv.mkdir()
    sentinel = venv / "pyvenv.cfg"
    sentinel.write_text("invalid sentinel that bootstrap must ignore")
    before = sentinel.read_bytes()
    result = subprocess.run(
        [uv, "run", "--offline", "--isolated", "--no-project",
         "--no-python-downloads", "--python", "3.13", "python", "-c",
         "import sys; assert sys.version_info[:2] == (3, 13); print('stdlib bootstrap passed')"],
        cwd=tmp_path, check=True, capture_output=True, text=True,
    )
    assert result.stdout.strip() == "stdlib bootstrap passed"
    assert sentinel.read_bytes() == before
    assert list(venv.iterdir()) == [sentinel]
    assert not (tmp_path / "uv.lock").exists()
