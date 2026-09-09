# Basic Desktop

Status: Active

## Normative Clauses

- BASIC-01: Only the sortie cycle timer and official bombing-zone/airfield
  Basic Navigation belong in this local surface. No account, Enhanced data,
  solver, fuel, landing assistance, map image, phone, sound or updater is loaded.
- BASIC-02: Read bounded official indicators, state, map objects and map info
  through the existing fixed-loopback ExtUI resolver. Never expose a listener,
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

## Contract Coverage

- [behavioral] `native/telemetry_gateway/cmd/bomana_basic/model_test.go` covers
  BASIC-03 and BASIC-04 through timer and official-target snapshots.
- [behavioral] `native/telemetry_gateway/cmd/bomana_basic/source_test.go` covers
  BASIC-01, BASIC-02 and BASIC-03 through a real bounded loopback HTTP server.
- [behavioral] `native/telemetry_gateway/cmd/bomana_basic/window_windows_test.go`
  covers BASIC-05 through real native windows, settings commands and rendered
  alpha layers. Own-window render artifacts are distinct from game acceptance.
- [behavioral] `native/telemetry_gateway/cmd/bomana_basic/window_windows_test.go`
  checks BASIC-06 native startup without companion processes. The manual builder
  `tools/build_basic_desktop.ps1` additionally executes the final EXE alone,
  checks dependency imports and records source and file-size facts.
- [manual] BASIC-03, BASIC-04 and BASIC-05 actual War Thunder overlay use remains
  a separate acceptance step.
