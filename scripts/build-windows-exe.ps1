using namespace System.Runtime.InteropServices

$ErrorActionPreference = "Stop"

if (
    -not [RuntimeInformation]::IsOSPlatform([OSPlatform]::Windows) -or
    [RuntimeInformation]::ProcessArchitecture -ne [Architecture]::X64
) {
    throw "This script requires Windows Architecture.X64 from RuntimeInformation.ProcessArchitecture."
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$distDir = Join-Path $repoRoot "extensions\vscode\bin\win32-x64"
$workDir = Join-Path $repoRoot "build\pyinstaller"
$entryPoint = Join-Path $repoRoot "src\codex_usage\__main__.py"
$exePath = Join-Path $distDir "codex-usage.exe"
$processTreeSmokeScript = Join-Path $repoRoot "scripts\packaged_windows_process_tree_smoke.py"
$parallelSmokeScript = Join-Path $repoRoot "scripts\packaged_parallel_cache_smoke.py"
$reportSmokeScript = Join-Path $repoRoot "scripts\packaged_report_smoke.py"
$smokeScript = Join-Path $repoRoot "scripts\smoke-test-packaged-sync.py"

New-Item -ItemType Directory -Force -Path $distDir | Out-Null
New-Item -ItemType Directory -Force -Path $workDir | Out-Null
Remove-Item -LiteralPath $exePath -Force -ErrorAction SilentlyContinue

Push-Location $repoRoot
try {
    uv run --group package pyinstaller `
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

    uv run python $processTreeSmokeScript --executable $exePath
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged Windows process-tree smoke test exited with code $LASTEXITCODE"
    }

    uv run python $parallelSmokeScript --executable $exePath --expected-target win32-x64
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged parallel cache smoke test exited with code $LASTEXITCODE"
    }

    uv run python $reportSmokeScript --executable $exePath
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged report smoke test exited with code $LASTEXITCODE"
    }

    uv run python $smokeScript --executable $exePath
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged Task Transfer smoke test exited with code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
