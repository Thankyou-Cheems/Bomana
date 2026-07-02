# Release Signing Spec

Status: Accepted
Owner: Bomana maintainers
Prefix: `SIGN-`

## Scope

This spec governs release manifests, signing keys, launcher verification,
portable release builds, GitHub release workflows, and Tencent/EdgeOne update
asset deployment.

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
  `package_sha256`. The signed launcher payload is exactly `schema_version`,
  `launcher_version`, `launcher_asset`, `launcher_sha256`, and
  `launcher_size_bytes`.
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

## Contract Coverage

- `tests/contracts/test_manifest_schemas.py` enforces `SIGN-01`, `SIGN-02`, and
  `SIGN-10` with stdlib schema validation plus real Ed25519 sign/verify/tamper
  checks.
- `tests/test_launcher_core.py` covers signing, verification, tampering, and
  kind-confusion behavior.
- `tests/test_quality_release_workflows.py` covers verify-before-trust order,
  local-only Tencent deployment, version allowlists, workflow permissions, and
  SHA-pinned actions.
