from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import pytest

from tools.datamine_utils import normalize_datamine_caliber_m
from tools.weapon_fire_control_extractor import (
    _extract_motor_stages,
    _guidance_envelope_evidence,
    _guidance_min_range_evidence,
    _model_support_audit,
    extract_catalog,
    resolve_json_pointer,
)

ROOT = Path(__file__).resolve().parent.parent
CATALOG_PATH = ROOT / "bomana/data/weapon_fire_control.json"


@pytest.fixture(scope="module")
def catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_known_legacy_weapon_records(catalog: dict[str, Any]) -> None:
    weapons = catalog["weapons"]

    aim9l = weapons["us_aim9l_sidewinder"]
    assert (aim9l["role"], aim9l["guidance_kind"], aim9l["propulsion"]) == (
        "aam",
        "ir",
        "powered",
    )
    assert aim9l["mass_start_kg"] == pytest.approx(84.46)
    assert aim9l["fins_aoa_horiz"] == pytest.approx(22.5)
    assert aim9l["start_speed_mps"] == 0
    assert aim9l["max_speed_mps"] == 1000
    assert aim9l["hard_max_distance_m"] == 18000
    assert aim9l["stat_card_range_m"] == 18000
    assert aim9l["source_pointers"]["start_speed_mps"] == "/rocket/startSpeed"
    assert aim9l["motor_stages"] == [{"duration_s": 5.3, "thrust_n": 10800.0, "mass_end_kg": 57.06}]

    aim120 = weapons["us_aim_120a"]
    assert aim120["guidance_kind"] == "radar_active"
    assert aim120["motor_stages"] == [
        {"duration_s": 1.7, "thrust_n": 22300.0, "mass_end_kg": 131.75},
        {"duration_s": 5.3, "thrust_n": 13485.0, "mass_end_kg": 101.33},
    ]

    agm65d = weapons["us_agm_65d"]
    assert (agm65d["role"], agm65d["guidance_kind"]) == ("agm", "ir")
    assert agm65d["hard_max_distance_m"] == 26400
    assert agm65d["stat_card_range_m"] == 23000
    assert agm65d["max_speed_mps"] == 2000
    assert agm65d["motor_stages"][1] == {
        "duration_s": 3.5,
        "thrust_n": 8899.49,
        "mass_end_kg": 197.3125,
    }

    kh29t = weapons["su_kh_29t"]
    assert (kh29t["role"], kh29t["guidance_kind"]) == ("agm", "tv")
    assert kh29t["motor_stages"] == [{"duration_s": 4.5, "thrust_n": 50800.0, "mass_end_kg": 559.2}]


def test_known_guided_and_glide_bombs(catalog: dict[str, Any]) -> None:
    weapons = catalog["weapons"]
    gbu12 = weapons["us_gbu_12_paveway_2"]
    assert (gbu12["role"], gbu12["control"], gbu12["guidance_kind"]) == (
        "bomb",
        "guided",
        "laser",
    )
    assert gbu12["planform"] == "glide"
    assert gbu12["guidance"]["range_max_m"] == pytest.approx(4876.8)

    gbu39 = weapons["us_gbu_39"]
    assert (gbu39["guidance_kind"], gbu39["planform"]) == ("ins_gnss", "glide")
    assert gbu39["wing_area_mult"] == pytest.approx(3.5)

    spice = weapons["il_spice_250"]
    assert (spice["guidance_kind"], spice["planform"]) == ("mixed", "glide")
    assert spice["guidance"]["range_max_m"] == 100000

    assert weapons["us_agm_154a1_jsow"]["planform"] == "glide"
    assert weapons["su_umpk_500m62"]["planform"] == "glide"
    assert not [
        weapon_id
        for weapon_id, weapon in weapons.items()
        if weapon["role"] == "bomb"
        and weapon["control"] == "guided"
        and weapon["planform"] == "high_drag"
    ]


def test_datamine_caliber_anomaly_rule_is_narrow_and_evidence_backed() -> None:
    normalized, evidence = normalize_datamine_caliber_m(
        0.82,
        "bomb_ussr_82mm_o_832.blkx",
        "bomb_82mm_mortar",
    )

    assert normalized == pytest.approx(0.082)
    assert evidence == {
        "field": "caliber_m",
        "rule": "datamine_mm_identity_decimal_shift",
        "raw_value": 0.82,
        "normalized_value": 0.082,
        "evidence": ["bomb_82mm_mortar", "bomb_ussr_82mm_o_832.blkx"],
    }
    assert normalize_datamine_caliber_m(0.81, "bomb_82mm_mortar") == (0.81, None)
    assert normalize_datamine_caliber_m(0.82, "unidentified_payload") == (0.82, None)


def test_known_modern_propulsion_records(catalog: dict[str, Any]) -> None:
    weapons = catalog["weapons"]
    aim54a = weapons["us_aim_54a"]
    assert aim54a["propulsion"] == "powered"
    assert aim54a["model_unsupported_reasons"] == []
    assert aim54a["motor_stages"] == [
        {"duration_s": 0.5, "thrust_n": 0.0, "mass_end_kg": 446.562},
        {"duration_s": 27.8, "thrust_n": 12981.21, "mass_end_kg": 283.269},
    ]

    kd88 = weapons["ch_kd_88_missile_ir"]
    assert kd88["propulsion"] == "powered"
    assert kd88["motor_stages"][1]["duration_s"] == pytest.approx(825.0)
    assert kd88["motor_stages"][1]["thrust_n"] == pytest.approx(2836.36366)
    assert kd88["motor_stages"][1]["mass_end_kg"] == 665

    yj91a = weapons["cn_yj91a"]
    assert yj91a["propulsion"] == "powered"
    assert yj91a["model_unsupported_reasons"] == [
        "conditional_propulsion_autopilot",
        "impulse_factor_index",
        "instantaneous_mass_change",
        "variable_propulsion_factor",
    ]
    assert yj91a["motor_stages"][1]["mass_end_kg"] == 439
    assert yj91a["motor_stages"][2]["mass_end_kg"] == 386
    assert (
        yj91a["source_pointers"]["motor_stages.1.mass_end_kg.instant_mass_lost_1"]
        == "/rocket/propulsion0/impulse1/massLost"
    )
    assert (
        yj91a["source_pointers"][
            "model_unsupported.conditional_propulsion_autopilot.propulsion1.startTimeMin"
        ]
        == "/rocket/guidance/propulsionAutopilot/propulsion1/startTimeMin"
    )
    assert (
        yj91a["source_pointers"]["model_unsupported.impulse_factor_index.propulsion1.impulse0"]
        == "/rocket/propulsion1/impulse0/factorIndex"
    )
    assert (
        yj91a["source_pointers"][
            "model_unsupported.instantaneous_mass_change.propulsion0.impulse1.mass_lost"
        ]
        == "/rocket/propulsion0/impulse1/massLost"
    )


def test_model_support_audit_detects_conditional_and_discrete_propulsion() -> None:
    section = {
        "guidance": {
            "propulsionAutopilot": {
                "propulsion1": {
                    "startTimeMin": 2.75,
                    "velocityMin": 450.0,
                    "PidControllerCruise": {"prop": 0.05, "intg": 0.5},
                }
            }
        },
        "propulsion0": {
            "impulse0": {"time": 0.0, "force": 0.0, "massLost": 42.0},
            "impulse1": {"massFlow": 3.5, "isp": 17000.0, "factorIndex": 0},
        },
        "propulsionFactor0": {"ThrustByMachThrottle2D0": [0.1, 0.7]},
    }

    reasons, pointers = _model_support_audit("rocket", section)

    assert reasons == [
        "conditional_propulsion_autopilot",
        "impulse_factor_index",
        "instantaneous_mass_change",
        "variable_propulsion_factor",
    ]
    assert (
        pointers[
            "model_unsupported.conditional_propulsion_autopilot.propulsion1."
            "PidControllerCruise.prop"
        ]
        == "/rocket/guidance/propulsionAutopilot/propulsion1/PidControllerCruise/prop"
    )
    document = {"rocket": section}
    for pointer in pointers.values():
        resolve_json_pointer(document, pointer)


def test_aam_guidance_min_range_evidence_is_condition_preserving() -> None:
    section = {
        "minDistance": 30.0,
        "guidance": {
            "table0": {
                "rangeMin": [430.0, 1100.0, 500.0, 950.0],
                "rangeMinDogfight": [380.0, 2300.0, 420.0, 2150.0],
            },
            "table1": {"rangeMin": [460.0, 1010.0, 510.0, 1130.0]},
        },
    }

    evidence, pointers = _guidance_min_range_evidence("rocket", section, role="aam")

    assert evidence == {
        "tables": [
            {
                "table": "table0",
                "range_min_m": [430.0, 1100.0, 500.0, 950.0],
                "range_min_dogfight_m": [380.0, 2300.0, 420.0, 2150.0],
            },
            {
                "table": "table1",
                "range_min_m": [460.0, 1010.0, 510.0, 1130.0],
            },
        ],
        "conservative_floor_m": 380.0,
    }
    assert pointers == {
        "guidance_min_ranges.table0.range_min_m": "/rocket/guidance/table0/rangeMin",
        "guidance_min_ranges.table0.range_min_dogfight_m": (
            "/rocket/guidance/table0/rangeMinDogfight"
        ),
        "guidance_min_ranges.table1.range_min_m": "/rocket/guidance/table1/rangeMin",
    }
    assert section["minDistance"] == 30.0


def test_aam_guidance_envelope_preserves_conditions_and_orders_altitudes() -> None:
    section = {
        "guidance": {
            "table0": {
                "altitude": 5000.0,
                "fighterMach": [0.9, 1.2],
                "targetMach": [0.9, 0.9],
                "targetMach2Mult": -1.0,
                "rangeMin": [500.0, 1200.0, 600.0, 1300.0],
                "rangeMax": [13000.0, 81000.0, 15000.0, 92000.0],
                "rangeMinDogfight": [900.0, 3000.0, 1000.0, 2900.0],
                "rangeMaxDogfight": [13000.0, 19000.0, 20000.0, 21000.0],
                "rangeMaxAltDiff": [500.0, 0.0],
                "rangeMaxDogfightAltDiff": [500.0, 0.0],
                "timeMax": [39.0, 70.0, 41.0, 119.0],
                "timeMaxAltDiff": [500.0, 0.0],
                "altDiff": [500.0, 1000.0],
            },
            "table1": {
                "altitude": 1000.0,
                "fighterMach": [0.9, 1.2],
                "targetMach": [0.9, 0.9],
                "targetMach2Mult": -1.0,
                "rangeMin": [400.0, 1100.0, 500.0, 1200.0],
                "rangeMax": [8000.0, 62000.0, 9000.0, 67000.0],
            },
        }
    }

    envelope, pointers = _guidance_envelope_evidence("rocket", section, role="aam")

    assert envelope is not None
    assert [table["table"] for table in envelope["tables"]] == ["table1", "table0"]
    assert envelope["tables"][1] == {
        "table": "table0",
        "altitude_m": 5000.0,
        "fighter_mach": [0.9, 1.2],
        "target_mach": [0.9, 0.9],
        "target_mach2_mult": -1.0,
        "range_min_m": [500.0, 1200.0, 600.0, 1300.0],
        "range_max_m": [13000.0, 81000.0, 15000.0, 92000.0],
        "range_min_dogfight_m": [900.0, 3000.0, 1000.0, 2900.0],
        "range_max_dogfight_m": [13000.0, 19000.0, 20000.0, 21000.0],
        "range_max_alt_diff_m": [500.0, 0.0],
        "range_max_dogfight_alt_diff_m": [500.0, 0.0],
        "time_max_s": [39.0, 70.0, 41.0, 119.0],
        "time_max_alt_diff_m": [500.0, 0.0],
        "alt_diff_m": [500.0, 1000.0],
    }
    assert pointers["guidance_envelope.table0"] == "/rocket/guidance/table0"
    assert pointers["guidance_envelope.table0.range_max_m"] == "/rocket/guidance/table0/rangeMax"
    document = {"rocket": section}
    for pointer in pointers.values():
        resolve_json_pointer(document, pointer)

    agm_envelope, agm_pointers = _guidance_envelope_evidence("rocket", section, role="agm")
    assert agm_envelope == envelope
    assert agm_pointers == pointers


def test_aam_guidance_envelope_skips_incomplete_legacy_tables() -> None:
    section = {
        "guidance": {
            "table0": {
                "altitude": 1000.0,
                "fighterMach": [0.9, 1.2],
                "targetMach": [0.9, 0.9],
                "rangeMin": [400.0, 1100.0, 500.0, 1200.0],
                "rangeMax": [8000.0, 62000.0, 9000.0, 67000.0],
            }
        }
    }

    assert _guidance_envelope_evidence("rocket", section, role="aam") == (None, {})
    minimums, _ = _guidance_min_range_evidence("rocket", section, role="aam")
    assert minimums is not None


def test_aam_guidance_envelope_rejects_invalid_core_shape() -> None:
    section = {
        "guidance": {
            "table0": {
                "altitude": 1000.0,
                "fighterMach": [0.9],
                "targetMach": [0.9, 0.9],
                "targetMach2Mult": -1.0,
                "rangeMin": [400.0, 1100.0, 500.0, 1200.0],
                "rangeMax": [8000.0, 62000.0, 9000.0, 67000.0],
            }
        }
    }

    with pytest.raises(RuntimeError, match="expected 2"):
        _guidance_envelope_evidence("rocket", section, role="aam")


def test_current_aam_guidance_table_coverage(catalog: dict[str, Any]) -> None:
    aams = [weapon for weapon in catalog["weapons"].values() if weapon["role"] == "aam"]
    with_range_min = [weapon for weapon in aams if "guidance_min_ranges" in weapon]
    with_dogfight = [
        weapon
        for weapon in with_range_min
        if any("range_min_dogfight_m" in table for table in weapon["guidance_min_ranges"]["tables"])
    ]

    assert len(aams) == 199
    assert len(with_range_min) == 176
    assert len(with_dogfight) == 110
    for weapon in with_range_min:
        evidence = weapon["guidance_min_ranges"]
        all_values = [
            value
            for table in evidence["tables"]
            for field in ("range_min_m", "range_min_dogfight_m")
            for value in table.get(field, [])
        ]
        assert evidence["conservative_floor_m"] == min(all_values)
    aim9l = catalog["weapons"]["us_aim9l_sidewinder"]
    assert aim9l["min_distance_m"] == 30.0
    assert aim9l["guidance_min_ranges"]["conservative_floor_m"] > 30.0


def test_current_unsupported_model_reason_counts(catalog: dict[str, Any]) -> None:
    weapons = catalog["weapons"].values()
    counts = {
        code: sum(code in weapon["model_unsupported_reasons"] for weapon in weapons)
        for code in (
            "conditional_propulsion_autopilot",
            "variable_propulsion_factor",
            "impulse_factor_index",
            "instantaneous_mass_change",
        )
    }
    unsupported = sum(bool(weapon["model_unsupported_reasons"]) for weapon in weapons)

    assert counts == {
        "conditional_propulsion_autopilot": 23,
        "variable_propulsion_factor": 11,
        "impulse_factor_index": 11,
        "instantaneous_mass_change": 15,
    }
    assert unsupported == 26


def test_known_legacy_command_guided_records_are_not_dropped(catalog: dict[str, Any]) -> None:
    weapons = catalog["weapons"]

    for weapon_id, role in (
        ("fr_aa20", "aam"),
        ("us_agm_12b_bullpup", "agm"),
        ("de_fx1400", "bomb"),
    ):
        weapon = weapons[weapon_id]
        assert weapon["role"] == role
        assert weapon["control"] == "guided"
        assert weapon["guidance_kind"] == "unknown"
        assert weapon["guidance"]["type"] == "legacy_command"
        assert weapon["guidance"]["control_sensitivity"] > 0
        assert weapon["source_pointers"]["guidance.control_sensitivity"].endswith(
            "/controlSensitivity"
        )


def test_modern_propulsion_shape_normalization() -> None:
    section = {
        "mass": 600.0,
        "propulsion0": {
            "fireDelay": 0.5,
            "impulse0": {"time": 2.5, "force": 107100.0, "massLost": 119.0},
            "impulse1": {"time": 0.0, "force": 0.0, "massLost": 42.0},
        },
        "propulsion1": {
            "impulse0": {
                "massFlow": 3.5333,
                "isp": 17225.0,
                "massLost": 53.0,
                "factorIndex": 0,
            }
        },
    }
    stages = _extract_motor_stages("rocket", section)
    assert [stage.mass_end_kg for stage in stages] == [600.0, 439.0, 386.0]
    assert stages[2].duration_s == pytest.approx(53.0 / 3.5333)
    assert stages[2].thrust_n == pytest.approx(3.5333 * 17225.0)


def test_one_canonical_reference_chain_per_compatible_aircraft(
    catalog: dict[str, Any],
) -> None:
    for weapon in catalog["weapons"].values():
        chains = weapon["reference_chains"]
        compatible = weapon["compatible_aircraft"]
        assert len(chains) == len(compatible)
        chain_aircraft = {Path(chain[0].split("#", 1)[0]).stem.casefold() for chain in chains}
        assert chain_aircraft == set(compatible)
        assert all(
            chain[-1] == f"{weapon['source_file']}#/{weapon['source_section']}" for chain in chains
        )


def test_nested_container_keeps_aircraft_compatibility(catalog: dict[str, Any]) -> None:
    agm65d = catalog["weapons"]["us_agm_65d"]
    assert "a_10c" in agm65d["compatible_aircraft"]
    chain = next(
        chain
        for chain in agm65d["reference_chains"]
        if Path(chain[0].split("#", 1)[0]).stem.casefold() == "a_10c"
    )
    assert any("/weapons/containers/lau_88a_agm_65d_x_3.blkx#/blk" in hop for hop in chain)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_localization(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter=";", lineterminator="\n")
        writer.writerow(
            [
                "<ID|readonly|noverify>",
                "<English>",
                "<French>",
                "<Italian>",
                "<German>",
                "<Spanish>",
                "<Russian>",
                "<Polish>",
                "<Czech>",
                "<Turkish>",
                "<Chinese>",
            ]
        )
        writer.writerow(
            [
                "weapons/test_bomb",
                "Test guided bomb",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "",
                "测试制导炸弹",
            ]
        )


def test_case_insensitive_recursive_container_fixture(tmp_path: Path) -> None:
    datamine = tmp_path / "War-Thunder-Datamine"
    (datamine / "version").parent.mkdir(parents=True)
    (datamine / "version").write_text("test-version\n", encoding="utf-8")
    fm = datamine / "aces.vromfs.bin_u/gamedata/flightmodels/Test_Plane.blkx"
    _write_json(
        fm,
        {
            "WeaponSlots": {
                "WeaponSlot": {
                    "index": 1,
                    "WeaponPreset": [
                        {
                            "name": "guided",
                            "iconType": "glide_guided_bomb_small",
                            "Weapon": {
                                "trigger": "guided bombs",
                                "blk": "gameData/WEAPONS/CONTAINERS/RACK.BLK",
                            },
                        },
                        {
                            "name": "rocket",
                            "Weapon": {
                                "trigger": "rockets",
                                "blk": "gameData/Weapons/RocketGuns/Test_Rocket.blk",
                            },
                        },
                        {
                            "name": "missing",
                            "Weapon": {
                                "trigger": "aam",
                                "blk": "gameData/Weapons/RocketGuns/Missing.blk",
                            },
                        },
                    ],
                }
            }
        },
    )
    weapons = datamine / "aces.vromfs.bin_u/gamedata/weapons"
    _write_json(
        weapons / "containers/Rack.blkx",
        {"container": True, "blk": "gameData/Weapons/Containers/Nested.blk", "bullets": 2},
    )
    _write_json(
        weapons / "containers/Nested.blkx",
        {"container": True, "blk": "gameData/Weapons/BombGuns/Test_Bomb.blk", "bullets": 2},
    )
    _write_json(
        weapons / "bombguns/Test_Bomb.blkx",
        {
            "bombGun": True,
            "mesh_deployed": "test_bomb_wings",
            "bomb": {
                "bulletName": "test_bomb",
                "mass": 100.0,
                "caliber": 0.2,
                "CxK": 1.2,
                "dragCx": 0.02,
                "wingAreaMult": 3.0,
                "finsAoaHor": 0.2,
                "finsAoaVer": 0.2,
                "timeLife": 60.0,
                "guidanceType": "sns",
                "guidance": {"guidanceAutopilot": {"reqAccelMax": 8.0}},
            },
        },
    )
    _write_json(
        weapons / "rocketguns/Test_Rocket.blkx",
        {
            "rocketGun": True,
            "rocket": {
                "mass": 20.0,
                "caliber": 0.1,
                "timeFire": 1.0,
                "force": 1000.0,
                "massEnd": 15.0,
            },
        },
    )
    _write_localization(datamine / "lang.vromfs.bin_u/lang/units_weaponry.csv")

    result = extract_catalog(datamine, require_clean=False)
    assert set(result["weapons"]) == {"test_bomb"}
    weapon = result["weapons"]["test_bomb"]
    assert weapon["compatible_aircraft"] == ["test_plane"]
    assert weapon["planform"] == "glide"
    assert weapon["display_name"] == "Test guided bomb"
    assert weapon["display_name_zh"] == "测试制导炸弹"
    assert weapon["start_speed_mps"] == 0
    assert "start_speed_mps" not in weapon["source_pointers"]
    assert len(weapon["reference_chains"]) == 1
    assert [
        f"{Path(hop.split('#', 1)[0]).name}#/blk"
        for hop in weapon["reference_chains"][0]
        if "/containers/" in hop.casefold()
    ] == ["Rack.blkx#/blk", "Nested.blkx#/blk"]
    assert len(result["meta"]["unresolved_references"]) == 1

    source = json.loads((datamine / weapon["source_file"]).read_text(encoding="utf-8"))
    for pointer in weapon["source_pointers"].values():
        resolve_json_pointer(source, pointer)
