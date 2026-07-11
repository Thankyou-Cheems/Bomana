# ADR 0006: Offer a selectable temporary glide model

Status: Accepted
Date: 2026-07-11
Supersedes: the fail-closed-only glide availability decision in ADR 0005.
ADR 0005's Datamine-table priority, AAM wording, current-contact boundary, and
official-provider follow-up remain in force.

## Context

ADR 0005 correctly removed the old iron-bomb surrogate, but presenting only
`glide_envelope_unavailable` left glide-capable guided stores without a useful
release-time cue. The user explicitly prefers a visibly provisional estimate
over no estimate while the native War Thunder comparison implementation and
reusable official trajectory samples remain unavailable.

A current public FoxThree audit found no stable data API. Its client-side glide
behavior can be described by a small lift-to-drag/energy-height heuristic, but
its bundled records are stale relative to Bomana's Datamine snapshot and the
site does not publish a license for its application/data bundles. Its Live Ops
“loaded missile” wording is also not automatic detection: the missile comes
from a user-controlled combobox or URL state, and its bridge exposes no loaded
store identity.

## Decision

Add a persisted ballistic-model policy with two choices:

- `foxthree_compatible` is the default. A valid Datamine conditional table
  still wins. A glide record without a usable table receives a clean-room
  compatibility estimate using only current 8111 launch state and the bundled
  Datamine record:
  `L/D = clamp(2.4 * wing_area_mult, 1.5, 12)`,
  `energy_height = max(0, launch_altitude - target_altitude) + v^2/(2g)`, and
  `range = 0.8 * L/D * energy_height`, capped by Datamine lifetime times launch
  speed and `hard_max_distance_m` when present.
- `strict_official` disables that temporary glide fallback and retains
  `glide_envelope_unavailable`. It does not disable existing CCRP, valid
  Datamine condition tables, or already documented non-glide conservative
  solvers.

The compatibility result is always `quality=experimental`, uses distinct
within/beyond experimental-reference statuses, and is neutral/yellow. The UI
must name the active model and state that the heuristic does not simulate
control surfaces or autopilot and is not a lock, launch authorization, hit
guarantee, or official War Thunder trajectory.

Do not vendor FoxThree JavaScript, bundled weapon records, or performance
tables. Weapon identity and all weapon-specific parameters remain generated
from the current War Thunder Datamine. Weapon selection remains manual until a
named official 8111 field is captured and regression-tested.

## Consequences

- Glide stores now receive a practical default reach/release reference instead
  of an empty card, while users can opt back into fail-closed behavior.
- The estimate can materially disagree with the game because it lacks terrain,
  target altitude, maneuver, lift curve, induced drag, guidance law, and
  autopilot behavior. The experimental label is therefore part of correctness,
  not optional UI polish.
- Equal `wing_area_mult` and similar caps can still produce similar results for
  aerodynamically different weapons. This temporary model must not be used as
  calibration evidence.
- `Bomana-7x2s` remains open for a versioned official sample provider or a
  genuinely calibrated independent lift/autopilot solver. Such a provider may
  replace the temporary heuristic without changing the manual-selection and
  compact-UI decisions.
