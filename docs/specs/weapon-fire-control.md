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
  Every condition-dependent guided-weapon `guidance/tableN` record MUST remain
  an ordered, independently addressable table with exact source pointers and
  values for `altitude`, `fighterMach`, `targetMach`, `targetMach2Mult`,
  `rangeMin`, and `rangeMax`; every present `rangeMinDogfight`,
  `rangeMaxDogfight`, `rangeMaxAltDiff`, `rangeMaxDogfightAltDiff`, `timeMax`,
  `timeMaxAltDiff`, and `altDiff` value MUST also be preserved. Derived
  all-scenario floors or ceilings are audit evidence, not replacements for the
  preserved table cells.
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
- `WFC-06`: A powered weapon with a valid condition-dependent
  `guidance/tableN` launch envelope MUST use table selection/interpolation before
  the one-dimensional point-mass solver, and that table-backed reference MUST
  remain available when the same record also carries
  `conditional_propulsion_unsupported`. A table-cell `rangeMax` is an initial
  launch separation for that condition and MUST NOT be clipped by the weapon's
  top-level `maxDistance`. When no valid conditional table is available,
  powered-weapon range and time estimates MUST use point-mass integration
  starting from nonzero Datamine `startSpeed` or otherwise carrier TAS, plus
  staged thrust, staged mass, `CxK`, caliber, lifetime, maximum-speed limit, and
  `maxDistance` hard cutoff; this fallback MUST NOT treat stat-card `rangeMax`
  or `endSpeed` as a dynamic launch range or terminal-energy threshold and MUST
  NOT use a shared altitude/airspeed bonus formula or constant-speed TTI; an
  unsupported conditional-propulsion record without a usable table MUST fail
  closed as `insufficient_data/conditional_propulsion_unsupported`.
- `WFC-07`: Normal guided-bomb estimates MUST use Datamine mass, aerodynamics,
  control-surface, guidance, and lifetime fields, while experimental glide
  estimates MUST use the Datamine wing-area multiplier, lifetime, and hard
  distance fields defined below; both MUST be labelled as estimates, and
  free-fall and high-drag bombs MUST continue to use the existing CCRP solver.
  Every catalog weapon routed to CCRP MUST resolve its
  freshly generated physics by exact catalog ID or by the Datamine source-file
  stem recorded in the CCRP asset; a missing mapping MUST produce
  `insufficient_data/ccrp_physics_unavailable` and MUST NOT reuse the previous
  selection or generic fallback physics. Under either ballistic-model policy,
  a valid Datamine `guidance/tableN` MUST take priority for a glide weapon. With
  no usable table, `strict_official` MUST return
  `insufficient_data/glide_envelope_unavailable`; `foxthree_compatible` MUST
  instead use the documented clean-room equivalent lift-to-drag/energy-height
  estimate, return `quality=experimental` and
  `reason=foxthree_compatible_glide`, and MUST NOT calculate or display the
  free-fall mass/caliber/`dragCx` trajectory as a practical glide range cue.
- `WFC-08`: AAM estimates MUST use only hostile aircraft contacts currently
  returned by `/map_obj.json`; finite current-response `dx`/`dy` values MUST be
  preserved and used only to infer a two-dimensional radial-aspect hint, while
  absent or invalid motion MUST remain unknown and MUST NOT be reconstructed
  from a persisted track. When the selected hostile contact disappears from the
  current response, its valid cue MUST be cleared in that calculation cycle;
  calculation throttling MUST NOT defer the disappearance or preserve a stale
  target. Because 8111 does not provide target altitude, target speed magnitude,
  verified lock identity, or a three-dimensional aspect, every conditional-table
  result MUST retain `two_dimensional` quality and reference wording and MUST
  suppress lock, authorization, `Rtr`, `Rne`, `NEZ`, and guaranteed-intercept
  claims.
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
  A valid AAM conditional table with unknown target altitude, speed magnitude,
  or aspect MUST instead produce a qualified `two_dimensional` reference with
  `reason=datamine_guidance_envelope`; it MUST NOT fall back to the one-dimensional
  solver or fail solely because its propulsion model is unsupported.
- `WFC-11`: Background calculation MUST follow the existing lock-in prepare,
  lock-free compute, lock-in apply pattern, and Tk presenters/renderers MUST
  consume only immutable `UISnapshot` fields. Apply MUST reject work whose
  weapon selection, target, or ballistic-model policy changed during compute.
  Rate limiting MAY defer equivalent ground-target work, but MUST NOT defer a
  current AAM contact update or the transition from a present hostile contact
  to no target.
- `WFC-12`: The primary UI MUST reuse the existing compact bombing card as a
  weapon-solution card and MUST NOT add a tactical map, a new primary navigation
  row, or promote POI above the existing zone-oriented navigation status. The
  App and its builders MUST reuse GameLogic's single validated catalog result;
  if that result is unavailable, the card MUST show an unavailable state and
  the selector MUST be disabled without attempting an independent reload.
- `WFC-13`: UI wording MUST distinguish supported ground `estimated in
  envelope`; AAM `within_all_aspect_reference`, `within_aspect_reference`,
  `head_on_only_reference`, and `beyond_envelope_reference` states as neutral
  Datamine conditional-envelope references; experimental glide
  `within_experimental_reference` and `beyond_experimental_reference`; strict
  glide `insufficient_data/glide_envelope_unavailable`; and `align`, `too
  close`, `out of range`, `no target`, and other `insufficient data` states. It MUST NOT
  call a conditional-table reference an exact hit range, call an estimated
  state a game lock, launch authorization, `Rtr`, `Rne`, or `NEZ`, present an
  iron-bomb trajectory as a glide envelope, or use a continuous flashing cue.
- `WFC-14`: The generator, runtime catalog loader, and contract tests MUST load
  `docs/specs/schemas/weapon-fire-control.schema.json` rather than restating its
  required catalog fields or schema version.
- `WFC-15`: This spec MUST remain Draft until real War Thunder smoke covers at
  least one free-fall bomb, guided bomb, glide bomb, AGM, and AAM scenario plus
  directed selection-field capture across those categories.
- `WFC-16`: `WeaponBallisticModelConfig` MUST accept only
  `foxthree_compatible` and `strict_official`, MUST default to
  `foxthree_compatible`, and the weapon selector MUST visibly explain both
  choices, persist the selected value as `weapon_ballistic_model`, and apply it
  to `WeaponBallisticModelConfig.selected_model` without requiring an app
  restart.

## Model Notes

These are Bomana model choices, not imported weapon-performance values:

- Condition-dependent AAM and AGM tables are the primary launch-range reference. The
  solver preserves their launch-altitude, carrier-Mach, target-Mach, scenario,
  range, and time axes and interpolates only within that source-backed domain.
  A table `rangeMax` describes initial separation; it is not a missile path
  length and is therefore independent of top-level `maxDistance`.
- Current `/map_obj.json` `dx`/`dy` can distinguish only two-dimensional radial
  motion for scenario selection. Unknown target altitude and speed magnitude
  keep every result a reference rather than a lock, NEZ, or guaranteed hit.
- Powered weapons without a valid conditional table use a one-dimensional
  point-mass fallback along the current target bearing. Air density is ISA
  density at launch altitude; a nonzero Datamine `startSpeed` is the initial
  speed, while zero inherits carrier TAS. Datamine motor stages change thrust
  and mass, while `CxK` and caliber set axial drag. Integration stops at
  Datamine lifetime/`maxDistance` or at a conservative post-burn speed floor
  (220 m/s for AAM, 90 m/s for AGM); it does not simulate loft, target closure,
  target maneuver, lift, or a three-dimensional path.
- A normal guided bomb starts from the existing ballistic trajectory and only
  reduces that result using a fixed 0.85 ceiling plus a bounded Datamine
  guidance/control-authority factor; it never extends the ballistic result.
- A glide bomb without a usable official table follows the explicit user
  policy. `strict_official` reports an unavailable state.
  `foxthree_compatible` is the default temporary model and computes
  `L/D = clamp(2.4 * wing_area_mult, 1.5, 12)`,
  `energy_height = max(0, launch_altitude - target_altitude) + v^2/(2g)`, and
  `range = 0.8 * L/D * energy_height`; unknown target altitude uses zero datum,
  and Datamine lifetime times launch speed plus `hard_max_distance_m` cap the
  result when present. It is an experimental reach cue, not an official curve,
  lift/autopilot simulation, hit guarantee, or reuse of the iron-bomb path.
- The card's green state is reserved for supported ground-weapon estimates that
  are inside the estimate and aligned within 10 degrees. AAM conditional-table
  references and experimental glide references are neutral/yellow, and an
  unavailable glide model has no in-envelope cue. None is War Thunder's lock
  state or launch authorization.

## Contract Coverage

- [behavioral] `tests/contracts/test_weapon_fire_control_schema.py` enforces
  `WFC-01`, `WFC-02`, `WFC-05`, `WFC-07`, and `WFC-14` with
  generated-catalog validation, provenance checks, legacy command-guidance
  records, conditional-propulsion reason codes, complete guided-weapon conditional-table
  axes/range/time provenance, CCRP source-ID parity, and schema-tamper rejection.
- [behavioral] `tests/test_weapon_data_extractor.py` enforces `WFC-01`,
  `WFC-02`, `WFC-05`, and `WFC-14` with exact `tableN` identity, axis/output
  retention, source pointers, and deterministic generated output.
- [behavioral] `tests/contracts/test_weapon_fire_control_runtime.py` enforces
  `WFC-06..WFC-08`, `WFC-10..WFC-12` with a generated long-range AAM table
  anchor, source-ID alias resolution, immediate hostile disappearance, and
  reuse of GameLogic's unavailable catalog result across the UI boundary.
- [behavioral] `tests/test_weapon_catalog.py` enforces `WFC-02..WFC-05` with
  structured multi-axis classification, aircraft/container compatibility,
  localization, and manual selection fallback cases.
- [behavioral] `tests/test_weapon_solver.py` enforces `WFC-06..WFC-10` with
  conditional-table priority, table-backed conditional-propulsion references,
  staged-motor fallback, aligned-SOG TTI, strict glide-provider unavailability,
  FoxThree-compatible experimental glide formula/caps, ground-target, and
  failure cases.
- [behavioral] `tests/test_weapon_envelope.py` enforces `WFC-06`, `WFC-08`, and
  `WFC-10` with altitude/carrier-Mach/target-radial-Mach interpolation,
  aspect/end-point selection, table-range independence from `maxDistance`,
  time-field lookup, and machine-readable malformed-cell failures.
- [behavioral] `tests/test_weapon_scheduler.py` enforces `WFC-07`, `WFC-10`, and
  `WFC-11` with prepare/compute/apply state transitions, missing-CCRP
  fail-closed behavior, and stale selection/target/model result rejection.
- [behavioral] `tests/test_map_objects_contract.py` enforces `WFC-08` by keeping
  only currently returned hostile aircraft contacts, preserving finite current
  `dx`/`dy`, and excluding the player and friendly aircraft.
- [behavioral] `tests/test_panel_presenter.py`, `tests/test_panel_renderer.py`,
  and `tests/test_ui_geometry.py` enforce `WFC-12` and `WFC-13` with compact-card
  conditional-reference/unavailable wording, conditional detail-row layout,
  and no added primary navigation row.
- [behavioral] `tests/test_weapon_selector.py` enforces `WFC-16` with explicit
  model labels, valid-value rejection, immediate runtime application, and
  `weapon_ballistic_model` persistence.
- [manual] `docs/guides/weapon-fire-control-smoke.md` covers `WFC-04`, `WFC-07`,
  `WFC-08`, `WFC-09`, and `WFC-15`; automated tests do not claim target-altitude,
  lock-state, current-store, terrain, or live-game accuracy coverage.
