# Weapon Fire-Control Live Smoke Guide

This guide validates behavior that offline tests cannot prove: real selected
stores, live 8111 contact visibility, target/terrain height limits, and the
usefulness of the estimated envelopes in War Thunder.

## Preconditions

- Run an Enhanced source or packaged build containing
  `bomana/data/weapon_fire_control.json`.
- Record the build commit plus the catalog's `meta.source_version` and
  `meta.source_commit`.
- Keep runtime data limited to `/indicators`, `/state`, `/map_obj.json`, and
  `/map_info.json`.
- Use `uv run python tools/record_8111_session.py --label weapon-selection`
  when directed field evidence is needed. Keep raw captures under the default
  gitignored `recordings/` directory unless they pass the normal fixture
  promotion review.

## Directed Selection Capture

Use one aircraft that can carry all practical categories, then record a
repeatable sequence:

1. Spawn with an AAM, AGM, normal guided bomb, glide bomb, and free-fall bomb.
2. Hold each category selected for at least five seconds without firing.
3. Cycle forward and backward through every selected store twice.
4. Fire/release one item from each category and keep recording through the next
   selection transition.
5. Compare complete `/indicators` and `/state` key/value transitions against the
   known `weapon2`/`weapon4` button pulses.

Do not enable automatic selection unless a stable named field identifies the
same category/store before release across repeated sessions and a behavioral
test pins that field. A pulse correlated only with firing is not selection.

## Scenario Matrix

| Scenario | Required observation |
|---|---|
| Free-fall/high-drag bomb | Existing CCRP release cue remains available and uses the manually selected bomb. |
| Guided bomb | Card says estimate, uses the forward POI/zone, and never says game lock or authorization. |
| Glide bomb, default model | Card names the FoxThree-compatible temporary model, reports a neutral/yellow experimental within/beyond reference, shows no iron-bomb trajectory as glide range, and makes no lock/hit guarantee. |
| Glide bomb, strict mode | Card reports `insufficient data` with `glide envelope unavailable` (or the localized equivalent), shows no practical range, and gives no synthetic toss command. |
| AGM | Too-close, align, estimated-in-envelope, and out-of-range transitions follow the same current ground target without a new map. |
| Complex conditional propulsion | A weapon with a valid `guidance/tableN` envelope keeps its Datamine reference despite `conditional_propulsion_unsupported`; a weapon without a valid table still reports insufficient data instead of a guessed point-mass range. |
| Ground countdown | Time-to-window appears only while aligned and closing; turning away or losing positive SOG closure removes it. |
| AAM with visible hostile | Only a currently returned hostile contact feeds the estimate; a valid conditional table produces a neutral/yellow `within all-aspect`, `within current-aspect`, `head-on only`, or `beyond envelope` reference with `two_dimensional` quality and no lock/NEZ/Rtr/Rne claim. |
| AAM current radial motion | Turning the target from opening to crossing to closing changes only the two-dimensional aspect-dependent reference when the current contact carries finite `dx`/`dy`; removing those fields returns to an aspect-unknown reference without reconstructing a track. |
| AIM-120C-5 high-energy launch | At matched high-altitude/high-speed inputs, the displayed maximum follows the interpolated Datamine condition table and is not collapsed to the one-dimensional `maxDistance` cutoff; record the official comparison result at the same inputs. |
| AAM with friendly only | No friendly aircraft is selected as a target. |
| Contact disappears | AAM cue returns to no-target on the next current snapshot; no ghost contact or reconstructed track remains. |
| Unknown/incompatible weapon | In-envelope cue is suppressed and the card asks for a valid manual selection. |
| Standard/Lite build | App starts without the Enhanced-only catalog/schema and shows no weapon-solution card. |

## Calibration Notes

For each supported example, record release altitude, TAS, indicated target
distance, selected weapon ID, card range/status/reason/quality, current hostile
`dx`/`dy` availability, and observed time to impact. For AAM table references,
also record which altitude/carrier-Mach/target-Mach cells and scenario bounds
were selected or interpolated. Compare against War Thunder's own guided-weapon
comparison at the same launch altitude, launch speed, target altitude, target
speed, initial distance, and aspect. A difference measured at mismatched inputs
is not calibration evidence.

The game's native `buildMissileTrajectoryData` implementation and reusable
static output curves are not present in the current Datamine checkout. A future
official-curve provider therefore needs a reproducible sample set. For each
sample, retain the game version, weapon/source ID, vehicle, every comparison
input, trajectory/telemetry output, capture method, and raw-artifact hash. Cover
axis endpoints and interior values before using interpolation, and keep sampled
output versioned separately from the existing configuration-derived catalog.
Alternatively, a new independent lift/autopilot solver must be calibrated with
several repeatable official-comparison and live-release cases before it can
replace the temporary compatibility heuristic as the default provider.

Treat discrepancies as model evidence: adjust documented model choices only
with several repeatable cases, never by importing GreasyFork/Wiki/forum range
tables as runtime parameters. Do not mark a glide envelope as validated merely
because the experimental cue or strict unavailable state renders correctly;
that smoke covers presentation and policy switching, not range accuracy.

The current Draft contract intentionally does not claim target altitude,
terrain elevation, verified radar lock, three-dimensional target closure,
dependable target-speed magnitude, maneuver energy, or full three-dimensional
accuracy. Record those gaps rather than marking the smoke as passed by
assumption.
