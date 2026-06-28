import time
import unittest

from bomana.config import BombConfig
from bomana.core.ballistics import calculate_bomb_trajectory
from bomana.core.logic import GameLogic
from bomana.core.state import LifeState, Phase, TelemetryData, Zone


class BombPredictionClassificationTests(unittest.TestCase):
    def test_guided_and_glide_bombs_are_not_listed_for_ccrp_prediction(self) -> None:
        guided_ids = [
            "us_gbu_39",
            "us_agm_154a1_jsow",
            "su_kab_500kr",
            "cn_ls_6_250",
            "de_hosbo_glide",
            "br_lizard_2",
            "de_fx1400",
            "jp_500lb_mk82_gcs_1",
        ]
        freefall = BombConfig.get_bomb_data("su_fab100")

        for bomb_id in guided_ids:
            with self.subTest(bomb_id=bomb_id):
                bomb = BombConfig.get_bomb_data(bomb_id)
                self.assertIsNotNone(bomb)
                self.assertFalse(bomb["prediction_supported"])
                self.assertEqual(bomb["prediction_kind"], "guided_glide")

        self.assertIsNotNone(freefall)
        self.assertTrue(freefall["prediction_supported"])
        self.assertEqual(freefall["prediction_kind"], "freefall")
        self.assertNotIn("us_gbu_39", BombConfig.search_bombs("gbu39", limit=20))
        self.assertIn(
            "us_gbu_39",
            BombConfig.search_bombs("gbu39", limit=20, include_unsupported=True),
        )

    def test_high_drag_bombs_keep_ccrp_prediction_profile(self) -> None:
        snakeye = BombConfig.get_bomb_data("us_500lb_mk_82_ldgp_snakeye")
        air_retarded = BombConfig.get_bomb_data("us_500lb_mk_82_ldgp_air")
        parachute = BombConfig.get_bomb_data("su_fab500sh")
        stealth_retarder = BombConfig.get_bomb_data("cn_gp_250_4")

        for bomb in (snakeye, air_retarded, parachute, stealth_retarder):
            self.assertIsNotNone(bomb)
            self.assertTrue(bomb["prediction_supported"])
            self.assertEqual(bomb["prediction_kind"], "high_drag")


class BombPredictionLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self._selected_bomb = BombConfig.selected_bomb

    def tearDown(self) -> None:
        BombConfig.selected_bomb = self._selected_bomb

    def _alive_game(
        self, *, bomb_id: str, mach: float | None = 0.82
    ) -> tuple[GameLogic, TelemetryData]:
        BombConfig.selected_bomb = bomb_id
        game = GameLogic()
        now = time.time()
        with game._lock:
            game.state.phase = Phase.ALIVE
            game.state.current_life = LifeState(spawn_time=now - 30.0, life_index=1)
            game.state.zone_nav.target_zone = Zone(
                id="zone-a",
                index=1,
                x=0.5,
                y=0.25,
                distance=0.12,
            )
            game.state.zone_nav.ground_speed = 220.0 / (100.0 * 1000.0)
        tel = TelemetryData(
            ind_ok=True,
            state_resp_ok=True,
            valid=True,
            type_name="test_plane",
            ias_kmh=760.0,
            tas_kmh=980.0,
            mach=mach,
            altitude_m=1200.0,
            fuel_kg=500.0,
            fuel0_kg=700.0,
        )
        return game, tel

    def test_guided_glide_bomb_blocks_prediction_before_integration(self) -> None:
        game, tel = self._alive_game(bomb_id="us_gbu_39")

        with game._lock:
            work = game._prepare_bombing_calculation_locked(tel, time.time(), player_present=True)

        self.assertIsNone(work)
        self.assertFalse(game.state.bombing_calc_valid)
        self.assertEqual(game.state.cached_bombing_unavailable_reason, "guided_glide")

    def test_mach_limit_blocks_freefall_prediction_before_integration(self) -> None:
        game, tel = self._alive_game(bomb_id="su_fab100", mach=1.01)

        with game._lock:
            work = game._prepare_bombing_calculation_locked(tel, time.time(), player_present=True)

        self.assertIsNone(work)
        self.assertFalse(game.state.bombing_calc_valid)
        self.assertEqual(game.state.cached_bombing_unavailable_reason, "release_mach_limit")

    def test_high_drag_bomb_still_enters_prediction_with_high_drag_profile(self) -> None:
        game, tel = self._alive_game(bomb_id="us_500lb_mk_82_ldgp_snakeye", mach=0.82)

        with game._lock:
            work = game._prepare_bombing_calculation_locked(tel, time.time(), player_present=True)

        self.assertIsNotNone(work)
        self.assertEqual(work["bomb_params"]["prediction_kind"], "high_drag")


def test_high_drag_brake_remains_active_after_deploy_window() -> None:
    high_drag_params = {
        "mass": 254.0,
        "caliber": 0.273,
        "drag_cx": 0.0257,
        "brakeTime": [0.1, 0.3],
        "brakeCxK": 110.0,
        "stab_enabled": True,
    }
    low_drag_params = dict(high_drag_params, stab_enabled=False)

    _time_hi, range_hi, _speed_hi = calculate_bomb_trajectory(
        release_alt_m=600.0,
        release_speed_ms=220.0,
        bomb_params=high_drag_params,
    )
    _time_lo, range_lo, _speed_lo = calculate_bomb_trajectory(
        release_alt_m=600.0,
        release_speed_ms=220.0,
        bomb_params=low_drag_params,
    )

    assert range_hi > 450.0
    assert range_hi < range_lo * 0.5


def test_high_drag_database_profile_keeps_release_cue_from_lagging_too_far() -> None:
    snakeye_params = BombConfig.get_bomb_physics_params("us_500lb_mk_82_ldgp_snakeye")

    _flight_time, bomb_range_m, _impact_speed = calculate_bomb_trajectory(
        release_alt_m=300.0,
        release_speed_ms=220.0,
        bomb_params=snakeye_params,
    )

    assert 450.0 <= bomb_range_m <= 650.0
