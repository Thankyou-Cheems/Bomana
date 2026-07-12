# Navigation Cues And Actions Spec

Status: Accepted
Owner: Bomana maintainers
Prefix: `NAVCUE-`

## Scope

This spec governs the shared integrated/standalone heading-tape cues, the
standalone-navigation mode transition, visible main-window action affordances,
and the tray fallback for optional administrator hotkeys.

## Non-goals

- This spec does not promote POIs or traceback locations into the primary
  navigation status row.
- This spec does not define how core telemetry detects or stores a traceback
  location.
- This spec does not weaken the optional privileged-hotkey boundary in
  `docs/specs/startup-elevation.md`.

## Normative Clauses

- `NAVCUE-01`: `HeadingTape` MUST render an in-range POI as four red L-shaped
  corners around an open center and MUST NOT use a diamond glyph for its
  marker, distance label, overflow cue, or legend.
- `NAVCUE-02`: A `traceback` target MUST have marker and overflow cues that are
  visually distinct from POI cues and MUST remain on the existing heading tape
  without creating another navigation row.
- `NAVCUE-03`: The standalone navigation title-bar close action and
  `WM_DELETE_WINDOW` MUST call `AppNavigationServices.switch_to_integrated()`;
  `NavigationWindow.hide()` MUST remain a temporary lifecycle operation that
  does not change the configured mode.
- `NAVCUE-04`: `AppNavigationServices` MUST route toggle and explicit mode
  changes through one idempotent private mode-setting path and MUST persist and
  refresh UI state only when the configured mode changes.
- `NAVCUE-05`: Main-window navigation, weapon-selection, nudge, and panel-close
  actions MUST have persistent styled-button affordances, and a weapon
  selection action MUST appear before the rightmost close action while the
  existing whole-card click target remains available.
- `NAVCUE-06`: When `_hotkey_broker_action` is `elevate`, the tray MUST expose an
  `启用游戏内热键…` action whose callback reaches `App._on_nudge_action()` only
  through the Tk dispatcher.
- `NAVCUE-07`: `App._nudge_text()` MUST tell a locked user to switch out of the
  game and press the configured lock key before clicking the App action, or to
  use the tray action directly.
- `NAVCUE-08`: Standalone navigation mode MUST move only the shared heading
  tape out of the main window; main-window zone and airfield list visibility
  MUST continue to follow the persisted `show_zones` and `show_airfields`
  choices and MUST change only through the existing manual panel actions.
- `NAVCUE-09`: While the selected weapon role is `aam`, both heading tapes
  MUST project every current `hostile_aircraft` and every POI in the immutable
  snapshot as non-primary potential navigation targets, MUST remove primary and
  active-target emphasis from every zone, and MUST visibly state
  `战区解算已暂停，仅进行导航`. These cues and any selected AAM calculation
  target MUST NOT imply a game lock, launch authorization, or verified target.

## Contract Coverage

- [behavioral] `tests/test_ui_geometry.py` enforces `NAVCUE-01` and `NAVCUE-02`
  with Canvas marker geometry and overflow text.
- [static] `tests/test_ui_geometry.py` enforces `NAVCUE-05` with legend, widget
  type, shared style, and rightmost-action checks.
- [behavioral] `tests/test_navigation_runtime.py` enforces `NAVCUE-03` and
  `NAVCUE-04` with explicit-close, temporary-hide, persistence, and idempotence
  cases.
- [behavioral] `tests/test_runtime_services.py` enforces `NAVCUE-06` with
  dynamic tray visibility and dispatcher delivery.
- [behavioral] `tests/test_ui_app_config.py` enforces `NAVCUE-07` with locked
  and unlocked privilege-guidance cases.
- [behavioral] `tests/test_panel_renderer.py` enforces `NAVCUE-08` by keeping
  persisted zone and airfield lists mounted while the heading tape is
  standalone.
- [behavioral] `tests/test_navigation_presenter.py`,
  `tests/test_panel_renderer.py`, and `tests/test_navigation_window.py` enforce
  `NAVCUE-09` with all-current-hostile/POI projection, neutral zones, and the
  shared navigation-only notice.
