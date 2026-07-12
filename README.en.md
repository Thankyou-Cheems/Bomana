<div align="center">

<img src="bomana/assets/branding/app.png" width="200" alt="Bomana">

# Bomana

**War Thunder SB Timer** · 战雷全真模式收益计时器

War Thunder is a vehicle-combat video game; Bomana is a multifunction timer for simulator battles.<br>
Terms like “bomb / bombing / CCRP” here mean **in-game virtual concepts only**, not anything in the real world. Have fun!

War Thunder 是一款载具对战电子游戏；Bomana 是面向全真模式的多功能计时器。<br>
文中的「炸弹 / 投弹 / CCRP」等均指**游戏内虚拟概念**，与现实无关。祝你玩得开心！

<!-- Versions from EdgeOne CDN (what players actually get). GitHub "latest" is often a launcher-only tag. -->
[![App](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fversion%3Fchannel%3DEnhanced&query=%24.app_version&label=app&prefix=v&color=0ea5e9)](https://ruikang.wang/bomana/)
[![Launcher](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Flauncher&query=%24.launcher_version&label=launcher&prefix=v&color=6366f1)](https://ruikang.wang/bomana/)
[![License](https://img.shields.io/badge/license-MIT-22c55e)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14%2B-eab308)](https://www.python.org/)
[![DAU](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.dau_unique_device&label=DAU&color=22c55e)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)
[![Launches](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.launcher_start_total&label=launches&color=3b82f6)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)

**[Site / CDN download](https://ruikang.wang/bomana/)** ·
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
- [Runtime isolation and security boundary](#runtime-isolation-and-security-boundary)
- [Build and release](#build-and-release)
- [References](#references)
- [Update service repository](#update-service-repository)

---

# For players

Everyday use: download, features, and common questions—with as little jargon as possible.

## Compliance statement

> Older builds published before this statement were removed. Downloading and using a current build means you have read and accept this statement.

### Boundary in one sentence

Bomana does **not** read game memory, inject code, edit game files, or press keys / automate the match for you.  
It only reads data the game **already exposes on your machine**, and shows timing and cues in **its own** windows or web page.

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
| Memory reads, injection, client-file edits, macros, driving the game for you | **Forbidden**; Bomana does not ship this |

### What Bomana actually does (player wording)

| Topic | Behavior |
|-------|----------|
| Data source | Only the game’s local info pages (you can open `http://localhost:8111` in a browser). **No** process memory reads. |
| Process relationship | Separate program and windows; not embedded in the game, no DLL injection, no game-file edits. |
| Hotkeys | F7–F11 control **Bomana only** (timer, lock, corner, sound). They do **not** synthesize keys into the game. |
| Optional elevated hotkeys | Shown only when the game may be elevated and global hotkeys can fail; **you** confirm before any system UAC. Decline → timer / nav / window buttons still work. |
| Optional desktop overlay | Off by default; Bomana’s own transparent window for **ownship navigation**. Hostiles never go on the desktop HUD or heading tape. |
| Hostiles on the web map | If shown, only from the **current** official local map sample; cleared on failure or absence. No history tracks, no invented targets. |
| Web buttons | Change Bomana only (timer, corner, sound, panels, optional weapon settings)—**not** the game client. |

### What you should know

1. A **clean technical design is not a written guarantee** of never being sanctioned. Follow the EULA and your own risk judgment.  
2. More conservative use: keep LAN off, leave the overlay off, avoid web-map hostile display if you prefer.  
3. Endpoint lists, process-query scope, and contract tests: [Runtime isolation and security boundary](#runtime-isolation-and-security-boundary).

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

- Bomana’s own transparent window **above** the game for a main-target cue (off by default; enable in settings)
- Not a game render change and not process injection; opacity, scale, and display options available
- Hostile units never appear on this overlay

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
| **Enhanced** | Timer + navigation + fuel + weapon reference + web cockpit | Full toolkit (recommended) |
| **Standard** | Timer + navigation + fuel (no weapon reference, no web cockpit) | No weapon reference or web panel |
| **Lite** | Timer only (no web cockpit) | Minimal UI |

Standard / Lite packages **omit** web-cockpit code. If Launcher web options are checked, launch shows a degradation notice and forces those options off for that run (saved prefs remain for a later Enhanced channel).

Notes:

- First run usually needs the network; later runs can start offline from a local package  
- Newer launchers keep one previous app version for rollback  
- App 8.0.0+ requires Launcher 3.0.0+  
- Display name: `Bomana香焦`  
- Site entry: [China site / CDN](https://ruikang.wang/bomana/) or [GitHub Pages](https://thankyou-cheems.github.io/Bomana/)

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

**About optional elevated hotkeys:**

- Bomana and the launcher always run at ordinary integrity; **startup never auto-prompts UAC**.
- An optional grant appears only when the game may be elevated (or elevation cannot be determined).
- After you confirm, Windows may ask to allow a **hotkey-only** helper that notifies Bomana of reset / lock / corner / sound—**no** game injection and **no** game key synthesis.
- If you decline: timer, navigation, window buttons, and local data reads keep working; only global F7–F11 while the game is focused may fail.

---

## FAQ

### Does it read memory, inject, or play the game for me?

No. Runtime data is only the game’s local info pages; UI is separate windows; hotkeys and web buttons only change Bomana. No memory reads, injection, game-file edits, macros, or synthesized game keys. Details and contract tests: [Runtime isolation and security boundary](#runtime-isolation-and-security-boundary).

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
| `/map_obj.json` | Map objects (zones, airfields, player, units in the current sample, …) |
| `/map_info.json` | Map metadata |
| `/map.img` | Official tactical thumbnail (bounded, low-rate, content-typed) |
| `/icons.ttf` | Official tactical icon font (bounded, low-cadence, signature-checked) |

- Fixed base: `http://127.0.0.1:8111` (or equivalent localhost)  
- JSON access is centralized in `bomana/core/telemetry.py`; runtime must not scatter raw `requests` / `urlopen`  
- Spec: [docs/specs/runtime-8111-boundary.md](docs/specs/runtime-8111-boundary.md)

### Bundled static data

| File | Role |
|------|------|
| `ccrp_bomb_params.json` | Free-fall / high-drag bomb params |
| `weapon_fire_control.json` | Weapon catalog, loadouts, condition tables |
| `fm_speed_limits.json` | Airframe IAS / Mach limits |

Static libraries are **build-time** extracts from public datamine sources. Runtime only reads the JSON; it does not open the game install tree or decrypt client packs mid-sortie.

### Polling

- Healthy: ~50 ms (20 Hz)  
- API down: ~1.25 s  

### Web cockpit data flow

- Bomana is the only 8111 reader; the web stack never proxies or forwards 8111 routes  
- App publishes filtered snapshots, bounded map bitmaps, and Tk-owned control state  
- Hostiles mirror the current `/map_obj.json` sample only; never desktop HUD / heading tape  
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

## Runtime isolation and security boundary

Implementation detail for “official 8111 only, process isolation, no game automation.” Player summary: [Compliance statement](#compliance-statement).

### Isolation sketch

```text
War Thunder  ──official loopback HTTP :8111 only──►  Bomana App (ordinary integrity)
                                                       ├─ Own Tk / HUD windows (not game children)
                                                       ├─ Optional web cockpit (separate port; no 8111 proxy)
                                                       └─ Optional hotkey broker (after user UAC confirm)
                                                            └─ Named pipe: Bomana action IDs only
```

| Boundary | Implementation notes |
|----------|----------------------|
| No memory / injection | Runtime must not contain `ReadProcessMemory`, `WriteProcessMemory`, `CreateRemoteThread`, `pymem`, `frida`, etc. |
| No game input synthesis | Runtime must not use `SendInput` / `keybd_event` into the game; web contracts ban the same |
| No client edits | Runtime does not use `game.log`, client packs, or install trees as live data sources |
| Windows | Independent topmost layered windows; no `SetParent` onto the game HWND |
| Hotkeys | `RegisterHotKey` → callbacks mutate Bomana only; broker also only registers hotkeys (no hooks / polling) |

### Sole optional touch of the game process (read-only)

To decide whether to **show** the elevated-hotkey affordance, the App may:

1. Enumerate **visible** top-level windows whose title contains `War Thunder`  
2. Open candidates with `PROCESS_QUERY_LIMITED_INFORMATION`  
3. Confirm image name `aces.exe` / `aces64.exe` / `aces_BE.exe`  
4. `TOKEN_QUERY` for elevation  

It must **not** snapshot all processes, enumerate modules, read memory, or reuse a game handle for other purposes. Spec: `docs/specs/startup-elevation.md` (`ELEV-03`, …).

### Optional hotkey broker

| Item | Constraint |
|------|------------|
| When | Only after explicit user confirm; never auto-UAC on startup |
| Path | Packaged `bomana/bin/BomanaHotkeyBroker.exe` + adjacent SHA256 only |
| Actions | Fixed: `reset` / `lock` / `corner` / `beep` / optional `zones`; keys F1–F12 |
| IPC | Local named pipe; frames carry status / action IDs only |
| App process | May open Bomana with `SYNCHRONIZE \| PROCESS_QUERY_LIMITED_INFORMATION` to wait for exit—target is **Bomana**, not the game |
| Forbidden | No keyboard hooks, no game inspection, no network, no service / task / autostart install |

### Contract tests (run when touching boundaries)

```bash
uv run --extra dev python -m pytest ^
  tests/contracts/test_runtime_8111_boundary.py ^
  tests/contracts/test_startup_elevation_contract.py ^
  tests/contracts/test_web_dashboard_contract.py -q
```

| Test | Covers |
|------|--------|
| `test_runtime_8111_boundary` | API base, endpoint allowlist, dangerous API tokens, centralized HTTP, recorder/replay |
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
