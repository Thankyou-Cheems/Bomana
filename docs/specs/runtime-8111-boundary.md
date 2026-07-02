# Runtime 8111 Boundary Spec

Status: Accepted
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

## Contract Coverage

- `tests/contracts/test_runtime_8111_boundary.py` enforces `R8111-01` through
  `R8111-04` by checking the runtime base URL, endpoint whitelist, dangerous API
  strings, and centralized HTTP access.
- `tests/test_quality_gate_config.py` and `tools/scripts/check_smoke.bat` keep
  automated smoke on pytest rather than real 8111 access.
