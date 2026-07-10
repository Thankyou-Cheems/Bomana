"""Behavioral coverage for the schema-backed weapon catalog."""

import copy
import json
from pathlib import Path

import pytest

from bomana.core.weapon_catalog import WeaponCatalog, WeaponCatalogError

ROOT = Path(__file__).resolve().parents[1]
SHARED_SCHEMA = ROOT / "docs/specs/schemas/weapon-fire-control.schema.json"


def _weapon(
    weapon_id: str,
    name: str,
    *,
    role: str = "bomb",
    propulsion: str = "unpowered",
    control: str = "unguided",
    planform: str = "normal",
    aircraft: tuple[str, ...] = ("test_plane",),
) -> dict:
    return {
        "id": weapon_id,
        "display_name": name,
        "display_name_zh": name,
        "role": role,
        "propulsion": propulsion,
        "control": control,
        "guidance_kind": "none" if control == "unguided" else "tv",
        "planform": planform,
        "model_unsupported_reasons": [],
        "source_file": f"aces.vromfs.bin_u/gamedata/weapons/{weapon_id}.blkx",
        "source_sha256": "a" * 64,
        "source_pointers": {"mass": "/rocket/mass"},
        "reference_chains": [[f"weapons/{weapon_id}", f"presets/{weapon_id}"]],
        "source_section": "bomb" if role == "bomb" else "rocket",
        "trigger_groups": ["bombs" if role == "bomb" else "rockets"],
        "compatible_aircraft": list(aircraft),
        "mass_start_kg": 100.0,
        "mass_end_kg": 90.0,
        "caliber_m": 0.2,
        "cx_k": 0.2,
        "drag_cx": 0.04,
        "wing_area_mult": 1.0,
        "fins_aoa_horiz": 0.0,
        "fins_aoa_vert": 0.0,
        "time_life_s": 30.0,
        "start_speed_mps": 0.0,
        "min_distance_m": 0.0,
        "hard_max_distance_m": 20000.0,
        "stat_card_range_m": 0.0,
        "max_speed_mps": 500.0,
        "mach_max": 2.0,
        "motor_stages": [],
        "guidance": {"type": "none", "seeker": "none"},
    }


def _catalog_payload() -> dict:
    weapons = {
        "z_missile": _weapon(
            "z_missile",
            "Zulu Missile",
            role="aam",
            propulsion="powered",
            control="guided",
        ),
        "su_fab100": _weapon("su_fab100", "FAB-100"),
        "a_glide": _weapon("a_glide", "Alpha Glide", control="guided", planform="glide"),
    }
    weapons["z_missile"]["guidance_kind"] = "ir"
    weapons["z_missile"]["motor_stages"] = [
        {"duration_s": 2.0, "thrust_n": 3000.0, "mass_end_kg": 90.0}
    ]
    return {
        "schema_version": 1,
        "meta": {
            "generated_at_utc": "2026-07-10T00:00:00Z",
            "source_repo": "gszabi99/War-Thunder-Datamine",
            "source_version": "2.47.0.0",
            "source_commit": "b" * 40,
            "source_subdirs": ["weapons", "flightmodels", "lang"],
            "weapon_count": len(weapons),
            "aircraft_count": 2,
            "unresolved_references": [],
        },
        "weapons": weapons,
        "aircraft_weapons": {
            "test_plane": ["z_missile", "su_fab100", "a_glide"],
            "other_plane": ["su_fab100"],
        },
    }


def _write_catalog(tmp_path: Path, payload: dict | None = None) -> Path:
    path = tmp_path / "weapon_fire_control.json"
    path.write_text(json.dumps(payload or _catalog_payload()), encoding="utf-8")
    return path


def test_catalog_defaults_to_su_fab100_and_queries_stably(tmp_path: Path) -> None:
    catalog = WeaponCatalog(_write_catalog(tmp_path), SHARED_SCHEMA)

    assert catalog.selected_weapon_id == "su_fab100"
    assert catalog.selection_source == "manual"
    assert [item["id"] for item in catalog.search()] == [
        "a_glide",
        "su_fab100",
        "z_missile",
    ]
    assert [item["id"] for item in catalog.for_aircraft("TEST_PLANE")] == [
        "a_glide",
        "su_fab100",
        "z_missile",
    ]
    assert catalog.compatible("z_missile", "test_plane")
    assert not catalog.compatible("z_missile", "other_plane")
    assert [item["id"] for item in catalog.search("missile", role="aam")] == ["z_missile"]


def test_catalog_selection_rejects_unknown_id_and_source_without_mutation(tmp_path: Path) -> None:
    catalog = WeaponCatalog(_write_catalog(tmp_path), SHARED_SCHEMA)

    assert catalog.set_selected("z_missile", source="manual")
    assert not catalog.set_selected("missing", source="manual")
    assert not catalog.set_selected("su_fab100", source="weapon2")
    assert catalog.selected_weapon_id == "z_missile"
    assert catalog.selection_source == "manual"


def test_catalog_returns_defensive_record_copies(tmp_path: Path) -> None:
    catalog = WeaponCatalog(_write_catalog(tmp_path), SHARED_SCHEMA)

    first = catalog.get("su_fab100")
    assert first is not None
    first["display_name"] = "mutated"

    assert catalog.get("su_fab100")["display_name"] == "FAB-100"


def test_selection_snapshot_is_atomic_and_defensive(tmp_path: Path) -> None:
    catalog = WeaponCatalog(_write_catalog(tmp_path), SHARED_SCHEMA)
    catalog.set_selected("z_missile", source="manual")

    weapon_id, source, weapon = catalog.selection_snapshot()
    assert (weapon_id, source) == ("z_missile", "manual")
    assert weapon is not None
    weapon["display_name"] = "mutated"

    assert catalog.selected_weapon["display_name"] == "Zulu Missile"


def test_runtime_required_fields_come_from_shared_schema(tmp_path: Path) -> None:
    schema = json.loads(SHARED_SCHEMA.read_text(encoding="utf-8"))
    schema["required"] = [*schema["required"], "runtime_probe"]
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    with pytest.raises(WeaponCatalogError, match="runtime_probe"):
        WeaponCatalog(_write_catalog(tmp_path), schema_path)


def test_runtime_schema_const_is_enforced(tmp_path: Path) -> None:
    schema = json.loads(SHARED_SCHEMA.read_text(encoding="utf-8"))
    schema = copy.deepcopy(schema)
    schema["properties"]["schema_version"]["const"] = 999
    schema_path = tmp_path / "schema.json"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    with pytest.raises(WeaponCatalogError, match="schema const"):
        WeaponCatalog(_write_catalog(tmp_path), schema_path)
