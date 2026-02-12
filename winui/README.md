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

If `BOMANA_WINUI_EXE` is not set, the app probes:
- `winui/Bomana.WinUI3.exe`
- `Bomana.WinUI3.exe`

## Frontend Contract
See `winui/SNAPSHOT_API.md`.
