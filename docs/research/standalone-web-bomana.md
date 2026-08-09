# Standalone Web Bomana Research

Status: Design research retained on 2026-08-09; not implemented or released.

## Objective

Offer a discoverable Bomana browser experience that can run without an
in-game overlay, while keeping the Launcher a local orchestrator rather than a
web-application host.

The public website preview and the application web surface are separate. The
preview is a normal public page for product and account information. The
standalone web surface is application runtime behavior and must not be shown as
available before a released artifact declares it.

## Preserved decisions

1. The Launcher owns discovery and handoff. The selected application owns the
   web server, routes, ports, browser behavior, and feature settings.
2. Optional Launcher actions come from signed artifact capabilities, including
   `web_overlay` and `web_standalone`; channel names are not feature flags.
3. Missing or unknown capabilities fail closed. Historical applications remain
   startable, but new web actions stay hidden.
4. The public and subscriber repositories remain separate. Shared contracts
   may live in the public repository, while paid implementation and data stay
   within the subscriber boundary.
5. DAU collection remains one Bomana product metric across public, subscriber,
   overlay, and standalone-web surfaces. A repository or edition split must
   not create separate headline DAU series.

## Analytics boundary

The standalone surface should reuse the privacy-safe daily-active signal and
the same aggregate history used by the desktop editions. It must not add page
tracking, raw browsing history, account identifiers, coordinates, map choices,
or weapon selections merely because it runs in a browser.

Collection can stay unified before cross-surface deduplication is finalized.
Before implementation, define whether one installation using both desktop and
standalone surfaces on the same day contributes one or two active signals, and
document the stable anonymous key used to enforce that definition.

## Questions before implementation

- Is the standalone surface served by a local application process, a remote
  service, or both?
- How does a browser session prove the selected public or subscriber edition
  without exposing a reusable entitlement secret?
- Which origins, loopback bindings, CSRF protections, and browser-launch rules
  are required?
- Which signed manifest owns `web_standalone`, its URL or launch parameters,
  and its minimum compatible Launcher version?
- What is the exact same-day deduplication rule for unified DAU across surfaces
  and editions?
- Which functions remain local-only when terrain or subscriber data must not
  cross the repository and delivery boundaries?

## Evidence required to call it released

- A signed released artifact declares `web_standalone`.
- The Launcher hides the action for older or unsupported artifacts and exposes
  it only for the declared capability.
- Browser startup, local/remote failure behavior, authorization, and downgrade
  behavior are exercised end to end.
- DAU reaches the unified aggregate without collecting disallowed fields or
  double-counting contrary to the documented metric definition.

Until all four conditions are met, this document describes a design direction,
not a current Bomana feature.
