# 202607 SDD Phase 1 Proposal

## Problem

`bomana/config.py` had become a large mixed module containing feature flags,
metadata re-exports, runtime settings classes, and static resource paths. Phase 1
splits this into a package while preserving the public `bomana.config` facade.

## Scope

- Move config classes to `bomana/config/settings.py`.
- Add `bomana/config/feature_profile.py` as the build-variant flag patch target.
- Add `bomana/config/metadata.py` and `bomana/config/static_data.py`.
- Add `bomana/config/__init__.py` re-exports for compatibility.
- Update launcher/package validation to accept legacy `bomana/config.py` and new
  `bomana/config/__init__.py` app markers.
- Add config variant contract tests.

## Non-goals

- No runtime default value changes.
- No call-site import rewrites beyond physical marker/build tooling updates.
- No variant-specific user config files.
- No remote push.

## Acceptance

- Existing `from bomana.config import X` imports continue to work.
- `from bomana import config` and `config.X` continue to work.
- `ENABLE_*` precedence and variant matrix are covered by contract tests.
- Build scripts patch `feature_profile.py` and restore it.
- Ruff and pytest pass.
