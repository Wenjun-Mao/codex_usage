"""Portable source-contract checks; no Windows/PowerShell execution is claimed."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
HELPER_PATH = ROOT / "scripts/windows-build-toolchain.ps1"
HELPER = HELPER_PATH.read_text()


@pytest.mark.parametrize("filename", ["build-agent-windows-x64.ps1", "build-windows-exe.ps1"])
def test_both_entrypoints_initialize_before_touching_old_outputs(filename):
    source = (ROOT / "scripts" / filename).read_text()
    assert '. (Join-Path $PSScriptRoot "windows-build-toolchain.ps1")' in source
    prepare = source.index("Initialize-WindowsSqliteRuntime -RepoRoot $repoRoot")
    assert prepare < source.index("Remove-Item")
    assert prepare < source.index("New-Item")
    assert prepare < source.index("uv sync --locked")


def test_vs2022_cpp_discovery_and_explicit_target_preservation():
    preserve = HELPER.index('if ($env:VSCMD_VER -or $env:VSCMD_ARG_TGT_ARCH)')
    discover = HELPER.index("$installation = & $vswhere")
    assert preserve < discover
    assert "Assert-WindowsX64Toolchain\n        return" in HELPER[preserve:discover]
    assert "-version '[17.0,)'" in HELPER
    assert "Microsoft.VisualStudio.Component.VC.Tools.x86.x64" in HELPER
    assert '-arch=x64 -host_arch=x64' in HELPER
    assert 'Test-WindowsToolchainVersion -Version $env:VisualStudioVersion' in HELPER
    assert '$parsed.Major -ge 17' in HELPER


def test_sdk_tools_and_search_paths_are_validated_not_just_path_presence():
    for name in ("cl.exe", "link.exe", "dumpbin.exe", "vcruntime.h", "Windows.h",
                 "sdkddkver.h", "stdio.h", "kernel32.lib", "ucrt.lib", "vcruntime.lib"):
        assert name in HELPER
    assert "GetFullPath($actual.Source) -ne [IO.Path]::GetFullPath($expected)" in HELPER
    assert "$env:INCLUDE" in HELPER and "$env:LIB" in HELPER
    assert "$search -notcontains" in HELPER


def test_devcmd_is_child_only_no_profile_or_autorun_or_command_text_path_injection():
    assert '$start.FileName = Join-Path $env:SystemRoot "System32\\cmd.exe"' in HELPER
    assert "/d /u /s /c" in HELPER
    assert '$start.EnvironmentVariables["CODEX_USAGE_VSDEVCMD"] = $devcmd' in HELPER
    assert 'call "%CODEX_USAGE_VSDEVCMD%"' in HELPER
    assert "$start.UseShellExecute = $false" in HELPER
    assert "$start.StandardOutputEncoding = [Text.Encoding]::Unicode" in HELPER
    assert "$process.ExitCode -ne 0" in HELPER
    assert HELPER.index("$process.ExitCode -ne 0") < HELPER.index("foreach ($line in $stdout.Result")
    assert "$line.IndexOf('=')" in HELPER  # Values may contain additional '='.
    assert "$separator -gt 0" in HELPER  # Skip cmd hidden drive variables.


def test_environment_is_restored_on_success_or_failure_including_added_names():
    assert '$snapshot = [Environment]::GetEnvironmentVariables("Process")' in HELPER
    assert "if (-not $Snapshot.Contains($name))" in HELPER
    assert '[Environment]::SetEnvironmentVariable($name, $null, "Process")' in HELPER
    assert '[Environment]::SetEnvironmentVariable($name, $Snapshot[$name], "Process")' in HELPER
    assert re.search(r"finally\s*{\s*Restore-WindowsBuildEnvironment -Snapshot \$snapshot", HELPER)


def test_bootstrap_matches_action_without_requiring_project_virtualenv():
    action = (ROOT / ".github/actions/qualification-tools/action.yml").read_text()
    assert 'python-version: "3.13"' in action
    assert "astral-sh/setup-uv@" in action
    assert "Get-Command python.exe -CommandType Application" in HELPER
    assert "uv run --isolated --no-project --no-python-downloads --python $bootstrapPython python" in HELPER
    assert "uv run --no-sync" not in HELPER
    assert "uv sync" not in HELPER


def test_uv_bootstrap_uses_explicit_python_without_creating_project_venv(tmp_path):
    uv = shutil.which("uv")
    assert uv is not None, "uv is a required repository qualification tool"
    private_env = tmp_path / "must-not-be-created"
    result = subprocess.run(
        [uv, "run", "--offline", "--isolated", "--no-project", "--no-python-downloads",
         "--python", sys.executable, "python", "-c", "import sys; print(sys.base_prefix)"],
        cwd=tmp_path, env={**os.environ, "UV_PROJECT_ENVIRONMENT": str(private_env)},
        check=True, capture_output=True, text=True,
    )
    assert Path(result.stdout.strip()).resolve() == Path(sys.base_prefix).resolve()
    assert not private_env.exists()
    assert not (tmp_path / ".venv").exists()


@pytest.mark.parametrize("filename", ["build-agent-windows-x64.ps1", "build-windows-exe.ps1"])
def test_native_preflight_is_required_before_preparation_or_output_deletion(filename):
    source = (ROOT / "scripts" / filename).read_text()
    invoke = '& (Join-Path $PSScriptRoot "test-windows-build-toolchain.ps1")'
    start = source.index(invoke)
    end = source.index("Initialize-WindowsSqliteRuntime -RepoRoot")
    assert start < end < source.index("Remove-Item")
    assert end < source.index("New-Item")
    assert 'if ($LASTEXITCODE -ne 0) { throw "Windows toolchain preflight failed" }' in source[start:end]
    assert '. (Join-Path $PSScriptRoot "test-windows-build-toolchain.ps1")' not in source


def test_native_preflight_contains_parser_and_environment_behavior_checks():
    native = (ROOT / "scripts/test-windows-build-toolchain.ps1").read_text()
    assert "[System.Management.Automation.Language.Parser]::ParseFile" in native
    for filename in ("windows-build-toolchain.ps1", "build-agent-windows-x64.ps1", "build-windows-exe.ps1"):
        assert filename in native
    assert "if ($errors.Count) { throw" in native
    assert "function Assert-WindowsX64Toolchain" in native
    assert '$env:VSCMD_ARG_TGT_ARCH = "x64"' in native
    assert "if (-not $script:validated) { throw" in native
    assert "function Import-WindowsX64Toolchain" in native
    assert 'throw "mock toolchain failure"' in native
    assert 'Initialize-WindowsSqliteRuntime -RepoRoot "unused"' in native
    assert "if (-not $failed) { throw" in native
    assert 'throw "New variable leaked"' in native
    assert 'throw "Failed import leaked a variable"' in native
    assert 'throw "Failed import changed PATH"' in native
    assert re.search(r"finally\s*{\s*Restore-WindowsBuildEnvironment -Snapshot \$snapshot", native)
    assert "exit 0" in native
