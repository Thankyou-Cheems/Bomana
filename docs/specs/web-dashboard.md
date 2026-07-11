# Web Dashboard Spec

Status: Draft
Owner: Bomana maintainers
Prefix: `WDB-`

## Scope

This spec governs the Bomana Web Cockpit HTTP runtime, snapshot and control-state
projections, authenticated semantic commands, static browser assets, local/LAN
access, packaging, threading, privacy, and tray lifecycle.

## Non-goals

- This spec does not authorize new War Thunder endpoints, a terrain-map fetch,
  browser/game injection, game-file changes, or direct game input.
- It does not make Bomana a general reverse proxy or remote administration API.
- It does not authorize arbitrary config paths, keyboard synthesis, reflection,
  arbitrary callbacks, elevated-broker changes, or new network capabilities.
- It does not claim that automated tests replace phone, firewall, multi-NIC,
  packaged-build, DPI, or live War Thunder smoke.

## Normative Clauses

- `WDB-01`: When Web autostart is enabled, the App MUST start a dedicated
  non-8111 listener on `127.0.0.1`; when disabled, only an explicit App action
  may lazily start that same loopback listener.
- `WDB-02`: LAN listening MUST require an explicit current-run user action and
  MUST bind one discovered RFC1918 IPv4 address rather than `0.0.0.0`.
- `WDB-03`: Bomana MUST NOT persist LAN access, LAN control, selected listener
  address or port, pairing material, authorization epochs, or Web sessions.
- `WDB-04`: The HTTP runtime MUST consume only published immutable projections
  owned by the App; it MUST NOT request, proxy, or forward any 8111 route.
- `WDB-05`: HTTP workers MUST NOT import or call Tk or directly read or mutate
  App state or config persistence.
- `WDB-06`: `/api/v1/snapshot` responses MUST conform to
  `docs/specs/schemas/web-dashboard-snapshot.schema.json`.
- `WDB-07`: The map projection MUST be limited to ownship, zones, airfields,
  POIs, current selected targets, and Trace back; hostile-aircraft contacts and
  raw map payloads MUST NOT be published.
- `WDB-08`: Every process MUST generate fresh high-entropy pairing material, and
  every rotation MUST immediately invalidate the preceding pairing code.
- `WDB-09`: Every successful pairing MUST create a distinct session token,
  authorization record, CSRF proof, and bounded idempotency store.
- `WDB-10`: Snapshot and control-state access MUST fail closed without a valid
  `HttpOnly; SameSite=Strict` session cookie, and pairing failures MUST be
  bounded per client and time window.
- `WDB-11`: The server MUST validate `Host` against loopback or the active
  private listener and MUST NOT emit permissive CORS headers.
- `WDB-12`: HTML, API, and error responses MUST emit `no-store`, `nosniff`,
  `no-referrer`, frame denial, and a self-only CSP that forbids external assets,
  plugins, embedding, and `eval`.
- `WDB-13`: HTTP routes MUST be explicit; the only authenticated write route is
  `POST /api/v1/commands`, and all other API routes MUST be read-only.
- `WDB-14`: The runtime MUST NOT log client IPs, request paths, query strings,
  pairing codes, session tokens, CSRF proofs, idempotency keys, command bodies,
  or telemetry payloads, and MUST NOT persist dashboard projections.
- `WDB-15`: The browser UI MUST load all HTML, CSS, JavaScript, and fonts from
  packaged Bomana resources and MUST NOT use a CDN, remote font, analytics
  script, or external request.
- `WDB-16`: The App MUST stop local and LAN listeners with bounded shutdown
  before destroying Tk, and stopped listener addresses MUST be reusable.
- `WDB-17`: Every build variant MUST package the dashboard modules, schemas, and
  assets while existing `ENABLE_*` switches remain authoritative.
- `WDB-18`: The tray MUST keep local open and current-run LAN actions
  discoverable without adding a new always-visible primary App surface.
- `WDB-19`: Release handoffs MUST report desktop browser, phone/LAN, Windows
  Firewall, multi-NIC, packaged-resource, DPI, and live-game smoke separately
  from CI.
- `WDB-20`: A successful loopback pairing MAY receive `control` scope, but a LAN
  pairing MUST receive `view` scope while current-run LAN control is disabled.
- `WDB-21`: Enabling LAN control MUST require an explicit current-run App action,
  rotate the pairing code, and grant `control` scope only to later successful
  LAN pairings.
- `WDB-22`: Revoking LAN control MUST immediately advance the authorization
  epoch, invalidate every LAN-control session, and rotate the pairing code.
- `WDB-23`: `GET /api/v1/control-state` MUST return a non-empty per-session CSRF
  proof only to `control` sessions and MUST return `null` for `view` sessions.
- `WDB-24`: Every Web write MUST have a currently valid `control` session and a
  non-empty `X-Bomana-CSRF` value matching that session in constant time. The
  final submission lock MUST recheck the session maximum age after request
  parsing and before queue acceptance.
- `WDB-25`: Every Web write MUST have exactly one non-empty `Origin` whose
  serialized origin exactly equals the request's validated Bomana origin;
  missing, `null`, multiple, or merely allowlisted origins MUST be rejected.
- `WDB-26`: Every Web write MUST use exactly `application/json`, a decimal
  `Content-Length` from 1 through 4096 bytes, no `Transfer-Encoding`, one JSON
  value, and no trailing non-whitespace bytes.
- `WDB-27`: Every Web command body MUST validate against the production-loaded
  `docs/specs/schemas/web-dashboard-command.schema.json` before queueing.
- `WDB-28`: Every Web write MUST carry one `Idempotency-Key` matching
  `[A-Za-z0-9][A-Za-z0-9._:-]{0,127}`, and each session MUST retain at most 128
  distinct keys without evicting an accepted key during that session.
- `WDB-29`: Reuse of a retained key with the same canonical validated body MUST
  return the original accepted response without re-execution; reuse with a
  different canonical body MUST return `409 idempotency_conflict`.
- `WDB-30`: A validated command accepted by the dispatcher queue MUST return
  HTTP 202 with `schema_version: 1`, `command_id` equal to the idempotency key,
  `status: "queued"`, and the captured `submitted_revision`.
- `WDB-31`: An unavailable dispatcher queue MUST return
  `503 queue_unavailable`, MUST NOT create an accepted idempotency record, and
  MUST NOT execute the command later.
- `WDB-32`: The queued envelope MUST be immutable and MUST capture the session,
  transport, control scope, authorization epoch, command id, canonical command,
  and submitted revision.
- `WDB-33`: The Tk owner thread MUST recheck the session's authorization epoch,
  control scope, maximum age, and current-run LAN-control authority immediately
  before execution.
- `WDB-34`: The Tk owner thread MUST recheck every applicable `ENABLE_*` gate,
  catalog identity, aircraft compatibility, enum, and target validity
  immediately before execution.
- `WDB-35`: Tk completion MUST publish exactly one bounded `recent_commands`
  entry with `succeeded` or `rejected`, a stable reason code, the submitted
  revision, and the resulting monotonically increasing control-state revision.
- `WDB-36`: The browser MUST discover completion by polling
  `GET /api/v1/control-state`; the POST handler MUST NOT wait for Tk or return a
  synchronous timeout for work that can execute later.
- `WDB-37`: The Complete Action Matrix below is exhaustive; the server and Tk
  executor MUST reject every command or field combination not listed there.
- `WDB-38`: Web command dispatch MUST NOT use reflection, arbitrary callback
  names, synthesized keyboard input, arbitrary config paths, arbitrary commands,
  generic toggles for target-state commands, or any elevated broker path.
- `WDB-39`: Command responses and control-state responses MUST conform to
  `web-dashboard-command-response.schema.json` and
  `web-dashboard-control-state.schema.json`, respectively.
- `WDB-40`: `GET /api/v1/control-state` MUST expose only the current session's
  permissions, applicable capabilities, semantic target state, bounded weapon
  choices, and that session's bounded recent command completions.
- `WDB-41`: A matrix command that requires persistence MUST publish `succeeded`
  only after both target state and existing config representation commit; a
  persistence failure MUST leave the prior target state effective and publish
  `persistence_failed`.
- `WDB-42`: Completion reasons MUST be exactly `ok`,
  `authorization_revoked`, `feature_disabled`, `invalid_target`,
  `weapon_not_found`, `weapon_incompatible`, `state_unavailable`,
  `persistence_failed`, or `execution_failed`.
- `WDB-43`: Before queueing, the HTTP layer MUST reject a command absent from
  the session's current immutable capabilities as `409 capability_unavailable`;
  this early check MUST NOT replace the Tk rechecks in `WDB-33` and `WDB-34`.

## Complete Action Matrix

| Command | Exact request fields after `schema_version` and `command` | Tk-owned semantic result | Required server/Tk rechecks |
|---|---|---|---|
| `action.reset_timer` | `confirmed: true` | Invoke the existing immediate manual timer reset once; do not synthesize the reset hotkey or its double-press state. | Current authorization and target App availability. |
| `action.cycle_corner` | none | Advance once to the next existing `Corner` and persist through the existing config path. | Current authorization and available corner set. |
| `state.set_locked` | `locked: boolean` | Set the App/window lock to the explicit target state and persist it; an already-satisfied target remains a successful no-op. | Current authorization and valid window state. |
| `state.set_beep_enabled` | `enabled: boolean` | Set the existing sound manager to the explicit target state and persist it; an already-satisfied target remains a successful no-op. | Current authorization and sound manager availability. |
| `state.set_zone_sound_enabled` | `enabled: boolean` | Set the existing zone-sound preference to the explicit target state and persist it. | Current authorization and `ENABLE_ZONES`. |
| `config.set_panel_visibility` | `target: zones|airfields|fuel|speed|checklist|weapon_solution`; `enabled: boolean` | Set exactly one existing panel preference and persist it. | `zones` -> `ENABLE_ZONES`; `airfields` -> `ENABLE_AIRFIELDS`; `fuel` -> `ENABLE_FUEL`; `speed` -> always available; `checklist` -> `ENABLE_CHECKLIST`; `weapon_solution` -> `ENABLE_CCRP`; plus current effective-state validity. |
| `weapon.select` | `weapon_id: non-empty string` | Select and persist exactly that existing catalog weapon id through the existing manual-selection semantic path. | Current authorization, `ENABLE_CCRP`, exact catalog membership, and current-aircraft compatibility. |
| `weapon.set_ballistic_model` | `model: foxthree_compatible|strict_official` | Set and persist exactly that existing ballistic model. | Current authorization, `ENABLE_CCRP`, and exact enum membership. |

Persistence and stable completion-reason semantics are governed by `WDB-41` and
`WDB-42`.

## Contract Coverage

- [static] `tests/contracts/test_web_dashboard_contract.py` enforces
  `WDB-01..WDB-09`, `WDB-11..WDB-18`, and `WDB-20..WDB-43` through ownership
  scans, forbidden-path scans, schema
  self-checks, the exhaustive action discriminants, packaged assets, and
  response shapes.
- [behavioral] `tests/test_web_dashboard_presenter.py` enforces `WDB-04`,
  `WDB-06`, `WDB-07`, `WDB-14`, and `WDB-17` with schema-valid finite snapshot
  projection, feature gating, and hostile/raw-field exclusion.
- [behavioral] `tests/test_web_dashboard_server.py` enforces `WDB-01..WDB-03`,
  `WDB-08..WDB-16`, `WDB-20..WDB-31`, `WDB-33`, `WDB-36`, `WDB-39`, and
  `WDB-40` with
  real ephemeral listeners, distinct pairing sessions, scope/revocation,
  submit/Tk-recheck expiry boundaries, Host/Origin/CSRF/body/idempotency cases,
  headers, and port reuse.
- [behavioral] `tests/test_runtime_services.py` enforces `WDB-01..WDB-05`,
  `WDB-16`, `WDB-18`, `WDB-20..WDB-22`, and `WDB-32..WDB-36` with autostart,
  lazy-start, publish, LAN-control, revocation, dispatcher, and shutdown cases.
- [behavioral] `tests/test_ui_app_config.py` enforces `WDB-33..WDB-35` and
  `WDB-37..WDB-42` with Tk reauthorization, feature/target rechecks, airborne
  weapon compatibility, rollback-on-save-failure, and completion reasons.
- [behavioral] `tests/test_build_metadata.py` enforces `WDB-17` by building all
  three App variants and checking their Web modules, schemas, and assets.
- [manual] Trusted-LAN phone/control/revoke, firewall allow/deny, multi-NIC,
  packaged variant, DPI, and live War Thunder checks cover `WDB-02`, `WDB-03`,
  `WDB-15..WDB-22`, `WDB-33..WDB-36`, and `WDB-40` without claiming automated
  equivalence.
