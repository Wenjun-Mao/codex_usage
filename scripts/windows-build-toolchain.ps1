# Shared by native package entrypoints, including npm invoked from a bash runner.
# VS discovery follows https://github.com/microsoft/vswhere/wiki/Find-VC.
# No installation, registry changes, or persistent environment changes are made.
# Portable source tests cannot qualify cmd/VsDevCmd or MSVC execution; the existing
# Windows package job must still exercise discovery, compilation and freezing.

function Restore-WindowsBuildEnvironment {
    param([System.Collections.IDictionary] $Snapshot)
    foreach ($name in [Environment]::GetEnvironmentVariables("Process").Keys) {
        if (-not $Snapshot.Contains($name)) {
            [Environment]::SetEnvironmentVariable($name, $null, "Process")
        }
    }
    foreach ($name in $Snapshot.Keys) {
        [Environment]::SetEnvironmentVariable($name, $Snapshot[$name], "Process")
    }
}

function Assert-WindowsX64Toolchain {
    if ($env:VSCMD_ARG_TGT_ARCH -ne "x64" -or $env:VisualStudioVersion -notlike "17.*") {
        throw "A VS 2022 x64 target developer environment is required."
    }
    if (-not $env:VCToolsInstallDir -or -not $env:WindowsSdkDir -or -not $env:WindowsSDKVersion) {
        throw "The MSVC environment is missing VC tools or Windows SDK locations."
    }
    $hostArch = $env:VSCMD_ARG_HOST_ARCH
    if ($hostArch -notin @("x64", "x86")) {
        throw "Unsupported MSVC host architecture: $hostArch"
    }
    $toolDir = Join-Path $env:VCToolsInstallDir "bin\Host$hostArch\x64"
    foreach ($name in @("cl.exe", "link.exe", "dumpbin.exe")) {
        $expected = Join-Path $toolDir $name
        $actual = Get-Command $name -CommandType Application -ErrorAction Stop | Select-Object -First 1
        if (-not (Test-Path -LiteralPath $expected -PathType Leaf) -or
            [IO.Path]::GetFullPath($actual.Source) -ne [IO.Path]::GetFullPath($expected)) {
            throw "PATH must select the installed VS 2022 x64 tool: $expected"
        }
    }
    $sdkVersion = $env:WindowsSDKVersion.TrimEnd([char[]]'\/')
    $headers = @(
        (Join-Path $env:VCToolsInstallDir "include\vcruntime.h"),
        (Join-Path $env:WindowsSdkDir "Include\$sdkVersion\um\Windows.h"),
        (Join-Path $env:WindowsSdkDir "Include\$sdkVersion\shared\sdkddkver.h"),
        (Join-Path $env:WindowsSdkDir "Include\$sdkVersion\ucrt\stdio.h")
    )
    $libraries = @(
        (Join-Path $env:VCToolsInstallDir "lib\x64\vcruntime.lib"),
        (Join-Path $env:WindowsSdkDir "Lib\$sdkVersion\um\x64\kernel32.lib"),
        (Join-Path $env:WindowsSdkDir "Lib\$sdkVersion\ucrt\x64\ucrt.lib")
    )
    foreach ($group in @(
        @{ Files = $headers; SearchPath = $env:INCLUDE; Name = "INCLUDE" },
        @{ Files = $libraries; SearchPath = $env:LIB; Name = "LIB" }
    )) {
        $search = @($group.SearchPath -split ";" | ForEach-Object { $_.Trim('"').TrimEnd('\') })
        foreach ($file in $group.Files) {
            if (-not (Test-Path -LiteralPath $file -PathType Leaf) -or
                $search -notcontains (Split-Path -Parent $file).TrimEnd('\')) {
                throw "Incomplete VS 2022 C++/Windows SDK $($group.Name): $file"
            }
        }
    }
}

function Import-WindowsX64Toolchain {
    # An explicitly selected developer environment is authoritative. Never mix
    # installations or silently replace an invalid supplied target/toolset.
    if ($env:VSCMD_VER -or $env:VSCMD_ARG_TGT_ARCH) {
        Assert-WindowsX64Toolchain
        return
    }
    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
        throw "VS 2022 C++ x64 tools/Windows SDK required: installed vswhere.exe not found."
    }
    $installation = & $vswhere -latest -products '*' -version '[17.0,18.0)' `
        -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
    if ($LASTEXITCODE -ne 0 -or -not $installation) {
        throw "No supported installed VS 2022 C++ x64 toolchain was found."
    }
    $installPath = ([string]$installation).Trim()
    $devcmd = Join-Path $installPath "Common7\Tools\VsDevCmd.bat"
    if (-not (Test-Path -LiteralPath $devcmd -PathType Leaf) -or $devcmd -match '["\r\n]') {
        throw "Invalid installed VS 2022 VsDevCmd.bat path."
    }
    # Pass the discovered path as a child-only environment value, not executable
    # command text. /d disables cmd AutoRun; /u gives set output a known encoding.
    $start = New-Object System.Diagnostics.ProcessStartInfo
    $start.FileName = Join-Path $env:SystemRoot "System32\cmd.exe"
    $start.Arguments = '/d /u /s /c "call "%CODEX_USAGE_VSDEVCMD%" -no_logo -arch=x64 -host_arch=x64 >nul && set"'
    $start.UseShellExecute = $false
    $start.CreateNoWindow = $true
    $start.RedirectStandardOutput = $true
    $start.RedirectStandardError = $true
    $start.StandardOutputEncoding = [Text.Encoding]::Unicode
    $start.StandardErrorEncoding = [Text.Encoding]::Unicode
    $start.EnvironmentVariables["CODEX_USAGE_VSDEVCMD"] = $devcmd
    $process = New-Object System.Diagnostics.Process
    $process.StartInfo = $start
    try {
        $null = $process.Start()
        $stdout = $process.StandardOutput.ReadToEndAsync()
        $stderr = $process.StandardError.ReadToEndAsync()
        $process.WaitForExit()
        if ($process.ExitCode -ne 0) {
            throw "VS 2022 VsDevCmd failed ($($process.ExitCode)): $($stderr.Result)"
        }
        foreach ($line in $stdout.Result -split '\r?\n') {
            $separator = $line.IndexOf('=')
            # Ignore cmd's hidden drive-current-directory variables (=C:=...).
            if ($separator -gt 0) {
                $name = $line.Substring(0, $separator)
                if ($name -ne "CODEX_USAGE_VSDEVCMD") {
                    [Environment]::SetEnvironmentVariable($name, $line.Substring($separator + 1), "Process")
                }
            }
        }
    }
    finally {
        $process.Dispose()
    }
    Assert-WindowsX64Toolchain
}

function Initialize-WindowsSqliteRuntime {
    param([Parameter(Mandatory = $true)] [string] $RepoRoot)
    $snapshot = [Environment]::GetEnvironmentVariables("Process")
    try {
        Import-WindowsX64Toolchain
        # qualification-tools installs Python 3.13 and uv, not a project .venv.
        # Select that installed Python explicitly; do not bootstrap via --no-sync.
        $bootstrapPython = (Get-Command python.exe -CommandType Application -ErrorAction Stop |
            Select-Object -First 1).Source
        uv run --isolated --no-project --no-python-downloads --python $bootstrapPython python `
            (Join-Path $RepoRoot "scripts\build_sqlite_runtime_windows.py")
        if ($LASTEXITCODE -ne 0) { throw "Windows SQLite runtime preparation failed" }
    }
    finally {
        Restore-WindowsBuildEnvironment -Snapshot $snapshot
    }
}
