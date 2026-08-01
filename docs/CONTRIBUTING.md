# Contributing to Bomana

Bomana is developed on Windows with Python 3.14, `uv`, pytest, and Ruff. This
public repository accepts changes to Lite, Standard, the universal Launcher,
and their stable integration interfaces. Super Bomb implementation belongs in
the private subscriber repository.

## Sources of truth

| Topic | Source |
|---|---|
| Module and dependency boundaries | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| Durable behavior contracts | [`specs/`](specs/) |
| Test placement | [`../tests/README.md`](../tests/README.md) |
| Failure modes | [`PITFALLS.md`](PITFALLS.md) |
| User-visible changes | [`CHANGELOG.md`](CHANGELOG.md) |

## Set up

```powershell
git clone https://github.com/YOUR_USERNAME/Bomana.git
cd Bomana
uv sync --python 3.14.5 --extra dev --frozen
uv run python Bomana.pyw
```

Public source runs Standard. Do not patch the source tree to emulate
`Enhanced`; use the private repository for subscriber development.

## Workflow

1. Read the owning contract and nearby tests.
2. Make one coherent change behind an existing module interface, or introduce a
   small interface before changing multiple consumers.
3. Update behavior tests and final-artifact assertions.
4. Run focused checks, then the repository gates.
5. Report automated, packaged, and real-game evidence separately.

Preserve unrelated working-tree changes. Do not weaken a security, update, or
release-closure check to make a build pass.

## Required checks

```powershell
uv run --extra dev ruff check .
uv run --extra dev ruff format --check .
uv run --extra dev pytest
git diff --check
```

Additional checks:

| Area | Evidence |
|---|---|
| Native hotkey broker | Cargo format/test and development broker build |
| Launcher or release code | Focused manifest/install tests and packaged Launcher smoke |
| 8111/runtime/UI | Focused tests plus separately reported live-game smoke |
| Edition or closure policy | Inspect generated Standard and Lite archives |
| Visible UI | Screenshots at representative DPI/scale settings |

Automated fixtures are not evidence of current live War Thunder behavior.

## Architecture rules

- Use `bomana.editions` for channel identity and access decisions.
- Use `bomana.release_closure` for public artifact contents.
- Public modules may depend on `bomana.ui.strike_prediction`, but never on a
  subscriber implementation module.
- Keep CheemsPay account and billing semantics behind the subscription authority
  interface.
- Keep Tk access on the UI owner thread.
- Keep offline research and extraction data outside production paths.
- Reject an unavailable or unverifiable input instead of inventing a fallback
  authority.

## Tests and contracts

Contract tests begin with an exact line such as:

```python
# enforces: docs/specs/config-variants.md CFG-01
```

Prefer observable behavior, in-memory adapters, and final ZIP inspection over
source-string assertions. Private behavior tests and model fixtures must not be
copied into the public repository.

## Releases

Public CI builds only Standard and Lite. It may also build the universal
Launcher. `Enhanced` is assembled and published by private CI after both local
receipt validation and server-side artifact authorization are configured.

Release changes must preserve Ed25519 signatures, SHA-256 verification,
compatibility floors, atomic installation, and rollback. Never print, commit,
rotate, or replace production private keys as part of an ordinary code change.

The website under `docs/` is a separate public deployment. Follow
[`guides/public-site-cutover.md`](guides/public-site-cutover.md) for a reversible
cutover. GitHub-hosted Actions must not SSH, rsync, or scp artifacts to the
Tencent host.

## Pull requests

Use focused branches and Conventional Commits. Include the objective, relevant
contract, checks run, manual-smoke status, and screenshots when UI changed.
