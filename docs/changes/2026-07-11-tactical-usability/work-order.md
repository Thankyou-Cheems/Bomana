# Tactical Usability Work Order

Status: In progress
Date: 2026-07-11
Tracking: `Bomana-7x2s.1`, `Bomana-2oa.1`, `Bomana-2oa.2`, `Bomana-2oa.3`, `Bomana-2oa.4`

## Objective

Improve Bomana's practical combat cues without adding a tactical-map surface:
provide a selectable temporary glide model, retain honest manual weapon
selection, track the player's last confirmed loss position, match War Thunder's
POI bracket, expose obvious and consistent actions, and make standalone-window
closure restore integrated navigation.

## Evidence and Decisions

- FoxThree's Live Ops shoot cue reads a site-local missile selection. Its public
  bridge does not expose a loaded-store field, and current 8111 captures do not
  establish one. Bomana therefore retains `selection_source=manual` until a
  named official field passes directed capture tests.
- Datamine conditional guidance tables remain the primary AAM/AGM reference.
  The selectable FoxThree-compatible policy is only a clean-room, explicitly
  experimental fallback for records without a usable table, especially glide
  weapons. No FoxThree bundle, record, or performance table is vendored.
- A successful, non-empty `/map_obj.json` response losing its Player object is
  present in the tracked full-sortie fixture. Existing
  `ALIVE -> LOSS_PENDING -> WAIT_NEXT` confirmation is the loss authority;
  localized `/hudmsg` text is not needed.
- The supplied POI reference is a red, open-center, four-corner bracket.

## Invariants

- `INV-1`: Runtime data remains limited to the four already approved official
  8111 endpoints. This change does not add `/hudmsg`, `/gamechat`, memory reads,
  injection, packet inspection, logs, or game-file access.
- `INV-2`: Valid Datamine conditional tables take priority in every model mode.
  The FoxThree-compatible fallback is selectable, defaults on for usability,
  is labelled experimental, and never claims a lock, NEZ, guaranteed hit, or
  official War Thunder trajectory.
- `INV-3`: Weapon selection remains manual/unknown unless a named current 8111
  field is captured and regression-tested. Release/button pulses are not store
  identities.
- `INV-4`: Trace back records only the player's own last valid coordinates in
  memory, confirms them only at `WAIT_NEXT`, survives the next spawn, and is
  cleared with new-battle context. Hostile contacts are never persisted.
- `INV-5`: POI and Trace back remain secondary markers on the existing shared
  heading tape. Zone navigation remains primary; no new primary row or map
  window is introduced.
- `INV-6`: Interactive UI uses one visible action-control vocabulary. Close
  actions stay on the right. The privileged-hotkey request remains explicit,
  but is reachable from the tray when the locked overlay is click-through.
- `INV-7`: Closing the standalone navigation surface is a mode transition back
  to `integrated`; temporary history-mode suspension may still call `hide()`.
- `INV-8`: Tray/background callbacks cross into Tk through
  `TkEventDispatcher`; background code does not touch Tk widgets directly.
- `INV-9`: Existing release signing, launcher integrity, and feature flags are
  unchanged. No secret, deployment, or release operation is in scope.

## Boundaries

- Core state and solver: `bomana/core/state.py`, `lifecycle.py`, `logic.py`,
  `weapon_solver.py`, `weapon_scheduler.py`.
- Configuration and model selection: `bomana/config/settings.py`,
  `bomana/ui/dialogs.py`, `bomana/ui/app.py`.
- Presentation and interaction: `bomana/ui/navigation_presenter.py`,
  `widgets.py`, `navigation_runtime.py`, `nav_window.py`, `main_window.py`,
  `tk_style.py`, `runtime_services.py`, and presenter/renderer helpers.
- Specifications and contract tests: `docs/specs/weapon-fire-control.md`,
  `docs/specs/runtime-8111-boundary.md`, `docs/specs/navigation-cues.md`, and
  focused tests under `tests/`.

## Acceptance Gates

1. Datamine-backed AIM-120C-5 conditional-table anchors remain unchanged.
2. Default temporary mode produces a qualified glide range; strict mode keeps
   `glide_envelope_unavailable`.
3. Model selection persists and is visible in the weapon selector/card.
4. Transient/failing map frames never create a crash marker; confirmed loss in
   a valid map sequence does, and the next life sees bearing/distance.
5. Shared POI drawing emits four open corner segments and red POI semantics.
6. Standalone X/WM close restores integrated mode, persists, rerenders, and
   refreshes tray state.
7. Admin action is available through the tray with explicit confirmation, and
   main UI guidance explains F8/tray recovery while locked.
8. Focused tests, full pytest, Ruff check, Ruff format check, contract tests,
   and independent diff review pass.

## Out of Scope / Follow-up

- Claiming automatic loaded-store detection from FoxThree or the current 8111
  surface.
- Reproducing War Thunder's native `buildMissileTrajectoryData` exactly.
- Persisting crash locations across app restarts or battle/map identities.
- Adding a minimap, hostile track history, or a new primary navigation panel.
