# Privacy and Data Boundary

Bomana is designed as a local desktop tool. Lite and Standard do not require a
Bomana account and do not send gameplay telemetry to Bomana or CheemsPay. The
standalone Lite green distribution sends the bounded anonymous daily-active
event described below.

## Public App data

The public App reads only War Thunder's official loopback HTTP endpoints:

- `http://localhost:8111/indicators`
- `http://localhost:8111/state`
- `http://localhost:8111/map_obj.json`
- `http://localhost:8111/map_info.json`

It stores user preferences and local runtime state on the current Windows user
profile. It does not read game-process memory, inject code, modify game files,
or control the game.

## Lite green daily-active event

The green distribution bypasses the Launcher, so it reports one successful
`version_check` event per UTC day directly to
`https://bomanaupdate.ruikang.wang/api/v1/event`. The event contains:

- UTC event time;
- the fixed `Lite` channel and `green` distribution identity;
- the public App version;
- a one-way hashed Windows machine identifier and a random local install ID;
- ordinary HTTP metadata visible to the hosting infrastructure.

It does not include War Thunder telemetry, map state, aircraft, weapons, user
configuration, CheemsPay identity, file paths, or game-process data. All local
state and network work runs on a daemon thread with a bounded timeout. Failure
does not block, reject, or delay the Bomana UI startup path, and a failed event
is retried on a later launch rather than marked successful.

Set `BOMANA_DISABLE_DAU=1` or create an empty `.bomana_disable_dau` file in the
current Windows user profile to disable this event. Managed Lite and Standard
continue to rely on the Launcher update flow and do not start this App-side
reporter.

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
