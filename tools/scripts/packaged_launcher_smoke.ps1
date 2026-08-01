#requires -Version 7
Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true

# Usage: pwsh -File tools/scripts/packaged_launcher_smoke.ps1 [Standard|Lite] [artifact-dir]
# When artifact-dir is omitted, this script builds both the selected public App
# and the universal Launcher before inspecting the release closure.

function Read-Literal {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Name
    )
    $source = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
    $pattern = [regex]::Escape($Name) + '\s*=\s*["'']([^"'']+)["'']'
    $match = [regex]::Match($source, $pattern)
    if (-not $match.Success) {
        throw "Unable to read $Name from $Path"
    }
    return $match.Groups[1].Value.Trim()
}

function Assert-FileSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Expected
    )
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actual -ne $Expected.Trim().ToLowerInvariant()) {
        throw "SHA-256 mismatch: $Path"
    }
    return $actual
}

function Assert-SignedManifest {
    param(
        [Parameter(Mandatory = $true)][object]$Manifest,
        [Parameter(Mandatory = $true)][string]$Label
    )
    if ($null -eq $Manifest.manifest_signature) {
        throw "$Label missing manifest_signature"
    }
    if ([string]$Manifest.manifest_signature.algorithm -ne 'ed25519') {
        throw "$Label manifest signature algorithm is not ed25519"
    }
    if ([string]::IsNullOrWhiteSpace([string]$Manifest.manifest_signature.key_id)) {
        throw "$Label manifest signature key_id is empty"
    }
    if ([string]::IsNullOrWhiteSpace([string]$Manifest.manifest_signature.signature)) {
        throw "$Label manifest signature is empty"
    }
}

$variant = if ($args.Count -ge 1) { [string]$args[0] } else { 'Standard' }
if ($variant -notin @('Standard', 'Lite')) {
    throw "Public smoke accepts only Standard or Lite, got: $variant"
}

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../..')).Path
$artifactDir = if ($args.Count -ge 2) {
    (Resolve-Path -LiteralPath ([string]$args[1])).Path
} else {
    Join-Path $repoRoot 'dist'
}

$env:PYTHONPATH = ''
$env:PYTHONHOME = ''
$env:PYTHONNOUSERSITE = '1'

if ($args.Count -lt 2) {
    $syncArgs = @('sync', '--extra', 'build', '--frozen')
    & uv @syncArgs
    if ($LASTEXITCODE -ne 0) {
        throw "uv sync failed with exit code $LASTEXITCODE"
    }
    $buildArgs = @(
        'run', '--frozen', 'python', 'tools/build_portable.py',
        '--variant', $variant, '--target', 'all'
    )
    & uv @buildArgs
    if ($LASTEXITCODE -ne 0) {
        throw "public package build failed with exit code $LASTEXITCODE"
    }
}

$appVersion = Read-Literal -Path (Join-Path $repoRoot 'bomana/metadata.py') -Name '__version__'
$launcherVersion = Read-Literal -Path (Join-Path $repoRoot 'launcher/metadata.py') -Name 'LAUNCHER_VERSION'
$appManifestPath = Join-Path $artifactDir "manifest_$variant.json"
$launcherManifestPath = Join-Path $artifactDir 'launcher_manifest.json'
$appPath = Join-Path $artifactDir "Bomana_app_${variant}_v${appVersion}.zip"
$launcherPath = Join-Path $artifactDir "Bomana_launcher_v${launcherVersion}.exe"

foreach ($path in @($appManifestPath, $launcherManifestPath, $appPath, $launcherPath)) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        throw "Required public artifact is missing: $path"
    }
}

$appManifest = Get-Content -LiteralPath $appManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
$launcherManifest = Get-Content -LiteralPath $launcherManifestPath -Raw -Encoding UTF8 | ConvertFrom-Json
Assert-SignedManifest -Manifest $appManifest -Label "manifest_$variant.json"
Assert-SignedManifest -Manifest $launcherManifest -Label 'launcher_manifest.json'

if ([string]$appManifest.channel -ne $variant) {
    throw "App manifest channel mismatch"
}
if ([string]$appManifest.app_version -ne $appVersion) {
    throw "App manifest version mismatch"
}
if ([string]$launcherManifest.launcher_version -ne $launcherVersion) {
    throw "Launcher manifest version mismatch"
}

$appHash = Assert-FileSha256 -Path $appPath -Expected ([string]$appManifest.package_sha256)
$launcherHash = Assert-FileSha256 -Path $launcherPath -Expected ([string]$launcherManifest.launcher_sha256)

Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive = [System.IO.Compression.ZipFile]::OpenRead($appPath)
try {
    $entryNames = @($archive.Entries | ForEach-Object { $_.FullName.Replace('\', '/') })
    foreach ($required in @(
        'Bomana.pyw',
        'bomana_version.py',
        'bomana/config/feature_profile.py',
        'bomana/bin/BomanaHotkeyBroker.exe',
        'bomana/bin/BomanaHotkeyBroker.sha256'
    )) {
        if ($required -notin $entryNames) {
            throw "Public App archive is missing: $required"
        }
    }

    $subscriberPrefixes = @(
        'bomana/web/',
        'bomana/assets/web/',
        'bomana/core/ballistics.py',
        'bomana/core/offline_rigidbody_',
        'bomana/core/terrain_elevation.py',
        'bomana/core/weapon_',
        'bomana/ui/bombing_',
        'bomana/data/weapon_fire_control.json',
        'bomana/data/visible_trajectory_references.json'
    )
    foreach ($entryName in $entryNames) {
        foreach ($prefix in $subscriberPrefixes) {
            if ($entryName.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) {
                throw "Subscriber path entered public App archive: $entryName"
            }
        }
    }
} finally {
    $archive.Dispose()
}

[ordered]@{
    variant = $variant
    app_version = $appVersion
    launcher_version = $launcherVersion
    app_sha256 = $appHash
    launcher_sha256 = $launcherHash
    subscriber_paths_present = $false
} | ConvertTo-Json -Depth 6 -Compress
