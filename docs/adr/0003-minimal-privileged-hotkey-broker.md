# ADR 0003: Use an optional zero-install privileged hotkey broker

## Context

War Thunder may run at high integrity on Windows. A medium-integrity Bomana
process then loses game-foreground `RegisterHotKey` delivery even though the
same bindings work with ordinary foreground windows. Elevating the entire
mutable Python App package crossed too much code through UAC. Requiring a paid
Authenticode identity and a separate installer would make the safer broker path
impractical for this free project.

GitHub Artifact Attestations can establish that a release artifact came from a
specific repository, workflow, and commit. They complement Bomana's signed
release manifests and SHA-256 checks, but Windows does not consume them as an
Authenticode publisher identity.

## Decision

Keep the launcher and Python App at ordinary integrity and register ordinary
hotkeys first. At startup, make a narrowly allowlisted read-only query of visible
War Thunder top-level processes to determine whether the game is elevated. Do
not request UAC when the game is confirmed ordinary.

Ship the fixed-action native broker inside each verified App package. When the
game is elevated, absent, or unknown, expose an optional button. Only after the
user clicks it and acknowledges that Windows will show an Unknown publisher
prompt may Bomana launch the bundled broker with `runas`. Validate the adjacent
SHA-256 and hold the broker file against write/delete replacement while it
starts. The broker executes in place and sends only fixed action IDs over
per-launch ACL-restricted IPC; it is never installed or persisted.

Generate GitHub Artifact Attestations for release assets. Keep Tencent/EdgeOne
deployment on the maintainer workstation; Actions must not carry CVM deployment
credentials or upload release assets to Tencent.

## Consequences

- Ordinary-integrity games use the default hotkey path without UAC or warnings.
- Users can manually approve one UAC prompt when an elevated game needs it,
  without installing a helper, service, certificate, or scheduled task.
- Without Authenticode, Windows correctly displays Unknown publisher. Users who
  need provenance assurance must verify the release attestation and checksums.
- A user-writable package is a weaker local trust boundary than Program Files
  plus Authenticode. The fixed native surface, package hash chain, SHA sidecar,
  launch-time file lock, explicit consent, and no-persistence design reduce but
  do not eliminate that residual risk.
