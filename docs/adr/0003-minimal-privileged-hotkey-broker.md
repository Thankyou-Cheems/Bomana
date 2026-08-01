# ADR 0003: Use an optional zero-install privileged hotkey broker

Status: Amended
Date: 2026-07-10
Amended: 2026-07-24

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
hotkeys directly. The production App does not enumerate game windows or
processes, query executable identities or tokens, or use game focus/integrity
as a runtime input. Startup never requests UAC.

The fixed-action native broker remains package-verifiable compatibility
infrastructure. A build may expose it only as an explicit user-initiated action,
never because it inspected the game. After the user acknowledges that Windows
will show an Unknown publisher prompt, Bomana may launch only the bundled broker
with `runas`. It validates the adjacent SHA-256 and holds the file against
write/delete replacement while it starts. The broker executes in place and
sends only fixed Bomana action IDs over per-launch ACL-restricted IPC; it is
never installed or persisted.

Generate GitHub Artifact Attestations for release assets. Keep Tencent/EdgeOne
deployment on the maintainer workstation; Actions must not carry CVM deployment
credentials or upload release assets to Tencent.

## Consequences

- The default hotkey path has no game-process query, UAC, or warning.
- Users can manually approve one UAC prompt when an elevated game needs it,
  without installing a helper, service, certificate, or scheduled task.
- Without Authenticode, Windows correctly displays Unknown publisher. Users who
  need provenance assurance must verify the release attestation and checksums.
- A user-writable package is a weaker local trust boundary than Program Files
  plus Authenticode. The fixed native surface, package hash chain, SHA sidecar,
  launch-time file lock, explicit consent, and no-persistence design reduce but
  do not eliminate that residual risk.
