$ErrorActionPreference = "Stop"

$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$forbiddenPaths = @(
    "Bomana.pyw",
    "launcher.pyw",
    "launcher",
    "bomana/core",
    "bomana/ui",
    "native/hotkey_broker",
    "frontend/src/runtime/solver-client.ts",
    "frontend/src/runtime/solver.worker.ts",
    "frontend/src/runtime/terrain-repository.ts",
    "frontend/src/runtime/y66-calibration.ts",
    "frontend/src/runtime/airfield-targeting.ts",
    "frontend/src/runtime/gamechat-zone-marks.ts",
    "frontend/src/runtime/mobile-pairing.ts"
)
foreach ($relative in $forbiddenPaths) {
    if (Test-Path -LiteralPath (Join-Path $root $relative)) {
        throw "Forbidden public path exists: $relative"
    }
}

$python = @(Get-ChildItem -LiteralPath $root -Recurse -File -Include *.py,*.pyw | Where-Object {
    $_.FullName -notlike "*\node_modules\*" -and $_.FullName -notlike "*\.git\*"
})
if ($python.Count) {
    throw "Retired Python files remain: $($python.FullName -join ', ')"
}

$publicSources = @(
    (Join-Path $root "frontend\src\public-main.ts")
    (Join-Path $root "frontend\src\public-runtime.ts")
    (Join-Path $root "frontend\src\public-telemetry.ts")
)
$forbiddenSymbols = "solveWeaponEnvelope|terrainAltitude|Y66Calibration|applyOfficialChatZoneMarks|pairingToken|gridLabelAtNormalized"
foreach ($source in $publicSources) {
    if ((Get-Content -Raw -LiteralPath $source) -match $forbiddenSymbols) {
        throw "Enhanced symbol leaked into public source: $source"
    }
}

foreach ($edition in @("Lite", "Standard")) {
    $dist = Join-Path $root "frontend\dist\$edition"
    if (-not (Test-Path -LiteralPath (Join-Path $dist "index.html"))) {
        throw "Missing public build: $edition"
    }
    $leaks = @(Get-ChildItem -LiteralPath $dist -Recurse -File | Where-Object {
        $_.Name -match "[.](wasm)$|terrain|guided|ballistic|y66|airfield-catalog|mobile-pairing"
    })
    if ($leaks.Count) {
        throw "$edition build leaked private assets: $($leaks.Name -join ', ')"
    }
}

Write-Output "public_boundary=clean"
