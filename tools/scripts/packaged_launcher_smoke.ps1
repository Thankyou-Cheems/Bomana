<#
.SYNOPSIS
Builds or reuses release assets, stages them under a hostile Windows path, and
smokes the packaged launcher-to-app handoff.

.DESCRIPTION
The default path builds signed launcher + app assets with tools/build_portable.py,
copies the packaged launcher and app zip to a temporary directory containing
spaces and Chinese characters, installs the app zip into the frozen-launcher
layout, poisons Python-related environment variables and PATH for the launched
process, then automates the launch button and waits for the packaged app window.

This is an interactive Windows desktop smoke. Use -SkipGuiHandoff only when a
runner can validate packaging layout but cannot interact with GUI windows.
#>
[CmdletBinding()]
param(
    [ValidateSet("Enhanced", "Standard", "Lite")]
    [string]$Variant = "Enhanced",

    [string]$ArtifactDir = "",

    [string]$SmokeRoot = "",

    [switch]$NoBuild,

    [switch]$SkipGuiHandoff,

    [switch]$KeepWorkDir,

    [ValidateRange(10, 600)]
    [int]$LaunchTimeoutSec = 90
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = "Stop"

function Assert-Windows {
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw "packaged launcher smoke requires Windows"
    }
}

function Resolve-FullPath {
    param([Parameter(Mandatory = $true)][string]$Path)
    return [System.IO.Path]::GetFullPath($Path)
}

function Assert-PathWithin {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Root
    )

    $fullPath = Resolve-FullPath $Path
    $fullRoot = Resolve-FullPath $Root
    $rootWithSeparator = $fullRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) +
        [System.IO.Path]::DirectorySeparatorChar
    if (
        -not $fullPath.Equals($fullRoot, [StringComparison]::OrdinalIgnoreCase) -and
        -not $fullPath.StartsWith($rootWithSeparator, [StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "refusing to operate outside expected root: $fullPath (root: $fullRoot)"
    }
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    Push-Location -LiteralPath $WorkingDirectory
    try {
        & $FilePath @ArgumentList
        if ($LASTEXITCODE -ne 0) {
            throw "$FilePath failed with exit code $LASTEXITCODE"
        }
    }
    finally {
        Pop-Location
    }
}

function Get-JsonProperty {
    param(
        [Parameter(Mandatory = $true)]$Object,
        [Parameter(Mandatory = $true)][string]$Name
    )

    $property = $Object.PSObject.Properties[$Name]
    if ($null -eq $property) {
        return $null
    }
    return $property.Value
}

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "missing JSON file: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Assert-ManifestSignature {
    param(
        [Parameter(Mandatory = $true)]$Manifest,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $signature = Get-JsonProperty $Manifest "manifest_signature"
    if ($null -eq $signature) {
        throw "$Label is missing manifest_signature"
    }
    if ([string](Get-JsonProperty $signature "algorithm") -ne "ed25519") {
        throw "$Label manifest_signature.algorithm must be ed25519"
    }
    if ([string]::IsNullOrWhiteSpace([string](Get-JsonProperty $signature "key_id"))) {
        throw "$Label manifest_signature.key_id must not be empty"
    }
    if ([string]::IsNullOrWhiteSpace([string](Get-JsonProperty $signature "signature"))) {
        throw "$Label manifest_signature.signature must not be empty"
    }
}

function Assert-FileSha256 {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Expected,
        [Parameter(Mandatory = $true)][string]$Label
    )

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        throw "$Label missing: $Path"
    }
    $actual = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    $expectedLower = $Expected.Trim().ToLowerInvariant()
    if ($actual -ne $expectedLower) {
        throw "$Label SHA256 mismatch: expected $expectedLower, got $actual"
    }
}

function Resolve-ReleaseArtifacts {
    param(
        [Parameter(Mandatory = $true)][string]$Directory,
        [Parameter(Mandatory = $true)][string]$VariantName
    )

    $artifactRoot = Resolve-FullPath $Directory
    $appManifestPath = Join-Path $artifactRoot "manifest_$VariantName.json"
    $launcherManifestPath = Join-Path $artifactRoot "launcher_manifest.json"
    $appManifest = Read-JsonFile $appManifestPath
    $launcherManifest = Read-JsonFile $launcherManifestPath

    Assert-ManifestSignature $appManifest "manifest_$VariantName.json"
    Assert-ManifestSignature $launcherManifest "launcher_manifest.json"

    $appAsset = [string](Get-JsonProperty $appManifest "package_asset")
    $launcherAsset = [string](Get-JsonProperty $launcherManifest "launcher_asset")
    if ([string]::IsNullOrWhiteSpace($appAsset)) {
        throw "manifest_$VariantName.json package_asset is empty"
    }
    if ([string]::IsNullOrWhiteSpace($launcherAsset)) {
        throw "launcher_manifest.json launcher_asset is empty"
    }

    $appPackage = Join-Path $artifactRoot $appAsset
    $launcherExe = Join-Path $artifactRoot $launcherAsset
    Assert-FileSha256 $appPackage ([string](Get-JsonProperty $appManifest "package_sha256")) $appAsset
    Assert-FileSha256 $launcherExe ([string](Get-JsonProperty $launcherManifest "launcher_sha256")) $launcherAsset

    $expectedLauncherSize = [int64](Get-JsonProperty $launcherManifest "launcher_size_bytes")
    $actualLauncherSize = (Get-Item -LiteralPath $launcherExe).Length
    if ($expectedLauncherSize -ne $actualLauncherSize) {
        throw "$launcherAsset size mismatch: expected $expectedLauncherSize, got $actualLauncherSize"
    }

    $entrypoint = [string](Get-JsonProperty $appManifest "entrypoint")
    if ($entrypoint -ne "Bomana.pyw") {
        throw "unsupported app entrypoint in manifest_$VariantName.json: $entrypoint"
    }

    return [pscustomobject]@{
        ArtifactRoot = $artifactRoot
        AppPackage = $appPackage
        AppManifest = $appManifestPath
        LauncherExe = $launcherExe
        LauncherManifest = $launcherManifestPath
        Entrypoint = $entrypoint
    }
}

function Install-AppPackage {
    param(
        [Parameter(Mandatory = $true)][string]$PackagePath,
        [Parameter(Mandatory = $true)][string]$InstallRoot
    )

    $appDir = Join-Path $InstallRoot "app"
    Assert-PathWithin $appDir $InstallRoot
    if (Test-Path -LiteralPath $appDir) {
        Remove-Item -LiteralPath $appDir -Recurse -Force
    }
    New-Item -ItemType Directory -Path $appDir -Force | Out-Null

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::ExtractToDirectory($PackagePath, $appDir)

    $required = @(
        "Bomana.pyw",
        "bomana\config.py",
        "bomana\metadata.py"
    )
    foreach ($relative in $required) {
        $candidate = Join-Path $appDir $relative
        if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            throw "installed app package is missing $relative"
        }
    }
    return $appDir
}

function Write-SmokeLauncherState {
    param(
        [Parameter(Mandatory = $true)][string]$InstallRoot,
        [Parameter(Mandatory = $true)][string]$VariantName
    )

    $state = [ordered]@{
        channel = $VariantName
        download_source_mode = "primary"
        use_system_proxy = $false
        state_updated_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    }
    $statePath = Join-Path $InstallRoot "launcher_state.json"
    $state | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $statePath -Encoding UTF8
    return $statePath
}

function New-PoisonBin {
    param([Parameter(Mandatory = $true)][string]$Root)

    $poisonBin = Join-Path $Root "poison bin no python"
    New-Item -ItemType Directory -Path $poisonBin -Force | Out-Null
    foreach ($name in @("python.exe", "python3.exe", "py.exe", "uv.exe")) {
        Set-Content -LiteralPath (Join-Path $poisonBin $name) -Value "not a valid executable" -Encoding ASCII
    }
    foreach ($name in @("python.cmd", "python.bat", "py.cmd", "uv.cmd")) {
        $shim = "@echo off`r`necho poisoned Python shim must not run 1>&2`r`nexit /b 9009`r`n"
        Set-Content -LiteralPath (Join-Path $poisonBin $name) -Value $shim -Encoding ASCII
    }
    return $poisonBin
}

function New-SmokeEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$SmokeRootPath,
        [Parameter(Mandatory = $true)][string]$PoisonBin,
        [Parameter(Mandatory = $true)][string]$VariantName
    )

    $profileRoot = Join-Path $SmokeRootPath "user profile 用户"
    $appData = Join-Path $profileRoot "AppData\Roaming"
    $localAppData = Join-Path $profileRoot "AppData\Local"
    $tempRoot = Join-Path $SmokeRootPath "temp 临时"
    foreach ($directory in @($profileRoot, $appData, $localAppData, $tempRoot)) {
        New-Item -ItemType Directory -Path $directory -Force | Out-Null
    }

    $systemRoot = $env:SystemRoot
    if ([string]::IsNullOrWhiteSpace($systemRoot)) {
        $systemRoot = Join-Path $env:WINDIR ""
    }
    $pathValue = "$PoisonBin;$systemRoot\System32;$systemRoot"
    return [ordered]@{
        PATH = $pathValue
        PATHEXT = ".COM;.EXE;.BAT;.CMD"
        PYTHONHOME = Join-Path $PoisonBin "invalid-pythonhome"
        PYTHONPATH = Join-Path $PoisonBin "invalid-pythonpath"
        PYTHONNOUSERSITE = "1"
        PYTHONUSERBASE = Join-Path $PoisonBin "invalid-userbase"
        PYTHONUTF8 = "1"
        PYTHONIOENCODING = "utf-8"
        USERPROFILE = $profileRoot
        HOME = $profileRoot
        APPDATA = $appData
        LOCALAPPDATA = $localAppData
        TEMP = $tempRoot
        TMP = $tempRoot
        BOMANA_CHANNEL = $VariantName.ToLowerInvariant()
        BOMANA_UPDATE_BASE_URL = "http://127.0.0.1:9"
        BOMANA_PRIMARY_ALLOW_PACKAGE_DOWNLOAD = "0"
        BOMANA_LAUNCHER_DATA_DIR = Join-Path $SmokeRootPath "launcher data 数据"
        BOMANA_LAUNCHER_DOWNLOAD_DIR = Join-Path $SmokeRootPath "downloads 下载"
        BOMANA_PACKAGED_LAUNCHER_SMOKE = "1"
    }
}

function Add-SmokeUiAutomationTypes {
    Add-Type -AssemblyName UIAutomationClient
    Add-Type -AssemblyName UIAutomationTypes
    Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class BomanaSmokeWin32 {
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool EnumChildWindows(IntPtr hWndParent, EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int maxCount);

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int GetClassName(IntPtr hWnd, StringBuilder text, int maxCount);

    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [DllImport("user32.dll")]
    public static extern IntPtr SendMessage(IntPtr hWnd, int msg, IntPtr wParam, IntPtr lParam);

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    public static IntPtr[] TopLevelWindowsForProcess(int processId) {
        var handles = new List<IntPtr>();
        EnumWindows(delegate(IntPtr hWnd, IntPtr lParam) {
            uint windowPid;
            GetWindowThreadProcessId(hWnd, out windowPid);
            if (windowPid == (uint)processId && IsWindowVisible(hWnd)) {
                handles.Add(hWnd);
            }
            return true;
        }, IntPtr.Zero);
        return handles.ToArray();
    }

    public static IntPtr[] ChildWindows(IntPtr parent) {
        var handles = new List<IntPtr>();
        EnumChildWindows(parent, delegate(IntPtr hWnd, IntPtr lParam) {
            handles.Add(hWnd);
            return true;
        }, IntPtr.Zero);
        return handles.ToArray();
    }

    public static string WindowText(IntPtr hWnd) {
        var text = new StringBuilder(512);
        GetWindowText(hWnd, text, text.Capacity);
        return text.ToString();
    }

    public static string ClassName(IntPtr hWnd) {
        var text = new StringBuilder(256);
        GetClassName(hWnd, text, text.Capacity);
        return text.ToString();
    }
}
"@
}

function Invoke-UiAutomationLaunchButton {
    param([Parameter(Mandatory = $true)][IntPtr]$WindowHandle)

    try {
        $root = [System.Windows.Automation.AutomationElement]::FromHandle($WindowHandle)
        if ($null -eq $root) {
            return $false
        }
        $condition = [System.Windows.Automation.PropertyCondition]::new(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Button
        )
        $buttons = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
        foreach ($button in $buttons) {
            $name = [string]$button.Current.Name
            if ($name -match "^启动(?!器)") {
                $pattern = $button.GetCurrentPattern(
                    [System.Windows.Automation.InvokePattern]::Pattern
                )
                $pattern.Invoke()
                return $true
            }
        }
    }
    catch {
        return $false
    }
    return $false
}

function Invoke-Win32LaunchButton {
    param([Parameter(Mandatory = $true)][IntPtr]$WindowHandle)

    $bmClick = 0x00F5
    foreach ($child in [BomanaSmokeWin32]::ChildWindows($WindowHandle)) {
        $text = [BomanaSmokeWin32]::WindowText($child)
        $className = [BomanaSmokeWin32]::ClassName($child)
        if ($className -like "*Button*" -and $text -match "^启动(?!器)") {
            [BomanaSmokeWin32]::SetForegroundWindow($WindowHandle) | Out-Null
            [BomanaSmokeWin32]::SendMessage($child, $bmClick, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
            return $true
        }
    }
    return $false
}

function Wait-AndInvokeLaunchButton {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][int]$TimeoutSec
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSec)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($Process.HasExited) {
            throw "launcher exited before the launch button was invoked; exit code $($Process.ExitCode)"
        }
        foreach ($window in [BomanaSmokeWin32]::TopLevelWindowsForProcess($Process.Id)) {
            $title = [BomanaSmokeWin32]::WindowText($window)
            if ($title -notmatch "Bomana") {
                continue
            }
            if (Invoke-UiAutomationLaunchButton $window) {
                return
            }
            if (Invoke-Win32LaunchButton $window) {
                return
            }
        }
        Start-Sleep -Milliseconds 500
    }
    throw "timed out waiting for launcher launch button; this smoke requires an interactive Windows desktop"
}

function Wait-AppWindow {
    param(
        [Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process,
        [Parameter(Mandatory = $true)][int]$TimeoutSec
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSec)
    while ([DateTime]::UtcNow -lt $deadline) {
        if ($Process.HasExited) {
            throw "launcher/app process exited before the app window appeared; exit code $($Process.ExitCode)"
        }
        foreach ($window in [BomanaSmokeWin32]::TopLevelWindowsForProcess($Process.Id)) {
            $title = [BomanaSmokeWin32]::WindowText($window)
            if ($title -eq "WT Timer") {
                return $window
            }
        }
        Start-Sleep -Milliseconds 500
    }
    throw "timed out waiting for packaged app window title 'WT Timer'"
}

function Start-SmokeLauncher {
    param(
        [Parameter(Mandatory = $true)][string]$LauncherPath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)]$Environment
    )

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $LauncherPath
    $psi.WorkingDirectory = $WorkingDirectory
    $psi.UseShellExecute = $false

    $removeKeys = @()
    foreach ($key in $psi.EnvironmentVariables.Keys) {
        $name = [string]$key
        if (
            $name -like "PYTHON*" -or
            $name -in @("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT", "UV_PYTHON", "CONDA_PREFIX")
        ) {
            $removeKeys += $name
        }
    }
    foreach ($key in $removeKeys) {
        $psi.EnvironmentVariables.Remove($key)
    }
    foreach ($entry in $Environment.GetEnumerator()) {
        $psi.EnvironmentVariables[[string]$entry.Key] = [string]$entry.Value
    }

    return [System.Diagnostics.Process]::Start($psi)
}

function Stop-SmokeProcess {
    param($Process)

    if ($null -eq $Process) {
        return
    }
    try {
        if (-not $Process.HasExited) {
            $Process.CloseMainWindow() | Out-Null
            if (-not $Process.WaitForExit(5000)) {
                $Process.Kill()
                $Process.WaitForExit(5000) | Out-Null
            }
        }
    }
    catch {
        try {
            if (-not $Process.HasExited) {
                $Process.Kill()
            }
        }
        catch {
        }
    }
}

Assert-Windows

$repoRoot = Resolve-FullPath (Join-Path $PSScriptRoot "..\..")
$createdSmokeRoot = $false
if ([string]::IsNullOrWhiteSpace($SmokeRoot)) {
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $SmokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) "Bomana packaged smoke 中文 路径 $stamp"
    $createdSmokeRoot = $true
}
$workRoot = Resolve-FullPath $SmokeRoot
$installRoot = Join-Path $workRoot "install target 启动器 路径"
$launcherProcess = $null
$success = $false
$failed = $false

try {
    Write-Host "[1/7] Preparing smoke workspace: $workRoot"
    New-Item -ItemType Directory -Path $workRoot -Force | Out-Null
    New-Item -ItemType Directory -Path $installRoot -Force | Out-Null

    if ($NoBuild) {
        if ([string]::IsNullOrWhiteSpace($ArtifactDir)) {
            $ArtifactDir = Join-Path $repoRoot "dist"
        }
        Write-Host "[2/7] Reusing release artifacts from: $ArtifactDir"
    }
    else {
        if ([string]::IsNullOrWhiteSpace($ArtifactDir)) {
            $ArtifactDir = Join-Path $workRoot "build output 产物"
        }
        $uv = Get-Command uv -ErrorAction SilentlyContinue
        if ($null -eq $uv) {
            throw "uv is required to build release smoke artifacts"
        }
        Write-Host "[2/7] Building signed launcher and app package with tools/build_portable.py"
        $env:PYTHONPATH = ""
        $env:PYTHONHOME = ""
        $env:PYTHONNOUSERSITE = "1"
        Invoke-NativeCommand -FilePath $uv.Source -WorkingDirectory $repoRoot -ArgumentList @(
            "run",
            "--frozen",
            "--extra",
            "build",
            "python",
            "tools\build_portable.py",
            "--variant",
            $Variant,
            "--target",
            "all",
            "--output",
            (Resolve-FullPath $ArtifactDir)
        )
    }

    Write-Host "[3/7] Validating signed release manifests and asset hashes"
    $artifacts = Resolve-ReleaseArtifacts -Directory $ArtifactDir -VariantName $Variant

    Write-Host "[4/7] Copying packaged launcher and app assets into hostile path"
    $assetCopyRoot = Join-Path $installRoot "release assets 发布产物"
    New-Item -ItemType Directory -Path $assetCopyRoot -Force | Out-Null
    $launcherTarget = Join-Path $installRoot ([System.IO.Path]::GetFileName($artifacts.LauncherExe))
    Copy-Item -LiteralPath $artifacts.LauncherExe -Destination $launcherTarget -Force
    Copy-Item -LiteralPath $artifacts.AppPackage -Destination $assetCopyRoot -Force
    Copy-Item -LiteralPath $artifacts.AppManifest -Destination $assetCopyRoot -Force
    Copy-Item -LiteralPath $artifacts.LauncherManifest -Destination $assetCopyRoot -Force

    Write-Host "[5/7] Installing app package into frozen launcher layout"
    $appPackageCopy = Join-Path $assetCopyRoot ([System.IO.Path]::GetFileName($artifacts.AppPackage))
    $appDir = Install-AppPackage -PackagePath $appPackageCopy -InstallRoot $installRoot
    Write-SmokeLauncherState -InstallRoot $installRoot -VariantName $Variant | Out-Null
    Write-Host "      installed app: $appDir"

    Write-Host "[6/7] Preparing poisoned Python environment"
    $poisonBin = New-PoisonBin $workRoot
    $smokeEnv = New-SmokeEnvironment -SmokeRootPath $workRoot -PoisonBin $poisonBin -VariantName $Variant

    if ($SkipGuiHandoff) {
        Write-Host "[7/7] Skipping GUI launcher/app handoff by request"
    }
    else {
        Write-Host "[7/7] Launching packaged launcher and verifying app handoff"
        Add-SmokeUiAutomationTypes
        $launcherProcess = Start-SmokeLauncher `
            -LauncherPath $launcherTarget `
            -WorkingDirectory $installRoot `
            -Environment $smokeEnv
        Wait-AndInvokeLaunchButton -Process $launcherProcess -TimeoutSec $LaunchTimeoutSec
        Wait-AppWindow -Process $launcherProcess -TimeoutSec $LaunchTimeoutSec | Out-Null
        Write-Host "      app window appeared from packaged launcher process $($launcherProcess.Id)"
    }

    $success = $true
    Write-Host "[OK] Packaged launcher smoke passed."
}
catch {
    $failed = $true
    Write-Host "[error] Packaged launcher smoke failed: $($_.Exception.Message)" -ForegroundColor Red
    $logPath = Join-Path $installRoot "launcher.log"
    if (Test-Path -LiteralPath $logPath -PathType Leaf) {
        Write-Host "[info] launcher.log tail:"
        Get-Content -LiteralPath $logPath -Tail 80 -Encoding UTF8
    }
}
finally {
    Stop-SmokeProcess $launcherProcess
    if ($success -and (-not $KeepWorkDir) -and $createdSmokeRoot) {
        Assert-PathWithin $workRoot ([System.IO.Path]::GetTempPath())
        Remove-Item -LiteralPath $workRoot -Recurse -Force
    }
    else {
        Write-Host "[info] smoke workspace kept at: $workRoot"
    }
}

if ($failed) {
    exit 1
}
exit 0
