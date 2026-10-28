using namespace System.Runtime.InteropServices

$ErrorActionPreference = "Stop"

if (
    -not [RuntimeInformation]::IsOSPlatform([OSPlatform]::Windows) -or
    [RuntimeInformation]::ProcessArchitecture -ne [Architecture]::X64
) {
    throw "This script requires Windows x64."
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
. (Join-Path $PSScriptRoot "windows-build-toolchain.ps1")
$targetTriple = "x86_64-pc-windows-msvc"
$binaryName = "codex-usage-agent-$targetTriple"
$distDir = Join-Path $repoRoot "build\packaged-agent\$targetTriple"
$workDir = Join-Path $repoRoot "build\pyinstaller-agent-$targetTriple"
$entryPoint = Join-Path $repoRoot "src\codex_usage\agent_main.py"
$binaryPath = Join-Path $distDir "$binaryName.exe"
$runtimePython = Join-Path $repoRoot "build\sqlite-runtime-windows-x64\install\python.exe"
$previousProjectEnvironment = $env:UV_PROJECT_ENVIRONMENT

Push-Location $repoRoot
try {
    & (Join-Path $PSScriptRoot "test-windows-build-toolchain.ps1")
    if ($LASTEXITCODE -ne 0) { throw "Windows toolchain preflight failed" }
    Initialize-WindowsSqliteRuntime -RepoRoot $repoRoot
    $env:UV_PROJECT_ENVIRONMENT = Join-Path $repoRoot "build\package-venv-windows-x64"
    uv sync --locked --python $runtimePython --group package
    if ($LASTEXITCODE -ne 0) { throw "Private package environment preparation failed" }
    uv run --no-sync python scripts/build_sqlite_runtime_windows.py `
        --check-python (Join-Path $env:UV_PROJECT_ENVIRONMENT "Scripts\python.exe")
    if ($LASTEXITCODE -ne 0) { throw "Private package interpreter qualification failed" }
    uv run --no-sync python scripts/check_sqlite_runtime.py
    if ($LASTEXITCODE -ne 0) { throw "SQLite runtime qualification failed" }
    New-Item -ItemType Directory -Force -Path $distDir, $workDir | Out-Null
    Remove-Item -LiteralPath $binaryPath -Force -ErrorAction SilentlyContinue
    uv run --no-sync pyinstaller `
        --noconfirm `
        --clean `
        --onefile `
        --console `
        --name $binaryName `
        --paths src `
        --distpath $distDir `
        --workpath $workDir `
        --specpath $workDir `
        $entryPoint
    if ($LASTEXITCODE -ne 0) { throw "PyInstaller exited with code $LASTEXITCODE" }
    & $binaryPath --help | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Packaged agent help failed" }
    uv run --no-sync python scripts/verify_packaged_sqlite.py --executable $binaryPath `
        --output output/qualification/package-win32-x64/sqlite-runtime.json
    if ($LASTEXITCODE -ne 0) { throw "Packaged SQLite runtime qualification failed" }
    uv run --no-sync python scripts/smoke-test-packaged-agent.py --executable $binaryPath `
        --parallel-evidence output/qualification/package-win32-x64/collector-parallel.json `
        --wal-evidence output/qualification/package-win32-x64/sqlite-maintenance.json
    if ($LASTEXITCODE -ne 0) { throw "Packaged agent smoke failed" }
}
finally {
    $env:UV_PROJECT_ENVIRONMENT = $previousProjectEnvironment
    Pop-Location
}
