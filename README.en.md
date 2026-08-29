<div align="center">

<img src="docs/assets/bomana-app.png" width="144" alt="Bomana app icon">

# Bomana

**Browser Companion for War Thunder Simulator Battles** · War Thunder 全真模式浏览器伴侣

[![App Web](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomana.ruikang.wang%2Fapp%2Fapp-release.json&query=%24.app_web_version&label=App%20Web&prefix=v&color=0ea5e9)](https://bomana.ruikang.wang/launcher/)
[![Bridge](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomana.ruikang.wang%2Fdownloads%2Fbridge-release.json&query=%24.bridge_version&label=Bridge&prefix=v&color=6366f1)](https://bomana.ruikang.wang/launcher/)
[![Product DAU](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fstats%2Fdaily&query=%24.metrics.dau_unique_device&label=product%20DAU&color=22c55e&cacheSeconds=300)](https://bomanaupdate.ruikang.wang/api/v1/stats/daily)
[![Public Editions](https://img.shields.io/badge/Lite%20%2B%20Standard-MIT-22c55e)](LICENSE)
[![Runtime](https://img.shields.io/badge/runtime-Browser%20%2B%20Windows-eab308)](https://bomana.ruikang.wang/launcher/)

**[Online Launcher](https://bomana.ruikang.wang/launcher/)** ·
[GitHub Releases](https://github.com/Thankyou-Cheems/Bomana/releases) ·
[中文](README.md)

</div>

---

Bomana is an independent third-party browser companion for War Thunder Simulator Battles.
War Thunder is a vehicle-combat video game; “bomb”, “bombing”, and “CCRP” in this project
refer only to in-game virtual mechanics, not real-world use.

- **Lite**: respawn-cycle timer only.
- **Standard**: basic navigation to official zones and airfields, plus fuel and checklist tools.
- **Bridge**: a read-only Windows gateway for official 8111 routes and the Local Data Store.
- **Enhanced**: the subscriber Edition; tactical intelligence, terrain, airport modules, and weapon-solving implementation are not part of this public repository.

Open <https://bomana.ruikang.wang/launcher/>, run `BomanaBridge.exe`, and select Lite or Standard.

The retired Python App, desktop Launcher, and hotkey broker remain available in Git history and existing Releases. Their history is not rewritten or deleted.

## Anonymous daily active

The new Browser + Bridge architecture remains compatible with product daily-active reporting.
After an Edition initializes, the hosted Browser App sends one best-effort anonymous signal per
UTC day. Switching among Lite, Standard, and Enhanced in the same browser still counts once.
Bridge does not report daily active, and no 8111 telemetry, gameplay state, account data, or payment
data enters the collector. The Product DAU badge reads the public migration-compatible aggregate;
see the [privacy notes](docs/PRIVACY.md) for the boundary.

## Usage boundary and anti-misunderstanding note

Bomana is not a game modification and is not affiliated with, authorized by, or sponsored by
Gaijin. At runtime, Bridge only forwards War Thunder's official `localhost:8111` data in read-only
mode. Bomana does not read game-process memory, inject code, modify game files, simulate player
input, or automate matches.

This describes the technical boundary; it is not official approval or a guarantee against account
action. Always follow the [Gaijin Terms of Service](https://legal.gaijin.net/termsofservice) and the
rules of the server you use, and decide for yourself whether to run any third-party tool.

MIT licensed.
