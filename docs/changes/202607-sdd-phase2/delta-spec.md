# 202607 SDD Phase 2 Delta Spec

## UI Presenter Boundary

- `UI-PRES-01`: Core modules must not import `bomana.ui` presenters. During the
  compatibility period, `GameLogic.snapshot()` may still populate legacy
  `UISnapshot` display fields, but new presenter extraction must not introduce a
  core-to-UI dependency.
- `UI-PRES-02`: Headless presenter modules must not import `tkinter`, call widget
  mutation methods, perform grid/pack layout, play sounds, or create runtime
  overlays.
- `UI-PRES-03`: Tk renderers and runtime services may apply presenter models, but
  they retain ownership of widget `.config()`, layout visibility, sound playback,
  tray refresh, and overlay lifecycle.
- `UI-PRES-04`: `UISnapshot` remains the compatibility surface for existing UI
  consumers until a later phase introduces a separate domain snapshot adapter.

## New Presenter Modules

- `bomana/ui/panel_presenter.py`: fuel, bombing, speed strip, and speed-history
  header view models.
- `bomana/ui/hud_presenter.py`: HUD target and standby model selection.
- `bomana/ui/dialog_presenter.py`: settings-dialog option and summary models.
- `bomana/ui/snapshot_presenter.py`: top-level lifecycle/status presentation
  model for the future `DomainSnapshot -> UISnapshot` adapter.

## Behavior

No user-visible string, color, layout, or sound behavior is intentionally changed.
The extraction is intended to make these behaviors testable without Tk.
