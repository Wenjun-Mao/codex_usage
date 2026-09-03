param(
    [Parameter(Mandatory = $true)]
    [string]$Installer,

    [Parameter(Mandatory = $true)]
    [string]$Archive
)

$ErrorActionPreference = "Stop"

$installerPath = (Resolve-Path -LiteralPath $Installer).Path
$archivePath = [IO.Path]::GetFullPath($Archive)
$archiveDirectory = Split-Path -Parent $archivePath
New-Item -ItemType Directory -Force -Path $archiveDirectory | Out-Null
Remove-Item -LiteralPath $archivePath -Force -ErrorAction SilentlyContinue

# The Tauri v2 NSIS updater consumes a ZIP containing the setup executable.
# Repacking after Authenticode signing keeps its detached updater signature valid.
Compress-Archive -LiteralPath $installerPath -DestinationPath $archivePath -CompressionLevel Optimal

$entries = [IO.Compression.ZipFile]::OpenRead($archivePath)
try {
    if ($entries.Entries.Count -ne 1 -or $entries.Entries[0].Name -ne [IO.Path]::GetFileName($installerPath)) {
        throw "The updater archive must contain exactly the signed NSIS installer."
    }
}
finally {
    $entries.Dispose()
}

Write-Output $archivePath
