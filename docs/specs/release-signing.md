# Release Signing Spec

Status: Accepted
Owner: Bomana maintainers
Prefix: `SIGN-`

## Scope

This spec governs release manifests, signing keys, launcher verification,
portable release builds, GitHub Artifact Attestations, GitHub release workflows,
and Tencent/EdgeOne update asset deployment, including the native hotkey broker
bundled inside each App package.

## Non-goals

- This spec does not authorize private-key rotation.
- This spec does not define the separate `bomana-worker` service internals.
- This spec does not require Tencent/EdgeOne public responses to match the strict
  local manifest schemas after service-derived fields are added.

## Normative Clauses

- `SIGN-01`: `manifest_<Variant>.json` and `launcher_manifest.json` must contain
  a non-empty Ed25519 `manifest_signature.algorithm`, `manifest_signature.key_id`,
  and `manifest_signature.signature`.
- `SIGN-02`: The signed app payload is exactly `schema_version`, `channel`,
  `app_version`, `min_launcher_version`, `entrypoint`, `package_asset`, and
  `package_sha256`, `changelog_asset`, and `changelog_sha256`. The signed
  launcher payload is exactly `schema_version`, `launcher_version`,
  `launcher_asset`, `launcher_sha256`, and `launcher_size_bytes`.
- `SIGN-03`: Launcher and deploy code must call
  `verify_release_manifest_signature(expected_kind=...)` before trusting version,
  asset, SHA256, entrypoint, or URL fields. Launcher updates must prefer signed
  `launcher_sha256` over any service-derived `package_sha256` alias.
- `SIGN-04`: Build signing requires `BOMANA_RELEASE_ED25519_PRIVATE_KEY`,
  `BOMANA_RELEASE_ED25519_PUBLIC_KEY`, and `BOMANA_RELEASE_SIGNING_KEY_ID`. The
  public key must match the private key. The default key id is
  `bomana-release-2026-06`.
- `SIGN-05`: Do not generate, rotate, overwrite, upload, or print release private
  keys unless the user explicitly approves the private-key retention plan.
  TencentCloudPublic / `bomana-update` must not hold the release private key.
- `SIGN-06`: Tencent/EdgeOne services may only forward `manifest_signature` and
  add derived fields such as URL, source, size, and launcher `package_sha256`
  compatibility aliases.
- `SIGN-07`: Tencent/EdgeOne deployment must run locally from the maintainer
  workstation through `tools/deploy_update_assets.py`. GitHub Actions must not
  SSH, rsync, or scp release assets to TencentCloudPublic/CVM. Do not introduce
  unapproved paid COS/CDN artifact storage.
- `SIGN-08`: Release workflows default to `permissions: contents: read`; only the
  final release job may use `contents: write`. Release version/tag inputs must be
  allowlisted. GitHub expressions must enter shell scripts through environment
  variables. External `uses:` actions must be pinned to full commit SHAs.
- `SIGN-09`: App `--version` values must match `bomana/metadata.py __version__`;
  launcher `--version` values must match `launcher/metadata.py LAUNCHER_VERSION`.
- `SIGN-10`: `docs/specs/schemas/app-manifest.schema.json` and
  `docs/specs/schemas/launcher-manifest.schema.json` are the shape source of
  truth for local release-owned manifests.
- `SIGN-11`: Launcher release/signing helpers used by `launcher.pyw`,
  `launcher/`, and release tools must live under the `launcher` package, not the
  app package namespace. This avoids app-package import isolation resolving a
  launcher helper from an installed app bundle with a different version.
- `SIGN-12`: Every App package MUST contain
  `bomana/bin/BomanaHotkeyBroker.exe` plus its adjacent SHA256 sidecar, and the
  release workflow MUST build that broker from `native/hotkey_broker/` in the
  same workflow run before packaging; no separate broker installer or broker
  GitHub Release asset may be published.
- `SIGN-13`: Release jobs that produce App or Launcher assets MUST grant only
  `contents: read`, `id-token: write`, `attestations: write`, and
  `artifact-metadata: write`, then use a full-commit-pinned `actions/attest@v4`
  step to attest the final executable/package, manifest, and checksum files
  before uploading them as workflow artifacts.
- `SIGN-14`: Artifact Attestations MUST supplement rather than replace Ed25519
  manifest verification and SHA256 asset checks; user documentation MUST state
  that `gh attestation verify <artifact> --repo Thankyou-Cheems/Bomana` verifies
  GitHub build provenance but does not create an Authenticode/UAC publisher.
- `SIGN-15`: Each App release MUST publish a version-specific changelog asset;
  Launcher MUST resolve it from the same selected source as the App manifest,
  verify its signed SHA256 before display, and show it after a successful App
  update. Changelog retrieval failure MAY warn without rolling back an already
  verified App install.

## Contract Coverage

- [behavioral] `tests/contracts/test_manifest_schemas.py` enforces `SIGN-01`,
  `SIGN-02`, `SIGN-10`, and `SIGN-15` with schema validation plus real Ed25519
  sign/verify/tamper checks.
- [behavioral] `tests/contracts/test_launcher_package_boundaries.py` and
  `tests/test_launcher_core.py` enforce verify-before-projection, version-source,
  kind-confusion, and package-ownership rules in `SIGN-03`, `SIGN-09`, and
  `SIGN-11`.
- [behavioral] `tests/test_build_metadata.py` enforces signing-input and version
  consistency rules in `SIGN-04` and `SIGN-09`.
- [static] `tests/test_quality_release_workflows.py` enforces `SIGN-03` and
  `SIGN-05..SIGN-09` and `SIGN-12..SIGN-14`, including local-only Tencent
  deployment, forwarding boundaries, input allowlists, least permissions,
  full-commit-pinned attestation actions, bundled broker packaging, and the
  absence of an installer/release-side broker asset.
- [behavioral] `tests/test_launcher_update_service.py` enforces source-aligned
  changelog resolution and SHA256 verification in `SIGN-15`.
- [manual] Explicit maintainer approval of any private-key retention or rotation
  plan covers the authorization portion of `SIGN-05`.
