# Config Variants Spec

Status: Amended (2026-07)
Owner: Bomana maintainers
Prefix: `CFG-`

## Scope

This spec governs the `bomana/config/` package, feature flags, build variants,
panel effective state, persisted user config, and explicit configuration
submodule boundaries.

## Non-goals

- This spec does not introduce variant-specific user config files.
- This spec does not change current default feature behavior.
- This spec authorizes only the explicit Launcher LAN-startup boolean; it does
  not authorize persisted listener addresses/ports, pairing, sessions, CSRF,
  authorization epochs, or other Web-control state.

## Normative Clauses

- `CFG-01`: Source runs default to full functionality. Build scripts may
  temporarily patch `ENABLE_*` flags in `bomana/config/feature_profile.py` while
  building variants and must restore the source file afterward.
- `CFG-02`: Variant matrix is fixed: Enhanced enables all listed features;
  Standard disables only `ENABLE_CCRP`; Lite disables CCRP/weapon solution,
  zones, airfields, fuel, and checklist. `ENABLE_ADVANCED_SETTINGS` stays true.
- `CFG-03`: `ENABLE_*` flags take precedence over user config. A build-disabled
  feature must not be re-enabled by persisted config, UI, tray, hotkey, or core
  code.
- `CFG-04`: Enhanced, Standard, and Lite variants share one config schema and
  config file. Do not introduce variant-specific config storage.
- `CFG-05`: Config persistence must store `compile_switches`. When a feature
  changes from disabled to enabled, its panel returns to the default visible
  state. If historical switches are missing, preserve the user's hidden-panel
  choices.
- `CFG-06`: Effective feature state is build flag plus user panel state. Speed is
  always available; speed-history mode may temporarily suppress other extended
  panels.
- `CFG-07`: If `ENABLE_ZONES` is false, standalone navigation config is invalid
  and must be forced back to integrated mode.
- `CFG-08`: Config package changes must preserve `from bomana import config`
  as a package import, but callers must import symbols from explicit
  submodules: `bomana.config.feature_profile`, `bomana.config.settings`, or
  `bomana.config.static_data`. Project metadata lives in `bomana.metadata`, and
  runtime theme tokens live in `bomana.ui.theme`.
- `CFG-09`: For backward compatibility, `ENABLE_CCRP` and persisted
  `show_bombing` MUST gate the complete compact weapon-solution card, including
  CCRP, AAM, AGM, guided-bomb, and glide-bomb estimates; code MUST NOT create a
  parallel feature flag or panel key for that card.
- `CFG-10`: The only Launcher-persisted Web preferences MUST be boolean
  `web_dashboard_autostart` (default `true`), boolean
  `web_dashboard_auto_open` (default `false`), and boolean
  `web_dashboard_lan_enabled` (default `false`).
- `CFG-11`: A missing or non-boolean Launcher Web preference MUST fall back to
  its `CFG-10` default rather than applying truthiness coercion.
- `CFG-12`: Launcher bootstrap MUST pass only the three `CFG-10` booleans to the
  App and MUST NOT pass or persist a Web host, port, pairing URL, selected
  interface, separate LAN-control choice, session, CSRF proof, or authorization
  epoch.
- `CFG-13`: The App MUST choose the listener and port, generate pairing URLs,
  discover eligible interfaces, decide browser-open timing after successful
  loopback startup, and own all live LAN listeners and control state.
- `CFG-14`: Selecting `web_dashboard_lan_enabled` MUST also select
  `web_dashboard_autostart`; clearing Web autostart MUST clear LAN startup so
  the Launcher cannot request LAN without an App Web runtime.

## Contract Coverage

- [static] `tests/contracts/test_config_variants.py` enforces
  `CFG-01..CFG-04` and `CFG-06..CFG-14` across the variant matrix, build patch
  target, shared config path, panel precedence, navigation fallback, package
  boundary, and the exact Launcher Web preference allowlist.
- [behavioral] `tests/test_file_utils_persistence.py` enforces `CFG-04` and
  `CFG-05` with single-file persistence and compile-switch migration cases.
- [behavioral] `tests/test_launcher_update_service.py` and
  `tests/test_launcher_launch_flow.py` enforce `CFG-10..CFG-14` with defaults,
  strict boolean recovery, forbidden legacy-key migration, state round-trips,
  and bootstrap handoff cases.
- [behavioral] `tests/test_runtime_services.py` enforces `CFG-10`, `CFG-12`, and
  `CFG-13` with loopback autostart, lazy start, optional local open, automatic
  interface discovery, and App-owned LAN/control lifecycle cases.
