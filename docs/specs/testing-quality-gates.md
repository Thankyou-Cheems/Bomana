# Testing And Quality Gates Spec

Status: Accepted
Owner: Bomana maintainers
Prefix: `QG-`

## Scope

This spec governs local validation, CI quality gates, automated test boundaries,
test layout, and release/deploy verification tests.

## Non-goals

- This spec does not impose a repository-wide coverage threshold.
- This spec does not make automated tests a substitute for real War Thunder
  smoke.
- This spec does not require Ruff Unicode ambiguity rules to run on the whole
  repository.

## Normative Clauses

- `QG-01`: Code-changing tasks must run `uv run --extra dev ruff check .` and
  `uv run --extra dev ruff format --check .`. Pure docs or issue-only changes
  may mark Ruff as not applicable.
- `QG-02`: Refactor milestone closeout must have Ruff and pytest green. Do not
  delete, skip, or weaken tests just to pass a milestone.
- `QG-03`: `tools/scripts/check_smoke.bat` is the fast local smoke entrypoint and
  must run the same pytest suite as `uv run --extra dev pytest`.
- `QG-04`: CI quality gates use Windows, Python 3.14, `uv sync --extra dev
  --frozen`, Ruff, pytest smoke, and read-only default permissions.
- `QG-05`: Test layers should stay searchable: `test_core_*`, `test_ui_*`,
  `test_launcher_*`, `test_utils_*`, `test_quality_*`. New spec contract tests
  belong under `tests/contracts/` and should include `# enforces` headers.
- `QG-06`: Release/build/launcher/deploy tests must call
  `verify_release_manifest_signature`; do not only assert that signature fields
  exist or mock away verification.
- `QG-07`: Real War Thunder / 8111 smoke is manual validation and must not be
  included in automated-test conclusions.
- `QG-08`: Relevant focused tests should run for touched areas. Release or asset
  changes also need build or packaged-launcher smoke when appropriate.
- `QG-09`: Ruff defaults include `RUF012` and `RUF013`. `RUF001`, `RUF002`, and
  `RUF003` are targeted scans only.
- `QG-10`: During the SDD repository refactor consolidation, work is committed
  and merged locally unless the user explicitly authorizes a remote push.

## Contract Coverage

- `tests/test_quality_gate_config.py` checks pytest/smoke behavior.
- `tests/test_quality_release_workflows.py` checks release workflow policy.
- `tests/README.md` records `tests/contracts/` as the spec contract layer.
- Task state remains in `bd`; durable validation rules live in `docs/specs/`.
