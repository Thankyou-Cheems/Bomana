<div align="center">

<img src="bomana/assets/branding/app.png" width="144" alt="Bomana">

# Bomana

War Thunder flight assistance for sortie timing, zone and airfield navigation, speed safety, fuel and landing references, and an optional picture-in-picture navigator.

[![App Web](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomana.ruikang.wang%2Fapp%2Fapp-release.json&query=%24.app_web_version&label=App%20Web&prefix=v&color=0ea5e9)](https://bomana.ruikang.wang/launcher/)
[![Bridge](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomana.ruikang.wang%2Fdownloads%2Fbridge-release.json&query=%24.bridge_version&label=Bridge&prefix=v&color=6366f1)](https://bomana.ruikang.wang/launcher/)
[![Editions](https://img.shields.io/badge/editions-Lite%20%2B%20Standard-22c55e)](https://bomana.ruikang.wang/launcher/)
[![Runtime](https://img.shields.io/badge/runtime-browser%20%2B%20Go-0ea5e9)](docs/ARCHITECTURE.md)
[![License](https://img.shields.io/badge/license-MIT-64748b)](LICENSE)

[Open Bomana](https://bomana.ruikang.wang/) · [Online Launcher and downloads](https://bomana.ruikang.wang/launcher/) · [Flight toolbox](https://bomana.ruikang.wang/calculator/)

</div>

Bomana puts the timer, direction, zones, airfields and flight state you repeatedly check in a full-real sortie into one browser cockpit. The local Bridge reads War Thunder's official ExtUI data; the Web app presents and calculates from that data. Bridge reads only the fixed local interfaces. It does not inspect game memory, inject code, change game files or automate the game.

> Bomana is a third-party tool and is not affiliated with Gaijin. Port 8111 exposes only what the game makes available to the local machine. When observations are missing, the app hides or downgrades confidence; fuel, landing and weapon values are assistance references, not guarantees of a hit, destruction or safe recovery. Follow the current War Thunder rules and decide whether to use it.

## Choose an edition

| Edition | For | Main capabilities | Source and access |
| --- | --- | --- | --- |
| **Lite** | You only need a timer | Sortie / respawn cycle, progress, sound cues and manual reset | Public source; open it from the online Launcher |
| **Standard** | You want dependable basic navigation | Everything in Lite; official zone and airfield navigation, heading tape, aircraft speed limits, fuel time remaining, basic landing references, checklist, picture-in-picture and LAN mobile pairing | Public source; open it from the online Launcher |
| **Enhanced** | You need broader tactical assistance | Everything in Standard; tactical map, zone-area references, POI / Y66 target assistance, airfield module cues, terrain assistance, CCRP and other weapon release references, enhanced landing information | Separately provided authorized edition; see the Launcher; implementation is not in this repository |

Enhanced uses available map and flight observations to present references for zones, airfields and release windows. Server state, terrain masking, loadout identity and other internal game decisions are not fully observable through 8111, so the UI preserves uncertainty instead of presenting estimates as certain outcomes.

## See it in action

<div align="center">

<img src="docs/assets/shots/web-app-current.webp" width="820" alt="Bomana Web cockpit with heading tape, zone navigation and mission information">

<br>

<img src="docs/assets/shots/pip-window-current.webp" width="820" alt="Bomana picture-in-picture navigator with heading tape, CCRP, speed and miniature map">

</div>

The desktop Web page, picture-in-picture window and phone page share one Bridge source of official 8111 observations; each surface maintains its own timer and presentation state. The floating window uses the browser's Document Picture-in-Picture feature. A browser suspended by the system may pause processing; after it resumes, Bomana reconnects and restores the bounded sortie state it can safely recover.

## Start in three steps

1. Open the [online Launcher](https://bomana.ruikang.wang/launcher/), download and run `BomanaBridge.exe`. When the Bomana tray icon appears, return to the Launcher and connect.
2. Start War Thunder and make sure its official ExtUI data is available. Bomana checks the fixed local 8111, 9222 and 10333 ports in order; no upstream address needs to be entered.
3. Choose Lite or Standard and open the App. Standard mobile pairing shows a QR code on the computer; a phone on the same LAN can open it without an account. Enhanced authorization, when required, is described by the Launcher.

The Bridge download page shows its version, SHA-256 and provenance information. The Launcher only discovers, explains and opens fixed entry points; it does not silently execute a downloaded program. Run a downloaded Bridge update yourself.

## What is public here

This repository is Bomana's generated public source distribution. Its public scope includes:

- Lite / Standard Web, shared runtime, public parameters and Launcher;
- the read-only official 8111 Bridge, LAN mobile pairing and local resource storage;
- the navigation, speed and fuel references, landing assistance and picture-in-picture surfaces included in the public editions;
- the public data endpoints and basic tools behind the online toolbox.

Enhanced solvers, terrain data and advanced target features are described only at the user-facing capability level. Their implementation, dedicated data and authorization resources are outside this repository. Public `main` is generated after validation; new contributions are incorporated into the maintained source and exported by an explicit file list. Do not create a second independently maintained product or release path in this tree; see [Contributing](docs/CONTRIBUTING.md).

## Develop locally

Use Node.js 22, pnpm 11.3.0, Go 1.25 and PowerShell 7:

```pwsh
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend check
go -C native/telemetry_gateway test ./...
go -C native/telemetry_gateway vet ./...
```

Web outputs are written to `frontend/dist/Lite`, `frontend/dist/Standard` and `frontend/dist/launcher`. Public CI checks source and builds only. It has no production credentials, does not deploy production, and does not build Enhanced or official release packages. Use the [online Launcher](https://bomana.ruikang.wang/launcher/) for current downloads.

Basic Desktop is a minimal Windows timer / basic-navigation program whose source is public and can be built manually when needed; this repository does not promise a prebuilt desktop download. Enhanced Desktop is a separate private, manually delivered edition and is not built by public CI.

Read the [public edition contract](docs/specs/public-editions.md), [Bridge notes](docs/specs/bridge.md), [public architecture](docs/ARCHITECTURE.md), [privacy statement](docs/PRIVACY.md) and [MIT license](LICENSE) for the remaining boundaries.
