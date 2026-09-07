# Bomana

War Thunder sortie timer and flight navigation. Lite provides the timer; Standard adds official zone / airfield navigation, aircraft speed limits, fuel estimates, a picture-in-picture window and local mobile pairing.

[Website](https://bomana.ruikang.wang/) · [Launcher and Bridge downloads](https://bomana.ruikang.wang/launcher/) · [Flight toolbox](https://bomana.ruikang.wang/calculator/)

This is a generated public source distribution. Public Web, its shared runtime and parameters, Bridge and Launcher come from one maintained source and are synchronized after validation. Contributions are incorporated in the maintained source first, then exported here. Existing history, tags and Releases are preserved; use the online Launcher for current downloads.

Enhanced solvers, terrain and advanced target algorithms are private. Bridge relays official 8111 observations and provides local storage / pairing transport. It neither controls the game nor owns edition entitlements.

With Node.js 22, pnpm 11.3.0, Go 1.25 and PowerShell 7:

```pwsh
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend check
go -C native/telemetry_gateway test ./...
go -C native/telemetry_gateway vet ./...
```

Outputs: `frontend/dist/Lite`, `Standard` and `launcher`. Local builds use a public development signing key; production Bridge accepts production signed assets only. Public Actions run checks without production credentials. Official builds and signing belong to the maintained source; deployment is performed locally by the maintainer.

Standard mobile pairing needs the same LAN and no account. Desktop picture-in-picture requires a supported Edge / Chrome version. Browser suspension can pause processing; reconnect and sortie recovery handle resume. Fuel estimates remain conditional on aircraft data and observed flight samples.

[Edition boundaries](docs/specs/public-editions.md) · [Architecture](docs/ARCHITECTURE.md) · [Privacy](docs/PRIVACY.md) · [MIT license](LICENSE).
