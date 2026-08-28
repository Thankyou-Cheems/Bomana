# Contributing

Use PowerShell 7 on Windows. Do not require Python for the current source tree.

## Web

```powershell
cd frontend
pnpm install --frozen-lockfile
pnpm check
```

`pnpm check` runs unit tests, builds Lite and Standard, and builds the Online Launcher.

## Bridge

```powershell
cd native\telemetry_gateway
go test ./...
go vet ./...
```

## Public-boundary rule

Do not add Enhanced algorithms, terrain data, chat recognition, tactical coordinates, Y66, airport-module inference, or weapon-solving implementation to this repository. The Launcher may retain the Enhanced label and public authorization client, but public builds cannot contain Enhanced assets.

Run `tools/check_public_boundary.ps1` after building. This public repository contains no deployment workflow, production server path, SSH/Caddy operation, or release credential. Deployment belongs to the private release closure.
