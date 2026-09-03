using namespace System.Runtime.InteropServices

$ErrorActionPreference = "Stop"

if (
    -not [RuntimeInformation]::IsOSPlatform([OSPlatform]::Windows) -or
    [RuntimeInformation]::ProcessArchitecture -ne [Architecture]::X64
) {
    throw "This script requires Windows x64."
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$targetTriple = "x86_64-pc-windows-msvc"
$binaryName = "codex-usage-agent-$targetTriple"
$distDir = Join-Path $repoRoot "apps\desktop\src-tauri\binaries"
$workDir = Join-Path $repoRoot "build\pyinstaller-agent-$targetTriple"
$entryPoint = Join-Path $repoRoot "src\codex_usage\agent_main.py"
$binaryPath = Join-Path $distDir "$binaryName.exe"

New-Item -ItemType Directory -Force -Path $distDir, $workDir | Out-Null
Remove-Item -LiteralPath $binaryPath -Force -ErrorAction SilentlyContinue

Push-Location $repoRoot
try {
    uv run --group package pyinstaller `
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
    uv run python scripts/smoke-test-packaged-agent.py --executable $binaryPath
    if ($LASTEXITCODE -ne 0) { throw "Packaged agent smoke failed" }
}
finally {
    Pop-Location
}
