<div align="center">

<img src="bomana/assets/branding/app.png" width="180" alt="Bomana">

# Bomana

**Timer and flight assistance for War Thunder simulator battles**

[![App](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Fversion%3Fchannel%3DStandard&query=%24.app_version&label=Standard&prefix=v&color=0ea5e9)](https://bomana.ruikang.wang/)
[![Launcher](https://img.shields.io/badge/dynamic/json?url=https%3A%2F%2Fbomanaupdate.ruikang.wang%2Fapi%2Fv1%2Flauncher&query=%24.launcher_version&label=launcher&prefix=v&color=6366f1)](https://bomana.ruikang.wang/)
[![Public License](https://img.shields.io/badge/public%20editions-MIT-22c55e)](LICENSE)

**[Download](https://bomana.ruikang.wang/)** · **[中文](README.md)**

</div>

Bomana is a standalone desktop application. It reads only War Thunder's official
local `localhost:8111` data. It does not read game-process memory, inject code,
modify game files, or operate the game for the player.

## Editions

| Edition | Access | Features |
|---|---|---|
| **Standard** | Public, MIT | Timer, navigation, fuel, checklist, speed and overspeed cues |
| **Lite** | Public, MIT | Core timer and minimal UI |
| **Lite Green** | Public, MIT, launcher-free | Lite features with an embedded Python runtime |
| **Super Bomb** (`Enhanced` channel) | Paid CheemsPay subscription | Strike Prediction, offline terrain, and Web Cockpit |

This repository is the complete public release closure for Lite and Standard.
The differentiated Super Bomb implementation, model data, private tests, and
release definition live in a separate private closure and are not built here.

The universal Launcher preserves the stable `Enhanced` channel identity. It uses
CheemsPay device authorization and never collects a CheemsPay password. Local
device identity, session state, and signed receipts are protected with Windows
DPAPI. Lite and Standard never contact CheemsPay.

## Install

1. Download the Windows Launcher from the [Bomana site](https://bomana.ruikang.wang/).
2. Standard and Lite are anonymous public downloads.
3. Super Bomb opens a browser for CheemsPay authorization.
4. Start War Thunder and enter a battle so official 8111 data is available.

Launcher verifies signed manifests, SHA-256 hashes, compatibility, atomic
installation, and one-version rollback.

For a launcher-free install, download `Bomana_Green_Lite_v8.7.0.zip` from the
GitHub Release, extract it, and run `Bomana.exe`. It contains the complete Python
runtime and only the Lite feature set. An anonymous daily-active event is sent
asynchronously; network failures never block startup or disable features.

## Public capabilities

Standard includes configurable mission timing, zone/airfield/POI navigation,
fuel and return estimates, speed/overspeed cues, checklists, tray controls,
window locking, and global hotkeys.

Lite keeps the mission timer and minimal window/tray controls. It does not include
navigation, fuel, Strike Prediction, or Web Cockpit.

## Data and security boundary

The public App uses only these official 8111 endpoints:

- `/indicators`
- `/state`
- `/map_obj.json`
- `/map_info.json`

Production releases never read process memory. Offline research workspaces and
experimental captures are not release inputs.

The subscription client is only an access decision. Enhanced manifest and
artifact delivery must also validate a short-lived CheemsPay-derived artifact
grant; public URLs or a client-only gate are not compliant paid delivery.

## Run from source

Windows, Python 3.14+, and [uv](https://docs.astral.sh/uv/) are required:

```powershell
uv sync --extra dev --frozen
uv run python Bomana.pyw
```

Public source defaults to Standard.

## Test

```powershell
uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
```

Tests target public module interfaces, Launcher installation/rollback, signed
manifests, and final artifact closure.

## Build

The public builder accepts only Standard and Lite:

```powershell
uv run --frozen python tools/build_portable.py --variant Standard --target app
uv run --frozen python tools/build_portable.py --variant Lite --target app
uv run --frozen python tools/build_portable.py --variant Lite --target green
uv run --frozen python tools/build_portable.py --target launcher
```

Signed App manifests require the `BOMANA_RELEASE_ED25519_PRIVATE_KEY`,
`BOMANA_RELEASE_ED25519_PUBLIC_KEY`, and `BOMANA_RELEASE_SIGNING_KEY_ID`
environment variables. Launcher builds additionally require the public
`CHEEMSPAY_LICENSE_PUBLIC_KEY_DER_BASE64URL` and `CHEEMSPAY_LICENSE_KEY_ID`.
Private keys must never enter the repository or logs. This builder rejects
`Enhanced`.

## Architecture

- `bomana/editions.py` is the single Edition Policy module.
- `bomana/release_closure.py` classifies public versus subscriber source paths.
- `launcher/subscription_access.py` provides the CheemsPay HTTP adapter, an
  in-memory adapter, device proof, and pinned receipt verification.
- `launcher/subscription_store.py` owns DPAPI persistence.
- `launcher/subscription_workflow.py` owns login-to-receipt orchestration.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and the
[migration runbook](docs/guides/public-private-edition-migration.md).

## License

The Lite/Standard public closure in this repository is licensed under the
[MIT License](LICENSE). Future private Super Bomb additions are outside this
repository's MIT grant. Earlier revisions obtained under MIT retain the rights
granted at that time; rewriting official Git history does not revoke those rights
or remove external copies.

War Thunder® and related marks belong to Gaijin Entertainment AG. Bomana is an
independent project and is not affiliated with, authorized by, or sponsored by
Gaijin.
