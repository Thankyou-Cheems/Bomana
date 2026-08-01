# Bomana Public Architecture

This document describes the source and release closure that is intentionally
public. Lite and Standard are public MIT editions. Super Bomb keeps the stable
`Enhanced` release-channel identity but is assembled only in a private
subscriber repository.

## System boundary

Bomana is a local Windows desktop application. Its public runtime reads War
Thunder data only from the official `localhost:8111` HTTP interface, combines
those observations with user configuration, and renders local UI. It does not
read game-process memory, inject code, modify game files, or send game input.

The public repository owns four bounded responsibilities:

1. **Public App** -- Lite and Standard timing, navigation, fuel, checklist,
   speed, configuration, and local UI.
2. **Edition Policy** -- the canonical edition names, access class, public
   feature matrix, and build eligibility.
3. **Universal Launcher** -- signed-manifest resolution, verified installation,
   rollback, and the CheemsPay subscription client.
4. **Release Closure** -- a fail-closed classification that prevents subscriber
   implementation and data from entering public artifacts.

## Module map

```text
Bomana.pyw
  -> bomana.config       configuration and public feature profiles
  -> bomana.core         official 8111 transport, timing, navigation, state
  -> bomana.ui           Standard/Lite presentation and desktop lifecycle

launcher.pyw
  -> launcher.core                    manifests, hashes, install, rollback
  -> launcher.subscriber_artifacts     private logical-resource namespace
  -> launcher.subscription_workflow   authorization orchestration
       -> subscription_access         CheemsPay port + HTTPS adapter
       -> subscription_store          Windows DPAPI persistence

bomana.editions          single Edition Policy module
bomana.release_closure   public/subscriber source-path policy
bomana.ui.strike_prediction
                         optional subscriber UI port; inert publicly
```

Dependencies point inward toward small interfaces. Public App modules never
import private prediction, model, terrain, or Web Cockpit implementations. The
private repository supplies its adapter at assembly time; Lite and Standard use
the inert adapter.

## Edition Policy

`bomana.editions` is the only authority for edition identity and access class.

| Canonical channel | Access | Public build allowed |
|---|---|---|
| `Lite` | Public | Yes |
| `Standard` | Public | Yes |
| `Enhanced` | CheemsPay subscription | No |

Public source defaults to Standard. Public builders reject `Enhanced` rather
than silently producing a partial or mislabeled package. The Launcher may still
recognize `Enhanced`; channel identity is an interoperability contract, not
permission to package subscriber code.

## Public runtime flow

1. The App loads and normalizes local configuration.
2. The selected public feature profile is derived from Edition Policy.
3. Runtime workers poll the bounded official 8111 endpoints.
4. Core state machines calculate timing, navigation, fuel, and safety cues.
5. Immutable view state crosses into the Tk owner thread for rendering.
6. Shutdown stops workers before destroying UI resources.

Network failure, incomplete telemetry, and stale observations degrade to an
explicit unavailable state. They do not activate hidden data sources.

## Subscriber access seam

The universal Launcher uses an OAuth-style device authorization flow. The user
authenticates in a browser controlled by CheemsPay; Bomana does not collect an
account password. A local Ed25519 device identity proves possession, and the
Launcher verifies a pinned, device-bound EdDSA subscription receipt.

Receipt validation is fail closed and covers issuer, audience, application,
feature, device thumbprint, service expiry, receipt expiry, entitlement version,
and a bounded offline-validity window. Secrets and receipts are stored with
Windows DPAPI for the current user.

For online Enhanced delivery, the Launcher requests a fresh CheemsPay grant for
one exact logical resource, signs the exact gateway GET path with the device
key, and rejects redirects while authorization headers are present. This path
covers the App manifest, ZIP, changelog, terrain manifest, and every
content-addressed terrain object. The independently deployed gateway verifies
the grant with only CheemsPay's public key and serves a read-only private tree;
it receives neither database credentials nor the signing private key. Signed
release manifests and SHA-256 checks remain the content-integrity boundary
after authorization.

## Release closure

`bomana.release_closure` owns path classification. Public packaging walks the
candidate tree and includes a path only when that policy accepts it. The same
policy is tested directly and against generated ZIP contents.

The public closure excludes:

- subscriber prediction and weapon-model implementation;
- private model catalogs and terrain payloads;
- Web Cockpit runtime/assets;
- private extraction, calibration, capture, and terrain-build tools;
- private behavior tests and implementation-specific specs;
- an `Enhanced` App build definition.

ZIP filtering is defense in depth. Subscriber implementation is physically
absent from this repository; it is not merely hidden by a build flag.

## Release trust

App, Launcher, and subscriber manifests are signed with Ed25519. The Launcher
verifies the signature, artifact SHA-256, canonical file name, channel,
compatibility range, and downgrade policy before atomic installation. A last
known-good version is retained for rollback.

Private signing keys and CheemsPay issuer keys are deployment inputs, never
tracked files. Public CI builds only Lite and Standard. Private CI alone may
assemble `Enhanced` after its repository and delivery boundary are configured.

## Change rules

- Add edition behavior through `bomana.editions`, not scattered string checks.
- Add subscriber functionality behind the optional public port; do not add a
  private import to a public module.
- Treat release contents as an API and test the final archive.
- Keep adapters at system edges and use in-memory adapters in unit tests.
- Prefer behavior contracts over source-text assertions or private file-layout
  tests.
- A new official game endpoint requires an explicit boundary review.
- Offline research inputs must remain outside production release paths.

The split rationale is recorded in
[`adr/0011-separate-public-and-subscriber-editions.md`](adr/0011-separate-public-and-subscriber-editions.md).
The recoverable migration and cutover sequence is in
[`guides/public-private-edition-migration.md`](guides/public-private-edition-migration.md).
