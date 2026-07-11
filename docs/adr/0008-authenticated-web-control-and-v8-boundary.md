# ADR 0008: Add authenticated semantic Web control and an App 8 boundary

Status: Accepted (2026-07-11)

Supersedes: ADR 0007's read-only decision; its independent non-8111 Web
Cockpit, filtered projection, self-hosted UI, and explicit current-run LAN
access decisions remain in force.

## Context

The independent Web Cockpit now provides the correct desktop/mobile projection,
but read-only access cannot operate Bomana's existing timer, window, audio,
panel, weapon-selection, or ballistic-model semantics. Reusing global function
keys on a phone would be awkward and would incorrectly couple Web control to
Windows input and the optional privileged hotkey broker.

The change also makes App 8 and its launcher handoff intentionally incompatible
with earlier launchers. Existing launcher checks protect a new App from an old
Launcher through the signed `min_launcher_version`, but the reverse paths did
not yet share one fail-closed App-version boundary across launch, installation,
import, rollback, and recovery.

## Decision

Bomana will expose one paired command route containing only the eight semantic
commands in `docs/specs/web-dashboard.md`. HTTP workers authenticate, validate,
deduplicate, and enqueue immutable envelopes; the Tk owner thread reauthorizes
and executes exact existing App semantics. The browser polls a separate bounded
control-state projection for completion. Web control will never synthesize
keys, name callbacks, reflect over App objects, accept arbitrary config paths,
or extend the privileged broker.

Every successful pairing creates a distinct session. Loopback pairings may
control. LAN pairings remain view-only until the user explicitly enables LAN
control for the current run; enabling rotates the pairing code and affects only
later pairings. Revocation invalidates existing LAN-control sessions
immediately. No LAN, control, pairing, session, CSRF, or authorization state is
persisted.

Launcher 3 may persist only `web_dashboard_autostart` and
`web_dashboard_auto_open`. The App owns listener creation, selected port,
pairing URLs, browser-open timing, and all LAN/control runtime state.

App `8.0.0` requires Launcher `3.0.0` or newer, and Launcher `3.0.0` requires
App `8.0.0` or newer. `bomana_version.py` is the shared strict `X.Y.Z` boundary
for packaged App identity and every Launcher candidate path. Packaged App
identity is checked before runtime imports; only explicit
`BOMANA_SOURCE_DEVELOPMENT=1` in a non-frozen process may bypass a missing
launcher identity.

Release manifest schema version 1, Ed25519 verification order, and both signed
field sets remain unchanged. A verified online manifest version is compared
exactly with staged App metadata before any valid installation is replaced.

## Consequences

- Phones receive explicit buttons and target-state controls instead of emulated
  F7-F11 input, while desktop hotkeys retain their existing behavior.
- Browser acceptance is asynchronous: HTTP 202 means queued, not completed;
  completion is read from the session's bounded control-state history.
- LAN control is deliberately more cumbersome than LAN viewing and must be
  re-enabled and re-paired after every App start or revocation.
- Launcher 3 cannot launch, import, recover, or roll back to an App 7 package;
  compatibility failures preserve the current valid installation.
- Direct source execution now needs an explicit development marker when it does
  not arrive through Launcher bootstrap; frozen builds never honor that bypass.
- Physical phone/LAN/revocation, Firewall, multi-NIC, packaged DPI/browser, and
  live-game synchronization remain manual release gates.
