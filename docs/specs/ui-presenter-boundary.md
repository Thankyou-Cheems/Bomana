# UI Presenter Boundary Spec

Status: Accepted
Owner: Bomana maintainers
Prefix: `UI-PRES-`

## Scope

This spec governs the boundary between core snapshots, headless presenter
modules, Tk renderers, and runtime side effects.

## Non-goals

- This spec does not replace the Tk threading contract.
- This spec does not require presenter modules for every small formatting
  helper.
- This spec does not allow UI modules to weaken the official 8111-only runtime
  boundary.

## Normative Clauses

- `UI-PRES-01`: Core modules must not import `bomana.ui` modules. Core snapshots
  expose domain/runtime facts only; UI strings, colors, and widget-ready models
  belong in presenter modules.
- `UI-PRES-02`: Headless presenter modules must not import `tkinter`, call widget
  mutation methods, perform grid/pack layout, play sounds, create overlays, or
  own runtime side effects.
- `UI-PRES-03`: Tk renderers and runtime services may apply presenter models, but
  they retain ownership of widget `.config()`, layout visibility, sound
  playback, tray refresh, and overlay lifecycle.
- `UI-PRES-04`: `UISnapshot` is not a compatibility bridge for display strings
  or colors. New UI-facing strings, badges, fill ratios, and option summaries
  should be computed by presenter modules or a narrowly scoped renderer helper.

## Contract Coverage

- [static] `tests/contracts/test_ui_presenter_boundaries.py` enforces
  `UI-PRES-01` and `UI-PRES-02`.
- [behavioral] `tests/test_dialog_presenter.py`, `tests/test_hud_presenter.py`,
  `tests/test_navigation_presenter.py`, `tests/test_panel_presenter.py`, and
  `tests/test_snapshot_presenter.py` enforce headless view-model behavior in
  `UI-PRES-03` and `UI-PRES-04`.
- [behavioral] `tests/test_panel_renderer.py` and
  `tests/test_navigation_runtime.py` enforce renderer/runtime ownership of the
  side effects described by `UI-PRES-03`.
