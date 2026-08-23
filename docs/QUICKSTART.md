# Bomana Quick Start

Bomana Lite and Standard are public desktop editions. Super Bomb uses the same
Launcher but requires a CheemsPay subscription and a separately delivered
`Enhanced` package.

## Install and run

1. Download the Launcher from <https://bomana.ruikang.wang/>.
2. Select Standard for navigation and fuel tools or Lite for the compact timer;
   both public editions include the on-demand strike encyclopedia.
3. Launch War Thunder and enter a battle; the hangar often does not expose the
   full official 8111 data set.
4. Start Bomana. If Windows asks about network access, Lite and Standard need
   only loopback access to `localhost:8111`.

Alternatively, download `Bomana_Green_Lite_v8.7.17.zip` from the GitHub Release,
extract the complete directory, and run `Bomana.exe`. This launcher-free package
contains the Python runtime and the same Lite encyclopedia. Its anonymous daily-active
report runs in a background daemon thread, so an unavailable reporting endpoint
never delays application startup.

For Super Bomb, use the Launcher's `购买 / 试用` button to open the real
CheemsPay storefront. It currently exposes the one-year authorization and the
three-day trial. After payment, select `Enhanced`, follow the browser device
authorization prompt, and press `刷新订阅`. The Launcher never asks for a
CheemsPay password.

## Run public source

Requirements: Windows, Python 3.14+, and `uv`.

```powershell
uv sync --extra dev --frozen
uv run python Bomana.pyw
```

The public checkout defaults to Standard.

## Build public editions

```powershell
uv run --frozen python tools/build_portable.py --variant Standard --target app
uv run --frozen python tools/build_portable.py --variant Lite --target app
uv run --frozen python tools/build_portable.py --variant Lite --target green
uv run --frozen python tools/build_portable.py --target launcher
```

The public builder rejects `Enhanced`. Subscriber builds belong to the private
repository.

## Verify changes

```powershell
uv run --extra dev pytest
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
git diff --check
```

High-risk release changes should additionally inspect the produced ZIP and
verify its manifest signature, SHA-256, channel, compatibility range, and
absence of subscriber-only paths.

## Common symptoms

- **Waiting for game data** -- enter a live battle and confirm
  `http://localhost:8111/state` opens locally.
- **A public feature is unavailable** -- confirm the selected channel; Lite is
  intentionally smaller than Standard.
- **Super Bomb access expired** -- reconnect, select `Enhanced`, and refresh the
  device authorization. Cached receipts have a bounded offline lifetime.
- **Subscriber download is refused** -- local receipt validation and server-side
  artifact authorization must both pass.
- **Update is rejected** -- do not bypass signature, hash, or compatibility
  checks; reinstall through a trusted Launcher release.

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for boundaries and
[`PRIVACY.md`](PRIVACY.md) for data handling.
