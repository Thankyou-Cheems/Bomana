# Optional Privileged Hotkey Contract Spec

Status: Amended (2026-07-24)
Owner: Bomana maintainers
Prefix: `ELEV-`

## Scope

This spec governs the Windows integrity boundary between the ordinary Bomana
App and its optional, zero-install native hotkey broker: ordinary system hotkeys,
the prohibition on game-process probing, explicit UAC consent, bundled-runtime
validation, fixed-action IPC, fallback, and shutdown.

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
- `ELEV-03`: The production App MUST NOT enumerate game windows or processes,
  query game executable names or tokens, take process snapshots, enumerate
  modules, read process memory, or retain a game-process handle to configure
  hotkeys. Game focus and process integrity MUST NOT become runtime inputs.
- `ELEV-04`: Bomana MUST keep the ordinary `RegisterHotKey` backend regardless
  of whether the game is running or focused. A failed registration MAY identify
  the conflicting Bomana key but MUST NOT trigger a game query or automatic UAC.
- `ELEV-05`: A build MAY expose one explicit, user-initiated operation to enable
  the bundled elevated hotkey broker, but it MUST NOT be offered or invoked as
  the result of game-process detection. The same operation MAY be exposed on
  both an unlocked App surface and the tray.
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
  in `bomb_target`, `reset`, `lock`, `corner`, `beep`, and optional `zones`;
  bindings MUST be unique `F1` through `F12` keys.
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
  `ELEV-01..ELEV-12` across launcher/build flags, the absence of game-process
  probing, bundled path/hash locking, consent text, native broker source, IPC
  framing, and forbidden elevated App/install paths.
- [behavioral] `tests/test_hotkey_broker.py` enforces `ELEV-03`, `ELEV-05`, and
  `ELEV-07..ELEV-12` with fixed-path, hash, argument, frame, cancellation,
  failure, and lifecycle cases.
- [behavioral] `tests/test_runtime_services.py` and
  `tests/test_ui_app_config.py` enforce `ELEV-02`, `ELEV-04..ELEV-06`,
  `ELEV-11`, and `ELEV-13` with ordinary-first startup, no game-process query,
  no automatic UAC, explicit-consent dispatch, fallback, retry, and shutdown.
- [manual] A Windows release smoke covers `ELEV-03..ELEV-07`, `ELEV-10..ELEV-12`:
  confirm no game-process handle is opened, approve and deny any explicitly
  exposed broker action, exercise F6-F11, and confirm no installed or persistent
  component remains.
