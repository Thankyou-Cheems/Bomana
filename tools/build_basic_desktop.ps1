[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9]+\.[0-9]+\.[0-9]+(?:-[A-Za-z0-9.-]+)?$')]
    [string]$Version,
    [string]$OutputDir,
    [switch]$AllowDirty
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$root = Split-Path -Parent $PSScriptRoot
if (-not $IsWindows) { throw 'Basic Desktop packages must be built and checked on Windows.' }

function Invoke-Checked([string]$Command, [string[]]$Arguments) {
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Command failed with exit code $LASTEXITCODE" }
}

Push-Location $root
$previous = @{}
foreach ($name in @('CGO_ENABLED', 'GOOS', 'GOARCH')) { $previous[$name] = [Environment]::GetEnvironmentVariable($name, 'Process') }
try {
    $source = (Invoke-Checked git @('rev-parse', 'HEAD')).Trim()
    $dirty = @(Invoke-Checked git @('status', '--porcelain'))
    if ($dirty.Count -gt 0 -and -not $AllowDirty) { throw 'Build from a clean committed checkout; use -AllowDirty only for a development candidate.' }
    if (-not $OutputDir) { $OutputDir = Join-Path $root "dist/basic-desktop/$Version" }
    $OutputDir = [IO.Path]::GetFullPath($OutputDir)
    $exe = Join-Path $OutputDir 'BomanaBasic.exe'
    if ((Test-Path -LiteralPath $exe) -and -not $AllowDirty) { throw "Release artifact already exists: $exe" }
    New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
    $env:CGO_ENABLED = '0'
    $env:GOOS = 'windows'
    $env:GOARCH = 'amd64'
    Push-Location (Join-Path $root 'native/telemetry_gateway')
    try {
        Invoke-Checked go @('test', './cmd/bomana_basic', '-count=1')
        Invoke-Checked go @('vet', './cmd/bomana_basic')
        $nonStandard = @(Invoke-Checked go @('list', '-deps', '-f', '{{if not .Standard}}{{.ImportPath}}{{end}}', './cmd/bomana_basic') | Where-Object { $_ })
        $allowed = @('bomana/native/telemetry_gateway/internal/extui', 'bomana/native/telemetry_gateway/cmd/bomana_basic')
        foreach ($dependency in $nonStandard) { if ($dependency -notin $allowed) { throw "Unexpected linked dependency: $dependency" } }
        $dependencies = @(Invoke-Checked go @('list', '-deps', './cmd/bomana_basic'))
        foreach ($dependency in @('net/http', 'crypto/tls')) {
            if ($dependency -in $dependencies) { throw "Basic Desktop must use system HTTP instead of linking $dependency" }
        }
        $builtAt = [DateTimeOffset]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ')
        $flags = "-H=windowsgui -s -w -X main.version=$Version -X main.sourceCommit=$source -X main.builtAt=$builtAt"
        Invoke-Checked go @('build', '-trimpath', '-ldflags', $flags, '-o', $exe, './cmd/bomana_basic')
        $toolchain = (Invoke-Checked go @('version')).Trim()
    }
    finally { Pop-Location }
    & (Join-Path $PSScriptRoot 'assert_windows_gui_subsystem.ps1') -Path $exe | Out-Null
    & (Join-Path $PSScriptRoot 'assert_windows_application_icon.ps1') -Path $exe -IconPath (Join-Path $root 'native/telemetry_gateway/cmd/bomana_basic/app.ico') | Out-Null

    # Run the actual GUI executable from a directory containing only that EXE.
    # Its package check creates, paints and closes its own native window; it
    # never starts sampling, opens a browser or writes user settings.
    $isolated = Join-Path ([IO.Path]::GetTempPath()) ('bomana-basic-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $isolated | Out-Null
    try {
        $isolatedExe = Join-Path $isolated 'BomanaBasic.exe'
        Copy-Item -LiteralPath $exe -Destination $isolatedExe
        foreach ($mode in @('--build-info', '--check-package')) {
            $start = [Diagnostics.ProcessStartInfo]::new($isolatedExe)
            $start.WorkingDirectory = $isolated
            $start.UseShellExecute = $false
            $start.CreateNoWindow = $true
            $start.WindowStyle = [Diagnostics.ProcessWindowStyle]::Hidden
            $start.RedirectStandardOutput = $true
            $start.RedirectStandardError = $true
            $start.ArgumentList.Add($mode)
            $process = [Diagnostics.Process]::Start($start)
            try {
                if (-not $process.WaitForExit(15000)) { $process.Kill(); throw "Native package check timed out: $mode" }
                $stdout = $process.StandardOutput.ReadToEnd()
                $stderr = $process.StandardError.ReadToEnd()
                if ($process.ExitCode -ne 0) { throw "Native package check failed: $stderr $stdout" }
                $fact = $stdout | ConvertFrom-Json
                if ($fact.surface -ne 'basic-desktop' -or $fact.version -ne $Version) { throw 'Packaged identity mismatch.' }
                if ($mode -eq '--build-info' -and $fact.source -ne $source) { throw 'Packaged source mismatch.' }
                if ($mode -eq '--check-package' -and -not $fact.nativeWindow) { throw 'Native window failed to initialize.' }
            }
            finally { $process.Dispose() }
        }
        if (@(Get-ChildItem -LiteralPath $isolated).Count -ne 1) { throw 'The package extracted companion files.' }
    }
    finally {
        $resolved = [IO.Path]::GetFullPath($isolated)
        $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath())
        if (-not $resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -or (Split-Path -Leaf $resolved) -notlike 'bomana-basic-*') { throw 'Unexpected package-check cleanup path.' }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
    $bytes = (Get-Item -LiteralPath $exe).Length
    $info = [ordered]@{
        surface = 'basic-desktop'; version = $Version; source = $source
        dirty = ($dirty.Count -gt 0); builtAt = $builtAt; toolchain = $toolchain
        artifact = 'BomanaBasic.exe'; bytes = $bytes
        sha256 = (Get-FileHash -LiteralPath $exe -Algorithm SHA256).Hash.ToLowerInvariant()
        linkedProjectPackages = $nonStandard; httpTransport = 'windows-winhttp'; packageCheck = 'passed'
    }
    [IO.File]::WriteAllText((Join-Path $OutputDir 'build-info.json'), ($info | ConvertTo-Json -Depth 4) + "`n", [Text.UTF8Encoding]::new($false))
    Write-Output ("Built {0}: {1} bytes ({2:N2} MiB). Distribute the EXE alone." -f $exe, $bytes, ($bytes / 1MB))
}
finally {
    foreach ($name in $previous.Keys) { [Environment]::SetEnvironmentVariable($name, $previous[$name], 'Process') }
    Pop-Location
}
