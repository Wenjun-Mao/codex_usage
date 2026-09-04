$ErrorActionPreference = "Stop"

$extensionRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$repositoryRoot = Resolve-Path (Join-Path $extensionRoot "..\..")
$sourceBinary = Join-Path $repositoryRoot "apps\desktop\src-tauri\binaries\codex-usage-agent-x86_64-pc-windows-msvc.exe"
$targetBinary = Join-Path $extensionRoot "bin\win32-x64\codex-usage-agent.exe"

& (Join-Path $repositoryRoot "scripts\build-agent-windows-x64.ps1")
if ($LASTEXITCODE -ne 0) { throw "The Windows collector build failed." }
if (-not (Test-Path -LiteralPath $sourceBinary -PathType Leaf)) { throw "Expected packaged collector was not produced: $sourceBinary" }
Remove-Item -LiteralPath (Join-Path $extensionRoot "bin\darwin-arm64\codex-usage-agent") -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $targetBinary) | Out-Null
Copy-Item -LiteralPath $sourceBinary -Destination $targetBinary -Force
