# Separate Public Editions from the Subscriber Edition

Status: Accepted (2026-08-01)

Bomana will keep Lite and Standard complete in the public MIT repository while moving the differentiated Super Bomb implementation, model data, tests, and release definition into a separately access-controlled private module. The public Launcher and host may retain the stable `Enhanced` Release Channel and the integration seam, but CheemsPay owns Entitlements and paid artifact eligibility. After the private release closure is independently recoverable, the official public Git history may be rewritten so its reachable history contains only the public product. That rewrite changes the official repository topology; it does not revoke MIT permissions already granted to recipients of earlier revisions or remove their clones and forks. This split keeps the public editions genuinely buildable, prevents a package filter from masquerading as source isolation, and preserves the production rule that Strike Prediction never consumes process-memory research data.

## Consequences

- Future Super Bomb implementation and data use a non-MIT private release closure.
- Lite and Standard remain independently buildable from the public repository.
- Public-history rewriting is a final migration step after private preservation and public build verification, not the isolation mechanism itself.
- Previously distributed MIT revisions are treated as an existing compatibility and competition baseline even when they are no longer reachable from the official repository.
- Signed manifests, hash verification, atomic installation, and rollback remain Bomana responsibilities.
- Payment, account, device allowance, and Entitlement state remain CheemsPay responsibilities.
- The migration may preserve the canonical `Enhanced` channel name without preserving public Enhanced source ownership.
