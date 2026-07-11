# Bomana Web Cockpit Work Order

> Repo: `D:\Dev\Bomana`. This work order governs the 2026-07-11 local/LAN
> dashboard upgrade. `AGENTS.md` remains authoritative for repository-wide
> constraints; on a real conflict, stop and report instead of weakening either.

## 0. Role and decision

The orchestrator will add a Bomana-native responsive web cockpit on a dedicated
port. It will not replace, proxy, or modify War Thunder's `8111` page. AirSim is
comparison evidence only: its code, visual language, and non-standard licensed
assets must not be copied.

## 1. Context

- `GameLogic` is the only live 8111 polling owner.
- `UISnapshot` is the thread-safe core-to-presentation channel.
- `App` owns the Tk refresh loop; background services must never call Tk.
- `AppRuntimeServices` owns tray and auxiliary runtime lifecycles.
- Portable App ZIPs include the whole `bomana/` tree; legacy PyInstaller builds
  include `bomana/assets/` explicitly.
- Canonical contracts live in `docs/specs/`; all work is tracked by
  `Bomana-omis`.

## 2. Invariants

- `INV-1`: Runtime game data remains limited to the official four 8111 endpoints;
  the dashboard server must not poll, proxy, or expose raw 8111 responses.
- `INV-2`: The dashboard must never bind port `8111`, inject browser/game code,
  touch game files, read game memory, or add a browser-extension dependency.
- `INV-3`: The web map may show ownship, zones, airfields, POIs, selected targets,
  and Trace back only; it must not publish hostile-aircraft contacts.
- `INV-4`: Loopback starts automatically; LAN access is current-run-only and
  requires an explicit user action on a trusted network.
- `INV-5`: LAN data is read-only, paired with a per-process secret, self-hosted,
  and never logged or persisted.
- `INV-6`: HTTP threads may read only immutable published presentation state and
  must not call Tk; tray callbacks cross `TkEventDispatcher`.
- `INV-7`: No CDN, analytics, remote fonts, `eval`, inline script, UPnP, firewall
  mutation, administrator request, or new Internet request is permitted.
- `INV-8`: Existing `ENABLE_*` and panel behavior stay authoritative; disabled
  capabilities must not be recreated through the web surface.
- `INV-9`: Ruff and the full test suite must pass; tests may not be skipped or
  weakened to land the feature.
- `INV-10`: Real phone, firewall, multi-NIC, and live-game checks remain explicit
  manual smoke; automated tests must not claim them.

## 3. Phases

1. Record the independent-dashboard decision in an ADR and Draft canonical spec.
2. Add the schema-backed, headless snapshot presenter and filtered map scene.
3. Add a standard-library HTTP runtime with pairing, host/origin validation,
   strict headers, explicit routes, and bounded shutdown.
4. Add self-hosted responsive Bomana assets and connect App/tray lifecycle.
5. Update packaging, architecture, privacy, quick-start, changelog, and smoke docs.
6. Run focused server/browser tests, contract tests, full gates, read-only review,
   then close `Bomana-omis`, commit, and push.

## 4. Agent boundaries

Research and review agents are read-only. Production code and tests are
orchestrator-owned. A documentation-only agent may edit the public/docs files
named in phase 5 after receiving an explicit path scope; the orchestrator must
re-read and accept that diff. The final reviewer is read-only and must return
PASS or FAIL with an evidence-backed punch list. No reviewer may silently repair
findings.

## 5. Definition of done

- A desktop browser can open the loopback cockpit without any extension.
- Explicit LAN enablement returns a private-IP URL and a short pairing code.
- An authenticated browser receives a schema-valid live snapshot and vector map;
  unauthenticated, wrong-host, wrong-origin, traversal, and unsupported-method
  requests fail closed.
- The dashboard has no control route and no hostile-contact output.
- Shutdown releases every HTTP listener.
- Source, packaged-resource, contract, Ruff, and pytest gates pass.

## 6. Manual smoke still required

- War Thunder live data and map movement on desktop.
- A second phone/tablet on the same trusted LAN, including pairing and reconnect.
- Windows Firewall prompt/allow-deny behavior and a machine with multiple private
  adapters.
- Packaged Enhanced/Standard/Lite resource loading.
