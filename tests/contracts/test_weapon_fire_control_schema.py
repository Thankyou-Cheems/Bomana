# enforces: docs/specs/weapon-fire-control.md WFC-01 WFC-02 WFC-05 WFC-07 WFC-14

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from bomana.core.offline_rigidbody_catalog import load_catalog
from tools.datamine_utils import (
    SchemaValidationError,
    load_json_schema,
    validate_json_schema,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "docs/specs/schemas/weapon-fire-control.schema.json"
CATALOG_PATH = ROOT / "bomana/data/weapon_fire_control.json"
RIGIDBODY_CATALOG_PATH = ROOT / "bomana/data/offline_rigidbody_catalog.bin"
EXPECTED_COMMIT = "d5575f185021a950ac34e3854f17a34bafdc73e8"


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    return load_json_schema(SCHEMA_PATH)


@pytest.fixture(scope="module")
def catalog() -> dict[str, Any]:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def test_generated_catalog_matches_canonical_schema(
    schema: dict[str, Any],
    catalog: dict[str, Any],
) -> None:
    validate_json_schema(catalog, schema, path="weapon catalog")
    assert catalog["schema_version"] == schema["properties"]["schema_version"]["const"]
    assert catalog["meta"]["weapon_count"] == len(catalog["weapons"])
    assert catalog["meta"]["aircraft_count"] == len(catalog["aircraft_weapons"])


def test_catalog_records_pinned_clean_datamine_provenance(catalog: dict[str, Any]) -> None:
    meta = catalog["meta"]
    assert meta["source_version"] == "2.57.1.19"
    assert meta["source_commit"] == EXPECTED_COMMIT
    assert meta["source_repo"] == "https://github.com/gszabi99/War-Thunder-Datamine"
    assert len(meta["source_subdirs"]) >= 3
    assert meta["unresolved_references"] == [
        "aces.vromfs.bin_u/gamedata/flightmodels/su-6_am42_23.blkx#/weapon_presets/preset/4/blk -> gameData/FlightModels/weaponPresets/su_6_am42_fab50_rs82.blk",
        "aces.vromfs.bin_u/gamedata/flightmodels/su-6_am42_23.blkx#/weapon_presets/preset/5/blk -> gameData/FlightModels/weaponPresets/su_6_am42_fab50_rbs82.blk",
    ]

    serialized = json.dumps(catalog, ensure_ascii=False).casefold()
    assert "greasyfork" not in serialized
    for weapon_id, weapon in catalog["weapons"].items():
        assert weapon["id"] == weapon_id
        assert weapon["source_file"].startswith("aces.vromfs.bin_u/gamedata/weapons/")
        assert len(weapon["source_sha256"]) == 64
        assert weapon["source_pointers"]
        assert all(pointer.startswith("/") for pointer in weapon["source_pointers"].values())
        assert weapon["reference_chains"]
        assert isinstance(weapon["model_unsupported_reasons"], list)
        assert set(weapon["compatible_aircraft"]).issubset(catalog["aircraft_weapons"])


def test_known_records_keep_distinct_range_and_speed_semantics(
    catalog: dict[str, Any],
) -> None:
    aim9l = catalog["weapons"]["us_aim9l_sidewinder"]
    assert aim9l["source_file"].endswith("/rocketguns/us_aim9l_sidewinder.blkx")
    assert aim9l["hard_max_distance_m"] == 18000
    assert aim9l["stat_card_range_m"] == 18000
    assert aim9l["max_speed_mps"] == 1000
    assert aim9l["source_pointers"]["hard_max_distance_m"] == "/rocket/maxDistance"
    assert aim9l["source_pointers"]["stat_card_range_m"] == "/rocket/rangeMax"
    assert aim9l["source_pointers"]["max_speed_mps"] == "/rocket/endSpeed"

    agm65d = catalog["weapons"]["us_agm_65d"]
    assert agm65d["hard_max_distance_m"] == 26400
    assert agm65d["stat_card_range_m"] == 23000
    assert agm65d["max_speed_mps"] == 2000


def test_schema_backed_model_limits_and_aam_minima_keep_provenance(
    catalog: dict[str, Any],
) -> None:
    yj91a = catalog["weapons"]["cn_yj91a"]
    assert set(yj91a["model_unsupported_reasons"]) == {
        "conditional_propulsion_autopilot",
        "variable_propulsion_factor",
        "impulse_factor_index",
        "instantaneous_mass_change",
    }
    assert any(
        key.startswith("model_unsupported.conditional_propulsion_autopilot")
        for key in yj91a["source_pointers"]
    )
    assert any(
        key.startswith("model_unsupported.variable_propulsion_factor")
        for key in yj91a["source_pointers"]
    )

    aim9l = catalog["weapons"]["us_aim9l_sidewinder"]
    assert aim9l["model_unsupported_reasons"] == []
    assert aim9l["guidance_min_ranges"]["tables"][0]["table"] == "table0"
    assert len(aim9l["guidance_min_ranges"]["tables"][0]["range_min_m"]) > 1
    assert (
        aim9l["source_pointers"]["guidance_min_ranges.table0.range_min_m"]
        == "/rocket/guidance/table0/rangeMin"
    )
    assert aim9l["min_distance_m"] == 30.0


@pytest.mark.parametrize(
    ("weapon_id", "role", "trigger_group", "sensitivity", "source_pointer"),
    (
        ("fr_aa20", "aam", "aam", 0.2, "/rocket/controlSensitivity"),
        (
            "us_agm_12b_bullpup",
            "agm",
            "atgm",
            0.2,
            "/rocket/controlSensitivity",
        ),
        ("de_fx1400", "bomb", "bombs", 0.7, "/bomb/controlSensitivity"),
    ),
)
def test_legacy_command_guidance_keeps_datamine_control_evidence(
    catalog: dict[str, Any],
    weapon_id: str,
    role: str,
    trigger_group: str,
    sensitivity: float,
    source_pointer: str,
) -> None:
    weapon = catalog["weapons"][weapon_id]

    assert weapon["role"] == role
    assert weapon["control"] == "guided"
    assert trigger_group in weapon["trigger_groups"]
    assert weapon["guidance"] == {
        "type": "legacy_command",
        "seeker": "command",
        "control_sensitivity": sensitivity,
    }
    assert weapon["source_pointers"]["guidance.control_sensitivity"] == source_pointer
    assert weapon["source_pointers"]["guidance.type"] == source_pointer


def test_every_generated_solver_route_has_required_physics(catalog: dict[str, Any]) -> None:
    for weapon in catalog["weapons"].values():
        if weapon["propulsion"] == "powered":
            assert weapon["time_life_s"] > 0
            assert weapon["cx_k"] > 0
            assert weapon["motor_stages"]
            assert any(stage["thrust_n"] > 0 for stage in weapon["motor_stages"])
        elif weapon["control"] == "guided" and weapon["planform"] == "glide":
            assert weapon["wing_area_mult"] > 0
            assert weapon["cx_k"] > 0
        elif weapon["control"] == "guided":
            assert weapon["drag_cx"] > 0


def test_every_ccrp_routed_catalog_weapon_resolves_fresh_bomb_physics(
    catalog: dict[str, Any],
) -> None:
    ccrp = load_catalog(RIGIDBODY_CATALOG_PATH)["records"]
    ccrp_ids = set(ccrp)
    ccrp_aliases = {
        alias.casefold()
        for record in ccrp.values()
        for alias in record.get("aliases", ())
    }

    missing = [
        weapon_id
        for weapon_id, weapon in catalog["weapons"].items()
        if weapon["role"] == "bomb"
        and weapon["propulsion"] == "unpowered"
        and weapon["control"] == "unguided"
        and weapon["planform"] in {"normal", "high_drag"}
        and weapon_id not in ccrp_ids
        and weapon_id not in ccrp_aliases
    ]
    assert not missing


def test_schema_rejects_tampered_catalog(
    schema: dict[str, Any],
    catalog: dict[str, Any],
) -> None:
    missing_field = copy.deepcopy(catalog)
    del missing_field["weapons"]["us_aim9l_sidewinder"]["role"]
    with pytest.raises(SchemaValidationError, match="missing fields"):
        validate_json_schema(missing_field, schema, path="tampered")

    invalid_sha = copy.deepcopy(catalog)
    invalid_sha["weapons"]["us_aim9l_sidewinder"]["source_sha256"] = "not-a-sha"
    with pytest.raises(SchemaValidationError, match="pattern"):
        validate_json_schema(invalid_sha, schema, path="tampered")

    invalid_reason = copy.deepcopy(catalog)
    invalid_reason["weapons"]["us_aim9l_sidewinder"]["model_unsupported_reasons"] = [
        "pretend_supported"
    ]
    with pytest.raises(SchemaValidationError, match="allowed values"):
        validate_json_schema(invalid_reason, schema, path="tampered")


def test_guidance_envelope_schema_requires_exact_condition_shapes(
    schema: dict[str, Any],
    catalog: dict[str, Any],
) -> None:
    table_schema = schema["$defs"]["guidance_envelope_table"]
    pair_schema = schema["$defs"]["guidance_envelope_pair"]
    quad_schema = schema["$defs"]["guidance_envelope_quad"]
    assert set(table_schema["required"]) == {
        "table",
        "altitude_m",
        "fighter_mach",
        "target_mach",
        "target_mach2_mult",
        "range_min_m",
        "range_max_m",
    }
    assert pair_schema["minItems"] == pair_schema["maxItems"] == 2
    assert quad_schema["minItems"] == quad_schema["maxItems"] == 4

    candidate = copy.deepcopy(catalog)
    candidate["weapons"]["us_aim9l_sidewinder"]["guidance_envelope"] = {
        "tables": [
            {
                "table": "table0",
                "altitude_m": 1000.0,
                "fighter_mach": [0.9, 1.2],
                "target_mach": [0.9, 0.9],
                "target_mach2_mult": -1.0,
                "range_min_m": [430.0, 1100.0, 500.0, 950.0],
                "range_max_m": [8000.0, 62000.0, 9000.0, 67000.0],
            }
        ]
    }
    validate_json_schema(candidate, schema, path="envelope candidate")

    candidate["weapons"]["us_aim9l_sidewinder"]["guidance_envelope"]["tables"][0][
        "fighter_mach"
    ] = [0.9]
    with pytest.raises(SchemaValidationError, match="at least 2 items"):
        validate_json_schema(candidate, schema, path="invalid envelope")

    candidate["weapons"]["us_aim9l_sidewinder"]["guidance_envelope"]["tables"][0][
        "fighter_mach"
    ] = [0.9, 1.0, 1.2]
    with pytest.raises(SchemaValidationError, match="at most 2 items"):
        validate_json_schema(candidate, schema, path="invalid envelope")
