param([string]$AssetRoot = (Join-Path $PSScriptRoot "../frontend/dist"))

$ErrorActionPreference = 'Stop'
$previousAssetRoot = $env:BOMANA_MOBILE_ASSET_ROOT
$env:BOMANA_MOBILE_ASSET_ROOT = (Resolve-Path -LiteralPath $AssetRoot).Path
Push-Location (Join-Path $PSScriptRoot '../native/telemetry_gateway')
try {
    go test -tags mobile_browser -count=1 -run '^TestStandardMobilePairingBrowser$' -v .
    if ($LASTEXITCODE -ne 0) { throw 'Mobile pairing browser regression failed' }
}
finally {
    Pop-Location
    $env:BOMANA_MOBILE_ASSET_ROOT = $previousAssetRoot
}
