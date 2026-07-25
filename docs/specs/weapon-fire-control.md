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
  8111-supplied target altitude, dynamic/scene-object elevation, radar track,
  or launch authorization. `WFC-22` covers only locally extracted static terrain.
- This spec does not define or display AAM `Rtr`, `Rne`, `NEZ`, or a guaranteed
  intercept envelope from two-dimensional 8111 map data.
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
- `WFC-07`: Normal guided-bomb fallbacks MUST use Datamine mass, aerodynamics,
  control-surface, guidance, and lifetime fields and MUST return
  `quality=experimental/reason=guided_ballistic_uncalibrated`, while
  experimental glide estimates MUST use the Datamine wing-area multiplier,
  lifetime, and hard distance fields defined below; both MUST be labelled as estimates, and
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
- `WFC-08`: AAM estimates MUST use only hostile aircraft contacts or POIs
  currently returned by `/map_obj.json`; this permits a current POI that follows
  a pod/radar point to act as a beyond-visual-range calculation candidate without
  claiming its semantic identity. Finite current-response aircraft `dx`/`dy`
  values MUST be preserved and used only to infer a two-dimensional radial-aspect
  hint, while POI, absent, or invalid motion MUST remain unknown and MUST NOT be
  reconstructed from a persisted track. When the selected hostile contact or
  POI disappears from the current response, its valid cue MUST be cleared in
  that calculation cycle;
  calculation throttling MUST NOT defer the disappearance or preserve a stale
  target. Because 8111 does not provide target altitude, target speed magnitude,
  verified lock identity, or a three-dimensional aspect, every conditional-table
  result MUST retain `two_dimensional` quality and reference wording and MUST
  suppress lock, authorization, `Rtr`, `Rne`, `NEZ`, and guaranteed-intercept
  claims.
- `WFC-09`: AGM and guided/glide bomb estimates MUST use only the source selected
  by the explicit bombing target mode: `zone` or `poi`. Runtime selection MUST
  NOT infer one source from overlap, silently prioritize POI, or fall back to
  the other source when the selected kind is absent. Changing the mode MUST
  invalidate the previous target, altitude, pending work token, and solution.
  Unknown target/terrain elevation MUST downgrade the result to
  `two_dimensional` quality. A ground-target time-to-window MAY be
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
- `WFC-12`: The primary UI MUST use one shared bombing-bar presenter and widget
  for all hosts. The bar MAY be integrated into the primary card or detached
  into its own top-level window; when both bombing and navigation are detached,
  the bombing bar MUST mount below the detached navigation bar instead of
  opening a competing top-level window. It MUST NOT add a tactical map, a new
  primary navigation row, or promote POI into a primary navigation target.
  AAM navigation mode MAY
  show POIs beside all current hostile aircraft only as non-primary potential
  navigation cues while explicitly pausing zone preference; the same current
  POIs MAY participate in AAM fire-control target selection under `WFC-08`.
  The App and its builders MUST reuse GameLogic's single validated catalog result;
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
  `reason=player_visible_trajectory_reference` MUST use visible-curve and `>=`
  lower-bound wording, while `reason=guided_ballistic_uncalibrated` MUST name
  the result as uncalibrated; neither may use a green cue.
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
- `WFC-17`: A usable official condition-dependent table MUST remain authoritative
  under both ballistic policies. Public App/Web labels MUST present the choice
  only as `缺少官方数据时：使用推测替代` versus
  `缺少官方数据时：不应用模型`, MUST explain that official data always wins,
  and MUST NOT present the internal compatibility/provider identifier as the
  model name.
- `WFC-18`: The primary weapon card MUST lead with weapon, explicit target mode,
  target identity, offline terrain elevation when known, range/window, and one
  short quality/source label. Repeated caveats and model explanations belong in
  the selector/help surface; unavailable states MUST remain concise without
  hiding the machine-readable reason from Web/API projections.
- `WFC-19`: A player-visible trajectory observation MAY override the normal
  guided-bomb fallback only when it is versioned, visibly reaches its requested
  target, is explicitly runtime-enabled, matches the exact weapon and a static
  ground target, and stays within 100 m launch altitude, 10 m/s launch speed,
  and 150 m known target altitude of the recorded condition. An unknown ground
  elevation MAY match but MUST retain experimental quality. The reached target
  distance MUST be presented as a `>=` verified reference threshold, not a
  maximum envelope; a farther target means only `beyond_experimental_reference`.
  When runtime target elevation is unknown, the compact UI MUST retain the
  captured target-altitude condition instead of implying that the current
  target shares it.
  Time MAY be interpolated only between the recorded points. Such an observation
  MUST NOT calibrate another weapon, including any free-fall/high-drag bomb.
- `WFC-20`: Free-fall CCRP integration MUST preserve finite current
  `TelemetryData.vy_ms` as the bomb's initial vertical velocity. Its horizontal
  air-speed magnitude MUST be
  `sqrt((TAS/3.6)^2 - Vy^2)`; map-position history supplies ground-track
  direction and closing speed, not a replacement for TAS in aerodynamic drag.
  Runtime target altitude and every along-path collision query MUST use the
  validated local terrain pack described by `WFC-22`. Missing target height,
  altitude datum, current-map identity, or along-path height MUST fail closed.
  Runtime drag integration MUST use `dagor_gamephys_atmosphere_v2`: the
  versioned fourth-order density curve through 18.3 km and its
  `18300 / max(18300, h)` tail above that altitude, plus the bundled
  temperature-ratio polynomial and `a=20.1*sqrt(288.16*RT(h))` sound speed used
  for Mach-dependent drag. Density evaluation MUST use
  Dagor world Y, computed
  as 8111 `H, m` plus the active map pack's altitude datum. When finite usable
  IAS/TAS values exist, runtime MUST derive the mission sea-level density scale
  from `rho = 1.225 * (IAS/TAS)^2` and use the median of the battle-scoped last
  240 valid estimates to suppress integer-telemetry quantization. A temporary
  invalid sample MAY use that official-data cache; with no valid battle sample
  runtime MUST use the explicit standard `1.225 kg/m3` fallback. It MUST NOT
  restore the former exponential/temperature approximation.
  A calibration set MUST bind samples to one exact weapon identity, keep target
  elevation explicit, and separate temporally adjacent training and holdout
  blocks. A single-store fit MUST NOT change global drag tuning. A coefficient
  change MUST NOT be accepted when its validation gain is smaller than the
  reference-set synchronization uncertainty.
- `WFC-21`: The production CCRP dependency set is closed. Runtime free-fall
  calculation MUST use only the manually selected weapon's generated static
  property block, generated `prediction_kind`, current official 8111
  altitude/TAS/Vy/IAS/Mach/AoA/AoS/Ny/Wx, control-surface state, attitude,
  map coordinates/direction, and endpoint timestamps, plus the `WFC-22` local
  heightmap.
  Every `freefall` record MUST resolve
  `offline_rigidbody_projection_v2` and use
  official 8111 AoA and Vy/TAS with that store's generated mass, frontal and
  lateral area, signed stabilizer distance, inertia, aerodynamic coefficients,
  and rotational damping. The shared solver uses the
  bundled sound-speed, `CxBase(M)` and `Cxi(M)` functions, gravity
  `9.81 m/s2`, and constant-acceleration translation/rotation at `1/48 s`.
  `offline_rigidbody_catalog.bin` MUST be a bounded deterministic compressed
  container with an internal SHA256 integrity digest. It MUST expose only the
  normalized runtime primitives and selector aliases: per-record source paths,
  mesh names, timestamps, repository names, and source commits MUST NOT be
  embedded. A signed stabilizer distance MUST NOT be discarded merely because
  it is negative.
  Runtime MUST fail closed when AoA or any required static rigid-body property
  is absent.
  The solver MUST compute stabilizing moment from the total aerodynamic force
  transformed into body coordinates and MUST apply the versioned per-axis
  damping clamp that prevents a damping term from reversing angular velocity
  in one fixed step. It MUST NOT select a per-weapon moment multiplier.
  Runtime MUST NOT consume the display drag reference as the rigid-body axial
  coefficient, accept a
  user/runtime drag override, add an altitude/range/time correction, or restore
  the removed RK4 estimator. Because 8111 lacks the release quaternion
  and store angular state, production results MUST be labelled as an observable
  8111 projection, not exact runtime 6DOF state. Free-fall stores expose
  `quality=offline_rigidbody_8111_projection`.
  `high_drag` MUST report
  `offline_high_drag_unavailable` until its deployment dynamics have
  independent offline validation; no old brake-drag or release-lead
  estimate may be used.
- `WFC-23`: Ground-track release state MUST be a causal ordinary-least-squares
  fit over the nominal latest 0.20 seconds of official 8111 map positions in
  map-info world metres. Selection MAY admit at most 0.03 seconds of timestamp
  jitter so a nominal 10 Hz stream still supplies three observations, and MUST
  remain capped to the latest four observations so a 20 Hz stream does not add
  turn-direction lag. The target MUST be projected into along-track and
  cross-track components. Timing uses along-track distance and fitted ground
  speed; Euclidean distance is display-only. A cross-track miss above 100 m
  MUST report `off_axis` rather than emitting a release cue. Three samples,
  at least 0.09 seconds span, bounded sample age, speed, and fit residual are
  required before the solution becomes valid.
- `WFC-24`: `/state` and `/map_obj.json` MUST be requested adjacently and each
  successful response MUST receive the midpoint of its request interval from
  the same injected wall clock. One common solution time MUST be captured
  immediately after the map-object response, before any low-frequency
  `/map_info.json` refresh. The `WFC-23` regression window MUST end on the
  latest map observation time, then project its fitted world X/Z to the common
  solution time. 8111 `H, m` MUST be projected to the same time as
  `H + Vy * state_age`; TAS, IAS, and Vy themselves remain zero-order held
  because validation rejected first-difference velocity extrapolation.
  The IAS/TAS density pair MUST be evaluated at its original state-observation
  altitude rather than mixing it with the projected release altitude.
  State age, map age, and
  absolute endpoint skew MUST each be no more than 0.15 seconds; a timestamp
  more than 0.005 seconds in the future MUST also be rejected. Violations MUST
  report `time_alignment_unavailable` and emit no release cue. Runtime MUST NOT
  infer wind, rotate the release vector with AoS/body heading, or use future
  samples to smooth the current solution.
- `WFC-25`: Runtime MUST parse the real `/state` key `Wx, deg/s` while retaining
  the legacy `Wx` alias. It MUST causally derive TAS acceleration, vertical
  acceleration, AoA rate, AoS rate, and Mach rate only from adjacent valid
  `/state` midpoint samples between 0.02 and 0.50 seconds apart and MUST reset
  that history across invalid state responses or aircraft identity changes.
  It MUST also derive a robust body-heading rate from current official
  `/map_obj.json` `dx`/`dy`, but MUST use that rate only as a precision signal,
  never as the ballistic release direction.
  The release-suppression gate MUST be lateral only. It MUST compute the
  maximum available ratio from bank/roll angle `/50 deg`, `|AoS|/12 deg`,
  `|Wx|/60 deg/s`, and body-heading rate `/12 deg/s`. A ratio above `1.0`
  MUST report `release_dynamics_unresolved` and suppress the release cue.
  Steep but laterally stable dives and pull-ups MUST remain eligible for CCRP:
  AoA, Ny, pitch, elevator, Vy/vertical acceleration, TAS acceleration, and
  Mach rate/disagreement MUST NOT independently trip this suppression gate.
  When attitude is available, runtime MAY resolve the sign of cockpit pitch
  against `asin(Vy/TAS)+AoA` and compare the bounded
  `g*Ny*cos(pitch)*cos(bank)-g` vertical acceleration with the direct causal
  Vy derivative, but that value is a release-state diagnostic only.
  Missing optional lateral fields MUST retain the basic release state as
  `8111_basic_release_state`; they MUST NOT invent zeros to activate the gate.
  These signals constrain when a release cue is trustworthy; they MUST
  NOT modify `CxK`, rotate the release vector, or claim reconstruction of the
  missing bomb quaternion/angular state.
- `WFC-22`: Target elevation MUST come from a locally generated, terrain-only
  pack built from the installed client's Dagor `levels/*.bin` native `HM2`
  physics heightmap when present, otherwise its `lmap/LTdump` mesh. Extraction
  MUST exclude `SCN`, `RIGz`, splines, buildings, vegetation,
  vehicles, and dynamic objects. The committed/runtime code MUST NOT bundle a
  game texture, level binary, Oodle library, or extracted height grid. The
  extractor MAY use an explicitly supplied local compatible decoder, records
  every source SHA256, and MUST also consume the installed client's extracted
  `aces.vromfs.bin/levels/<map>.blk` config. The pack MUST record its finite
  `water_level` (or the engine's zero default when the field is absent), and
  when the field is explicit runtime MUST clamp underwater terrain to that
  water surface before returning
  `max(terrain_world_y, water_level) - water_level`, so it shares the 8111
  `H, m` datum and bombs do not target seabed. An absent field MUST use the
  zero datum without creating a water surface. The extractor preserves HM2 native samples and four-triangle diamond
  interpolation, or samples an LTdump grid initially at 64 m and adaptively at
  32/16/8 m until its configured P95 error target or bounded grid-size limit is
  met. It MUST declare its
  height scale and interpolation, zlib-compress samples, and store deterministic
  random source-query validation statistics. Production map selection MUST use
  only the official 8111 `/map.img` perceptual fingerprint plus
  `/map_info.json` bounds; it MUST reject a distant or genuinely ambiguous
  fingerprint. Target normalized X/Y MUST map to world X/Z with the 8111 Y axis
  inverted. Level `mapCoord0/mapCoord1` MUST be retained separately for map
  matching when collision-grid coverage is smaller than the tactical map, and
  the selected grid MUST use its declared diamond or bilinear
  interpolation. Missing, corrupt, unmatched, out-of-bounds, or no-data terrain
  MUST fail closed with `terrain_unavailable`; it MUST NOT synthesize a
  sea-level target, attach to the game process, or read client assets at
  runtime.
- `WFC-26`: The bombing bar MUST expose a dedicated configurable target-mode
  hotkey (default `F6`) and an equivalent button. Weapon selection MUST use one
  blue clickable text-box surface, matching the speed-threshold affordance,
  without adjacent previous/next controls. Its selector MUST show only catalog
  bombs verified compatible with the current airframe while airborne; an
  unknown or unmatched airborne identity MUST fail closed instead of falling
  back to the full catalog.
  In integrated mode the title MUST be `CCRP`, align with the airport/fuel
  section titles, use the shared red `关闭` action, and retain a separate
  detach action. In standalone or navigation-mounted mode the header MUST match
  the standalone-navigation style: its `✕` returns to integrated mode and no
  second return button is rendered. The selected target and numeric target
  elevation MUST use otherwise-free space in the title row, prioritize a known
  elevation when width is constrained, and omit terrain-provenance suffixes;
  no separate target/elevation row is rendered. At default scale the release
  cue MUST use a 42 px base height, while its brackets and status text remain
  within the canvas at supported text scales.
  Legacy trajectory/source and separate stability/detail rows MUST remain
  unmanaged; transient failure guidance belongs inside the cue.
  The symmetric CCRP convergence cue MUST be a render-only projection of
  immutable snapshot release timing/status. It MUST track a causal release
  deadline with a deadband, bounded correction, continuous 5.0/0.5-second
  mappings, and a short passed-state confirmation so normal 8111 noise cannot
  make the brackets visibly jump across state boundaries. It MAY smooth visual
  movement and pulse at the release window, but MUST NOT alter solver state,
  infer input, schedule release, or create a new runtime data source.

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
- A normal guided bomb first checks the narrow player-visible reference contract
  in `WFC-19`. The initial GBU-31 observation covers a 3 km, 250 m/s carrier and
  a static 0.1 km target requested at 10 km; its four interior points provide
  approximate time along that one curve. This is a verified reach lower bound,
  not a maximum or generalized flight model. Outside that neighbourhood, the
  fallback starts from the existing ballistic trajectory and only reduces it
  using a fixed 0.85 ceiling plus a bounded Datamine guidance/control-authority
  factor. Because it cannot model lift or autopilot behavior, it is experimental
  and never produces a green in-envelope cue.
- Free-fall CCRP combines a 0.20 s causal 8111 world-position track with
  a 0.03 s timestamp-jitter allowance, horizontal TAS, current Vy and AoA,
  IAS/TAS density scale, and the identified local terrain-only grid.
  `offline_rigidbody_projection_v2` uses the versioned offline rigid-body
  force/moment equations and optimized along-track specialization with each
  selected store's static property block. Catalog regression confirms that all
  331 currently supported free-fall records have a complete finite property
  block and produce a finite terrain intersection at the reference test
  envelope's level, climbing, and diving cases, including 12 records with
  negative stabilizer distance. This is a structural and numerical coverage
  result, not a claim that every store has equal measured impact accuracy.
  The former exact-500MC `1.075` stabilizing-moment scale is removed; all
  identities use the same versioned total-force moment and damping equations.
  Native fixed-step checkpoint regression covers the general three-dimensional
  kernel, while the optimized production specialization is required to match
  that kernel numerically for an equivalent planar state.
  The solver checks the offline terrain grid along the predicted path, not only
  at the selected target.
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
  failure cases, plus `WFC-19` visible-curve priority and uncalibrated fallback
  labeling.
- [behavioral] `tests/contracts/test_visible_trajectory_references.py` and
  [behavioral] `tests/test_visible_trajectory_reference.py` enforce `WFC-19`
  provenance, reached-target gating, narrow matching, and point-only time
  interpolation.
- [behavioral] `tests/test_weapon_envelope.py` enforces `WFC-06`, `WFC-08`, and
  `WFC-10` with altitude/carrier-Mach/target-radial-Mach interpolation,
  aspect/end-point selection, table-range independence from `maxDistance`,
  time-field lookup, and machine-readable malformed-cell failures.
- [behavioral] `tests/test_weapon_scheduler.py` enforces `WFC-07`, `WFC-10`, and
  `WFC-11` with prepare/compute/apply state transitions, missing-CCRP
  fail-closed behavior, and stale selection/target/model result rejection.
- [behavioral] `tests/test_bombing_prediction_constraints.py` enforces `WFC-20`,
  `WFC-21`, `WFC-22`, `WFC-23`, `WFC-24`, and `WFC-25` by preserving TAS/Vy,
  along/cross-track geometry, resolved terrain, bounded endpoint ages/skew, and
  altitude projection plus dynamic precision gating across the prepare/compute boundary.
- [behavioral] `tests/test_release_state.py` enforces the causal world-position
  fit, heading, speed, target projection, solution-time extrapolation, and
  timestamp-jitter/body-rate handling in `WFC-23` through `WFC-25`.
- [behavioral] `tests/test_telemetry_fetch_result.py` enforces the common-clock
  request-midpoint timestamps and causal state rates in `WFC-24` and `WFC-25`.
- [behavioral] `tests/test_release_observation.py` enforces `WFC-24` and
  `WFC-25` zero-order release velocity, bounded load/attitude diagnostic,
  missing-field fallback, and high-dynamics fail-closed behavior.
- [behavioral] `tests/test_terrain_elevation.py` and
  `tests/test_terrain_heightmap_extractor.py` enforce `WFC-22` coordinate-axis,
  fingerprint, integrity, bilinear/diamond query, Dagor HM2/LTdump block,
  triangle-height, level-datum conversion, and source-query validation contracts.
- [behavioral] `tests/test_bomb_trajectory_model.py` enforces `WFC-21` with
  the versioned Mach/sound-speed functions, fixed-step terrain intersection,
  removal of empirical override fields, high-drag fail-closed behavior, and
  derived anchors from the untouched temporal holdout.
- [static] `tests/contracts/test_offline_ballistics_runtime_boundary.py`
  verifies the closed production prediction dependency set and that the old
  empirical module is absent for `WFC-21`.
- [static] `tests/contracts/test_runtime_game_data_boundary.py` enforces
  `WFC-21` by fixing the game API origin to loopback port 8111 and confining
  outbound game-data HTTP calls to the telemetry module.
- [behavioral] `tests/test_map_objects_contract.py` enforces `WFC-08` by keeping
  only currently returned hostile aircraft/POI candidates, preserving finite
  aircraft `dx`/`dy`, treating POI motion as unknown, and excluding the player
  and friendly aircraft.
- [behavioral] `tests/test_bombing_bar.py`, `tests/test_bombing_runtime.py`,
  `tests/test_bombing_target_mode.py`, `tests/test_panel_presenter.py`,
  `tests/test_panel_renderer.py`, and `tests/test_ui_geometry.py` enforce
  `WFC-09`, `WFC-12`, `WFC-13`, `WFC-18`, `WFC-19`, and `WFC-26` with explicit
  target-source invalidation, integrated/standalone host routing, render-only
  convergence, compact conditional-reference/unavailable wording, and no added
  primary navigation row.
- [behavioral] `tests/test_weapon_selector.py` enforces `WFC-16` and `WFC-17` with explicit
  model labels, valid-value rejection, immediate runtime application, and
  `weapon_ballistic_model` persistence.
- [manual] `docs/guides/weapon-fire-control-smoke.md` covers `WFC-04`, `WFC-07`,
  `WFC-08`, `WFC-09`, and `WFC-15`; `docs/guides/terrain-heightmap.md` covers
  local extraction and live identity/elevation readback. Automated tests do not
  claim lock-state, current-store, or every-client-version live-game accuracy.
