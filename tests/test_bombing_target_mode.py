from bomana.config.settings import BombConfig
from bomana.core.logic import GameLogic
from bomana.core.state import BombingTarget


def test_target_mode_switch_invalidates_previous_solution_atomically() -> None:
    previous = BombConfig.target_mode
    game = GameLogic()
    try:
        BombConfig.target_mode = "zone"
        with game._lock:
            game.state.zone_nav.bombing_target = BombingTarget(
                id="zone-a",
                kind="zone",
                name="战区 #1",
                distance=0.1,
            )
            game.state.bombing_calc_valid = True
            game.state.cached_bombing_target_kind = "zone"
            game.state.cached_bombing_target_name = "战区 #1"

        assert game.set_bombing_target_mode("poi") is True

        with game._lock:
            assert game.state.zone_nav.bombing_target is None
            assert game.state.bombing_calc_valid is False
            assert game.state.cached_bombing_target_kind == ""
            assert game.state.cached_bombing_target_name == ""
            assert game.state.cached_bombing_unavailable_reason == "target_mode_changed"
        assert BombConfig.target_mode == "poi"
    finally:
        BombConfig.target_mode = previous


def test_target_mode_rejects_implicit_auto_mode() -> None:
    previous = BombConfig.target_mode
    game = GameLogic()
    try:
        BombConfig.target_mode = "zone"
        assert game.set_bombing_target_mode("auto") is False
        assert BombConfig.target_mode == "zone"
    finally:
        BombConfig.target_mode = previous
