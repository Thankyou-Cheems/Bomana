<div align="center">

<img src="bomana/assets/branding/app.png" width="200" alt="Bomana">

# Bomana

**War Thunder SB Timer** · 战雷全真模式收益计时器

War Thunder is a vehicle-combat video game; Bomana is a multifunction timer for simulator battles.<br>
Terms like “bomb / bombing / CCRP” here mean **in-game virtual concepts only**, not anything in the real world. Have fun!

War Thunder 是一款载具对战电子游戏；Bomana 是面向全真模式的多功能计时器。<br>
文中的「炸弹 / 投弹 / CCRP」等均指**游戏内虚拟概念**，与现实无关。祝你玩得开心！

<!-- Versions from EdgeOne CDN (what players actually get). GitHub "latest" is often a launcher-only tag. -->
[![App](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fversion%3Fchannel%3DEnhanced&query=%24.app_version&label=app&prefix=v&color=0ea5e9)](https://bomana.ruikang.wang/)
[![Launcher](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Flauncher&query=%24.launcher_version&label=launcher&prefix=v&color=6366f1)](https://bomana.ruikang.wang/)
[![License](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14%2B-eab308)](https://www.python.org/)
[![DAU](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.dau_unique_device&label=DAU&color=22c55e)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)
[![Launches](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.launcher_start_total&label=launches&color=3b82f6)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)

**[Site / CDN download](https://bomana.ruikang.wang/)** ·
[GitHub Pages](https://thankyou-cheems.github.io/Bomana/) ·
[Releases (backup)](https://github.com/Thankyou-Cheems/Bomana/releases)

**[English](#english-documentation)** · **[中文](README.md)**

</div>

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
- [Windows integration and hotkey broker](#windows-integration-and-hotkey-broker)
- [Build and release](#build-and-release)
- [References](#references)
- [Update service repository](#update-service-repository)

---

# For players

Everyday use: download, features, and common questions—with as little jargon as possible.

## Current implementation and usage notes

### Current implementation

The current Bomana build does **not** read game memory, inject code, edit game files, or press keys / automate the match for you.
It reads locally available game data and bundled versioned static data, then shows timing and cues in **its own** windows or web page.

### What the studio has said

In a [forum reply](https://forum.warthunder.com/t/tools-using-data-provided-on-port-8111/106664/16) (13 May 2024), community manager **Stona_WT** roughly indicated:

- Using localhost data for flight info and overlays is generally fine and not a bannable offense by itself.
- Showing enemy markers in markerless modes via a compass-style HUD overlay that the official map tool does not do is **not approved** and can be treated as an unfair advantage.

### Allowed / not approved / decide yourself

| Approach | Stance |
|----------|--------|
| Your own speed, altitude, fuel, reward timer | Studio-leaning **allowed** |
| Local public data for navigation, fuel, overspeed cues | Studio-leaning **allowed** (same class as tools like WTRTI) |
| Drawing enemies into a **game-like** compass / HUD overlay in markerless modes | **Not approved** |
| Mirroring hostiles that the official local map sample already returns, on a **separate web map only** | **Not explicitly ruled on**—you decide |
| Memory reads, injection, client-file edits, macros, driving the game for you | Not present in the current Bomana build |

### What Bomana actually does (player wording)

| Topic | Behavior |
|-------|----------|
| Data source | The current build reads the game’s local info pages (you can open `http://localhost:8111` in a browser) and bundled versioned static data. |
| Process relationship | Separate program and windows; not embedded in the game, no DLL injection, no game-file edits. |
| Hotkeys | F6–F11 control **Bomana only** (target source, timer, lock, corner, sound). They do **not** synthesize keys into the game. |
| Game-foreground hotkeys | Use Windows `RegisterHotKey`; Bomana does not enumerate or open the game process to infer integrity and never auto-prompts UAC. Use the bombing bar, main window, or tray equivalents if an integrity boundary blocks a hotkey. |
| Desktop surfaces | Main window, standalone navigation bar, and standalone CCRP bar; no fullscreen in-game HUD. |
| Hostiles on the web map | If shown, only from the **current** official local map sample; cleared on failure or absence. No history tracks, no invented targets. |
| Web buttons | Change Bomana only (timer, corner, sound, panels, optional weapon settings)—**not** the game client. |

### What you should know

1. A **clean technical design is not a written guarantee** of never being sanctioned. Follow the EULA and your own risk judgment.  
2. More conservative use: keep LAN off and avoid web-map hostile display if you prefer.
**You are responsible for how you use the tool.**

---

## Features

### 15-minute reward timer

In simulator battles, each spawn has about a 15-minute reward window. Bomana can:

- Detect spawn, landing, and death to start or reset the timer
- Show which life you are on
- Resume after an app restart when possible
- Warn near the end with voice or beeps

### Weapon delivery reference

超级爆弹版 provides delivery references for free-fall bombs and other supported weapons. Free-fall solving combines only official 8111 flight data, user-selected offline weapon parameters, and the launcher-managed offline terrain pack.

Notes:

- The bombing bar can stay integrated or detach; when navigation is also detached, it mounts directly below the navigation bar
- Click the blue weapon field to select a bomb verified for the current airframe; Bomana never reads or guesses the in-game loadout
- `F6` or the bar button explicitly selects Zone versus POI targeting, so overlapping targets are never resolved by an implicit guess
- Target, elevation, and release state share the header so the default CCRP card stays compact; symmetric brackets converge smoothly toward release, pulse green at the cue, and show a red overrun line after it
- All results remain external references, not the game’s internal solution or release authority

### Zone and airfield navigation

- Heading, distance, and time-to-target cues
- A nonlinear precision lane is built into the heading tape: near the target it shows left/right error, a capture gate, and a smoothed pipper without two extra status rows
- Optional auto-lock after holding aim on a target
- Friendly and optional enemy airfields remain on the main scale while the precision lane is active
- After respawning in the same match, direction to the last confirmed loss

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
| Themes and hotkeys | Light/dark; F6–F11 remappable |
| Tray | Minimize to the system tray |
| Text scale | Larger text without forcing the whole layout |
| Custom sounds | Import local audio by category |

### Local and phone web panel

View timer, map, fuel, and navigation in a browser on the PC or a phone on a trusted LAN. You can also run a small allowlist of **Bomana-only** controls (reset timer, corner, sound, and similar).

- Local-only by default; enable **LAN access and control** for phone use
- Enabling LAN also grants fixed-function control to later LAN pairings; disabling LAN immediately invalidates every LAN session
- The page does **not** synthesize game hotkeys or drive the game client
- If the web map shows hostiles, they only mirror the current official local sample—decide whether to use that under the compliance notes above

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
| **超级爆弹版** (internal channel: `Enhanced`) | Deep-learning high-precision strike model and terrain data | Maximum bombing-prediction accuracy with offline terrain |
| **Standard** | Timer + navigation + fuel (no weapon reference, no web cockpit) | No weapon reference or web panel |
| **Lite** | Timer only (no web cockpit) | Minimal UI |

Standard / Lite packages **omit** web-cockpit code. If Launcher web options are checked, launch shows a degradation notice and forces those options off for that run (saved prefs remain for 超级爆弹版).

Notes:

- First run usually needs the network; later runs can start offline from a local package  
- Newer launchers keep one previous app version for rollback  
- Current App 8.6.2 requires Launcher 3.3.0+
- Launcher shows the current offline-pack state, map count, and revision; unchanged revisions download nothing, while updates fetch only changed map objects
- Display name: `Bomana香焦`  
- Site entry: [Bomana site / China CDN](https://bomana.ruikang.wang/) or [GitHub Pages](https://thankyou-cheems.github.io/Bomana/); the former `/bomana` path is retained only as a compatibility redirect

### Optional: source run

If you already have Python / uv, you can run from source—see [Run from source](#run-from-source).

---

## Hotkeys

| Key | Action |
|-----|--------|
| `F6` | Toggle bombing target source: Zone / POI |
| `F7` | Manual timer reset (double-tap quickly) |
| `F8` | Lock / unlock window (click-through when locked) |
| `F9` | Cycle screen corners |
| `F10` | Master sound toggle |
| `F11` | Zone-destroyed sound toggle |

Hotkeys are remappable.

**About optional elevated hotkeys:**

- Bomana and the launcher always run at ordinary integrity. Startup registers only Windows system hotkeys and **never auto-prompts UAC**.
- The current App does not enumerate game windows, open the game process, or inspect its integrity to decide whether to show a hotkey prompt.
- If foreground integrity prevents F6–F11 delivery, use the equivalent bombing-bar, main-window, or tray buttons; timer, navigation, and official 8111 data remain available.

---

## FAQ

### Does it read memory, inject, or play the game for me?

The current build does not. Its UI is separate windows, and hotkeys and web buttons only change Bomana. The current implementation has no memory reads, injection, game-file edits, macros, or synthesized game keys.

### Is this treated as cheating?

- Timer and ownship flight/nav cues align with the studio’s public stance that localhost overlays for that class of data are generally fine.  
- Bomana does **not** draw enemies onto a game-like HUD / compass overlay.  
- Hostiles on a **separate web map** are a **gray area** (not explicitly ruled on)—your call.  
- No third-party tool can promise “never sanctioned.” Follow the EULA and your own risk judgment.

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

1. Click the blue CCRP weapon field and select the actual store
2. The cue pauses only for strong lateral manoeuvring such as steep bank, sideslip, roll, or turn; a laterally stable dive or pull-up remains eligible
3. If it says the target elevation is unavailable, confirm that Launcher has installed the Enhanced terrain pack

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

`BOMANA_SOURCE_DEVELOPMENT=1` only skips launcher identity for **explicit non-frozen source development**. Packaged apps never accept that exception. The protocol floor remains Launcher 3.0.0+, while the current App 8.6.2 requires Launcher 3.3.0+ before importing runtime modules; an older Launcher also blocks this App update before downloading package bytes from its signed manifest.

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
│  ├─ data/                   # Static assets (CCRP / weapons / speed limits)
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
- Speed limits: `bomana/data/fm_speed_limits.json`; offline rigid-body catalog: `bomana/data/offline_rigidbody_catalog.bin`

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

- `bomana/data/offline_rigidbody_catalog.bin`
- `bomana/data/weapon_fire_control.json`  
- `bomana/data/fm_speed_limits.json`  
- datamine source version / commit in the weapon and speed JSON metadata

The rigid-body catalog uses a deterministic compressed container with a
SHA-256 integrity check and carries no per-record file paths, mesh names, or
source-commit metadata.

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
| `/map_obj.json` | Map objects (zones, airfields, player, units in the current sample, …) |
| `/map_info.json` | Map metadata |
| `/map.img` | Official tactical thumbnail (bounded, low-rate, content-typed) |
| `/icons.ttf` | Official tactical icon font (bounded, low-cadence, signature-checked) |

- Fixed base: `http://127.0.0.1:8111` (or equivalent localhost)  
- JSON access is currently centralized in `bomana/core/telemetry.py`

### Bundled static data

| File | Role |
|------|------|
| `offline_rigidbody_catalog.bin` | Integrity-checked offline CCRP rigid-body catalog |
| `weapon_fire_control.json` | Weapon catalog, loadouts, condition tables |
| `fm_speed_limits.json` | Airframe IAS / Mach limits |

Static libraries are **build-time** extracts from public datamine sources. Runtime only reads bundled static assets; it does not open the game install tree or decrypt client packs mid-sortie.

### Polling

- Healthy: ~50 ms (20 Hz)  
- API down: ~1.25 s  

### Web cockpit data flow

- Bomana is the only 8111 reader; the web stack never proxies or forwards 8111 routes  
- App publishes filtered snapshots, bounded map bitmaps, and Tk-owned control state  
- Hostiles mirror the current `/map_obj.json` sample only; never standalone navigation or CCRP bars
- Writes require session CSRF, idempotency keys, and main-thread re-authorization; fixed semantic actions only (`bomana/web/control.py` allowlist)  
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

## Windows integration and hotkey broker

This section records the current window and optional-hotkey implementation. It no longer defines an 8111-only data-source security boundary.

### Isolation sketch

```text
War Thunder  ──loopback HTTP :8111──►  Bomana App (ordinary integrity)
                                                       ├─ Own Tk panel windows (not game children)
                                                       ├─ Optional web cockpit (separate port; no 8111 proxy)
                                                       └─ Optional hotkey broker (after user UAC confirm)
                                                            └─ Named pipe: Bomana action IDs only
```

| Boundary | Implementation notes |
|----------|----------------------|
| Windows | Independent topmost layered windows; no `SetParent` onto the game HWND |
| Hotkeys | `RegisterHotKey` → callbacks mutate Bomana only; broker also only registers hotkeys (no hooks / polling) |

### No game-process probing

The App registers ordinary Windows system hotkeys directly. It does not enumerate game windows or processes, query game executable names or tokens, inspect modules or memory, or auto-request UAC from game state. See `docs/specs/startup-elevation.md`.

### Optional hotkey broker

| Item | Constraint |
|------|------------|
| When | Only after explicit user confirm; never auto-UAC on startup |
| Path | Packaged `bomana/bin/BomanaHotkeyBroker.exe` + adjacent SHA256 only |
| Actions | Fixed: `bomb_target` / `reset` / `lock` / `corner` / `beep` / optional `zones`; keys F1–F12 |
| IPC | Local named pipe; frames carry status / action IDs only |
| App process | May open Bomana with `SYNCHRONIZE \| PROCESS_QUERY_LIMITED_INFORMATION` to wait for exit—target is **Bomana**, not the game |
| Forbidden | No keyboard hooks, no game inspection, no network, no service / task / autostart install |

### Related contract tests

```bash
uv run --extra dev python -m pytest ^
  tests/contracts/test_startup_elevation_contract.py ^
  tests/contracts/test_web_dashboard_contract.py -q
```

| Test | Covers |
|------|--------|
| `test_startup_elevation_contract` | Ordinary integrity, narrow probe, broker path/hash/forbiddens |
| `test_web_dashboard_contract` | No 8111 proxy, semantic command matrix, no input synthesis |

Dev-only note: datamine tools, session recording, and packaged-launcher smoke (PowerShell `keybd_event` for launcher UI only) are **outside** the player combat runtime. Recording defaults to gitignored `recordings/` and does not upload.

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
- No App ZIP embeds terrain. Launcher installs, verifies, and maintains `terrain-v1` only for `Enhanced`
- Terrain objects are content-addressed by SHA256; unchanged maps are reused and ordinary App releases neither include nor upload the roughly 118 MB dataset
- Release builds need `BOMANA_RELEASE_ED25519_PRIVATE_KEY`, `BOMANA_RELEASE_ED25519_PUBLIC_KEY`, and `BOMANA_RELEASE_SIGNING_KEY_ID` (default `bomana-release-2026-06`)  
- Unsigned or mismatched key material is rejected  

### GitHub Actions

| Trigger | Artifacts |
|---------|-----------|
| Tag `vX.Y.Z` | Launcher + three app channels |
| Tag `vX.Y.Z-app` | Three app channels only |
| Tag `vX.Y.Z-launcher` | Launcher only |
| `workflow_dispatch` | `all` / `app` / `launcher` |
| Manual `build-terrain.yml` run | Independent signed terrain manifest and content-addressed objects |

Builds use GitHub Artifact Attestations; no Authenticode PFX required. Signing trust boundary: [docs/specs/release-signing.md](docs/specs/release-signing.md).

### Tencent / EdgeOne deploy

**GitHub-hosted Actions must not SSH/rsync/scp to Tencent hosts.** Locally:

```bash
gh secret list --repo Thankyou-Cheems/Bomana
gh release download vX.Y.Z --dir dist
uv run python tools/deploy_update_assets.py --target app|launcher|all --version X.Y.Z
# Only when terrain data actually changes:
uv run python tools/deploy_update_assets.py --target terrain
```

Public endpoints must be checked with `verify_release_manifest_signature`.

### Artifact map

| File | Role |
|------|------|
| `Bomana_launcher_vX.Y.Z.exe` | Entry: update check, download verify, self-update, rollback |
| `launcher_manifest.json` | Launcher version, name, SHA256, Ed25519 signature |
| `Bomana_app_<Variant>_vX.Y.Z.zip` | Runnable package |
| `manifest_<Variant>.json` | App version, `min_launcher_version`, SHA256, signature |
| `terrain-release/terrain_manifest.json` | Independent terrain revision, per-file hashes/sizes, Ed25519 signature |
| `terrain-release/objects/*` | Content-addressed map/metadata objects; clients fetch only changed objects |
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
