# ADR 0001: Spec-Anchored Repository Rules

Status: Accepted
Date: 2026-07-02

## Context

Bomana had durable rules duplicated across `AGENTS.md`, `README.md`,
`docs/CONTRIBUTING.md`, `docs/QUICKSTART.md`, and `docs/ARCHITECTURE.md`.
During the SDD refactor, external guidance/workorder files are intentionally
local orchestration inputs rather than tracked repository documents.

The repository needs tracked, stable specs that agents and maintainers can cite
without committing the external workorder itself.

## Decision

- Keep canonical architecture contracts under `docs/specs/`.
- Keep canonical phase outcomes in durable specs, ADRs, architecture docs, and
  changelog entries. Temporary phase proposals, deltas, and evidence notes are
  not retained after the refactor is consolidated.
- Keep durable architecture decisions under `docs/adr/`.
- Keep `AGENTS.md`, `README.md`, `docs/CONTRIBUTING.md`,
  `docs/QUICKSTART.md`, and `docs/ARCHITECTURE.md` as routing documents and
  concise summaries instead of full duplicate rulebooks.
- Keep task state in `bd`; docs must not become a parallel issue tracker.
- SDD refactor work is committed and merged locally until the user explicitly
  authorizes a remote push. This temporarily overrides the default
  session-completion push rule for this refactor only.

## Consequences

- Rule changes should update the relevant spec first, then update entrypoint
  summaries only when a reader needs a routing hint.
- Contract tests in `tests/contracts/` should guard specs that are likely to
  drift during refactors.
- After the SDD refactor is pushed or otherwise formally closed, the default
  push policy can be restored or revised through a new ADR.
