[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [string]$IconPath = (Join-Path $PSScriptRoot "..\bomana\assets\branding\app.ico")
)

$ErrorActionPreference = "Stop"
$exePath = [IO.Path]::GetFullPath($Path)
$expectedPath = [IO.Path]::GetFullPath($IconPath)
if (-not (Test-Path -LiteralPath $exePath -PathType Leaf)) { throw "Bridge executable is missing: $exePath" }
if (-not (Test-Path -LiteralPath $expectedPath -PathType Leaf)) { throw "Bomana icon is missing: $expectedPath" }

Add-Type -AssemblyName System.Drawing
$actual = [Drawing.Icon]::ExtractAssociatedIcon($exePath)
$expected = [Drawing.Icon]::new($expectedPath, 32, 32)
if ($null -eq $actual) { throw "Bridge executable has no extractable Windows application icon" }

function Get-IconPixelHash([Drawing.Icon]$Icon) {
    $bitmap = $Icon.ToBitmap()
    try {
        $bytes = [byte[]]::new($bitmap.Width * $bitmap.Height * 4)
        $offset = 0
        for ($y = 0; $y -lt $bitmap.Height; $y++) {
            for ($x = 0; $x -lt $bitmap.Width; $x++) {
                $argb = $bitmap.GetPixel($x, $y).ToArgb()
                [BitConverter]::GetBytes($argb).CopyTo($bytes, $offset)
                $offset += 4
            }
        }
        return [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
    } finally {
        $bitmap.Dispose()
    }
}

try {
    if ($actual.Width -ne 32 -or $actual.Height -ne 32) {
        throw "Bridge application icon has unexpected size $($actual.Width)x$($actual.Height)"
    }
    $actualHash = Get-IconPixelHash $actual
    $expectedHash = Get-IconPixelHash $expected
    if ($actualHash -ne $expectedHash) {
        throw "Bridge application icon does not match the classic Bomana icon"
    }
    Write-Host "verified Windows application icon $actualHash"
} finally {
    $actual.Dispose()
    $expected.Dispose()
}
