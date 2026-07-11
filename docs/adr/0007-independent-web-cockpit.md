# ADR 0007: Serve an independent Bomana Web Cockpit

Status: Accepted (2026-07-11)

## Context

AirSim augments War Thunder's browser map by running a userscript inside the
`*:8111` origin, hiding parts of the original DOM, depending on undocumented page
globals, and appending its own panels. That is convenient on one configured
desktop browser, but it requires a userscript manager per browser, does not solve
mainstream mobile-browser access, and inherits upstream DOM/global changes.

War Thunder already owns port `8111`. Bomana cannot take over that listener
without a system/browser proxy, and a generic reverse proxy would risk exposing
unknown 8111 routes beyond Bomana's four-endpoint boundary.

## Decision

Bomana will serve a standalone, read-only Web Cockpit on its own port. The page
will consume a versioned projection of Bomana's existing `UISnapshot`; it will
not contact 8111 directly. Loopback access starts with Bomana. LAN access is
enabled explicitly for the current process, binds one private interface, and is
protected by a rotating pairing secret and same-origin session cookie.

The first version uses a Bomana-designed responsive interface and a normalized
vector tactical map. It will not copy AirSim code, licensed assets, layout, or
green MFD visual styling. A future browser extension may be a thin link/redirect
to this same dashboard, but it must not duplicate telemetry or solver logic.

## Consequences

- Desktop and mobile browsers share one implementation with no extension.
- Bomana remains the only 8111 poller and can filter data before LAN exposure.
- LAN users may need to allow the packaged App through Windows Firewall.
- The first map has no official terrain image; adding `/map.img` would require a
  separate boundary amendment and provenance/runtime validation.
- LAN HTTP is not encrypted. Pairing limits casual access, so users must enable
  it only on trusted local networks.
