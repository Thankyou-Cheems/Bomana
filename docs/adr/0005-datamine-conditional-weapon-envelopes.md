# ADR 0005: Prefer Datamine conditional weapon envelopes

Status: Accepted; glide availability superseded by ADR 0006
Date: 2026-07-11
Supersedes: the AAM and glide-model choices in ADR 0004; ADR 0004's compact UI,
manual selection, current-contact, and no-new-map decisions remain in force.

## Context

The first weapon-fire-control implementation treated a one-dimensional
point-mass integration as the primary AAM range model and treated its simulated
missile path length as the launch-range answer. For long-range weapons such as
AIM-120C-5, that produced a roughly 15 km cue even though the same Datamine record carries
condition-dependent `guidance/tableN` launch-envelope ranges for substantially
longer, high-energy engagements. Failing the entire record when its propulsion
autopilot was too complex to flatten also discarded those independent tables.

War Thunder's 2026 guided-weapon comparison can generate trajectory and
telemetry graphs through the game's native `buildMissileTrajectoryData` path.
The current Datamine checkout exposes the weapon configuration inputs and AAM
condition tables, but not that native implementation or reusable static output
curves. Consequently, Bomana can use preserved AAM tables directly, but it
cannot truthfully claim that the old iron-bomb gravity/drag path represents a
guided weapon's lift, autopilot, or glide range.

The official 8111 map response may expose a hostile contact's current `dx` and
`dy`, but it still does not expose target altitude, verified lock identity, or
a dependable target-speed magnitude. Those limits permit a two-dimensional
radial-aspect hint, not a three-dimensional intercept or NEZ.

## Decision

Preserve every AAM or AGM `guidance/tableN` table as a versioned source artifact,
including its altitude/carrier-Mach/target-Mach axes, scenario range fields,
time fields, exact table identity, and JSON pointers. Select and interpolate
that condition domain before considering the one-dimensional point-mass model.
The table path remains usable when propulsion carries an unsupported complex
autopilot, because the table is a separate source-backed launch-envelope
artifact. A table `rangeMax` is initial launch separation and is never clipped
by top-level `maxDistance`, which describes a different quantity.

Use only the selected contact's finite, current-response `dx`/`dy` to derive a
two-dimensional radial-aspect hint. Do not reconstruct missing motion or carry
it across responses. Because target altitude and speed magnitude remain
unknown, expose the result as a neutral/yellow Datamine conditional-envelope
reference, never as a lock, authorization, `Rtr`, `Rne`, `NEZ`, or guaranteed
intercept.

Do not use the iron-bomb trajectory as a practical glide-envelope cue. Until a
validated range provider exists, glide weapons report
`insufficient_data/glide_envelope_unavailable`. A future provider may be
accepted only through either (a) reproducible, versioned sampling of the
official comparison output with full input/provenance metadata or (b) an
independent lift/autopilot solver calibrated against repeatable official
comparison and live-game observations. Adding that provider requires a schema,
spec, regression-test, and smoke-guide amendment; this ADR does not assert that
the provider already exists.

Retain ADR 0004's compact Enhanced-only weapon-solution card, manual weapon
selection until a named 8111 field is verified, hostile-current-contact rule,
forward ground target, and prohibition on a new tactical map or primary
navigation row.

## Consequences

- Long-range AAM and supported AGM cues use the most relevant Datamine launch-envelope data
  instead of collapsing to a short one-dimensional path-length estimate.
- AAM output remains operationally useful but explicitly conditional: unknown
  target height/speed and two-dimensional aspect prevent exact-hit or NEZ
  claims.
- Complex propulsion no longer disables an otherwise valid conditional-table
  reference; it still disables the point-mass fallback when no valid table
  exists.
- Glide range guidance is temporarily unavailable rather than precise-looking
  but physically unrelated. Restoring it requires a validated provider, not a
  new name for the free-fall solver.
- The existing compact UI and manual-selection workflow remain stable; this
  decision does not add a map, settings surface, or navigation hierarchy.
