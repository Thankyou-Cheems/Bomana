# Runtime 8111 Boundary Spec

Status: Amended (2026-07)
Owner: Bomana maintainers
Prefix: `R8111-`

## Scope

This spec governs runtime app code under `Bomana.pyw` and `bomana/` that reads
War Thunder data or renders data-derived UI. It also governs automated tests that
claim to protect the War Thunder data boundary.

## Non-goals

- This spec does not govern `tools/sample_8111_attitude.py` or other manual
  developer diagnostics unless they are shipped as runtime behavior.
- This spec does not document Tencent/EdgeOne update service APIs.
- This spec does not replace manual War Thunder smoke testing.

## Normative Clauses

- `R8111-01`: Runtime game data must come only from the official loopback 8111
  HTTP service at `http://127.0.0.1:8111` or `http://localhost:8111`. Runtime
  code must not read game memory, inject code, unpack or decrypt logs, inspect
  packets, or modify game files.
- `R8111-02`: Runtime 8111 endpoint use is limited to `/indicators`, `/state`,
  `/map_obj.json`, and `/map_info.json`.
- `R8111-03`: Bomana must not display player-invisible enemy information,
  especially enemy unit/player marker overlays. UI may show only information
  that is public through 8111 and visible in-game or related to the player.
- `R8111-04`: Ownership is fixed: `TelemetryFetcher` owns `/indicators` and
  `/state`; `MapInfoFetcher` owns `/map_info.json`; `MapObjectsFetcher` parses
  `/map_obj.json` normalized coordinates only; `GameLogic` owns map scale
  semantics and coordinate conversion.
- `R8111-05`: Automated tests must not claim to be real 8111 smoke. Changes to
  telemetry or logic data flow must report whether manual in-game smoke was run.
- `R8111-06`: Polling defaults are 50 ms in normal mode and 1.25 s while the API
  is down. Tuning these values requires a delta spec or explicit approval.
- `R8111-07`: Static bundled data is allowed only as project data such as
  `bomana/data/ccrp_bomb_params.json` and `bomana/data/fm_speed_limits.json`.
  Static data provenance must be documented when refreshed.
- `R8111-08`: Runtime hotkey diagnostics must not enumerate or open War Thunder
  or anti-cheat processes, query another process token, or infer hotkey delivery
  from process elevation; the broker client may query only its own token to
  construct the current-user IPC DACL, and diagnosis must use registration and
  callback-delivery evidence.

## Contract Coverage

- [static] `tests/contracts/test_runtime_8111_boundary.py` enforces
  `R8111-01`, `R8111-02`, `R8111-04`, `R8111-06`, and `R8111-08` by checking
  the runtime base URL, endpoint whitelist, dangerous API strings, ownership,
  polling defaults, and the ban on process inspection.
- [behavioral] `tests/test_telemetry_fetch_result.py` and
  `tests/test_map_objects_contract.py` enforce the fetcher and coordinate
  ownership boundary in `R8111-04`.
- [manual] Runtime/data review covers the player-visible-information boundary in
  `R8111-03`; handoffs must record real War Thunder smoke for `R8111-05`,
  explicit approval for polling changes under `R8111-06`, and provenance review
  for data refreshes under `R8111-07`.
