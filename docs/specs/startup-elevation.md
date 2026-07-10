# Privileged Hotkey Broker Contract Spec

Status: Amended (2026-07)
Owner: Bomana maintainers
Prefix: `ELEV-`

## Scope

This spec governs the Windows integrity boundary between the ordinary Bomana
App and the optional elevated native hotkey broker, including UAC requests,
protected installation, fixed-action IPC, cancellation fallback, and shutdown.

## Non-goals

- This spec does not grant administrator rights to the launcher, Python App,
  update, download, extraction, rollback, or self-update work.
- This spec does not authorize keyboard hooks, key-state polling, raw input,
  game-process inspection, services, scheduled tasks, or startup persistence.
- Elevating the broker reduces a Windows input-integrity boundary; it is not a
  promise that every anti-cheat or input configuration will deliver hotkeys.

## Normative Clauses

- `ELEV-01`: The launcher, Python App, and all update/download/install work MUST
  remain `asInvoker`; builds MUST NOT use `requireAdministrator`,
  `uiAccess=true`, PyInstaller `--uac-admin`, or an elevated Python App child.
- `ELEV-02`: Bomana MAY request `runas` only for the fixed
  `%ProgramFiles%\Bomana\HotkeyBroker\BomanaHotkeyBroker.exe` path and MUST NOT
  accept an environment, command-line, config, or app-package override for that
  executable path.
- `ELEV-03`: The elevated runtime broker MUST be a native executable installed
  below `%ProgramFiles%\Bomana\HotkeyBroker`, protected by an explicit DACL
  that grants write access only to Administrators and SYSTEM, and
  Authenticode-signed before release.
- `ELEV-04`: The broker command line MUST accept only one generated
  `<app-pid>-<32-hex-nonce>` session token plus one binding for each fixed action
  in `reset`, `lock`, `corner`, `beep`, and optional `zones`; bindings MUST be
  unique `F1` through `F12` keys.
- `ELEV-05`: Broker IPC MUST use a local named pipe and stop event derived from
  the session token, explicit current-user/SYSTEM/Administrators DACLs,
  remote-client rejection, server-PID verification, and fixed eight-byte
  `BHK1` frames containing only status or allowlisted action IDs.
- `ELEV-06`: The broker MUST register each enabled binding at most once with
  `RegisterHotKey` and `MOD_NOREPEAT`; it MUST NOT hook or poll the keyboard,
  inspect the game, load app code or plugins, access the network, execute
  commands, or read/write user files.
- `ELEV-07`: UAC cancellation, a missing broker, IPC failure, or registration
  failure MUST leave the ordinary App alive, surface a persistent explanation
  of affected game-foreground hotkeys, retain window-local controls and
  official 8111 features, and expose one explicit retry or install action.
- `ELEV-08`: The broker MUST unregister all successful registrations and exit
  when the App process exits, the App signals the per-launch stop event, or IPC
  delivery fails; it MUST NOT install a service, scheduled task, or autostart
  entry.
- `ELEV-09`: Launcher and App code MUST NOT contain a path that runs
  `Bomana.pyw`, `launcher.bootstrap.launch_app()`, or any mutable app-package
  Python module under an elevated token.
- `ELEV-10`: Release tooling MUST refuse to publish the broker runtime or its
  installer unless Authenticode signing has succeeded and the shipped runtime
  path is the protected path defined by `ELEV-02` and `ELEV-03`.

## Contract Coverage

- [static] `tests/contracts/test_startup_elevation_contract.py` enforces
  `ELEV-01..ELEV-10` across launcher/build flags, fixed protected paths, native
  broker source, IPC framing, allowed APIs, and forbidden elevated App paths.
- [behavioral] `tests/test_hotkey_broker.py` enforces `ELEV-02`, `ELEV-04`,
  `ELEV-05`, `ELEV-07`, and `ELEV-08` with fixed-path, argument, frame,
  cancellation, failure, and lifecycle cases.
- [behavioral] `tests/test_runtime_services.py` enforces `ELEV-06..ELEV-08` with
  broker-first startup, local fallback, retry, and shutdown behavior.
- [manual] A signed Windows release smoke covers `ELEV-02`, `ELEV-03`,
  `ELEV-06..ELEV-08`, and `ELEV-10`: approve/deny UAC, verify the publisher and
  Program Files ACL, exercise F7-F11 with elevated War Thunder foreground, and
  confirm broker exit with the App.
