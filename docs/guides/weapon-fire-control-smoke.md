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
| Glide bomb | Card shows a neutral/yellow guided-ballistic reference rather than a green glide envelope, and gives no synthetic toss command. Record height/range evidence for a future lift-model calibration. |
| AGM | Too-close, align, estimated-in-envelope, and out-of-range transitions follow the same current ground target without a new map. |
| Complex conditional propulsion | PGM/AGM-130/ALARM/Kh-31/YJ-91-style unsupported propulsion semantics report insufficient data instead of a guessed range. |
| Ground countdown | Time-to-window appears only while aligned and closing; turning away or losing positive SOG closure removes it. |
| AAM with visible hostile | Only a currently returned hostile contact feeds the estimate; the result is a neutral/yellow two-dimensional maximum only, with unknown minimum and no NEZ/Rtr/Rne claim. |
| AAM with friendly only | No friendly aircraft is selected as a target. |
| Contact disappears | AAM cue returns to no-target on the next current snapshot; no ghost contact or reconstructed track remains. |
| Unknown/incompatible weapon | In-envelope cue is suppressed and the card asks for a valid manual selection. |
| Standard/Lite build | App starts without the Enhanced-only catalog/schema and shows no weapon-solution card. |

## Calibration Notes

For each supported example, record release altitude, TAS, indicated target
distance, selected weapon ID, card range/status, and observed time to impact.
Compare against War Thunder's own weapon/trajectory presentation when available.
Treat discrepancies as model evidence: adjust documented model constants only
with several repeatable cases, never by importing GreasyFork/Wiki/forum range
tables as runtime parameters.

The current Draft contract intentionally does not claim target altitude,
terrain elevation, verified radar lock, target closure, maneuver energy, or
full three-dimensional accuracy. Record those gaps rather than marking the
smoke as passed by assumption.
