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

- `tests/contracts/test_ui_presenter_boundaries.py` enforces `UI-PRES-01` and
  `UI-PRES-02`.
- Focused presenter tests cover status, panel, dialog, HUD, and navigation view
  model behavior without creating Tk widgets.
