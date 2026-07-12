# Bomana

> **New here?** Start at the project site: [https://thankyou-cheems.github.io/Bomana/](https://thankyou-cheems.github.io/Bomana/) — features, downloads, and how to get started.

**战雷全真模式收益计时器** | War Thunder SB Timer

War Thunder is a vehicle-combat video game; Bomana is a multifunction timer for War Thunder simulator battles.
In this README, terms like "bomb", "bombing", and "CCRP" refer only to virtual in-game concepts, not anything in the real world. Have fun!

War Thunder 是一款载具对战电子游戏；Bomana 是一个面向 War Thunder 全真模式的多功能计时器。
本文档中的“炸弹”“投弹”“CCRP”等词均指代游戏内的虚拟概念，不对应任何现实内容。祝你玩得开心！

<p align="center">
  <img src="bomana/assets/branding/app.png" width="320" alt="Bomana promotional art">
</p>

[![App Release](https://img.shields.io/github/v/release/Thankyou-Cheems/Bomana?label=app%20release)](https://github.com/Thankyou-Cheems/Bomana/releases/latest)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14%2B-yellow.svg)](https://www.python.org/)
[![DAU](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.dau_unique_device&label=DAU&color=brightgreen)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)
[![Launches](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.launcher_start_total&label=Launches&color=blue)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)

[Bomana website / downloads](https://thankyou-cheems.github.io/Bomana/) | [GitHub Releases](https://github.com/Thankyou-Cheems/Bomana/releases)

---

## Choose Language | 选择语言

|  |  |
|:--|:--|
| **[中文文档](README.md)** | Chinese (default on GitHub landing) |
| **[English Documentation](#english-documentation)** | This page |

---

# English Documentation

## Table of Contents

### For players

- [Compliance statement](#compliance-statement)
- [Features](#features)
- [Download and use](#download-and-use)
- [Hotkeys](#hotkeys)
- [FAQ](#faq)
- [Privacy](#privacy)
- [License and disclaimer](#license-and-disclaimer)
- [Sponsor](#sponsor)

### For developers

- [Documentation map](#documentation-map)
- [Run from source](#run-from-source)
- [Project layout](#project-layout)
- [Advanced configuration](#advanced-configuration)
- [Technical details](#technical-details)
- [Build and release](#build-and-release)
- [References](#references)
- [Update service repository](#update-service-repository)

---

# For players

Everyday use: download, features, and common questions—with as little jargon as possible.

## Compliance statement

> Older builds published before this statement were removed. Downloading and using a current build means you have read and accept this statement.

### What the studio has said

In a [forum reply](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/16) (13 May 2024), community manager **Stona_WT** roughly indicated:

- Using localhost data for flight info and overlays is generally fine and not a bannable offense by itself.
- Showing enemy markers in markerless modes via a compass-style HUD overlay that the official map tool does not do is **not approved** and can be treated as an unfair advantage.

### What Bomana does

| Approach | Stance |
|----------|--------|
| Show your own speed, altitude, fuel, etc. | Allowed |
| Use official local data for timing and navigation cues | Allowed |
| Draw enemies into a game-like compass / HUD overlay in markerless modes | Not approved |
| Mirror currently returned hostile units on a separate web map | Not explicitly ruled on—judge for yourself |
| Memory reads, injection, game-file edits | Forbidden |

Bomana’s principles:

1. Read only the official local game API—no memory reads, injection, or game-file edits
2. The timer is based on your own spawn time; it does not manipulate the server
3. Hostile units appear only on the separate web map from the current official sample; they do not enter the desktop HUD or heading tape
4. No trajectory reconstruction from history and no invented missing targets

**You are responsible for how you use the tool.** “Technically possible” is not the same as “officially approved.”

---

## Features

### 15-minute reward timer

In simulator battles, each spawn has about a 15-minute reward window. Bomana can:

- Detect spawn, landing, and death to start or reset the timer
- Show which life you are on
- Resume after an app restart when possible
- Warn near the end with voice or beeps

### Weapon delivery reference

Supported builds can show **estimated** release distance and timing windows (free-fall bombs, some missiles and guided weapons).

Notes:

- Estimates only—not the game’s internal solution
- You must pick the weapon by hand; the app does not guess loadouts
- Free-fall paths can be lightly calibrated under settings

### Zone and airfield navigation

- Heading, distance, and time-to-target cues
- Optional auto-lock after holding aim on a target
- Home airfield direction; enemy airfields optional
- After respawning in the same match, direction to the last confirmed loss

### On-screen navigation overlay (optional)

- Main-target cue over the game window (off by default; enable in settings)
- Opacity, scale, and display options

### Fuel and overspeed cues

- Fuel amount, burn rate, and rough return estimate
- Speed-limit style warnings by airframe (IAS and Mach)

### Sortie checklist

Custom pre-takeoff items (engine, gear, and so on).

### Window

| Capability | Notes |
|------------|--------|
| Transparent, always on top | Stay visible without blocking the view |
| Lock | Click-through when locked |
| Drag and edge snap | Free placement |
| Themes and hotkeys | Light/dark; F7–F11 remappable |
| Tray | Minimize to the system tray |
| Text scale | Larger text without forcing the whole layout |
| Custom sounds | Import local audio by category |

### Local and phone web panel

View timer, map, fuel, and navigation in a browser on the PC or a phone on a trusted LAN. You can also run a small allowlist of Bomana controls (reset timer, corner, sound, and similar).

- Local-only by default; enable **LAN access and control** for phone use
- Enabling LAN also grants fixed-function control to later LAN pairings; disabling LAN immediately invalidates every LAN session
- It does not synthesize game hotkeys or drive the game client

More step-by-step help: [docs/QUICKSTART.md](docs/QUICKSTART.md).

---

## Download and use

### Before you start

1. Platform: Windows  
2. Start War Thunder and **enter a battle** (hangar state usually has no useful flight data)  
3. No extra “local server” toggle is normally required

### Recommended: launcher

1. Open [Releases](https://github.com/Thankyou-Cheems/Bomana/releases)  
2. Download `Bomana_launcher_vX.X.X.exe` and run it (portable; no installer)  
3. Pick a channel; the launcher checks for and downloads the matching app package  

| Channel | Includes | Best for |
|---------|----------|----------|
| **Enhanced** | Timer + navigation + fuel + weapon reference | Full toolkit (recommended) |
| **Standard** | Timer + navigation + fuel | No weapon reference |
| **Lite** | Timer only | Minimal UI |

Notes:

- First run usually needs the network; later runs can start offline from a local package  
- Newer launchers keep one previous app version for rollback  
- App 8.0.0+ requires Launcher 3.0.0+  
- Display name: `Bomana香焦`  
- Site entry: [project site](https://thankyou-cheems.github.io/Bomana/)

### Optional: source run

If you already have Python / uv, you can run from source—see [Run from source](#run-from-source).

---

## Hotkeys

| Key | Action |
|-----|--------|
| `F7` | Manual timer reset (double-tap quickly) |
| `F8` | Lock / unlock window (click-through when locked) |
| `F9` | Cycle screen corners |
| `F10` | Master sound toggle |
| `F11` | Zone-destroyed sound toggle |

Hotkeys are remappable. The HUD overlay is settings-only (off by default).

If the game runs elevated, global hotkeys may ask you to approve a one-time helper. Declining does not block timing, navigation, or on-window buttons—only global shortcuts while the game is focused may fail.

---

## FAQ

### Window missing or in the wrong place?

1. Confirm you are in a battle  
2. Open `http://localhost:8111` in a browser and check for data  
3. Restart the game and re-enter battle if needed  
4. Press `F9` to cycle corners  

### Timer never starts?

1. Confirm you have spawned  
2. Confirm the local URL above works  
3. Wait 1–2 seconds for detection  

### Phone web panel?

1. Phone and PC on the same trusted LAN  
2. Enable **LAN access and control** in Bomana (main window or tray)  
3. Open the pairing code / link shown in the main window  
4. Allow Bomana on private networks if Windows Firewall prompts (Bomana does not change firewall rules itself)  

### Weapon / bombing cues feel wrong?

1. Manually select the correct weapon on the weapon card  
2. Values are estimates; map, wind, and attitude all matter  
3. Free-fall calibration under `Settings → Bombing` only affects that path  

### How is this different from WTRTI?

| | Bomana | WTRTI |
|--|--------|-------|
| Focus | SB reward timer + nav / weapon cues | General flight telemetry |
| 15-minute timer | Yes | No |
| Zone nav / weapon cues | Yes (by channel) | No |
| Highly custom gauges | No | Yes |

You can run both together.

### Where is the changelog?

See [docs/CHANGELOG.md](docs/CHANGELOG.md). Source version lives in `bomana/metadata.py`; published version is on the release badge above.

---

## Privacy

The launcher collects **anonymous** usage stats (device hash, install id, version, channel, event type) to improve the product and measure activity.

- No names, emails, game accounts, IPs, or match results  
- Open source and reviewable; opt-out is documented  
- Full policy: [docs/PRIVACY.md](docs/PRIVACY.md)  

Downloading and running the app means you acknowledge that policy.

---

## License and disclaimer

### License

**MIT License** — Copyright (c) 2024-2026 Cheems  

Free to use, copy, modify, and distribute, with the copyright and license notice retained. See [LICENSE](LICENSE).

### Disclaimer

**Trademark:** War Thunder® and related marks belong to Gaijin Entertainment AG. This is an independent project and is **not** affiliated with, endorsed by, or sponsored by Gaijin.

**Usage risk:** Misuse may violate the [Gaijin Terms of Service](https://legal.gaijin.net/termsofservice). You alone ensure your usage complies.

**Liability:** Provided “AS IS.” Authors are not liable for bans, damages, or other consequences. **Use at your own risk.**

---

## Sponsor

If Bomana helps you, WeChat sponsorship is welcome:

<img src="bomana/assets/branding/sponsor_wechat.png" width="200" alt="WeChat sponsor QR">

---

# For developers

Contributors, packaging, and maintenance.

## Documentation map

| Doc | Contents |
|-----|----------|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | Player-oriented quick start |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Structure, data flow, build chain |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | `bd` workflow, commits, release norms |
| [docs/specs/](docs/specs/) | Canonical specs (8111, signing, threads, variants, quality gates) |
| [docs/specs/version-compatibility.md](docs/specs/version-compatibility.md) | App 8 / Launcher 3 boundary |
| [docs/specs/web-dashboard.md](docs/specs/web-dashboard.md) | Web cockpit boundary and semantic control |
| [docs/specs/release-signing.md](docs/specs/release-signing.md) | Release signing and deploy rules |
| [docs/PRIVACY.md](docs/PRIVACY.md) | Telemetry and web LAN boundaries |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Changelog |
| [docs/PITFALLS.md](docs/PITFALLS.md) | Known pitfalls |
| [docs/guides/8111-session-recording.md](docs/guides/8111-session-recording.md) | Record 8111 sessions for offline replay |
| [docs/guides/web-cockpit-smoke.md](docs/guides/web-cockpit-smoke.md) | Web cockpit manual smoke |
| [tests/README.md](tests/README.md) | Test layout and spec mapping |
| [Agents.md](Agents.md) | Agent / contributor router and quality gates |

---

## Run from source

### Environment

- Windows  
- Python 3.14+ (repo pins 3.14.5 via `.python-version`)  
- [uv](https://docs.astral.sh/uv/getting-started/installation/)  

### Install and launch

```powershell
uv sync --python 3.14.5
$env:BOMANA_SOURCE_DEVELOPMENT = "1"
uv run python Bomana.pyw
```

`BOMANA_SOURCE_DEVELOPMENT=1` only skips launcher identity for **explicit non-frozen source development**. Packaged apps never accept that exception. App 8.0.0+ requires Launcher 3.0.0+ identity at runtime.

Optional elevated hotkey broker for source debugging:

```powershell
uv run python tools/build_hotkey_broker.py --mode dev --output bomana/bin
```

---

## Project layout

```text
.
├─ Bomana.pyw                 # App entry (single-instance / DPI / UI boot)
├─ launcher.pyw               # Portable launcher
├─ bomana_version.py          # Shared App / Launcher version boundary
├─ bomana/
│  ├─ config/                 # Feature flags, settings, static config
│  ├─ core/                   # State, telemetry, ballistics, navigation
│  ├─ data/                   # Static JSON (CCRP / weapons / speed limits)
│  ├─ assets/web/             # Web cockpit front-end
│  ├─ ui/                     # Tk UI and presenters
│  ├─ web/                    # Dedicated HTTP service and semantic control
│  └─ utils/
├─ launcher/                  # Manifests, download cache, install transactions
├─ native/hotkey_broker/      # Minimal privileged hotkey broker (Rust)
├─ tools/                     # Packaging, datamine, deploy
├─ tests/
└─ docs/
```

Notes:

- Logic lives under `bomana/`; `Bomana.pyw` is the boot boundary  
- Launcher and Python App run at ordinary integrity; only a user-confirmed fixed-action native broker may elevate  
- Speed limits: `bomana/data/fm_speed_limits.json`; bomb params: `bomana/data/ccrp_bomb_params.json`  

---

## Advanced configuration

### Compile-time feature flags

See `bomana/config/feature_profile.py`:

```python
ENABLE_CCRP = True
ENABLE_ZONES = True
ENABLE_AIRFIELDS = True
ENABLE_FUEL = True
ENABLE_CHECKLIST = True
ENABLE_ADVANCED_SETTINGS = True
```

### Refresh datamine static assets

One entry updates:

- `bomana/data/ccrp_bomb_params.json`  
- `bomana/data/weapon_fire_control.json`  
- `bomana/data/fm_speed_limits.json`  
- datamine source version / commit in each JSON `meta`  

```bash
git clone https://github.com/gszabi99/War-Thunder-Datamine.git
git -C .\War-Thunder-Datamine pull --ff-only

uv run python tools/update_datamine_assets.py ^
  .\War-Thunder-Datamine ^
  --no-bomb-report
```

Lower-level scripts: `tools/blkx_extractor.py`, `tools/fm_speed_extractor.py`, `tools/weapon_fire_control_extractor.py`.

Overspeed grading is cross-checked against [KaerMorh/WTSpeeder](https://github.com/KaerMorh/WTSpeeder); Bomana still owns its own `fm_speed_limits.json`.

---

## Technical details

### Runtime data (official local HTTP)

| Endpoint | Content |
|----------|---------|
| `/indicators` | Instruments (speed, fuel, validity, …) |
| `/state` | State (IAS, altitude, vertical speed, …) |
| `/map_obj.json` | Map objects (zones, airfields, player, …) |
| `/map_info.json` | Map metadata |
| `/map.img` | Official tactical thumbnail (bounded, low-rate) |

Official 8111 only—see [docs/specs/runtime-8111-boundary.md](docs/specs/runtime-8111-boundary.md).

### Bundled static data

| File | Role |
|------|------|
| `ccrp_bomb_params.json` | Free-fall / high-drag bomb params |
| `weapon_fire_control.json` | Weapon catalog, loadouts, condition tables |
| `fm_speed_limits.json` | Airframe IAS / Mach limits |

### Polling

- Healthy: ~50 ms (20 Hz)  
- API down: ~1.25 s  

### Web cockpit data flow

- Bomana is the only 8111 reader; the web stack never proxies 8111  
- App publishes filtered snapshots, bounded map bitmaps, and Tk-owned control state  
- Hostiles mirror the current `/map_obj.json` sample only; never desktop HUD / heading tape  
- Writes require session CSRF, idempotency keys, and main-thread re-authorization; fixed semantic actions only  
- Default `127.0.0.1:8777`; LAN binds concrete RFC1918 addresses, not `0.0.0.0`  
- Spec: [docs/specs/web-dashboard.md](docs/specs/web-dashboard.md)  

### Timer state machine (sketch)

```
[Wait] ──player seen──→ [In flight] ──speed <40 km/h ~3s──→ [Landed]
   ↑                      │                              │
   │                      ↓                              │
   └───no player ~1.2s──[Dead / hangar]←────~10s─────────┘
```

---

## Build and release

### Local packaging

```text
tools\scripts\build_portable.bat <Enhanced|Standard|Lite> <all|app|launcher> [version]
tools\scripts\build_app_package.bat Enhanced|Standard|Lite
tools\scripts\build_launcher.bat [version]
```

- `version` is a consistency check against source; for `all`, omit a single `version`  
- App ZIPs embed the minimal hotkey broker and its SHA256  
- Release builds need `BOMANA_RELEASE_ED25519_PRIVATE_KEY`, `BOMANA_RELEASE_ED25519_PUBLIC_KEY`, and `BOMANA_RELEASE_SIGNING_KEY_ID` (default `bomana-release-2026-06`)  
- Unsigned or mismatched key material is rejected  

### GitHub Actions

| Trigger | Artifacts |
|---------|-----------|
| Tag `vX.Y.Z` | Launcher + three app channels |
| Tag `vX.Y.Z-app` | Three app channels only |
| Tag `vX.Y.Z-launcher` | Launcher only |
| `workflow_dispatch` | `all` / `app` / `launcher` |

Builds use GitHub Artifact Attestations; no Authenticode PFX required. Signing trust boundary: [docs/specs/release-signing.md](docs/specs/release-signing.md).

### Tencent / EdgeOne deploy

**GitHub-hosted Actions must not SSH/rsync/scp to Tencent hosts.** Locally:

```bash
gh secret list --repo Thankyou-Cheems/Bomana
gh release download vX.Y.Z --dir dist
uv run python tools/deploy_update_assets.py --target app|launcher|all --version X.Y.Z
```

Public endpoints must be checked with `verify_release_manifest_signature`.

### Artifact map

| File | Role |
|------|------|
| `Bomana_launcher_vX.Y.Z.exe` | Entry: update check, download verify, self-update, rollback |
| `launcher_manifest.json` | Launcher version, name, SHA256, Ed25519 signature |
| `Bomana_app_<Variant>_vX.Y.Z.zip` | Runnable package |
| `manifest_<Variant>.json` | App version, `min_launcher_version`, SHA256, signature |
| `checksums_*.txt` | Integrity lists |

---

## References

- [War Thunder forum: tools on port 8111](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664)  
- [Stona_WT reply (#16)](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/16)  
- [Gaijin Terms of Service](https://legal.gaijin.net/termsofservice)  
- [WTRTI](https://mesofthorny.github.io/WTRTI/)  
- [KaerMorh/WTSpeeder](https://github.com/KaerMorh/WTSpeeder)  
- [War Thunder localhost:8111 docs](https://github.com/lucasvmx/WarThunder-localhost-documentation)  

---

## Update service repository

Standalone update / stats service (Docker / FastAPI):

- https://github.com/Thankyou-Cheems/bomana-worker  
- Path: `services/bomana-update-service/`  

This repo keeps the app and launcher. Deploy docs and iteration live in `bomana-worker`.  
This repo produces manifests with Ed25519 `manifest_signature`; the service does not re-sign and never needs the release private key. After deploy, validate public signatures with `tools/deploy_update_assets.py`.

---

*Made by 猹Cheems for the Space Monkeys community*
