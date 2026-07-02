# 202607 SDD Phase 1 Delta Spec

## Added

- `bomana/config/__init__.py`
- `bomana/config/feature_profile.py`
- `bomana/config/metadata.py`
- `bomana/config/static_data.py`
- `tests/contracts/test_config_variants.py`

## Moved

- `bomana/config.py` -> `bomana/config/settings.py`

## Changed

- Portable and legacy build scripts patch `bomana/config/feature_profile.py`
  instead of the old single-file config module.
- Launcher install validation accepts either legacy `bomana/config.py` or new
  `bomana/config/__init__.py` app markers.
- Version-info generation falls back to `bomana/metadata.py` when old config file
  paths are absent.
- Documentation now describes the config package layout.

## Behavior

No runtime defaults are intended to change. The public import surface remains
`bomana.config`.
