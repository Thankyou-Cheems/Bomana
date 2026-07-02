# 202607 SDD Phase 4 Proposal

## Problem

`launcher.pyw` is still the user-facing green launcher entrypoint and also owns
network source resolution, manifest verification, download caching, install
preflight, launcher self-update, telemetry, app bootstrap, and Tk UI. That shape
makes release-signing invariants hard to review because the order of "verify
manifest, then trust fields" is expressed inline in a large script.

## Scope

- Introduce a top-level `launcher/` package as the development-time owner for
  launcher responsibilities while preserving `launcher.pyw` as the compatibility
  and distribution entrypoint.
- Move or wrap manifest verification/projection, download-cache naming,
  install transaction exports, bootstrap helpers, self-update, GUI, and
  telemetry behind named package modules.
- Keep existing launcher behavior, update endpoints, Ed25519 key handling,
  Tencent local-only deployment semantics, and single-file PyInstaller output.
- Add contract tests for verify-before-trust and package/facade boundaries.

## Out Of Scope

- Running Tencent/EdgeOne deployment scripts.
- Generating, rotating, printing, or uploading signing private keys.
- Changing app manifest or launcher manifest signed field sets.
- Removing `launcher.pyw` compatibility exports during this phase.
- Pushing the branch to remote.

## Acceptance

- `launcher.pyw` remains runnable and remains the build entrypoint.
- New `launcher/` package modules expose the launcher architecture boundaries.
- Manifest parsing uses a verified projection helper before trusting version,
  asset, SHA256, entrypoint, or channel fields.
- Existing launcher install, rollback, self-update, and app bootstrap tests pass.
- Focused launcher tests, Ruff, and full pytest pass.
