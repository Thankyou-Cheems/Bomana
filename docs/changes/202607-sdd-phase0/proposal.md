# 202607 SDD Phase 0 Proposal

## Problem

The repository needs canonical, tracked architecture contracts before larger
refactors split config, UI, core logic, launcher packaging, and dialogs. Existing
rules were duplicated across multiple documents, and two local guidance files are
not meant to become repository artifacts.

## Scope

Phase 0 adds specs, schemas, contract tests, and document routing only. It does
not change production runtime behavior.

## In Scope

- Add canonical specs under `docs/specs/`.
- Add app and launcher manifest schemas under `docs/specs/schemas/`.
- Add contract tests under `tests/contracts/`.
- Add an ADR for spec-anchored docs and temporary SDD commit-only closeout.
- Update entrypoint docs so duplicated rules point to specs.
- Remove stale references to the retired GitHub-to-Tencent deployment workflow.

## Out Of Scope

- Splitting `bomana/config.py`.
- Moving UI presenters or runtime services.
- Changing 8111 parsing behavior.
- Changing release signing implementation.
- Pushing the branch to remote.

## Acceptance

- Specs, schemas, ADR, change evidence, and contract tests are tracked.
- Contract tests trace back to specs and run without real 8111 or release keys.
- Ruff, format check, focused contract tests, and the full pytest suite pass.
- Phase 0 is committed locally without pushing.
