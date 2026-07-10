# ADR 0004: Reuse the compact bombing card for estimated weapon envelopes

Status: Accepted
Date: 2026-07-10

## Context

The AirSim v10.0.27 userscript demonstrates that a map, range rings, and
separate AGM/GBU windows can present weapon-range cues, but its parameters are
hand-entered and its formulas do not model missile propulsion or a real
three-dimensional target. Adding another tactical map to Bomana would duplicate
the game's map and the existing integrated/standalone heading tapes while
consuming a large amount of UI space.

Bomana's real 2026-07-10 JAS 39C 8111 fixture contains `weapon2` and `weapon4`
button/release pulses but no selected weapon, store, loadout, or category field.
The same fixture exposes aircraft contacts only as two-dimensional map objects,
without target altitude, verified radar lock identity, or reliable target
velocity. Those inputs cannot support a truthful AAM NEZ or launch
authorization.

## Decision

Keep the existing Enhanced-only bombing panel location and general three-line
layout, but present it as a compact weapon-solution card. Free-fall/high-drag
bombs retain the current CCRP solution. AAM, AGM, guided-bomb, and glide-bomb
profiles use a separate Datamine-backed estimated-envelope solver and neutral
states such as two-dimensional maximum only, ballistic reference, align, too
close, out of range, no target, or insufficient data. A green in-envelope state
is reserved for supported ground-weapon models; it is not used for AAM or an
uncalibrated glide model.

Weapon selection remains explicit and manual until a directed real-game capture
proves a named 8111 selection field. The selector filters against aircraft
compatibility generated from Datamine weapon-slot, preset, and container
references; it never infers selection from a release pulse.

Ground weapons reuse Bomana's existing forward POI-or-zone bombing target. AAM
estimates may use only a hostile aircraft contact currently returned by
`/map_obj.json`, and the UI labels the result as two-dimensional. Do not add a
tactical map, range-ring overlay, new primary navigation row, lock claim,
authorization claim, `Rtr`, `Rne`, or `NEZ` in this phase.

Do not synthesize glide lift-to-drag from `wingAreaMult/CxK`: the current fields
do not establish lift-curve or induced-drag coefficients. Until live calibration
does, show only the existing mass/caliber/`dragCx` gravity trajectory as a
clearly labelled guided-ballistic reference. Likewise, fail closed for Datamine
propulsion autopilots, variable factor tables, or discrete mass changes that the
flat motor schedule cannot represent.

## Consequences

- The feature adds useful distance/window/TTI cues without a large new UI or a
  second navigation hierarchy.
- Manual selection is one extra cockpit action, but it is more honest than
  guessing from `weapon2`/`weapon4`; aircraft filtering keeps the choice list
  practical.
- Datamine source version, commit, source paths, hashes, and field pointers are
  reproducible, while the numerical model remains independently implemented.
- AAM results expose only a degraded two-dimensional maximum, with no claimed
  minimum range; ground-target countdowns use aligned SOG closure rather than
  launch TAS. Richer claims wait for verified target/selection data.
- A later optional map/debug/calibration view can be considered independently;
  it is not required for the primary fire-control workflow.
