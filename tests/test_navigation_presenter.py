from types import SimpleNamespace

from bomana.ui.navigation_presenter import build_navigation_tape_model


def test_enemy_airfield_marker_respects_core_target_selection() -> None:
    snap = SimpleNamespace(
        zones=[],
        friendly_airfield=None,
        enemy_airfields=[
            SimpleNamespace(relative=10.0, distance_km=12.0, is_target=False),
            SimpleNamespace(relative=15.0, distance_km=8.0, is_target=True, ete_str=""),
        ],
        zone_destroyed_alert=False,
    )

    model = build_navigation_tape_model(snap)

    enemy_targets = [target for target in model.targets if target["type"] == "enemy"]
    assert enemy_targets[0]["is_target"] is False
    assert enemy_targets[1]["is_target"] is True
    assert len(model.active_targets_info) == 1
    assert model.active_targets_info[0]["type"] == "enemy"


def test_interest_point_renders_as_non_primary_heading_marker() -> None:
    poi = SimpleNamespace(
        id="poi-1",
        name="补给点",
        distance_km=4.25,
        direction="右转 12°",
        relative=12.0,
        is_target=True,
        ete_str="00:34",
        cdi_indicator="偏右",
        cdi_color="#f2c14e",
    )
    zone = SimpleNamespace(
        id="zone-1",
        relative=-3.0,
        distance_km=7.0,
        is_target=True,
        ete_str="01:10",
    )
    snap = SimpleNamespace(
        interest_point=poi,
        zones=[zone],
        friendly_airfield=SimpleNamespace(relative=18.0, distance_km=20.0, ete_str="02:00"),
        enemy_airfields=[],
        zone_destroyed_alert=False,
    )

    model = build_navigation_tape_model(snap)

    poi_targets = [target for target in model.targets if target["type"] == "poi"]
    zone_targets = [target for target in model.targets if target["type"] == "zone"]
    assert poi_targets == [
        {
            "type": "poi",
            "relative": 12.0,
            "distance_km": 4.25,
            "is_primary": False,
            "is_target": True,
            "name": "补给点",
        }
    ]
    assert zone_targets[0]["is_primary"] is True
    assert zone_targets[0]["is_target"] is True
    assert model.primary_zone is zone
    assert model.primary_target is zone
    assert model.primary_target_info is not None
    assert model.primary_target_info["type"] == "zone"
    assert model.active_targets_info[0]["type"] == "zone"
    assert "poi" not in [info["type"] for info in model.active_targets_info]


def test_traceback_renders_without_replacing_primary_zone_or_active_rows() -> None:
    traceback = SimpleNamespace(
        id="traceback-life-1",
        name="上次坠毁点",
        distance_km=6.5,
        relative=22.0,
        is_target=True,
    )
    zone = SimpleNamespace(
        id="zone-1",
        relative=-4.0,
        distance_km=8.0,
        is_target=True,
        ete_str="01:20",
    )
    snap = SimpleNamespace(
        traceback_point=traceback,
        interest_point=None,
        zones=[zone],
        friendly_airfield=None,
        enemy_airfields=[],
        zone_destroyed_alert=False,
    )

    model = build_navigation_tape_model(snap)

    assert [target for target in model.targets if target["type"] == "traceback"] == [
        {
            "type": "traceback",
            "relative": 22.0,
            "distance_km": 6.5,
            "is_primary": False,
            "is_target": True,
            "name": "上次坠毁点",
        }
    ]
    assert model.primary_zone is zone
    assert model.primary_target is zone
    assert model.primary_target_info is not None
    assert model.primary_target_info["type"] == "zone"
    assert [info["type"] for info in model.active_targets_info] == ["zone"]


def test_destroyed_markers_use_snapshot_owned_display_data() -> None:
    snap = SimpleNamespace(
        zones=[],
        friendly_airfield=None,
        enemy_airfields=[],
        zone_destroyed_alert=True,
    )
    destroyed = [SimpleNamespace(relative=-7.0, distance_km=4.5)]

    model = build_navigation_tape_model(snap, destroyed_zones=destroyed)

    destroyed_targets = [target for target in model.targets if target["type"] == "destroyed"]
    assert destroyed_targets == [
        {
            "type": "destroyed",
            "relative": -7.0,
            "distance_km": 4.5,
            "is_primary": False,
        }
    ]
