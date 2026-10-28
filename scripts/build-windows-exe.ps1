using namespace System.Runtime.InteropServices

$ErrorActionPreference = "Stop"

if (
    -not [RuntimeInformation]::IsOSPlatform([OSPlatform]::Windows) -or
    [RuntimeInformation]::ProcessArchitecture -ne [Architecture]::X64
) {
    throw "This script requires Windows Architecture.X64 from RuntimeInformation.ProcessArchitecture."
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
. (Join-Path $PSScriptRoot "windows-build-toolchain.ps1")
$distDir = Join-Path $repoRoot "extensions\vscode\bin\win32-x64"
$workDir = Join-Path $repoRoot "build\pyinstaller"
$entryPoint = Join-Path $repoRoot "src\codex_usage\__main__.py"
$exePath = Join-Path $distDir "codex-usage.exe"
$processTreeSmokeScript = Join-Path $repoRoot "scripts\packaged_windows_process_tree_smoke.py"
$parallelSmokeScript = Join-Path $repoRoot "scripts\packaged_parallel_cache_smoke.py"
$reportSmokeScript = Join-Path $repoRoot "scripts\packaged_report_smoke.py"
$storageAnalysisSmokeScript = Join-Path $repoRoot "scripts\packaged_storage_analysis_smoke.py"
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
    New-Item -ItemType Directory -Force -Path $distDir | Out-Null
    New-Item -ItemType Directory -Force -Path $workDir | Out-Null
    Remove-Item -LiteralPath $exePath -Force -ErrorAction SilentlyContinue
    uv run --no-sync pyinstaller `
        --noconfirm `
        --clean `
        --onefile `
        --console `
        --name codex-usage `
        --paths src `
        --distpath $distDir `
        --workpath $workDir `
        --specpath $workDir `
        $entryPoint

    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller exited with code $LASTEXITCODE"
    }
    if (-not (Test-Path -LiteralPath $exePath)) {
        throw "Expected executable was not created: $exePath"
    }

    & $exePath --help | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged executable --help exited with code $LASTEXITCODE"
    }

    uv run --no-sync python $processTreeSmokeScript --executable $exePath
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged Windows process-tree smoke test exited with code $LASTEXITCODE"
    }

    uv run --no-sync python $parallelSmokeScript --executable $exePath --expected-target win32-x64
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged parallel cache smoke test exited with code $LASTEXITCODE"
    }

    uv run --no-sync python $reportSmokeScript --executable $exePath
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged report smoke test exited with code $LASTEXITCODE"
    }

    uv run --no-sync python $storageAnalysisSmokeScript --executable $exePath
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged Task Storage analysis smoke test exited with code $LASTEXITCODE"
    }

}
finally {
    $env:UV_PROJECT_ENVIRONMENT = $previousProjectEnvironment
    Pop-Location
}
