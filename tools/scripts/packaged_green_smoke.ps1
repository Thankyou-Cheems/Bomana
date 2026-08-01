#requires -Version 7
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

# Usage: pwsh -File tools/scripts/packaged_green_smoke.ps1 <green-zip>

if ($args.Count -ne 1) {
    throw 'Expected one argument: the Lite green ZIP path.'
}

$bundlePath = (Resolve-Path -LiteralPath ([string]$args[0])).Path
$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$buildRoot = [System.IO.Path]::GetFullPath((Join-Path $repoRoot 'build'))
$smokeRoot = [System.IO.Path]::GetFullPath((Join-Path $buildRoot 'green-smoke'))
$expectedPrefix = $buildRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
if (-not $smokeRoot.StartsWith($expectedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to use smoke directory outside build/: $smokeRoot"
}

$bundleName = [System.IO.Path]::GetFileName($bundlePath)
if ($bundleName -notmatch '^Bomana_Green_Lite_v[0-9]+\.[0-9]+\.[0-9]+\.zip$') {
    throw "Unexpected green bundle name: $bundleName"
}

$checksumPath = Join-Path ([System.IO.Path]::GetDirectoryName($bundlePath)) 'checksums_green_Lite.txt'
if (-not (Test-Path -LiteralPath $checksumPath -PathType Leaf)) {
    throw "Missing green checksum file: $checksumPath"
}
$checksumText = Get-Content -LiteralPath $checksumPath -Raw -Encoding UTF8
$escapedBundleName = [regex]::Escape($bundleName)
$checksumMatch = [regex]::Match($checksumText, "(?m)^$escapedBundleName  SHA256  ([0-9a-f]{64})\r?$")
if (-not $checksumMatch.Success) {
    throw 'Green checksum entry is missing or malformed.'
}
$bundleHash = (Get-FileHash -LiteralPath $bundlePath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($bundleHash -ne $checksumMatch.Groups[1].Value) {
    throw 'Green bundle SHA-256 mismatch.'
}

if (Test-Path -LiteralPath $smokeRoot) {
    Remove-Item -LiteralPath $smokeRoot -Recurse -Force
}
New-Item -ItemType Directory -Path $smokeRoot | Out-Null
Expand-Archive -LiteralPath $bundlePath -DestinationPath $smokeRoot

$executables = @(Get-ChildItem -LiteralPath $smokeRoot -Recurse -File -Filter 'Bomana_Green_Lite_v*.exe')
if ($executables.Count -ne 1) {
    throw "Expected exactly one green executable, found $($executables.Count)."
}
$executable = $executables[0]
$bundleRoot = $executable.Directory.FullName
$internalRoot = Join-Path $bundleRoot '_internal'
$pythonRuntimes = @(Get-ChildItem -LiteralPath $internalRoot -File -Filter 'python*.dll')
if ($pythonRuntimes.Count -lt 1) {
    throw 'Bundled Python runtime is missing.'
}

$brokerPath = Join-Path $internalRoot 'bomana/bin/BomanaHotkeyBroker.exe'
$brokerChecksumPath = Join-Path $internalRoot 'bomana/bin/BomanaHotkeyBroker.sha256'
foreach ($requiredPath in @($brokerPath, $brokerChecksumPath, (Join-Path $bundleRoot 'README_GREEN.txt'))) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required green bundle file is missing: $requiredPath"
    }
}
$brokerChecksumText = Get-Content -LiteralPath $brokerChecksumPath -Raw -Encoding ASCII
$brokerChecksumMatch = [regex]::Match($brokerChecksumText, '^([0-9a-f]{64})  BomanaHotkeyBroker\.exe\s*$')
if (-not $brokerChecksumMatch.Success) {
    throw 'Native broker checksum entry is malformed.'
}
$brokerHash = (Get-FileHash -LiteralPath $brokerPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($brokerHash -ne $brokerChecksumMatch.Groups[1].Value) {
    throw 'Native broker SHA-256 mismatch.'
}

$existingBrokerIds = @(
    Get-Process -Name 'BomanaHotkeyBroker' -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Id }
)
$previousDauOptOut = $env:BOMANA_DISABLE_DAU
$appProcess = $null
try {
    $env:BOMANA_DISABLE_DAU = '1'
    $startArgs = @{
        FilePath = $executable.FullName
        WorkingDirectory = $bundleRoot
        WindowStyle = 'Hidden'
        PassThru = $true
    }
    $appProcess = Start-Process @startArgs
    Start-Sleep -Seconds 5
    $appProcess.Refresh()
    if ($appProcess.HasExited) {
        throw "Packaged green application exited during startup with code $($appProcess.ExitCode)."
    }
} finally {
    if ($null -ne $appProcess -and -not $appProcess.HasExited) {
        Stop-Process -Id $appProcess.Id -Force
        $appProcess.WaitForExit(5000) | Out-Null
    }
    Get-Process -Name 'BomanaHotkeyBroker' -ErrorAction SilentlyContinue |
        Where-Object { $_.Id -notin $existingBrokerIds } |
        Stop-Process -Force
    if ($null -eq $previousDauOptOut) {
        Remove-Item -LiteralPath 'Env:BOMANA_DISABLE_DAU' -ErrorAction SilentlyContinue
    } else {
        $env:BOMANA_DISABLE_DAU = $previousDauOptOut
    }
}

[ordered]@{
    bundle = $bundleName
    bundle_sha256 = $bundleHash
    executable = $executable.Name
    python_runtime = $pythonRuntimes[0].Name
    native_broker_sha256 = $brokerHash
    startup_seconds = 5
    startup_blocked = $false
} | ConvertTo-Json -Depth 6 -Compress
