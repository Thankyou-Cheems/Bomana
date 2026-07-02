# Config Variants Spec

Status: Accepted
Owner: Bomana maintainers
Prefix: `CFG-`

## Scope

This spec governs `bomana/config.py`, any future `bomana/config/` package split,
feature flags, build variants, panel effective state, persisted user config, and
metadata/theme re-export compatibility.

## Non-goals

- This spec does not implement the Phase 1 config package split.
- This spec does not introduce variant-specific user config files.
- This spec does not change current default feature behavior.

## Normative Clauses

- `CFG-01`: Source runs default to full functionality. Build scripts may
  temporarily patch `ENABLE_*` flags while building variants and must restore the
  source file afterward.
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
- `CFG-08`: Config splitting must not break `from bomana import config`,
  `config.X`, metadata re-exports, theme re-exports, or existing default values.

## Contract Coverage

- Phase 0 records the contract without changing production behavior.
- Phase 1 must add `tests/contracts/test_config_variants.py` or equivalent
  focused coverage for `VARIANT_SWITCHES`, `PanelConfig`, compile-switch
  migration, disabled-zone navigation fallback, and re-export compatibility.
