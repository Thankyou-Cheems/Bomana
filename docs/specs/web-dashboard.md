# Web Dashboard Spec

Status: Draft
Owner: Bomana maintainers
Prefix: `WDB-`

## Scope

This spec governs the Bomana Web Cockpit HTTP runtime, its snapshot projection,
static browser assets, local/LAN access, authentication, packaging, threading,
privacy, and tray lifecycle.

## Non-goals

- This spec does not authorize new War Thunder endpoints, a terrain-map fetch,
  game commands, remote control, browser/game injection, or game-file changes.
- It does not make Bomana a general reverse proxy and does not govern AirSim.
- It does not claim that automated tests replace phone, firewall, multi-NIC,
  packaged-build, or live War Thunder smoke.

## Normative Clauses

- `WDB-01`: Bomana MUST serve the Web Cockpit on a dedicated non-8111 port and
  MUST start the primary listener on `127.0.0.1` only.
- `WDB-02`: LAN listening MUST require an explicit current-run user action and
  MUST bind one discovered RFC1918 IPv4 address rather than `0.0.0.0`.
- `WDB-03`: Bomana MUST NOT persist LAN-enabled state, add firewall/UPnP rules,
  request elevation, or expose the listener to a public address.
- `WDB-04`: The HTTP runtime MUST consume only a published immutable projection
  of `UISnapshot`; it MUST NOT request, proxy, or forward any 8111 route.
- `WDB-05`: The HTTP runtime MUST NOT import or call Tk, and tray callbacks that
  open, copy, enable, or disable access MUST cross `TkEventDispatcher.post()`.
- `WDB-06`: `/api/v1/snapshot` responses MUST conform to
  `docs/specs/schemas/web-dashboard-snapshot.schema.json`.
- `WDB-07`: The map projection MUST be limited to ownship, zones, airfields,
  POIs, current selected targets, and Trace back; hostile-aircraft contacts and
  raw map payloads MUST NOT be published.
- `WDB-08`: Every process MUST generate a new high-entropy session token and a
  short pairing code; successful pairing MUST replace the code-bearing URL with
  an HttpOnly `SameSite=Strict` session cookie.
- `WDB-09`: Snapshot access MUST fail closed without a valid session cookie, and
  failed pairing attempts MUST be bounded per client and time window.
- `WDB-10`: The server MUST validate `Host` against loopback or the active private
  listener and MUST reject a non-matching `Origin`; it MUST NOT emit permissive
  CORS headers.
- `WDB-11`: HTML, API, and error responses MUST emit `no-store`, `nosniff`,
  `no-referrer`, frame-denial, and a self-only CSP that forbids external assets,
  plugins, embedding, and `eval`.
- `WDB-12`: HTTP routes MUST be explicit and read-only except for the pairing
  cookie redirect; directory browsing, path traversal, arbitrary file reads,
  generic proxying, game control, and configuration mutation MUST be absent.
- `WDB-13`: The runtime MUST NOT log client IPs, request paths, query strings,
  pairing codes, session tokens, or telemetry payloads, and MUST NOT persist
  dashboard snapshots.
- `WDB-14`: The browser UI MUST load all HTML/CSS/JS/fonts from packaged Bomana
  resources and MUST NOT use a CDN, remote font, analytics script, or external
  request.
- `WDB-15`: The App MUST stop local and LAN listeners with bounded shutdown before
  destroying Tk, and stopped listener addresses MUST be reusable.
- `WDB-16`: Every build variant MUST package the dashboard assets, while existing
  `ENABLE_*` switches remain authoritative over which capabilities are exposed.
- `WDB-17`: The tray MUST provide a discoverable local open action and, when LAN
  is active, a private-IP share action plus pairing code without introducing a
  new always-visible main-window panel.
- `WDB-18`: Release handoffs MUST report real desktop browser, phone/LAN, Windows
  Firewall, multi-NIC, packaged-resource, and live-game smoke separately from CI.

## Contract Coverage

- [static] `tests/contracts/test_web_dashboard_contract.py` enforces
  `WDB-01..WDB-05`, `WDB-07`, `WDB-10..WDB-14`, `WDB-16`, and `WDB-17` by
  checking ownership, forbidden imports/routes/data, dispatcher paths, packaged
  assets, and self-hosted browser resources.
- [behavioral] `tests/test_web_dashboard_presenter.py` enforces `WDB-04`,
  `WDB-06`, `WDB-07`, `WDB-13`, and `WDB-16` with schema-valid finite projection,
  feature gating, and hostile/raw-field exclusion.
- [behavioral] `tests/test_web_dashboard_server.py` enforces `WDB-01..WDB-03`,
  `WDB-08..WDB-15` with real ephemeral listeners, pairing/rate-limit cases,
  Host/Origin/CORS/header/path/method cases, and port-reuse shutdown.
- [behavioral] `tests/test_runtime_services.py` enforces `WDB-05` and `WDB-15`
  with publish, startup-failure, LAN toggle, and shutdown lifecycle cases.
- [behavioral] `tests/test_build_metadata.py` enforces `WDB-16` by building all
  three App variants and checking their Web Cockpit modules and assets in ZIPs.
- [manual] Trusted-LAN phone, firewall allow/deny, multi-NIC, packaged variant,
  and live War Thunder checks cover `WDB-02`, `WDB-03`, `WDB-14..WDB-16`, and
  `WDB-18` without claiming automated equivalence.
