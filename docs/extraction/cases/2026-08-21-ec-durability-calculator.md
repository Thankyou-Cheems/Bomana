# EC durability, repair, and weapon-count calculator

## Agent Brief

| Field | Value |
| --- | --- |
| Format | `engineering-investigation/v1` |
| Case | `bomana-ec-durability-calculator-20260821` |
| Status | `validated` |
| Tracker frontier | [Strike encyclopedia release Case](2026-08-21-strike-encyclopedia-release.md) |
| Question | Can current static sources map displayed vehicle BR 1.0–14.7 to EC durability, recover bombing-point and airport damage/repair/self-destruction state machines, and support a truthful per-weapon quantity calculator? |
| Source / environment lock | Datamine `2.57.1.89` / `9f8cdbc99342ccc7aeb8d0e684eb1a409384053e`; current hash-locked mission templates and weapon BLKX; official Wiki/CDK sources; offline/static inspection only |
| Tooling | [`wt-vromfs-mission-layout/v1`](../toolchains.md), [`wt-vromfs-static/v1`](../toolchains.md), [`bomana-offline-boundary-audit/v1`](../toolchains.md) |
| Current conclusion | Room maximum BR maps exactly through descriptor `maxRank` to six durability bands; airport repair and bombing-point respawn are closed statically. The 90%/~3 s fire tail is a labelled static-parameter inference. Hangar base damage is the desktop `explosive.blkx` splash curve on TNT equivalent, with under-25 mm penetration restrained by `bombing_zone` armor. Napalm uses splash+fire inputs; nukes use the yield table. `gameparams` 1 kg TNT = 8 HP is not the hangar formula. |
| Current entry | `mis.vromfs.bin_u/gamedata/missions/templates/enduring_confrontation/{bdt_bases_destroy_template,ft_fields_template}.blkx` |

**Current route**: evaluate hangar splash formula from weapon BLK inputs and bundled `explosive.blkx` curves -> keep fire tail labelled as inference -> do not copy per-weapon `wpcost.weaponDamage` tables or the linear gameparams 8 HP/kg map.

**Known hazards**: do not divide `mission_hp` by raw explosive mass or Wiki TNTe; do not treat a practical six-Mk 83 reference as a native damage formula; keep aircraft, helicopter, bombing point, runway, and auxiliary-module branches separate; do not start/attach to the client or read process memory.

**Next action**: owner visual check of the 8.7.15 calculator page. A version/target/hit-condition-locked desktop calibration remains a separate frontier.

## Reproduce or continue

Use the exact source files and hashes recorded in the linked research note. Enumerate every assignment and consumer of balance level, base/module HP, damage restore, self-destruction, and bombing-area health. A successful trace must give trigger conditions, comparisons, timing units, update rate, and mode branches rather than isolated constants.

## Decision Trail

### D1 — Reopen “destruction equivalent” as a damage-state investigation

- **Approach**: extend the existing six HP rows with weapon TNTe and compute `ceil(hp / tnte)`.
- **Signal**: the existing source note explicitly found no `mission_hp` to TNT mapping, while the user reports a separate 90%-damage self-destruction state transition.
- **Cause**: target durability, weapon energy reference, and mission state-machine behavior are separate source chains.
- **Correction**: trace the full damage and recovery consumers before designing calculator outputs.
- **Lesson**: a target-count calculator needs a closed damage transfer function and terminal-state rule, not merely two numeric tables.

### D2 — Map user-visible BR through room `maxRank`, not the current vehicle

- **Approach**: trace `missionGetBalanceLevel` from the action global back to its writer and compare the descriptor keys with the current GUI rank-to-BR formatter.
- **Signal**: the sole writer consumes room descriptor `maxRank`; the GUI computes `round_0.1(rank/3+1)` and current `economicRankMax=41` displays 14.7.
- **Cause**: the task template tiers are room-balance tiers, while the user-facing vehicle selector exposes a different value that can be below the room cap.
- **Correction**: the calculator asks for the room's maximum allowed BR and resolves it to the exact rank 0--41. Script range 21--50 is retained as the template band but displayed as current BR 8.0--14.7.
- **Lesson**: a 2.3 vehicle in a room capped at 3.7 must use `maxRank=8`, not vehicle rank 4.

### D3 — Ship an honest partial calculator seam, not a guessed damage conversion

- **Approach**: search the current desktop archive and executable for the bombing-zone damage transfer function, then compare only as a provenance check with public sources.
- **Signal**: `aces.exe` loads `explosiveMassToSplashDamageForBombingZone`, but the current desktop `damagemodel.blkx` does not bundle the curve. A mobile datamine has a same-named curve, but it is a different product and disagrees with old desktop examples.
- **Cause**: exact target HP and target state machines are client-template data; weapon-to-bombing-zone damage is supplied through a separate runtime/server descriptor.
- **Correction**: implement exact BR/HP/repair/respawn outputs, label the 90% tail as inference, expose the official high-tier Mk 83 count only as a non-exact reference, and return `native_unknown` elsewhere.
- **Lesson**: matching field names across products do not authorize copying numeric curves.

## Findings and artifacts

| Finding | Evidence / artifact |
| --- | --- |
| Prior six-band HP tables and explicit HP/TNT non-claim | [Strike encyclopedia source note](../../research/war-thunder-strike-encyclopedia-source-2026-08-21.md) |
| Completed detailed source trace | [EC durability research note](../../research/war-thunder-ec-durability-damage-calculator-2026-08-21.md) |
| Evidence-labelled calculator core | `bomana/core/strike_damage_calculator.py` |
| Bundled behavior parameters | `bomana/data/strike_encyclopedia.json` |
| User-openable calculator page | `bomana/ui/strike_encyclopedia.py` |
| Calculator and UI regression tests | `tests/test_strike_damage_calculator.py`, `tests/test_ui_geometry.py` |
| Production release | App `8.7.15` in Enhanced, Standard, Lite, and Lite Green; EdgeOne and CheemsPay trees match SHA-256 `7d5a0277...90f0` for Enhanced |

## Limits

- HE bomb counts use the desktop gameparams HP↔TNT coefficient and explosive-type `strengthEquivalent`. This is full-equivalent hit accounting, not a distance-dependent splash curve. Napalm, the missing desktop `explosiveMassToSplashDamageForBombingZone` curve, and the outdated Wiki six-Mk-83 note must not be substituted for each other.
- `hpFireMult=0.1` and `fireSpeed=0.03` are current exact parameters, but their 90%/~3 s consumer semantics remain `static_parameter_inference`, not `exact_native`.
- Airport wall-clock repair interval depends on the rotator and active airfield count; only HP per repair visit is closed.
- Production 8.7.14 remains the previous immutable release; 8.7.15 is the calculator-bearing successor.
