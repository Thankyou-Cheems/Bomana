# Privacy and Data Boundary

Bomana is designed as a local desktop tool. Lite and Standard do not require a
Bomana account and do not send gameplay telemetry to Bomana or CheemsPay.

## Public App data

The public App reads only War Thunder's official loopback HTTP endpoints:

- `http://localhost:8111/indicators`
- `http://localhost:8111/state`
- `http://localhost:8111/map_obj.json`
- `http://localhost:8111/map_info.json`

It stores user preferences and local runtime state on the current Windows user
profile. It does not read game-process memory, inject code, modify game files,
or control the game.

## Updates

The Launcher contacts Bomana release services to resolve signed manifests and
download selected artifacts. Requests necessarily expose ordinary network
metadata such as IP address, time, HTTP headers, requested channel, and version
to the hosting infrastructure. Artifact integrity is checked locally before
installation.

## Super Bomb subscription

Lite and Standard do not contact CheemsPay. Selecting `Enhanced` starts a
browser-based device authorization with CheemsPay. The Launcher exchanges:

- the public application/client identity;
- an ephemeral device authorization code;
- a locally generated public device key and device label;
- a bearer session while refreshing authorization;
- a signed, device-bound subscription receipt.

Bomana does not collect or store the user's CheemsPay password or payment-card
details. CheemsPay remains the authority for account, billing, and subscription
records.

The local device private key, session data, and receipt are protected with
Windows DPAPI for the current user. The receipt contains bounded authorization
claims such as subject, product, features, device thumbprint, issue/expiry
times, entitlement version, token identifier, and signing-key identifier.

## Retention and removal

Removing Bomana does not automatically remove its per-user configuration and
Launcher state. Use the Launcher sign-out/remove-device action where available,
then delete the Bomana user-data directory if a complete local reset is desired.
Deleting local state does not delete CheemsPay account or billing records;
manage those through CheemsPay.

## Research boundary

Offline research captures, extraction tools, and experimental data are not
production inputs and are not transmitted by the public App. Only reviewed
static data may be assembled into the separate private subscriber release.

Security or privacy reports should follow the repository's published security
contact and disclosure process.
