# Startup Elevation Contract Spec

Status: Accepted
Owner: Bomana maintainers
Prefix: `ELEV-`

## Scope

This spec governs Windows UAC behavior at the portable/source launcher to App
handoff, the elevated child mode, cancellation fallback, and the user-facing
degraded-feature warning.

## Non-goals

- This spec does not grant administrator rights to launcher update, download,
  extraction, or self-update work.
- This spec does not add a keyboard hook, key-state polling, raw-input fallback,
  or any War Thunder process inspection.
- Elevation reduces a Windows integrity-level input boundary; it is not a
  promise that every anti-cheat or input configuration will deliver hotkeys.

## Normative Clauses

- `ELEV-01`: The launcher and all update/download/install work must remain
  `asInvoker`. Builds must not use `requireAdministrator`, `uiAccess=true`, or
  PyInstaller `--uac-admin`.
- `ELEV-02`: The default launcher App action on Windows must request elevation
  only at the App handoff. The elevated child must bypass launcher networking
  and update UI, recompute the local runtime root, and run only Bomana's fixed
  App entrypoint.
- `ELEV-03`: Elevation logic may query only the current Bomana/launcher process
  token. It must not enumerate, open, or inspect War Thunder or anti-cheat
  processes, and it must not run periodically in the background.
- `ELEV-04`: The elevated-child command must use absolute executable,
  launcher-entry, and working-directory paths with Windows-safe argument
  quoting. Its internal arguments must be limited to a fixed action and an
  allowlisted release channel; it must not accept an arbitrary command,
  entrypoint, or runtime path.
- `ELEV-05`: UAC cancellation or launch failure must leave the ordinary launcher
  alive and must not trigger an automatic retry loop. Cancellation is an
  expected user choice, not an application exception.
- `ELEV-06`: After elevation is not granted, the launcher must show a persistent
  warning that game-foreground global F7-F11 shortcuts may be unavailable when
  War Thunder runs at a higher integrity level, while window-local controls,
  tray actions, timer/navigation, and official 8111 data remain available. The
  same surface must offer both one-click elevation retry and ordinary launch.
- `ELEV-07`: A successful `runas` handoff must close the ordinary launcher
  without also running the App in that process. The child must independently
  verify that it is elevated before entering `launcher.bootstrap.launch_app()`;
  the App single-instance mutex remains owned only by the App process.
- `ELEV-08`: Each explicit launch or retry click may make at most one UAC
  request. Hotkey registration remains the single `RegisterHotKey` lifecycle
  defined by `docs/specs/threading-ui-contract.md`.

## Contract Coverage

- [static] `tests/contracts/test_startup_elevation_contract.py` enforces
  `ELEV-01..ELEV-08` across build flags, launcher control flow, fixed child
  arguments, current-process-only inspection, cancellation UI, and the ban on
  alternate input backends.
- [behavioral] `tests/test_launcher_elevation.py` enforces `ELEV-03..ELEV-05`,
  `ELEV-07`, and `ELEV-08` with current-token, command quoting, strict parsing,
  success, cancellation, and failure cases.
- [manual] Windows source and packaged-launcher smoke covers `ELEV-02`,
  `ELEV-05..ELEV-08`, including UAC approve/deny, ordinary fallback, no double
  App process, and a real War Thunder foreground shortcut check.
