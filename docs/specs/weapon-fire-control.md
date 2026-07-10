# Weapon Fire-Control Spec

Status: Draft
Owner: Bomana maintainers
Prefix: `WFC-`

## Scope

This spec governs the bundled War Thunder weapon catalog, weapon selection,
air-to-air and air-to-ground engagement-envelope estimation, guided/glide bomb
estimation, reuse of the existing CCRP path, and the compact UI that presents
those results.

## Non-goals

- This spec does not claim access to the game's selected store, sensor lock,
  target altitude, terrain elevation, radar track, or launch authorization.
- This spec does not define or display AAM `Rtr`, `Rne`, `NEZ`, or a guaranteed
  intercept envelope from two-dimensional 8111 map data.
- This spec does not authorize new runtime endpoints, game-memory reads,
  injection, packet inspection, log parsing, or game-file access.
- This spec does not replace real War Thunder calibration or smoke testing.

## Normative Clauses

- `WFC-01`: `bomana/data/weapon_fire_control.json` MUST be generated from a
  clean War-Thunder-Datamine checkout and MUST record the source game version,
  full source commit, source subdirectories, and source file, SHA256, field
  pointers, and aircraft/container reference chains for every weapon.
- `WFC-02`: Included role, propulsion, control, guidance, planform, physics
  fields, display names, and aircraft compatibility MUST derive from structured
  Datamine fields, localization, and aircraft/container preset references;
  GreasyFork, Wiki, forum, or hand-entered performance tables MUST NOT seed
  runtime weapon parameters. A positive legacy Datamine `controlSensitivity`
  MUST establish guided control when the same weapon also has structured
  guided-weapon trigger or icon evidence; that case MUST retain the source
  pointer and be represented as `guidance.type=legacy_command` with
  `guidance.seeker=command`, even when no modern seeker block exists.
  Condition-dependent AAM `guidance/tableN/rangeMin` and
  `rangeMinDogfight` arrays MUST remain grouped by table with their source
  pointers; any derived all-scenario floor is audit evidence, not a runtime
  engagement minimum without the missing target conditions.
- `WFC-03`: Runtime selection source MUST be one of `manual`, `8111`, or
  `unknown`; `weapon2`, `weapon3`, `weapon4`, and other button/release pulses
  MUST NOT be interpreted as the selected weapon or category.
- `WFC-04`: Bomana MUST use `selection_source=8111` only after a named 8111
  field has been captured across directed weapon-selection sessions and covered
  by a behavioral regression test; otherwise selection MUST remain manual or
  unknown.
- `WFC-05`: Catalog and solver boundaries MUST use SI units (`m`, `s`, `kg`,
  `N`, `m/s`, `deg`) and MUST preserve raw Datamine provenance for every
  converted value. A deterministic correction of a Datamine unit anomaly MUST
  retain the raw value, normalized value, rule, source pointer, and structured
  Datamine-only evidence in the generated record.
- `WFC-06`: Powered-weapon range and time estimates MUST use point-mass
  integration starting from nonzero Datamine `startSpeed` or otherwise carrier
  TAS, plus staged thrust, staged mass, `CxK`, caliber, lifetime, maximum-speed
  limit, and `maxDistance` hard cutoff; they
  MUST NOT treat stat-card `rangeMax` or `endSpeed` as a dynamic launch range or
  terminal-energy threshold and MUST NOT use a shared altitude/airspeed bonus
  formula or constant-speed TTI. Records containing conditional propulsion
  autopilots, variable propulsion-factor tables, factor-indexed impulses, or
  instantaneous mass changes that the flat point-mass schedule does not model
  MUST retain machine-readable unsupported reasons and fail closed as
  `insufficient_data/conditional_propulsion_unsupported`.
- `WFC-07`: Guided and glide bomb estimates MUST use Datamine mass,
  aerodynamics, control-surface, guidance, and lifetime fields and MUST be
  labelled as estimates; free-fall and high-drag bombs MUST continue to use the
  existing CCRP solver. Every catalog weapon routed to CCRP MUST resolve its
  freshly generated physics by exact catalog ID or by the Datamine source-file
  stem recorded in the CCRP asset; a missing mapping MUST produce
  `insufficient_data/ccrp_physics_unavailable` and MUST NOT reuse the previous
  selection or generic fallback physics. Until live evidence establishes a
  lift/drag mapping, glide weapons MUST NOT infer an L/D envelope from
  `wingAreaMult` and `CxK`; they MAY expose the existing mass/caliber/`dragCx`
  gravity integration only as a neutral/yellow guided-ballistic reference and
  MUST NOT present that reference as a green glide envelope.
- `WFC-08`: AAM estimates MUST use only hostile aircraft contacts currently
  returned by `/map_obj.json`; missing target altitude, verified lock identity,
  or target motion MUST downgrade the result to `two_dimensional` quality and
  MUST suppress lock, authorization, `Rtr`, `Rne`, and `NEZ` claims. When the
  selected hostile contact disappears from the current response, its valid cue
  MUST be cleared in that calculation cycle; calculation throttling MUST NOT
  defer the disappearance or preserve a stale target. Because 8111 does not
  provide the target aspect, motion, or altitude needed to select Datamine
  guidance-table cells, an AAM inside the computed two-dimensional maximum MUST
  use a neutral/yellow max-only status with unknown minimum range, never the
  green full-envelope status or top-level `minDistance` as an engagement bound.
- `WFC-09`: AGM and guided/glide bomb estimates MUST use the existing forward
  POI-or-zone bombing target; unknown target/terrain elevation MUST downgrade
  the result to `two_dimensional` quality. A ground-target time-to-window MAY be
  shown only while aligned and MUST use positive along-target ground closing
  speed derived from SOG and relative bearing; weapon launch TAS MUST NOT be
  reused as aircraft closing speed.
- `WFC-10`: Solver results MUST contain a machine-readable status and reason;
  missing selection, incompatible selection, missing target, invalid telemetry,
  unavailable/invalid catalog data, missing CCRP physics, or solver failure MUST
  suppress the in-envelope cue rather than silently substituting guessed data.
- `WFC-11`: Background calculation MUST follow the existing lock-in prepare,
  lock-free compute, lock-in apply pattern, and Tk presenters/renderers MUST
  consume only immutable `UISnapshot` fields. Rate limiting MAY defer equivalent
  ground-target work, but MUST NOT defer a current AAM contact update or the
  transition from a present hostile contact to no target.
- `WFC-12`: The primary UI MUST reuse the existing compact bombing card as a
  weapon-solution card and MUST NOT add a tactical map, a new primary navigation
  row, or promote POI above the existing zone-oriented navigation status. The
  App and its builders MUST reuse GameLogic's single validated catalog result;
  if that result is unavailable, the card MUST show an unavailable state and
  the selector MUST be disabled without attempting an independent reload.
- `WFC-13`: UI wording MUST distinguish supported ground `estimated in
  envelope`, AAM `within two-dimensional maximum only`, glide `within/beyond
  ballistic reference`, `align`, `too close`, `out of range`, `no target`, and
  `insufficient data`; it MUST NOT call a ballistic reference a glide limit,
  call an estimated state a game lock or launch authorization, or use a
  continuous flashing cue.
- `WFC-14`: The generator, runtime catalog loader, and contract tests MUST load
  `docs/specs/schemas/weapon-fire-control.schema.json` rather than restating its
  required catalog fields or schema version.
- `WFC-15`: This spec MUST remain Draft until real War Thunder smoke covers at
  least one free-fall bomb, guided bomb, glide bomb, AGM, and AAM scenario plus
  directed selection-field capture across those categories.

## Model Notes

These are Bomana model choices, not imported weapon-performance values:

- Powered weapons use a one-dimensional point-mass integration along the
  current target bearing. Air density is ISA density at launch altitude; a
  nonzero Datamine `startSpeed` is the initial speed, while zero inherits
  carrier TAS. Datamine motor stages change thrust and mass, while `CxK` and
  caliber set axial drag.
- Integration stops at Datamine lifetime/`maxDistance` or at a conservative
  post-burn speed floor (220 m/s for AAM, 90 m/s for AGM). It does not simulate
  loft, target closure, target maneuver, lift, or a three-dimensional path.
- A normal guided bomb starts from the existing ballistic trajectory and only
  reduces that result using a fixed 0.85 ceiling plus a bounded Datamine
  guidance/control-authority factor; it never extends the ballistic result.
- A glide bomb currently reuses only that Datamine-backed gravity/drag path as
  a guided-ballistic reference. `wingAreaMult` and `CxK` stay preserved for a
  future calibrated lift model, but are not converted into a synthetic L/D.
  Unknown terrain height uses sea level and forces the `two_dimensional` label;
  no synthetic toss command or green glide-envelope claim is produced.
- The card's green state is reserved for supported ground-weapon estimates that
  are inside the estimate and aligned within 10 degrees. AAM max-only and glide
  ballistic-reference states are neutral/yellow. None is War Thunder's lock
  state or launch authorization.

## Contract Coverage

- [behavioral] `tests/contracts/test_weapon_fire_control_schema.py` enforces
  `WFC-01`, `WFC-02`, `WFC-05`, `WFC-07`, and `WFC-14` with
  generated-catalog validation, provenance checks, legacy command-guidance
  records, conditional-propulsion reason codes, AAM minimum-table provenance,
  CCRP source-ID parity, and schema-tamper rejection.
- [behavioral] `tests/contracts/test_weapon_fire_control_runtime.py` enforces
  the fail-closed portions of `WFC-07`, `WFC-08`, `WFC-10`, `WFC-11`, and
  `WFC-12` with source-ID alias resolution, immediate hostile disappearance,
  and reuse of GameLogic's unavailable catalog result across the UI boundary.
- [behavioral] `tests/test_weapon_catalog.py` enforces `WFC-02..WFC-05` with
  structured multi-axis classification, aircraft/container compatibility,
  localization, and manual selection fallback cases.
- [behavioral] `tests/test_weapon_solver.py` enforces `WFC-06..WFC-10` with
  staged-motor, unsupported-propulsion fail-closed, altitude/airspeed, cap,
  aligned-SOG TTI, max-only AAM, glide ballistic-reference, ground-target, and
  failure cases.
- [behavioral] `tests/test_weapon_scheduler.py` enforces `WFC-07`, `WFC-10`, and
  `WFC-11` with prepare/compute/apply state transitions, missing-CCRP
  fail-closed behavior, and stale-result rejection.
- [behavioral] `tests/test_map_objects_contract.py` enforces `WFC-08` by keeping
  only currently returned hostile aircraft contacts and excluding the player
  and friendly aircraft.
- [behavioral] `tests/test_panel_presenter.py`, `tests/test_panel_renderer.py`,
  and `tests/test_ui_geometry.py` enforce `WFC-12` and `WFC-13` with compact-card
  wording, conditional detail-row layout, and no added primary navigation row.
- [manual] `docs/guides/weapon-fire-control-smoke.md` covers `WFC-04`, `WFC-08`,
  `WFC-09`, and `WFC-15`; automated tests do not claim target-altitude,
  lock-state, current-store, terrain, or live-game accuracy coverage.
