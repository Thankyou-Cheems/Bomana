# UI Presenter Boundary Spec

Status: Amended (2026-07)
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
- `UI-PRES-05`: Responsive compression for timer, speed, fuel, weapon, Web
  access, and optional elevation rows MUST preserve domain facts in the
  snapshot and compute focus ratios, concise copy, and visibility in presenters
  or renderer helpers; core logic MUST NOT emit widget-layout strings.
- `UI-PRES-06`: The speed strip MUST project the full current ratio below
  `0.7 * OverspeedConfig.CAUTION_RATIO` and continuously interpolate its lower
  viewport bound until the caution threshold so fill and all three breakup
  markers remain monotonic, visible, and dynamically separated.
- `UI-PRES-07`: Dynamic label wrapping or row visibility that increases required
  height MUST schedule one debounced geometry expansion; at supported App
  scale/DPI combinations the weapon card's bottom edge MUST remain at or above
  the bottom-card top edge.
- `UI-PRES-08`: Every App click target MUST use the shared clickable border or
  shadow plus pointer/hover feedback, while non-clickable labels MUST NOT use
  that affordance.
- `UI-PRES-09`: App fuel and weapon copy MUST use operationally clear air-combat
  terms, MUST NOT show selection-source text such as `手选`, and MUST omit a
  separate weapon model/quality row when the range/status rows already convey
  the actionable solution.

## Contract Coverage

- [static] `tests/contracts/test_ui_presenter_boundaries.py` enforces
  `UI-PRES-01` and `UI-PRES-02`.
- [behavioral] `tests/test_dialog_presenter.py`, `tests/test_hud_presenter.py`,
  `tests/test_navigation_presenter.py`, `tests/test_panel_presenter.py`, and
  `tests/test_snapshot_presenter.py` enforce headless view-model behavior in
  `UI-PRES-03..UI-PRES-06` and `UI-PRES-09`.
- [behavioral] `tests/test_panel_renderer.py` and
  `tests/test_navigation_runtime.py` enforce renderer/runtime ownership of the
  side effects described by `UI-PRES-03`.
- [behavioral] `tests/test_ui_geometry.py` and `tests/test_tk_style.py` enforce
  `UI-PRES-07..UI-PRES-08` with narrow wrapped-content geometry and shared
  clickable-affordance cases.
