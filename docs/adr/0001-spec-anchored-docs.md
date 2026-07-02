# ADR 0001: Spec-Anchored Repository Rules

Status: Accepted
Date: 2026-07-02

## Context

Bomana had durable rules duplicated across `AGENTS.md`, `README.md`,
`docs/CONTRIBUTING.md`, `docs/QUICKSTART.md`, and `docs/ARCHITECTURE.md`.
During the SDD refactor, the external guidance files `spec.md` and
`BOMANA_SDD_WORKORDER.md` are intentionally local orchestration inputs rather
than tracked repository documents.

The repository needs tracked, stable specs that agents and maintainers can cite
without committing the external workorder itself.

## Decision

- Keep canonical architecture contracts under `docs/specs/`.
- Keep phase proposals, deltas, evidence, and review notes under
  `docs/changes/<change-id>/`.
- Keep durable architecture decisions under `docs/adr/`.
- Keep `AGENTS.md`, `README.md`, `docs/CONTRIBUTING.md`,
  `docs/QUICKSTART.md`, and `docs/ARCHITECTURE.md` as routing documents and
  concise summaries instead of full duplicate rulebooks.
- Keep task state in `bd`; docs may record phase evidence but must not become a
  parallel issue tracker.
- During the active SDD refactor, phase work is committed locally and not pushed
  unless the user explicitly authorizes a push. This temporarily overrides the
  default session-completion push rule for this refactor only.

## Consequences

- Rule changes should update the relevant spec first, then update entrypoint
  summaries only when a reader needs a routing hint.
- Contract tests in `tests/contracts/` should guard specs that are likely to
  drift during refactors.
- When the SDD refactor finishes, the default push policy can be restored or
  revised through a new ADR.
