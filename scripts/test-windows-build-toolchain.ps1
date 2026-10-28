# Required native package preflight. Parses the real scripts and exercises
# environment policy with mocks; it does not compile or require installed MSVC.
# Windows execution is separate from portable pytest/source-contract coverage.
$ErrorActionPreference = "Stop"

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    throw "This toolchain preflight requires native Windows PowerShell."
}

$files = @(
    (Join-Path $PSScriptRoot "windows-build-toolchain.ps1"),
    (Join-Path $PSScriptRoot "build-agent-windows-x64.ps1"),
    (Join-Path $PSScriptRoot "build-windows-exe.ps1"),
    $PSCommandPath
)
foreach ($file in $files) {
    $tokens = $null
    $errors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile($file, [ref]$tokens, [ref]$errors)
    if ($errors.Count) { throw ($errors | Out-String) }
}

# Invoke with &, never dot-source this test: mock functions belong to this
# script scope and must not replace the calling package script's real helper.
$helper = $files[0]
. $helper
foreach ($version in @("17.0", "18.0", "19.0")) {
    if (-not (Test-WindowsToolchainVersion -Version $version)) { throw "Rejected supported MSVC version" }
}
foreach ($version in @("", "16.0", "invalid")) {
    if (Test-WindowsToolchainVersion -Version $version) { throw "Accepted invalid MSVC version" }
}
$newName = "CODEX_TEST_" + [Guid]::NewGuid().ToString("N")
$snapshot = [Environment]::GetEnvironmentVariables("Process")
try {
    try {
        [Environment]::SetEnvironmentVariable($newName, "new=value", "Process")
        [Environment]::SetEnvironmentVariable("PATH", "changed", "Process")
    }
    finally { Restore-WindowsBuildEnvironment -Snapshot $snapshot }
    if ([Environment]::GetEnvironmentVariable($newName, "Process")) { throw "New variable leaked" }
    if ($env:PATH -cne $snapshot["PATH"]) { throw "PATH changed" }

    # An explicitly supplied x64 environment must validate and bypass discovery.
    function Assert-WindowsX64Toolchain { $script:validated = $true }
    $script:validated = $false
    try {
        $env:VSCMD_ARG_TGT_ARCH = "x64"
        Import-WindowsX64Toolchain
        if (-not $script:validated) { throw "Explicit developer environment was not validated" }
    }
    finally { Restore-WindowsBuildEnvironment -Snapshot $snapshot }

    # Initialization must restore partial process changes even on failed import.
    function Import-WindowsX64Toolchain {
        [Environment]::SetEnvironmentVariable($newName, "partial", "Process")
        $env:PATH = "changed"
        throw "mock toolchain failure"
    }
    $failed = $false
    try { Initialize-WindowsSqliteRuntime -RepoRoot "unused" }
    catch { $failed = $_.Exception.Message -eq "mock toolchain failure" }
    if (-not $failed) { throw "Expected mock initialization failure" }
    if ([Environment]::GetEnvironmentVariable($newName, "Process")) { throw "Failed import leaked a variable" }
    if ($env:PATH -cne $snapshot["PATH"]) { throw "Failed import changed PATH" }
}
finally {
    Restore-WindowsBuildEnvironment -Snapshot $snapshot
}
Write-Output "Windows toolchain parser/environment preflight passed."
exit 0
