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
