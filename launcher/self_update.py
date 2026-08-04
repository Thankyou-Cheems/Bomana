"""Pure helpers for the Launcher helper-mediated self-update handoff.

The downloadable Launcher asset is versioned, while the locally installed
executable deliberately has one stable name.  This module only renders the
out-of-process helper; it never starts a process or overwrites a file itself.
"""

from __future__ import annotations

from pathlib import Path

STABLE_LAUNCHER_FILE_NAME = "Bomana_launcher.exe"
HELPER_WAIT_SECONDS = 120


def stable_launcher_path(running_launcher: Path) -> Path:
    """Return the shortcut-safe installed path beside a versioned asset."""

    return running_launcher.with_name(STABLE_LAUNCHER_FILE_NAME)


def _ps_literal(value: object) -> str:
    """Render a PowerShell single-quoted literal without interpolation."""

    return "'" + str(value).replace("'", "''") + "'"


def visible_update_notice(
    status: object, target_version: object, current_version: object
) -> str | None:
    """Return a user-visible completion notice only for the process actually running."""

    if str(status or "").strip().lower() != "success":
        return None
    target = str(target_version or "").strip()
    current = str(current_version or "").strip()
    if not target or target != current:
        return None
    return f"启动器已升级至 v{current}。"


def render_launcher_update_helper(
    *,
    target: Path,
    running_launcher: Path,
    staged: Path,
    result_path: Path,
    expected_sha256: str,
    old_pid: int,
    target_version: str,
    wait_seconds: int = HELPER_WAIT_SECONDS,
) -> str:
    """Return a recovery-safe PowerShell helper for one verified Launcher update.

    It waits for the old process, verifies the staged and replacement bytes,
    atomically swaps the stable name, restarts it, and retains one previous
    copy.  A restart failure attempts to restore that previous copy while
    retaining diagnostics and the staged candidate.
    """

    if int(old_pid) <= 0:
        raise ValueError("old_pid must be positive")
    if int(wait_seconds) <= 0:
        raise ValueError("wait_seconds must be positive")
    checksum = str(expected_sha256 or "").strip().lower()
    if len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
        raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")

    backup = target.with_name(f"{target.stem}.previous{target.suffix}")
    replacement = target.with_name(f".{target.stem}.replacement.{int(old_pid)}{target.suffix}")
    failed = target.with_name(f".{target.stem}.failed.{int(old_pid)}{target.suffix}")
    return f"""Set-StrictMode -Version 3.0
$ErrorActionPreference = 'Stop'
if ($PSVersionTable.PSVersion.Major -ge 7) {{
    $PSNativeCommandUseErrorActionPreference = $true
}}
$target = {_ps_literal(target)}
$runningLauncher = {_ps_literal(running_launcher)}
$staged = {_ps_literal(staged)}
$backup = {_ps_literal(backup)}
$replacement = {_ps_literal(replacement)}
$failed = {_ps_literal(failed)}
$resultPath = {_ps_literal(result_path)}
$expectedSha256 = {_ps_literal(checksum)}
$oldPid = {int(old_pid)}
$targetVersion = {_ps_literal(target_version)}
$waitSeconds = {int(wait_seconds)}
$replaceSucceeded = $false
$restartSucceeded = $false

function Write-Result([string]$status, [string]$message) {{
    $resultDir = Split-Path -Parent $resultPath
    if ($resultDir) {{
        New-Item -ItemType Directory -Path $resultDir -Force | Out-Null
    }}
    $tmpResultPath = "$resultPath.tmp"
    $payload = [ordered]@{{
        status = $status
        target_version = $targetVersion
        message = $message
        updated_utc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    }}
    $payload | ConvertTo-Json -Compress | Set-Content -LiteralPath $tmpResultPath -Encoding UTF8
    Move-Item -LiteralPath $tmpResultPath -Destination $resultPath -Force
}}

function Assert-FileSha256([string]$path, [string]$expected, [string]$label) {{
    $actual = (Get-FileHash -Algorithm SHA256 -LiteralPath $path).Hash.ToLowerInvariant()
    if ($actual -ne $expected) {{
        throw ($label + " SHA256 mismatch")
    }}
}}

function Restore-PreviousLauncher {{
    if (-not (Test-Path -LiteralPath $backup)) {{
        return $false
    }}
    $restore = "$target.restore.$oldPid"
    Remove-Item -LiteralPath $restore -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $backup -Destination $restore -Force
    if (-not (Test-Path -LiteralPath $restore)) {{
        throw "previous launcher copy was not created"
    }}
    if (Test-Path -LiteralPath $target) {{
        Remove-Item -LiteralPath $failed -Force -ErrorAction SilentlyContinue
        Move-Item -LiteralPath $target -Destination $failed -Force
    }}
    Move-Item -LiteralPath $restore -Destination $target -Force
    return $true
}}

try {{
    $deadline = [DateTime]::UtcNow.AddSeconds($waitSeconds)
    while (Get-Process -Id $oldPid -ErrorAction SilentlyContinue) {{
        if ([DateTime]::UtcNow -ge $deadline) {{
            throw "old launcher process did not exit before helper timeout"
        }}
        Start-Sleep -Seconds 1
    }}

    if (-not (Test-Path -LiteralPath $staged)) {{
        throw "staged launcher file missing"
    }}
    Assert-FileSha256 $staged $expectedSha256 "staged launcher"
    Remove-Item -LiteralPath $replacement -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $failed -Force -ErrorAction SilentlyContinue
    Copy-Item -LiteralPath $staged -Destination $replacement -Force
    if (-not (Test-Path -LiteralPath $replacement)) {{
        throw "replacement launcher file missing after copy"
    }}
    Assert-FileSha256 $replacement $expectedSha256 "replacement launcher"

    Remove-Item -LiteralPath $backup -Force -ErrorAction SilentlyContinue
    if (Test-Path -LiteralPath $target) {{
        Move-Item -LiteralPath $target -Destination $backup -Force
    }} elseif ((Test-Path -LiteralPath $runningLauncher) -and ($runningLauncher -ne $target)) {{
        Copy-Item -LiteralPath $runningLauncher -Destination $backup -Force
    }}
    Move-Item -LiteralPath $replacement -Destination $target -Force
    if (-not (Test-Path -LiteralPath $target)) {{
        throw "stable launcher target missing after replace"
    }}
    Assert-FileSha256 $target $expectedSha256 "stable launcher"
    $replaceSucceeded = $true
    $startedProcess = Start-Process -FilePath $target -WorkingDirectory (Split-Path -Parent $target) -PassThru
    if (-not $startedProcess) {{
        throw "launcher restart did not return a process"
    }}
    $restartSucceeded = $true
    Write-Result "success" ("Launcher replaced and restarted: " + $targetVersion)
}}
catch {{
    $detail = ($_ | Out-String).Trim()
    if ($replaceSucceeded -and (-not $restartSucceeded)) {{
        try {{
            if (Restore-PreviousLauncher) {{
                $detail = $detail + "`n已恢复上一版稳定启动器。"
            }}
        }} catch {{
            $detail = $detail + "`n恢复上一版失败: " + ($_ | Out-String).Trim()
        }}
    }} elseif ((-not (Test-Path -LiteralPath $target)) -and (Test-Path -LiteralPath $backup)) {{
        try {{
            Restore-PreviousLauncher | Out-Null
        }} catch {{
            $detail = $detail + "`n恢复上一版失败: " + ($_ | Out-String).Trim()
        }}
    }}
    if (Test-Path -LiteralPath $target) {{
        $detail = $detail + "`n当前稳定启动器文件: " + $target
    }}
    if (Test-Path -LiteralPath $backup) {{
        $detail = $detail + "`n可恢复的上一版启动器: " + $backup
    }}
    if (Test-Path -LiteralPath $staged) {{
        $detail = $detail + "`n新版启动器文件保留在: " + $staged
    }}
    Write-Result "error" $detail
    exit 1
}}
finally {{
    if ($replaceSucceeded -and $restartSucceeded) {{
        Remove-Item -LiteralPath $staged -Force -ErrorAction SilentlyContinue
    }}
    Remove-Item -LiteralPath $replacement -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
}}
"""
