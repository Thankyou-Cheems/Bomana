# Runtime 8111 Boundary Spec

Status: Amended (2026-07)
Owner: Bomana maintainers
Prefix: `R8111-`

## Scope

This spec governs runtime app code under `Bomana.pyw` and `bomana/` that reads
War Thunder data or renders data-derived UI. It also governs the collection and
replay boundaries of `tools/record_8111_session.py`,
`tools/replay_8111_session.py`, and automated tests that claim to protect the
War Thunder data boundary.

## Non-goals

- This spec does not govern `tools/sample_8111_attitude.py` or other manual
  developer diagnostics unless they are shipped as runtime behavior or collect
  reusable raw session data.
- This spec does not document Tencent/EdgeOne update service APIs.
- This spec does not replace manual War Thunder smoke testing.
- Weapon catalog, selection-source, solver, and estimate-wording requirements
  are governed by `docs/specs/weapon-fire-control.md`.

## Normative Clauses

- `R8111-01`: Runtime game data must come only from the official loopback 8111
  HTTP service at `http://127.0.0.1:8111` or `http://localhost:8111`. Runtime
  code must not read game memory, inject code, unpack or decrypt logs, inspect
  packets, or modify game files.
- `R8111-02`: Runtime 8111 endpoint use is limited to `/indicators`, `/state`,
  `/map_obj.json`, `/map_info.json`, and the official tactical-map image
  `/map.img`. The JSON recorder/replayer boundary remains limited to the four
  JSON endpoints and MUST NOT record the image body.
- `R8111-03`: Bomana must not reconstruct, infer, or persist player-invisible
  enemy information. The separate paired Web tactical map may mirror every
  positioned hostile unit in the latest raw successful `/map_obj.json` sample,
  and must clear that projection on raw failure or absence from the next sample;
  these positions must not appear in the desktop HUD or heading tape. A hostile
  aircraft contact may separately feed the existing aggregate two-dimensional
  weapon estimate only while `/map_obj.json` currently returns that contact.
- `R8111-04`: Ownership is fixed: `TelemetryFetcher` owns `/indicators` and
  `/state`; `MapInfoFetcher` owns `/map_info.json`; `MapObjectsFetcher` parses
  `/map_obj.json` normalized player, map-object, and current hostile-unit
  coordinates only; `MapImageFetcher` owns `/map.img`; `GameLogic` owns map
  scale semantics, coordinate conversion, Web tactical projection, and target
  selection. Only normalized hostile-aircraft contacts are eligible for the
  existing AAM target-selection path.
- `R8111-05`: Automated tests must not claim to be real 8111 smoke. Changes to
  telemetry or logic data flow must report whether manual in-game smoke was run.
- `R8111-06`: Polling defaults are 50 ms in normal mode and 1.25 s while the API
  is down. Tuning these values requires a delta spec or explicit approval.
- `R8111-07`: Static bundled data is allowed only as project data such as
  `bomana/data/ccrp_bomb_params.json`, `bomana/data/weapon_fire_control.json`,
  and `bomana/data/fm_speed_limits.json`. Static data provenance must be
  documented when refreshed.
- `R8111-08`: Runtime hotkey startup may enumerate visible top-level windows,
  filter `War Thunder` window-title candidates, and query only the image identity
  and token elevation of exact War Thunder executable names using
  `PROCESS_QUERY_LIMITED_INFORMATION` and `TOKEN_QUERY`;
  it must not take process snapshots, inspect modules or anti-cheat internals,
  read process memory, or use the result for any purpose except choosing whether
  to show the optional privileged-hotkey action.
- `R8111-09`: `tools/record_8111_session.py` MUST use the fixed official 8111
  base and only `/indicators`, `/state`, `/map_obj.json`, and `/map_info.json`;
  its CLI MUST NOT accept an alternate API base.
- `R8111-10`: Recorder-generated metadata MUST omit local user, account, and
  host identifiers; the recorder MUST default to the gitignored local
  `recordings/` directory and MUST NOT upload captures or inspect any process,
  memory, module, packet, log, or game file.
- `R8111-11`: Each completed recorder file MUST contain metadata, synchronized
  decoded endpoint payloads with response diagnostics and body hashes, and a
  summary; `Ctrl+C` MUST finalize a readable file rather than leaving the normal
  output path partial, and every JSONL record MUST conform to
  `docs/specs/schemas/8111-session-record.schema.json`.
- `R8111-12`: Replay MUST first validate every record plus stream order,
  monotonic sample time, summary counts, endpoint statistics, and aircraft types.
  Replay MUST consume only the selected local session file and MUST NOT make a
  network request, inspect a process, or replace the runtime App's default HTTP
  source.
- `R8111-13`: Replay MUST drive production `GameLogic` with a virtual wall clock
  derived from recording elapsed time. Normal App construction MUST retain the
  system wall clock and official 8111 HTTP source; real monotonic timing MAY
  remain in performance diagnostics and replay pacing.
- `R8111-14`: The `full-sortie` profile MUST fail unless it processes every
  sample and observes lobby endpoint failure, the alive phase, at least two
  takeoffs, a landing, refit, bomb-release pulse, 15-minute cycle rollover,
  critical overspeed, and player-object loss. Passing offline replay does not
  claim Tk rendering, global-hotkey, capture-cadence, or real-game smoke
  coverage.
- `R8111-15`: A raw recording promoted to `tests/fixtures/8111/` MUST be copied
  byte-for-byte only after full session validation, MUST retain equal source and
  fixture SHA256 values in a manifest conforming to
  `docs/specs/schemas/8111-replay-fixture-manifest.schema.json`.
- `R8111-16`: Every tracked raw fixture MUST replay with exact manifest coverage
  in the standard pytest suite; coordinates MAY be retained, but recorder-omitted
  user, account, host, and process identity fields MUST remain absent.
- `R8111-17`: Trace back sampling MUST update its last-coordinate candidate only
  from a successful `/map_obj.json` response containing valid Player
  coordinates.
- `R8111-18`: Trace back MUST confirm a candidate only on
  `LOSS_PENDING -> WAIT_NEXT` after uninterrupted successful non-empty map
  responses without Player; source failure, an empty response, or Player
  recovery MUST cancel the pending absence.
- `R8111-19`: Confirmed Trace back coordinates MUST remain process-memory-only
  and MUST NOT be written to App settings, timer restore, logs, or other
  persistent storage.
- `R8111-20`: A same-battle respawn MUST retain the confirmed Trace back point,
  while `prepare_new_battle_context()` and `reset_life_state()` MUST clear it.
- `R8111-21`: `MapImageFetcher` MUST use a dedicated proxy-disabled session,
  the fixed official loopback URL, bounded connect/read timeouts, streaming
  reads, and a hard decoded-body ceiling of 4 MiB. It MUST accept only PNG or
  JPEG image content and MUST fail closed on missing/invalid type, oversized
  declared or streamed bodies, request errors, or non-success status.
- `R8111-22`: The App MAY run one low-cadence map-image worker only while the
  Web Cockpit is running. That worker MUST remain outside Tk, publish an
  immutable in-memory image snapshot, stop with bounded shutdown, and MUST NOT
  persist, log, transform, upload, or expose the raw 8111 URL to the browser.

## Contract Coverage

- [static] `tests/contracts/test_runtime_8111_boundary.py` enforces
  `R8111-01`, `R8111-02`, `R8111-04`, `R8111-06`, `R8111-08..R8111-10`, and
  `R8111-12` by checking the runtime base URL, endpoint whitelist, dangerous API
  strings, ownership, polling defaults, narrow process-query allowlist,
  recorder boundaries, and the replay adapter's lack of network/process paths.
- [behavioral] `tests/test_telemetry_fetch_result.py` and
  `tests/test_map_objects_contract.py` enforce the current-contact visibility,
  hostile-unit classification, fetcher, and coordinate ownership boundaries in
  `R8111-03` and `R8111-04`.
- [behavioral] `tests/test_8111_recorder.py` enforces `R8111-10` and `R8111-11`
  with synchronized raw-payload capture, diagnostics, overwrite, timeout, and
  `Ctrl+C` finalization cases.
- [behavioral] `tests/contracts/test_8111_session_schema.py` enforces
  `R8111-11` and `R8111-12` with schema round-trip, shared validator use, and
  tamper rejection.
- [behavioral] `tests/test_8111_replay.py` enforces `R8111-12..R8111-16` with
  complete-stream validation, sequence tamper rejection, virtual-time production
  logic replay, every `full-sortie` coverage gate, and byte/hash/schema/timeline
  verification of the tracked real-session fixture.
- [behavioral] `tests/test_traceback.py` enforces `R8111-17`, `R8111-18`, and
  `R8111-20` by separating raw Player samples from endpoint failures and empty
  frames, pinning confirmation to the existing loss transition, preserving the
  point across respawn, and clearing it at battle-context reset.
- [behavioral] `tests/test_telemetry_fetch_result.py`,
  `tests/test_runtime_threading.py`, and `tests/test_runtime_services.py`
  enforce `R8111-21` and `R8111-22` with type/size/stream failures, immutable
  publication, low-cadence lifecycle, and bounded stop cases.
- [manual] Runtime/data review covers the player-visible-information boundary in
  `R8111-03`; handoffs must record real War Thunder smoke for `R8111-05`,
  explicit approval for polling changes under `R8111-06`, and provenance review
  for data refreshes under `R8111-07`; runtime/data-flow review covers the
  process-memory-only persistence boundary in `R8111-19`.
