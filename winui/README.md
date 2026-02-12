# WinUI3 Migration (Phase 1)

This folder documents the WinUI3 migration path.

## Current Status
- Python `GameLogic` stays as backend source of truth.
- New local snapshot API bridge is available at runtime.
- `Bomana.pyw` can launch WinUI3 frontend when `BOMANA_UI_RUNTIME=winui3`.
- Existing Tk UI remains default and unchanged.

## Runtime Switch
Set environment variables before launching:

```powershell
$env:BOMANA_UI_RUNTIME="winui3"
$env:BOMANA_WINUI_EXE="D:\path\to\Bomana.WinUI3.exe"  # optional override
python Bomana.pyw
```

Default behavior when `BOMANA_UI_RUNTIME` is not set:
- `auto` mode is used
- if WinUI frontend executable exists, app starts WinUI3
- otherwise app falls back to Tk UI

If `BOMANA_WINUI_EXE` is not set, the app probes:
- `winui/dist/Bomana.WinUI3.exe`
- `winui/Bomana.WinUI3.exe`
- `Bomana.WinUI3.exe`

For local dev build output, `bomana/ui/winui_host.py` also probes
`winui/Bomana.WinUI3/bin/**/Bomana.WinUI3.exe` and picks the latest one.

## Build Frontend Runtime

```powershell
python tools/build_winui_frontend.py --configuration Release --platform x64
```

or:

```bat
build_winui_frontend.bat Release x64
```

This exports runtime files to `winui/dist`, which portable app packaging can include.

## Frontend Contract
See `winui/SNAPSHOT_API.md`.
