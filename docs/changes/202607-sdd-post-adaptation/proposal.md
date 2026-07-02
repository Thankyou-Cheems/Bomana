# 202607 SDD Post-Adaptation Proposal

## Problem

The SDD refactor paused or deferred pre-existing bd work while module boundaries
were changing. Those issues must be re-evaluated against the new config, UI,
core, and launcher package boundaries before normal development resumes.

## Scope

- Review deferred non-SDD bd issues after Phase 5.
- Reopen issues that still make sense, with notes pointing to current modules.
- Leave external or boundary-changing work deferred with an explicit rationale.
- Keep temporary compatibility facades tracked by follow-up bd issues.
- Treat `spec.md` and `BOMANA_SDD_WORKORDER.md` as guidance-only local files.

## Out Of Scope

- Implementing the reopened feature or bug work.
- Removing compatibility facades during this adaptation pass.
- Pushing the branch to remote.
- Tracking work outside bd.

## Acceptance

- Every deferred non-SDD issue has a status or note update.
- Reopened work references the post-refactor module boundaries.
- Work that stays deferred has a concrete reason.
- bd ready exposes valid post-refactor work after the SDD epic closes.
