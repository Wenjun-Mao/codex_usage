$ErrorActionPreference = "Stop"

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$distDir = Join-Path $repoRoot "extensions\vscode\bin\win32-x64"
$workDir = Join-Path $repoRoot "build\pyinstaller"
$entryPoint = Join-Path $repoRoot "src\codex_usage\__main__.py"
$exePath = Join-Path $distDir "codex-usage.exe"

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
}
finally {
    Pop-Location
}
