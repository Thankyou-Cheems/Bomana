# Threading And Tk UI Contract Spec

Status: Amended (2026-07)
Owner: Bomana maintainers
Prefix: `THREAD-`, `HOTKEY-`

## Scope

This spec governs Tk ownership, background worker boundaries, hotkey callbacks,
tray callbacks, audio workers, diagnostics workers, and shutdown behavior in the
runtime app.

## Non-goals

- This spec does not try to statically prove every Tk call is on the main thread.
- This spec does not govern PyInstaller internals or OS message-loop internals.
- This spec does not replace manual smoke for HUD, tray, hotkeys, DPI, monitor,
  or window lifecycle changes.

## Normative Clauses

- `THREAD-01`: Tk widgets may be created, updated, and destroyed only by the Tk
  main thread.
- `THREAD-02`: Background threads, hotkey threads, and tray callbacks must return
  to the Tk main thread through `TkEventDispatcher.post()` or a Tk-owned
  queue/poller bridge before touching UI state. Background threads must not call
  Tk APIs directly, including `root.after(...)`.
- `THREAD-03`: `LogicPoller` owns the background `GameLogic.tick()` loop. It may
  update core state only and must not touch Tk. The UI refresh loop reads
  snapshot data on the Tk side.
- `THREAD-04`: `GlobalHotkeys` must register a non-null Win32 message-only HWND
  on the Tk owner thread and route `WM_HOTKEY` callbacks through
  `TkEventDispatcher.post()`; it must not own a background `GetMessageW` loop.
- `THREAD-05`: `pystray` runs on a daemon tray thread. Menu callbacks must not
  call UI methods directly; they must use `app.dispatcher.post(...)`.
- `THREAD-06`: `SoundManager` and diagnostics use worker queues. UI code may
  enqueue work but must not wait on playback or disk I/O during UI refresh.
- `THREAD-07`: Shutdown and destroyed-root paths must suppress expected
  `tk.TclError` / Tk main-loop `RuntimeError` failures so app exit stays quiet.
- `THREAD-08`: The native hotkey WndProc must only enqueue callbacks; it must not
  call Tk APIs or execute application callbacks reentrantly from Windows message
  dispatch.
- `HOTKEY-01`: Windows global hotkeys must use `RegisterHotKey` as the default
  backend. Runtime code must not add low-level keyboard hooks, polling fallback
  paths, or key-state polling for configured global hotkeys.
- `HOTKEY-02`: Hotkey registration, re-registration, unregistration, and
  message-window creation/destruction must run on the Tk owner thread. Callback
  dispatch must use the documented dispatcher bridge rather than a hook,
  polling fallback, or worker message loop.
- `HOTKEY-03`: `RegisterHotKey` failures must be surfaced through the configured
  UI error callback. Code must not silently switch to another input backend.
- `HOTKEY-04`: The hotkey backend must not inspect War Thunder/anti-cheat
  processes or infer delivery from another process's elevation. Windows App
  startup elevation is a separate launcher handoff governed by
  `docs/specs/startup-elevation.md`; it must not add another input backend.

## Contract Coverage

- [static] `tests/contracts/test_tk_thread_contract.py` enforces
  `THREAD-02..THREAD-06`, `THREAD-08`, `HOTKEY-01`, `HOTKEY-02`, and
  `HOTKEY-04` by checking dispatcher, hotkey, tray, poller, sound, and forbidden
  fallback paths.
- [behavioral] `tests/test_runtime_threading.py` and
  `tests/test_runtime_services.py` enforce dispatcher, poller, shutdown, and
  hotkey lifecycle behavior in `THREAD-02..THREAD-05`, `THREAD-07`,
  `HOTKEY-02`, and `HOTKEY-03`.
- [behavioral] `tests/test_system_portability.py` enforces `THREAD-04`,
  `THREAD-08`, `HOTKEY-02`, and `HOTKEY-03` with registration lifecycle tests
  plus a real Windows message-window dispatch test.
- [manual] Runtime review and Windows smoke cover the whole-app Tk ownership
  invariant in `THREAD-01` and real HUD/tray/hotkey lifecycle behavior.
