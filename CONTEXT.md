# Bomana Product Language

Bomana is one App presented through Web and connected to official local game data by Bridge.

## Language

**Web**:
The browser presentation of Bomana App.
_Avoid_: Desktop App, Web Edition

**Online Launcher**:
The Web entry at `bomana.ruikang.wang/launcher/` that discovers Bridge and opens an Edition.
_Avoid_: Desktop Launcher, installer

**Bridge**:
The local read-only companion that exposes fixed official 8111 routes and owns the Local Data Store.
_Avoid_: backend, solver, authenticator

**Bridge Tray Pairing**:
The account-blind local Bridge page that displays a temporary phone QR. Phone Web obtains its own signed lease when needed; Bridge verifies it without receiving an account access token.
_Avoid_: Bridge login, bundled Enhanced App, cloud relay

**Bridge Diagnostics**:
The bounded single-file connectivity reporter for Bridge ports, browser policy, and official 8111 reachability. It records no account authorization, pairing secret, game value, map, chat, or raw 8111 body.
_Avoid_: support bundle, telemetry upload, game logger

**Lite**:
The timer-only public Edition.
_Avoid_: trial, demo

**Standard**:
The public Edition with Basic Navigation, fuel, checklist, and reference capabilities.
_Avoid_: free Enhanced

**Basic Navigation**:
Official zone and airfield selection with bearing, distance, and heading cues. It excludes coordinates, chat recognition, countdowns, terrain, and inferred targets.
_Avoid_: tactical intelligence

**Enhanced**:
The subscriber Edition whose implementation and data remain in the private release closure.
_Avoid_: public build, Standard Plus

**Local Data Store**:
Bridge-owned persistent storage for user-selected, signed public objects.
_Avoid_: App installation, cloud backup

## Legacy

**Legacy Python App**:
The retired packaged desktop application retained only in repository history and old Releases.

**Legacy Desktop Launcher**:
The retired downloadable Launcher retained only in repository history and old Releases.
