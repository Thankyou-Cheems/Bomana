from types import SimpleNamespace

from bomana.core.state import Phase
from bomana.ui.hud_presenter import build_hud_target_model


def _zone(zone_id: str, relative: float, distance: float, *, target: bool = False):
    return SimpleNamespace(
        id=zone_id,
        relative=relative,
        distance_km=distance,
        is_target=target,
    )


def test_hud_target_model_prefers_core_target_and_sorts_secondaries() -> None:
    snap = SimpleNamespace(
        phase=Phase.ALIVE,
        api_down=False,
        api_down_pending=False,
        zones=[
            _zone("far", 24.0, 12.0),
            _zone("target", -9.0, 8.0, target=True),
            _zone("near", 3.0, 5.0),
        ],
        attitude_pitch_deg=2.5,
        attitude_roll_deg=-4.0,
        hud_attitude_fallback=False,
        player_heading=271.0,
        altitude_m=1500.0,
    )

    model = build_hud_target_model(snap, secondary_limit=1)

    assert model.has_target is True
    assert model.relative == -9.0
    assert model.distance == 8.0
    assert model.pitch == 2.5
    assert model.roll == -4.0
    assert model.fallback is False
    assert model.heading == 271.0
    assert model.altitude == 1500.0
    assert model.secondary_targets == [{"relative": 3.0, "distance": 5.0, "label": ""}]


def test_hud_target_model_falls_back_to_nearest_relative_zone() -> None:
    snap = SimpleNamespace(
        phase=Phase.ALIVE,
        api_down=False,
        api_down_pending=False,
        zones=[_zone("left", -35.0, 9.0), _zone("center", 8.0, 10.0)],
    )

    model = build_hud_target_model(snap, secondary_limit=2)

    assert model.has_target is True
    assert model.relative == 8.0
    assert model.secondary_targets == [{"relative": -35.0, "distance": 9.0, "label": ""}]


def test_hud_target_model_reports_standby_reason() -> None:
    no_target = SimpleNamespace(
        phase=Phase.ALIVE,
        api_down=False,
        api_down_pending=False,
        zones=[],
    )
    api_down = SimpleNamespace(
        phase=Phase.ALIVE,
        api_down=True,
        api_down_pending=False,
        zones=[],
    )
    pending = SimpleNamespace(
        phase=Phase.ALIVE,
        api_down=False,
        api_down_pending=True,
        zones=[],
    )
    hangar = SimpleNamespace(
        phase=Phase.HANGAR,
        api_down=False,
        api_down_pending=False,
        zones=[],
    )

    assert build_hud_target_model(no_target, secondary_limit=2).standby_text == "NO TARGET"
    assert build_hud_target_model(api_down, secondary_limit=2).standby_text == "8111 DELAY"
    assert build_hud_target_model(pending, secondary_limit=2).standby_text == "8111 PENDING"
    assert build_hud_target_model(hangar, secondary_limit=2).standby_text == "HUD STANDBY"
