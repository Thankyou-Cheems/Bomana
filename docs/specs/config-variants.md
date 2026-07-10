# Config Variants Spec

Status: Accepted
Owner: Bomana maintainers
Prefix: `CFG-`

## Scope

This spec governs the `bomana/config/` package, feature flags, build variants,
panel effective state, persisted user config, and explicit configuration
submodule boundaries.

## Non-goals

- This spec does not introduce variant-specific user config files.
- This spec does not change current default feature behavior.

## Normative Clauses

- `CFG-01`: Source runs default to full functionality. Build scripts may
  temporarily patch `ENABLE_*` flags in `bomana/config/feature_profile.py` while
  building variants and must restore the source file afterward.
- `CFG-02`: Variant matrix is fixed: Enhanced enables all listed features;
  Standard disables only `ENABLE_CCRP`; Lite disables CCRP, zones, airfields,
  fuel, and checklist. `ENABLE_ADVANCED_SETTINGS` stays true.
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

## Contract Coverage

- [static] `tests/contracts/test_config_variants.py` enforces
  `CFG-01..CFG-04` and `CFG-06..CFG-08` across the variant matrix, build patch
  target, shared config path, panel precedence, navigation fallback, and package
  boundary.
- [behavioral] `tests/test_file_utils_persistence.py` enforces `CFG-04` and
  `CFG-05` with single-file persistence and compile-switch migration cases.
