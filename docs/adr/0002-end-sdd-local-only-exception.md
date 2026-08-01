# ADR 0002: End The SDD Local-Only Closeout Exception

Status: Accepted
Date: 2026-07-10

## Context

ADR 0001 temporarily kept the spec-anchored repository refactor local until the
user authorized publication. That refactor and its canonical specs are now on
the remote `main` branch, so the temporary exception has reached its exit
condition. Leaving it in `AGENTS.md` and the quality-gate spec would create two
conflicting closeout policies.

## Decision

- End the SDD local-only commit and push exception.
- Restore the repository's default rule that completed work is pushed unless an
  explicitly authorized commit-only task is recorded in an active ADR or bd
  decision.
- Keep temporary phase policies in work orders or ADRs with an owner and exit
  condition; do not encode them as durable quality-gate clauses.

## Consequences

- Remove the obsolete SDD exception from `AGENTS.md`.
- Remove `QG-10` from `docs/specs/testing-quality-gates.md`.
- Keep ADR 0001 unchanged as the historical record of the original exception.
