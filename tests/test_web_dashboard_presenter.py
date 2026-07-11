import json
import math
from dataclasses import replace
from pathlib import Path

from bomana.core.state import (
    AirfieldDisplayInfo,
    NavigationPointDisplayInfo,
    Phase,
    TacticalMapPoint,
    UISnapshot,
    ZoneDisplayInfo,
)
from bomana.web.snapshot import (
    DashboardCapabilities,
    DashboardSnapshotStore,
    PublishedDashboardSnapshot,
    build_dashboard_payload,
)
from tools.datamine_utils import load_json_schema, validate_json_schema

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = load_json_schema(ROOT / "docs/specs/schemas/web-dashboard-snapshot.schema.json")


def _snapshot() -> UISnapshot:
    return UISnapshot(
        phase=Phase.ALIVE,
        life_index=2,
        cycle=3,
        remaining_sec=512.4,
        progress=0.43,
        sortie_id=7,
        api_down=False,
        api_down_pending=False,
        on_ground=False,
        landed_flash=False,
        zones=[
            ZoneDisplayInfo(
                id="zone-1",
                distance_km=12.4,
                direction="前方",
                relative=3.5,
                is_target=True,
                ete_str="02:10",
            )
        ],
        friendly_airfield=AirfieldDisplayInfo(
            id="home",
            side="friendly",
            distance_km=28.0,
            direction="后方",
            relative=175.0,
            is_target=False,
            ete_str="05:00",
        ),
        interest_point=NavigationPointDisplayInfo(
            id="poi-1",
            name="烟柱",
            distance_km=4.2,
            direction="右前",
            relative=12.0,
            is_target=False,
            ete_str="00:42",
        ),
        traceback_point=NavigationPointDisplayInfo(
            id="trace-1",
            name="上次坠毁点",
            distance_km=7.8,
            direction="左侧",
            relative=-34.0,
            is_target=True,
            ete_str="01:20",
        ),
        player_heading=93.0,
        fuel_kg=1540,
        fuel_percent=76.0,
        fuel_rate_kg_min=31.2,
        fuel_rate_stable=True,
        fuel_remaining_time_min=49.3,
        altitude_m=5200,
        return_fuel_needed_kg=880,
        return_status="safe",
        friendly_distance_km=28,
        gear_pct=0,
        bombing_valid=True,
        bomb_name="GBU-39",
        bomb_flight_time=102,
        release_distance_m=88600,
        time_to_release=12,
        release_status="approaching",
        bombing_target_kind="zone",
        bombing_target_name="战区 #1",
        ground_speed_kmh=910,
        aircraft_type_name="f-15e",
        attitude_pitch_deg=4.2,
        attitude_roll_deg=-8.5,
        attitude_reliable=True,
        overspeed_level="safe",
        overspeed_ratio=0.72,
        overspeed_current_ias_kmh=820,
        overspeed_current_mach=1.14,
        overspeed_limit_kmh=1200,
        overspeed_limit_mach=2.5,
        overspeed_match=True,
        weapon_id="gbu-39",
        weapon_display_name="GBU-39/B",
        weapon_role="glide_bomb",
        weapon_model="foxthree_compatible",
        weapon_quality="experimental",
        weapon_solution_valid=True,
        weapon_status="within_experimental_reference",
        weapon_reason="foxthree_compatible_glide",
        weapon_target_kind="zone",
        weapon_target_name="战区 #1",
        weapon_target_distance_m=72000,
        weapon_min_range_m=0,
        weapon_max_range_m=88600,
        weapon_time_to_target_s=102,
        map_player_x=0.48,
        map_player_y=0.62,
        map_points=(
            TacticalMapPoint("zone-1", "zone", 0.61, 0.42, "战区 #1", "target", True),
            TacticalMapPoint("home", "airfield", 0.2, 0.8, "友方机场", "friendly", False, True),
            TacticalMapPoint("poi-1", "poi", 0.55, 0.52, "烟柱", "poi"),
            TacticalMapPoint("trace-1", "traceback", 0.35, 0.68, "上次坠毁点", "traceback"),
            TacticalMapPoint("hostile-1", "hostile_aircraft", 0.8, 0.2, "敌机", "enemy"),
        ),
    )


def _published(*, capabilities: DashboardCapabilities | None = None) -> PublishedDashboardSnapshot:
    return PublishedDashboardSnapshot(
        sequence=12,
        generated_at=1234.5,
        snapshot=_snapshot(),
        checklist_items=("启动发动机", "收起落架"),
        capabilities=capabilities or DashboardCapabilities(True, True, True, True),
    )


def test_dashboard_payload_matches_schema_and_filters_hostile_contacts() -> None:
    payload = build_dashboard_payload(_published())

    validate_json_schema(payload, SCHEMA, path="dashboard")
    assert payload["schema_version"] == 1
    assert payload["map"]["player"] == {"x": 0.48, "y": 0.62, "heading_deg": 93.0}
    assert {point["kind"] for point in payload["map"]["points"]} == {
        "zone",
        "airfield",
        "poi",
        "traceback",
    }
    assert "hostile-1" not in json.dumps(payload, ensure_ascii=False)
    assert "source_debug" not in payload
    assert "perf_debug" not in payload


def test_dashboard_payload_normalizes_non_finite_values() -> None:
    snapshot = replace(_snapshot(), altitude_m=math.nan, ground_speed_kmh=math.inf)
    published = PublishedDashboardSnapshot(
        sequence=1,
        generated_at=math.nan,
        snapshot=snapshot,
        checklist_items=(),
        capabilities=DashboardCapabilities(True, True, True, True),
    )

    payload = build_dashboard_payload(published)

    validate_json_schema(payload, SCHEMA, path="dashboard")
    assert payload["generated_at"] == 0
    assert payload["flight"]["altitude_m"] == 0
    assert payload["flight"]["ground_speed_kmh"] == 0
    json.dumps(payload, allow_nan=False)


def test_disabled_capabilities_do_not_recreate_build_disabled_features() -> None:
    payload = build_dashboard_payload(
        _published(capabilities=DashboardCapabilities(False, False, False, False))
    )

    assert payload["navigation"]["zones"] == []
    assert payload["navigation"]["airfields"] == []
    assert payload["navigation"]["poi"] is None
    assert payload["navigation"]["traceback"] is None
    assert payload["map"]["points"] == []
    assert payload["fuel"]["return_status"] == "unavailable"
    assert payload["weapon"]["reason"] == "build_disabled"
    assert payload["bombing"]["enabled"] is False
    assert payload["checklist"]["items"] == []


def test_snapshot_store_copies_checklist_and_advances_sequence() -> None:
    wall_times = iter((10.0, 11.0))
    store = DashboardSnapshotStore(wall_time=lambda: next(wall_times))
    items = ["启动发动机"]

    store.publish(_snapshot(), items)
    items.append("不应进入已发布快照")
    first = store.read()
    store.publish(_snapshot(), items)
    second = store.read()

    assert first is not None and second is not None
    assert first.sequence == 1
    assert first.generated_at == 10.0
    assert first.checklist_items == ("启动发动机",)
    assert second.sequence == 2
    assert second.checklist_items == ("启动发动机", "不应进入已发布快照")
