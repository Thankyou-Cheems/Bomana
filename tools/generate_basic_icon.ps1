[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$root = Split-Path -Parent $PSScriptRoot
$command = Join-Path $root 'native/telemetry_gateway/cmd/bomana_basic'
& node (Join-Path $PSScriptRoot 'generate_basic_icon.mjs')
if ($LASTEXITCODE -ne 0) { throw 'Basic SVG icon rendering failed.' }
& go run github.com/akavel/rsrc@v0.10.2 -arch amd64 -ico (Join-Path $command 'app.ico') -o (Join-Path $command 'rsrc_windows_amd64.syso')
if ($LASTEXITCODE -ne 0) { throw 'Basic Windows icon resource generation failed.' }
