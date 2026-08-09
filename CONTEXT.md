# Bomana Product Editions

Bomana provides public flight-assistance editions and a subscriber-only strike-prediction edition while preserving stable release identities for existing installations.

## Editions

**Public Edition**:
An edition whose complete implementation, data, and release definition are available from the public Bomana repository without an entitlement. Lite and Standard are Public Editions.
_Avoid_: Free tier, community edition

**Lite**:
The minimal Public Edition centered on the respawn timer and essential status display.
_Avoid_: Trial, demo

**Standard**:
The basic Public Edition that adds navigation, fuel, and checklist capabilities without Strike Prediction or Web Cockpit.
_Avoid_: Basic tier, free Enhanced

**Subscriber Edition**:
An edition whose differentiated implementation and data are delivered only to a user with an active Entitlement. Super Bomb Edition is the Subscriber Edition.
_Avoid_: Premium flag, paid build

**Super Bomb Edition**:
The Subscriber Edition containing Strike Prediction, offline terrain support, and Web Cockpit. Its stable Release Channel is `Enhanced`.
_Avoid_: Enhanced source edition, full public edition

## Subscription

**Entitlement**:
The time-bounded right, owned by CheemsPay, for a user and an allowed set of devices to use the Super Bomb Edition.
_Avoid_: License key, purchase flag

**Subscription Receipt**:
A device-bound, signed proof of an Entitlement that Bomana can evaluate without a live CheemsPay request.
_Avoid_: Session token, activation code

## Release

**Release Channel**:
The stable artifact identity used by Launcher manifests and installed state. `Lite`, `Standard`, and `Enhanced` are Release Channels; a Release Channel is not an access decision.
_Avoid_: Edition access, subscription plan

## Web Surfaces

**Website Preview Entry**:
A Launcher action that opens the public Bomana website in the user's external browser. It is promotional and account-facing, not an application runtime surface.
_Avoid_: Embedded Web Cockpit, standalone web application

**Web Surface Launch Control**:
A discoverable Launcher action that hands off to an application-provided browser surface. The application owns its server, routes, ports, capabilities, and feature behavior.
_Avoid_: Launcher-hosted web application, inferred channel feature

**Signed Capability Metadata**:
Verified artifact metadata that declares optional application surfaces such as `web_overlay` and `web_standalone`. Unknown or absent capabilities fail closed, so their Launcher actions remain hidden.
_Avoid_: Channel-name inference, optimistic feature detection

**Standalone Web Surface**:
The planned Bomana browser surface that does not depend on an in-game overlay. It is research-only until a released artifact declares `web_standalone` through Signed Capability Metadata.
_Avoid_: Current feature, public website preview

## Strike Prediction

**Strike Prediction**:
The Super Bomb Edition capability that derives weapon guidance from official 8111 observations, user-selected configuration, bundled static data, and offline terrain.
_Avoid_: Native game solution, memory-assisted prediction
