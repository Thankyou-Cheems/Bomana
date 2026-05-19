# Test Suite Guide

Bomana keeps fast automated tests in `tests/`. These tests are part of the source tree and must be committed with the code they protect.

## Layers

- `test_core_*.py`: pure game logic, telemetry parsing, navigation math, timer state, and data contracts.
- `test_ui_*.py`: Tk-facing behavior that can run headlessly with fakes or narrow widget construction.
- `test_launcher_*.py`: launcher update, install, rollback, manifest, and network fallback behavior.
- `test_utils_*.py`: persistence, diagnostics, fonts, resource lookup, and other shared helpers.
- `test_quality_*.py`: repository quality gates and workflow configuration.

Existing files may keep their current names until they need substantial edits. When adding or heavily rewriting tests, use the layer prefix above so growth stays searchable.

## Scope Rules

- Prefer focused tests that encode one user-visible behavior or one maintenance contract.
- Keep real War Thunder / `localhost:8111` validation out of automated tests; document that as manual smoke in the PR or handoff.
- Use pytest-style tests by default. `tools/scripts/check_smoke.bat` is the canonical fast local suite and must run the same tests as `uv run --extra dev pytest`.
- Add a regression test next to the layer where the bug lives. If a test needs broad cross-file setup, first ask whether the production boundary is too wide.
