# Optional Privileged Hotkey Contract Spec

Status: Amended (2026-07)
Owner: Bomana maintainers
Prefix: `ELEV-`

## Scope

This spec governs the Windows integrity boundary between the ordinary Bomana
App and its optional, zero-install native hotkey broker, including the minimal
War Thunder elevation probe, explicit UAC consent, bundled-runtime validation,
fixed-action IPC, fallback, and shutdown.

## Non-goals

- This spec does not grant administrator rights to the launcher, Python App,
  update, download, extraction, rollback, or self-update work.
- This spec does not authorize keyboard hooks, key-state polling, raw input,
  process-memory access, module enumeration, services, scheduled tasks, or
  startup persistence.
- GitHub Artifact Attestations prove release-build provenance when a user
  verifies them; they do not make an unsigned executable show a verified UAC
  publisher or prevent all post-install modification of a user-writable package.
- Elevating the broker reduces a Windows input-integrity boundary; it is not a
  promise that every anti-cheat or input configuration will deliver hotkeys.

## Normative Clauses

- `ELEV-01`: The launcher, Python App, and all update/download/install work MUST
  remain `asInvoker`; builds MUST NOT use `requireAdministrator`,
  `uiAccess=true`, PyInstaller `--uac-admin`, or an elevated Python App child.
- `ELEV-02`: App startup MUST register the configured ordinary-integrity
  `RegisterHotKey` bindings first and MUST NOT display or initiate UAC
  automatically.
- `ELEV-03`: The startup probe MAY enumerate visible top-level windows, filter
  candidates by a `War Thunder` window title, and open only those candidate
  owners with `PROCESS_QUERY_LIMITED_INFORMATION` to confirm `aces.exe`,
  `aces64.exe`, or `aces_BE.exe`; only confirmed names MAY receive `TOKEN_QUERY`
  to read token elevation, and the probe MUST NOT take a process snapshot,
  enumerate modules, read process memory, or retain a game-process handle.
- `ELEV-04`: When the probe confirms War Thunder is not elevated, Bomana MUST
  keep the ordinary hotkey backend and MUST NOT show a privilege recommendation.
- `ELEV-05`: When War Thunder is elevated, not running, or cannot be queried,
  Bomana MUST keep ordinary hotkeys active and MAY show one explicit optional
  operation to enable elevated hotkeys. The same operation MAY be exposed on
  both the unlocked App surface and the tray so a locked click-through overlay
  cannot make it unreachable.
- `ELEV-06`: Bomana MAY invoke `runas` only after the user clicks the optional
  App or tray action and confirms the same Bomana-owned dialog that states UAC
  will appear, the broker is unsigned/Unknown publisher without Authenticode,
  and no installer, service, scheduled task, or autostart entry will be
  created. A tray callback MUST dispatch that action to the Tk owner thread.
- `ELEV-07`: The only broker executable path eligible for `runas` MUST be the
  resolved `bomana/bin/BomanaHotkeyBroker.exe` shipped in the current App
  package; it MUST NOT be overridden by environment, config, command-line, or
  download input, and the client MUST verify the adjacent release SHA256 then
  hold a non-write/non-delete-sharing file handle through broker startup.
- `ELEV-08`: The broker command line MUST accept only one generated
  `<app-pid>-<32-hex-nonce>` session token plus one binding for each fixed action
  in `reset`, `lock`, `corner`, `beep`, and optional `zones`; bindings MUST be
  unique `F1` through `F12` keys.
- `ELEV-09`: Broker IPC MUST use a local named pipe and stop event derived from
  the session token, explicit current-user/SYSTEM/Administrators DACLs,
  remote-client rejection, server-PID verification, and fixed eight-byte
  `BHK1` frames containing only status or allowlisted action IDs.
- `ELEV-10`: The broker MUST register each enabled binding at most once with
  `RegisterHotKey` and `MOD_NOREPEAT`; it MUST NOT hook or poll the keyboard,
  inspect the game, load App code or plugins, access the network, execute
  commands, or read/write user files.
- `ELEV-11`: UAC cancellation, a missing/tampered broker, IPC failure, or
  registration failure MUST leave the ordinary App alive, restore ordinary
  hotkeys, surface the limitation, and retain window-local controls and official
  8111 features.
- `ELEV-12`: The broker MUST unregister all successful registrations and exit
  when the App process exits, the App signals the per-launch stop event, or IPC
  delivery fails; it MUST execute in place and MUST NOT install another
  executable, service, scheduled task, or autostart entry.
- `ELEV-13`: While the App is locked/click-through, a visible privilege notice
  MUST explain that the user can switch out of the game and press the configured
  lock key before clicking the App action, or invoke the same consent action
  directly from the tray.

## Contract Coverage

- [static] `tests/contracts/test_startup_elevation_contract.py` enforces
  `ELEV-01..ELEV-12` across launcher/build flags, minimal process-query APIs,
  bundled path/hash locking, consent text, native broker source, IPC framing,
  and forbidden elevated App/install paths.
- [behavioral] `tests/test_hotkey_broker.py` enforces `ELEV-03`, `ELEV-05`, and
  `ELEV-07..ELEV-12` with process-probe, fixed-path, hash, argument, frame,
  cancellation, failure, and lifecycle cases.
- [behavioral] `tests/test_runtime_services.py` and
  `tests/test_ui_app_config.py` enforce `ELEV-02`, `ELEV-04..ELEV-06`,
  `ELEV-11`, and `ELEV-13` with ordinary-first startup, no automatic UAC,
  App/tray dispatch to one explicit consent path, locked-overlay guidance,
  fallback, retry, and shutdown behavior.
- [manual] A Windows release smoke covers `ELEV-03..ELEV-07`, `ELEV-10..ELEV-12`:
  start with War Thunder ordinary/elevated/closed, approve and deny UAC, verify
  the Unknown publisher warning, exercise F7-F11 with elevated War Thunder
  foreground, and confirm no installed/persistent component remains.
