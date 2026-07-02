# Threading And Tk UI Contract Spec

Status: Accepted
Owner: Bomana maintainers
Prefix: `THREAD-`

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
  to the Tk main thread through `TkEventDispatcher.post()` or `root.after(0, ...)`
  before touching UI state.
- `THREAD-03`: `LogicPoller` owns the background `GameLogic.tick()` loop. It may
  update core state only and must not touch Tk. The UI refresh loop reads
  snapshot data on the Tk side.
- `THREAD-04`: `GlobalHotkeys` listens on a Windows message thread. Configured
  callbacks must be posted back through `root.after(0, ...)`.
- `THREAD-05`: `pystray` runs on a daemon tray thread. Menu callbacks must not
  call UI methods directly; they must use `app.dispatcher.post(...)`.
- `THREAD-06`: `SoundManager` and diagnostics use worker queues. UI code may
  enqueue work but must not wait on playback or disk I/O during UI refresh.
- `THREAD-07`: Shutdown and destroyed-root paths must suppress expected
  `tk.TclError` / Tk main-loop `RuntimeError` failures so app exit stays quiet.

## Contract Coverage

- `tests/contracts/test_tk_thread_contract.py` enforces `THREAD-02` through
  `THREAD-05` by checking existing dispatcher, hotkey, tray, and poller routing.
- `tests/test_runtime_threading.py` and `tests/test_runtime_services.py` provide
  focused behavioral coverage for runtime helpers.
