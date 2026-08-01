# Super Bomb Release Closure

This inventory defines what must leave the public source closure and what may
remain as the public integration seam. It is a migration checklist, not a claim
that the split is already complete.

## Private Whole-File Implementation

Move these implementation modules behind the private Strike Prediction module:

- `bomana/core/atmosphere.py`
- `bomana/core/ballistics.py`
- `bomana/core/ccrp_scheduler.py`
- `bomana/core/offline_ballistics_model.py`
- `bomana/core/offline_rigidbody_catalog.py`
- `bomana/core/offline_rigidbody_properties.py`
- `bomana/core/offline_rigidbody_solver.py`
- `bomana/core/terrain_elevation.py`
- `bomana/core/visible_trajectory_reference.py`
- `bomana/core/weapon_catalog.py`
- `bomana/core/weapon_envelope.py`
- `bomana/core/weapon_scheduler.py`
- `bomana/core/weapon_solver.py`
- `bomana/ui/bombing_bar.py`
- `bomana/ui/bombing_runtime.py`
- `bomana/web/`

Move their differentiated runtime data:

- `bomana/data/offline_rigidbody_catalog.bin`
- `bomana/data/visible_trajectory_references.json`
- `bomana/data/weapon_fire_control.json`

## Shared Files Requiring Symbol Extraction

Do not delete these files wholesale. They contain public behavior as well as
subscriber behavior. First give the public host a narrow Strike Prediction
interface, then move the subscriber implementation and projections behind it:

- `bomana/core/logic.py`
- `bomana/core/state.py`
- `bomana/config/settings.py`
- `bomana/ui/app.py`
- `bomana/ui/dialogs.py`
- `bomana/ui/main_window.py`
- `bomana/ui/panel_renderer.py`
- `tools/build_portable.py`

The target public interface accepts an observation and returns a publishable
prediction projection. Catalog selection, model selection, schedulers, terrain
queries, stale-result rejection, and state mutation belong inside the private
implementation. A missing private adapter must produce an explicit unavailable
result, not silently fall back to a weaker solver.

## Private Tests, Tools, and Documentation

Move behavioral tests and fixtures whose value is the private implementation:

- `tests/test_atmosphere.py`
- `tests/test_bomb_trajectory_model.py`
- `tests/test_bombing_bar.py`
- `tests/test_bombing_prediction_constraints.py`
- `tests/test_bombing_runtime.py`
- `tests/test_bombing_target_mode.py`
- `tests/test_offline_rigidbody_*.py`
- `tests/test_terrain_*.py`
- `tests/test_visible_trajectory_reference.py`
- `tests/test_weapon_*.py`
- `tests/test_web_dashboard_*.py`
- matching files under `tests/contracts/`
- terrain, datamine, replay, and weapon extraction/build tools used only to
  produce private runtime data
- Super Bomb screenshots, smoke guides, schemas, and ADRs that disclose the
  private implementation or release closure

Private tests should target the Strike Prediction interface and its adapters.
Keep mathematical kernel tests only where they still provide a smaller and more
diagnostic interface than the whole module.

## Publicly Retained Modules

The public repository retains:

- timer, navigation, telemetry, diagnostics, release state, and public UI;
- `bomana/editions.py` as the canonical Edition Policy module;
- the universal Launcher, signed-manifest verification, atomic installation,
  and rollback;
- the public CheemsPay Subscription Access client and receipt verifier;
- a narrow optional Strike Prediction interface with an unavailable adapter;
- Lite and Standard tests and build definitions.

Keeping the CheemsPay client public does not expose the Super Bomb
implementation. It also does not authorize artifacts: the server-side grant is
the artifact seam.

## Research Exclusion

Offline reverse-engineering and process-memory research workspaces are not
production inputs and are not part of either release closure. No production
module may read game process memory. Research-derived claims must be promoted
only as reviewed static data with provenance before they can enter the private
release closure.

## Closure Checks

The migration is complete only when all of these are true:

1. A clean public clone builds and launches Lite and Standard.
2. Public source and reachable refs contain no private whole-file
   implementation or differentiated runtime data.
3. Public UI imports only the optional Strike Prediction interface.
4. A clean private clone builds Enhanced with all private behavioral tests.
5. The Launcher fails closed for Enhanced without a valid receipt and the
   artifact server independently fails closed without a valid grant.
6. Release manifests, hashes, signatures, update installation, and rollback are
   verified for both closures.
