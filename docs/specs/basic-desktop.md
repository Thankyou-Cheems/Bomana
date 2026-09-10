# Basic Desktop

Status: Active

## Normative Clauses

- BASIC-01: Only the sortie cycle timer and official bombing-zone/airfield
  Basic Navigation belong in this local surface. No account, Enhanced data,
  solver, fuel, landing assistance, map image, phone, sound or updater is loaded.
- BASIC-02: Read bounded official indicators, state, map objects and map info
  from `/indicators`, `/state`, `/map_obj.json` and `/map_info.json` through the
  existing fixed-loopback ExtUI resolver. Use Windows system HTTP with no proxy,
  redirects, cookies or automatic authentication; each read has a 600 ms total
  deadline and must reject a truncated declared response. Async buffers remain
  pinned until the final request-handle callback. Never expose a listener,
  accept a user-supplied upstream, inspect processes or automate game controls.
- BASIC-03: Default the timer to 15 minutes, allow integer periods 1–180 and
  manual reset. Preserve timer continuity across short telemetry gaps; clear
  stale navigation after three seconds and reset after twelve seconds without
  data or confirmed loss. Grounded ownship-marker loss must not alone reset a
  live timer. Period changes retain the current start time.
- BASIC-04: Navigate only official bombing zones and airfields. Reject missing
  position, heading or map scale rather than showing fabricated guidance.
  Support automatic forward-target selection and manual selection; keep manual
  selection stable across object reorder. Friendly airports retain visible
  direction cues, including at the tape edge. Do not infer airport modules/POI.
- BASIC-05: The always-on-top native window supports optional borderless
  presentation. Background, text and heading-icon opacity independently span
  0–100%, including true zero background alpha without dimming foreground.
  Store appearance/period settings. Settings, tray and recovery actions remain
  usable at zero opacity or while mouse pass-through is enabled; unavailable
  shortcuts must not be advertised as registered.
- BASIC-06: A manually built Windows x64 EXE needs no companion EXE, DLL, browser
  runtime or downloaded assets. Use system fonts and vector icons; strip build
  symbols and omit unused imports/data. Record actual bytes, source revision,
  dependency audit and package SHA256. Do not use an executable packer.
  The Windows package must not link Go's `net/http` or `crypto/tls` packages;
  shared port discovery is independent of the caller's HTTP implementation.
  The EXE, native windows and tray share the Bomana SVG-derived application
  icon, compiled into a compact Windows resource without a runtime SVG renderer.

## Contract Coverage

- [behavioral] `native/telemetry_gateway/cmd/bomana_basic/model_test.go` covers
  BASIC-03 and BASIC-04 through timer and official-target snapshots.
- [behavioral] `native/telemetry_gateway/cmd/bomana_basic/source_test.go` covers
  BASIC-01, BASIC-02 and BASIC-03 through a real bounded loopback HTTP server.
  Its canonical `/map_obj.json` fixture must start both navigation and the timer.
- [behavioral] `native/telemetry_gateway/cmd/bomana_basic/http_windows_test.go`
  covers BASIC-02 bounded Windows HTTP reads, chunked responses, truncated
  bodies and concurrent cancellation.
- [behavioral] `native/telemetry_gateway/cmd/bomana_basic/window_windows_test.go`
  covers BASIC-05 through real native windows, settings commands and rendered
  alpha layers. Own-window render artifacts are distinct from game acceptance.
- [behavioral] `native/telemetry_gateway/cmd/bomana_basic/window_windows_test.go`
  checks BASIC-06 native startup without companion processes. The manual builder
  `tools/build_basic_desktop.ps1` additionally executes the final EXE alone,
  checks dependency imports and its extracted application icon, and records
  source and file-size facts.
- [manual] BASIC-03, BASIC-04 and BASIC-05 actual War Thunder overlay use remains
  a separate acceptance step.
