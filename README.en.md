<div align="center">

<img src="bomana/assets/branding/app.png" width="200" alt="Bomana">

# Bomana

**War Thunder SB Timer** · 战雷全真模式收益计时器

War Thunder is a vehicle-combat video game. Bomana is an independent desktop
tool for simulator battles, helping players manage reward timers, navigation
information, and sortie preparation. Terms such as “bomb” and “bombing” here
refer to in-game virtual content only.

[![App](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fversion%3Fchannel%3DStandard&query=%24.app_version&label=Standard&prefix=v&color=0ea5e9)](https://bomana.ruikang.wang/)
[![Launcher](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Flauncher&query=%24.launcher_version&label=launcher&prefix=v&color=6366f1)](https://bomana.ruikang.wang/)
[![Public License](https://img.shields.io/badge/public%20editions-MIT-22c55e)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14%2B-eab308)](https://www.python.org/)

**[Site / download](https://bomana.ruikang.wang/)** ·
[GitHub Releases](https://github.com/Thankyou-Cheems/Bomana/releases) ·
[中文](README.md)

</div>

---

## Compliance statement

Bomana is an independent application, not a game modification. At runtime it
reads only the information that War Thunder exposes locally through
`localhost:8111`, then shows timers and reference information in its own
windows. It does not read game-process memory, inject code, modify game files,
press keys for the player, or automate a match.

This describes the implementation boundary, not an official endorsement or a
promise that any third-party tool is risk-free. Follow the
[Gaijin Terms of Service](https://legal.gaijin.net/termsofservice) and the rules
of the server you play on.

## Features

### Standard

- Configurable 15-minute reward-cycle timer
- Zone, airfield, and point-of-interest navigation
- Fuel, return-margin, and speed cues
- Sortie checklist, tray controls, window locking, and global hotkeys
- Local settings and state recovery

### Lite

- Core reward timer
- Minimal window and basic tray controls
- A simple choice for players who only need the timer

### Super Bomb

Super Bomb is a separate subscription edition for additional advanced features
and subscriber-only content beyond the public editions. It is delivered through
the Launcher and the official site according to subscription status. Exact
capabilities follow the site and the current release notes; its implementation,
data, and release packages are not published in this public repository.

## Download and use

### Before you start

1. Windows is required.
2. Start War Thunder and enter a battle; the hangar normally has no complete
   flight data.
3. No separate game installer is required. Once in battle, Bomana reads the
   local information exposed by the game.

### Recommended: Launcher

1. Download the Windows Launcher from the [Bomana site](https://bomana.ruikang.wang/)
   or [GitHub Releases](https://github.com/Thankyou-Cheems/Bomana/releases).
2. The Launcher checks versions, verifies downloads, and installs the selected
   channel.
3. Pick the edition that fits your use:

| Channel | Access | Best for |
|---|---|---|
| **Standard** | Public, MIT | Timer, navigation, and fuel information |
| **Lite** | Public, MIT | A minimal timer |
| **Lite Green** | Public, launcher-free | Extract and run without a separate Python install |
| **Super Bomb** | Paid subscription | Subscriber features beyond the public editions |

For Super Bomb, follow the Launcher prompt to open the official site, complete
the purchase or trial flow, and refresh the subscription status. The public
repository publishes only Lite, Standard, and Lite Green; it does not expose a
subscriber download URL.

The Launcher keeps one previous version for rollback. Lite Green includes the
Python runtime and runs directly as `Bomana.exe`; it sends one anonymous daily
activity event asynchronously. Network failures never block startup or disable
the app.

## Hotkeys

| Key | Action |
|---|---|
| `F7` | Manual timer reset (double-tap quickly) |
| `F8` | Lock / unlock the window |
| `F9` | Cycle through the four screen corners |
| `F10` | Master sound toggle |
| `F11` | Zone notification sound toggle |

Hotkeys are remappable. They control Bomana only and never send keys to the game.

## FAQ

### The window is empty. What should I check?

Confirm that the game is in a battle, then open `http://localhost:8111` in a
browser. If it has no useful data, re-enter the battle or wait briefly; the
hangar normally does not expose flight information.

### Does Bomana read memory, inject, or play the game for me?

No. Public editions use separate windows and the official local HTTP data. They
do not read process memory, inject, edit client files, or synthesize game keys.
No third-party tool can take responsibility for account or match risk.

### Which edition should I choose?

Standard is for players who want navigation, fuel, and more desktop assistance.
Lite keeps only the timer and the minimal UI. Lite Green has the same Lite
features but includes Python and does not require the Launcher. Super Bomb is a
separate paid subscription edition; see the official site for its current scope.

### How is this different from WTRTI?

Bomana focuses on the simulator-battle reward timer and simple navigation
references. WTRTI focuses on general flight telemetry. They can be used together;
follow each project's own rules and documentation.

## Privacy

The Launcher and Lite Green may send anonymous usage statistics (device hash,
install identifier, version, channel, and event type) for update service and
activity metrics. They do not collect names, email addresses, game accounts,
match results, or payment information. See the full [privacy policy](docs/PRIVACY.md).
Reporting fails silently when the network is unavailable and never blocks startup.

## License and disclaimer

The public Lite, Standard, and Lite Green source closure is licensed under the
[MIT License](LICENSE). New Super Bomb implementation, data, and release packages
belong to a separate subscriber closure and are not distributed here.

War Thunder® and related marks belong to Gaijin Entertainment AG. Bomana is an
independent project and is not affiliated with, authorized by, or sponsored by
Gaijin. The software is provided “AS IS”; use it at your own risk.

## Sponsor

If Bomana helps you, WeChat sponsorship is welcome:

<img src="bomana/assets/branding/sponsor_wechat.png" width="200" alt="WeChat sponsor QR">

---

# For developers

## Documentation map

| Document | Contents |
|---|---|
| [docs/QUICKSTART.md](docs/QUICKSTART.md) | Player-oriented quick start |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Structure, data flow, and build chain |
| [docs/CONTRIBUTING.md](docs/CONTRIBUTING.md) | Collaboration, commits, and release norms |
| [docs/PRIVACY.md](docs/PRIVACY.md) | Anonymous telemetry and privacy boundaries |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | Changelog |
| [docs/PITFALLS.md](docs/PITFALLS.md) | Known issues and troubleshooting |
| [tests/README.md](tests/README.md) | Test layout and spec mapping |

## Run from source

Windows, Python 3.14+, and [uv](https://docs.astral.sh/uv/) are required:

```powershell
uv sync --extra dev --frozen
uv run python Bomana.pyw
```

Public source defaults to Standard. See [CONTRIBUTING.md](docs/CONTRIBUTING.md)
for development and test commands.

## Project layout

```text
.
├─ Bomana.pyw                 # App entry
├─ launcher.pyw               # Portable launcher
├─ bomana/                    # Timer, navigation, state, and UI
├─ launcher/                  # Manifests, cache, and install transactions
├─ tools/                     # Build and release tools
├─ tests/                     # Public behavior and release-contract tests
└─ docs/                      # Player documentation and maintenance rules
```

## Build and release

The public builder accepts Lite, Standard, and Lite Green only:

```powershell
uv run --frozen python tools/build_portable.py --variant Standard --target app
uv run --frozen python tools/build_portable.py --variant Lite --target app
uv run --frozen python tools/build_portable.py --variant Lite --target green
uv run --frozen python tools/build_portable.py --target launcher
```

Release manifests use Ed25519 signatures; private keys must never enter the
repository or logs. Super Bomb is maintained by a separate private release
closure, so public CI neither builds nor uploads it.

## Update service repository

The standalone update and statistics service (Docker / FastAPI) lives in
[Thankyou-Cheems/bomana-worker](https://github.com/Thankyou-Cheems/bomana-worker).
This repository maintains the application and Launcher; deployment details live
with the update service.

---

*Made by 猹Cheems for the Space Monkeys community*
