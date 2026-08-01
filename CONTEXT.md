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

## Strike Prediction

**Strike Prediction**:
The Super Bomb Edition capability that derives weapon guidance from official 8111 observations, user-selected configuration, bundled static data, and offline terrain.
_Avoid_: Native game solution, memory-assisted prediction
