import math
import time
import unittest

from bomana.config.settings import BombConfig
from bomana.core import ccrp_scheduler
from bomana.core.logic import GameLogic
from bomana.core.offline_ballistics_model import (
    OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID,
)
from bomana.core.state import (
    BombingTarget,
    LifeState,
    MapInfo,
    Phase,
    TelemetryData,
    Zone,
)


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

    def test_high_drag_bombs_are_hidden_without_a_validated_offline_model(self) -> None:
        bomb_id = "us_500lb_mk_82_ldgp_snakeye"
        snakeye = BombConfig.get_bomb_data(bomb_id)

        self.assertIsNotNone(snakeye)
        self.assertFalse(snakeye["prediction_supported"])
        self.assertEqual(snakeye["prediction_kind"], "high_drag")
        self.assertNotIn(bomb_id, BombConfig.search_bombs("snakeye"))
        self.assertIn(bomb_id, BombConfig.search_bombs("snakeye", include_unsupported=True))

    def test_catalog_alias_resolves_matching_ccrp_physics(self) -> None:
        bomb = BombConfig.get_bomb_data("uk_1000lbs_mc_mk1_mk2_bomb")

        self.assertIsNotNone(bomb)
        self.assertEqual(bomb["mass"], 463.1)
        self.assertEqual(
            BombConfig.get_bomb_catalog_id("uk_1000lbs_mc_mk1_mk2_bomb"),
            "uk_1000lbs_mc_mk1_mk2",
        )
        self.assertEqual(
            BombConfig.get_bomb_catalog_id("uk_1000lbs_mc_mk1_mk2"),
            "uk_1000lbs_mc_mk1_mk2",
        )


class BombPredictionLogicTests(unittest.TestCase):
    def setUp(self) -> None:
        self._selected_bomb = BombConfig.selected_bomb

    def tearDown(self) -> None:
        BombConfig.selected_bomb = self._selected_bomb

    def _alive_game(
        self,
        *,
        bomb_id: str,
        mach: float | None = 0.82,
    ) -> tuple[GameLogic, TelemetryData]:
        BombConfig.selected_bomb = bomb_id
        game = GameLogic()
        now = time.time()
        with game._lock:
            game.state.phase = Phase.ALIVE
            game.state.current_life = LifeState(spawn_time=now - 30.0, life_index=1)
            game.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[100_000.0, 100_000.0],
            )
            game.state.zone_nav.target_zone = Zone(
                id="zone-a",
                index=1,
                x=0.5,
                y=0.46,
                distance=0.04,
            )
            nav = game.state.zone_nav
            nav.bombing_target = BombingTarget(
                id="zone-a",
                kind="zone",
                name="战区 #1",
                distance=0.04,
                relative=0.0,
                x=0.5,
                y=0.46,
            )
            nav.release_track_valid = True
            nav.release_world_x_m = 50_000.0
            nav.release_world_z_m = 50_000.0
            nav.release_velocity_x_ms = 0.0
            nav.release_velocity_z_ms = 220.0
            nav.release_ground_speed_ms = 220.0
            nav.release_track_heading_deg = 0.0
            nav.ground_speed = 220.0 / 100_000.0
        tel = TelemetryData(
            ind_ok=True,
            state_resp_ok=True,
            valid=True,
            type_name="test_plane",
            ias_kmh=760.0,
            tas_kmh=980.0,
            mach=mach,
            aoa_deg=3.0,
            altitude_m=1200.0,
            fuel_kg=500.0,
            fuel0_kg=700.0,
        )
        return game, tel

    @staticmethod
    def _prepare(
        game: GameLogic,
        tel: TelemetryData,
        **kwargs,
    ):
        now = kwargs.pop("now", time.time())
        return ccrp_scheduler.prepare_bombing_calculation(
            game.state,
            tel,
            now,
            player_present=True,
            target_alt_m=kwargs.pop("target_alt_m", 0.0),
            atmosphere_altitude_datum_m=kwargs.pop("atmosphere_altitude_datum_m", 60.0),
            terrain_height_at_world=kwargs.pop(
                "terrain_height_at_world",
                lambda _world_x, _world_z: 0.0,
            ),
            **kwargs,
        )

    def test_release_state_is_aligned_to_one_solution_time(self) -> None:
        game, tel = self._alive_game(bomb_id="uk_1000lbs_gp")
        tel.state_sample_time = 100.0
        tel.vy_ms = 20.0
        with game._lock:
            game.state.zone_nav.release_track_sample_time = 100.04
            work = self._prepare(game, tel, now=100.10)

        self.assertIsNotNone(work)
        assert work is not None
        self.assertAlmostEqual(work["state_age_s"], 0.10)
        self.assertAlmostEqual(work["map_age_s"], 0.06)
        self.assertAlmostEqual(work["endpoint_skew_s"], 0.04)
        self.assertAlmostEqual(work["altitude_projection_m"], 2.0)
        self.assertAlmostEqual(work["altitude_m"], 1202.0)
        self.assertEqual(work["release_state_source"], "8111_basic_release_state")
        self.assertFalse(work["precision_gate_available"])

    def test_complete_high_dynamics_8111_state_fails_closed(self) -> None:
        game, tel = self._alive_game(bomb_id="uk_1000lbs_gp")
        tel.aoa_deg = 4.0
        tel.aos_deg = 2.0
        tel.normal_load_factor = 1.1
        tel.angular_velocity_x = 5.0
        tel.attitude_roll_deg = 65.0
        tel.attitude_roll_present = True

        with game._lock:
            game.state.zone_nav.release_body_heading_rate_deg_s = 18.0
            game.state.zone_nav.release_body_heading_rate_available = True
            work = self._prepare(game, tel)

        self.assertIsNone(work)
        self.assertEqual(
            game.state.cached_bombing_unavailable_reason,
            "release_dynamics_unresolved",
        )
        self.assertTrue(game.state.cached_bombing_precision_gate_available)
        self.assertGreater(game.state.cached_bombing_maneuver_score, 1.0)

    def test_laterally_stable_dive_and_pull_up_keep_ccrp_available(self) -> None:
        cases = (
            ("steep_dive", -120.0, -58.0, 24.0, 0.35, -100.0),
            ("hard_pull", 80.0, 34.0, 18.0, 4.2, 100.0),
        )
        for label, vy_ms, pitch_deg, aoa_deg, load_factor, elevator_pct in cases:
            with self.subTest(label=label):
                game, tel = self._alive_game(bomb_id="uk_1000lbs_gp")
                tel.vy_ms = vy_ms
                tel.aoa_deg = aoa_deg
                tel.aos_deg = 0.2
                tel.normal_load_factor = load_factor
                tel.angular_velocity_x = 2.0
                tel.attitude_pitch_deg = pitch_deg
                tel.attitude_pitch_present = True
                tel.attitude_roll_deg = 3.0
                tel.attitude_roll_present = True
                tel.elevator_pct = elevator_pct
                tel.vertical_acceleration_ms2 = 35.0 if label == "hard_pull" else -12.0

                with game._lock:
                    work = self._prepare(game, tel)

                self.assertIsNotNone(work)
                assert work is not None
                self.assertEqual(work["release_state_source"], "8111_dynamics_gated")
                self.assertTrue(work["precision_gate_available"])
                self.assertLess(work["maneuver_score"], 1.0)

    def test_stale_future_or_skewed_8111_frames_fail_closed(self) -> None:
        cases = (
            ("stale_state", 99.84, 99.95),
            ("stale_map", 99.95, 99.84),
            ("endpoint_skew", 100.004, 99.851),
            ("future_state", 100.006, 99.95),
        )
        for label, state_sample_time, map_sample_time in cases:
            with self.subTest(label=label):
                game, tel = self._alive_game(bomb_id="uk_1000lbs_gp")
                tel.state_sample_time = state_sample_time
                with game._lock:
                    game.state.zone_nav.release_track_sample_time = map_sample_time
                    work = self._prepare(game, tel, now=100.0)

                self.assertIsNone(work)
                self.assertEqual(
                    game.state.cached_bombing_unavailable_reason,
                    "time_alignment_unavailable",
                )

    def test_guided_glide_bomb_blocks_prediction_before_integration(self) -> None:
        game, tel = self._alive_game(bomb_id="us_gbu_39")

        with game._lock:
            work = self._prepare(game, tel)

        self.assertIsNone(work)
        self.assertEqual(game.state.cached_bombing_unavailable_reason, "guided_or_glide")

    def test_supersonic_release_uses_versioned_mach_curve_instead_of_old_limit(self) -> None:
        game, tel = self._alive_game(bomb_id="su_fab100", mach=1.15)

        with game._lock:
            work = self._prepare(game, tel)

        self.assertIsNotNone(work)

    def test_high_drag_bomb_is_rejected_without_old_profile(self) -> None:
        game, tel = self._alive_game(bomb_id="us_500lb_mk_82_ldgp_snakeye")

        with game._lock:
            work = self._prepare(game, tel)

        self.assertIsNone(work)
        self.assertEqual(
            game.state.cached_bombing_unavailable_reason,
            "offline_high_drag_unavailable",
        )

    def test_poi_bombing_target_uses_track_geometry(self) -> None:
        game, tel = self._alive_game(bomb_id="su_fab100")

        with game._lock:
            game.state.zone_nav.bombing_target = BombingTarget(
                id="poi-smoke",
                kind="poi",
                name="Smoke",
                distance=0.04,
                relative=0.0,
                x=0.5,
                y=0.46,
            )
            work = self._prepare(game, tel)

        self.assertIsNotNone(work)
        assert work is not None
        self.assertEqual(work["target_kind"], "poi")
        self.assertEqual(work["target_name"], "Smoke")
        self.assertAlmostEqual(work["target_distance_m"], 4000.0)
        self.assertAlmostEqual(work["target_along_track_m"], 4000.0)
        self.assertAlmostEqual(work["target_cross_track_m"], 0.0)

    def test_explicit_selected_weapon_physics_does_not_reuse_global_bomb(self) -> None:
        game, tel = self._alive_game(bomb_id="su_fab100")
        selected_params = BombConfig.get_bomb_physics_params("uk_1000lbs_mc_mk1_mk2_bomb")

        with game._lock:
            work = self._prepare(game, tel, bomb_params=selected_params)

        self.assertIsNotNone(work)
        self.assertEqual(work["bomb_params"]["mass"], 463.1)

    def test_release_tas_and_vertical_speed_are_resolved_separately(self) -> None:
        game, tel = self._alive_game(bomb_id="uk_1000lbs_gp")
        tel.vy_ms = -42.5

        with game._lock:
            work = self._prepare(game, tel)

        self.assertIsNotNone(work)
        assert work is not None
        self.assertEqual(work["initial_vz_ms"], -42.5)
        self.assertAlmostEqual(
            work["horizontal_air_speed_ms"],
            math.sqrt((980.0 / 3.6) ** 2 - 42.5**2),
        )
        self.assertEqual(
            work["trajectory_model_id"],
            OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID,
        )
        self.assertEqual(
            work["trajectory_model_quality"],
            "offline_rigidbody_8111_projection",
        )

    def test_exact_mk82_selection_reaches_generic_rigidbody_runtime_model(self) -> None:
        game, tel = self._alive_game(bomb_id="us_500lb_mk_82_ldgp")

        with game._lock:
            work = self._prepare(game, tel)

        self.assertIsNotNone(work)
        assert work is not None
        self.assertEqual(
            work["trajectory_model_id"],
            OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID,
        )
        self.assertEqual(
            work["trajectory_model_quality"],
            "offline_rigidbody_8111_projection",
        )
        self.assertEqual(work["bomb_params"]["weapon_id"], "us_500lb_mk_82_ldgp")

    def test_exact_500mc_selection_forwards_aoa_to_rigidbody_model(self) -> None:
        game, tel = self._alive_game(bomb_id="uk_500lb_mc_mk1_mk4_long_tail")
        tel.aoa_deg = 3.1

        with game._lock:
            work = self._prepare(game, tel)

        self.assertIsNotNone(work)
        assert work is not None
        self.assertEqual(
            work["trajectory_model_id"],
            OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID,
        )
        self.assertEqual(work["initial_aoa_deg"], 3.1)

    def test_exact_500mc_fails_closed_when_8111_aoa_is_missing(self) -> None:
        game, tel = self._alive_game(bomb_id="uk_500lb_mc_mk1_mk4_long_tail")
        tel.aoa_deg = None

        with game._lock:
            work = self._prepare(game, tel)

        self.assertIsNone(work)
        self.assertEqual(
            game.state.cached_bombing_unavailable_reason,
            "release_attitude_unavailable",
        )

    def test_generic_freefall_fails_closed_when_8111_aoa_is_missing(self) -> None:
        game, tel = self._alive_game(bomb_id="uk_1000lbs_gp")
        tel.aoa_deg = None

        with game._lock:
            work = self._prepare(game, tel)

        self.assertIsNone(work)
        self.assertEqual(
            game.state.cached_bombing_unavailable_reason,
            "release_attitude_unavailable",
        )

    def test_nonfinite_release_vertical_speed_is_not_forwarded(self) -> None:
        game, tel = self._alive_game(bomb_id="uk_1000lbs_gp")
        tel.vy_ms = float("nan")

        with game._lock:
            work = self._prepare(game, tel)

        self.assertIsNotNone(work)
        assert work is not None
        self.assertIsNone(work["initial_vz_ms"])
        self.assertAlmostEqual(work["horizontal_air_speed_ms"], 980.0 / 3.6)

    def test_missing_ias_tas_density_pair_uses_standard_density(self) -> None:
        game, tel = self._alive_game(bomb_id="uk_1000lbs_gp")
        tel.ias_kmh = 760.0
        tel.tas_kmh = 980.0
        with game._lock:
            valid = self._prepare(game, tel)
        assert valid is not None
        self.assertEqual(valid["air_density_source"], "8111_ias_tas_filtered")

        tel.ias_kmh = 99.0
        tel.vy_ms = 3.0
        with game._lock:
            cached = self._prepare(game, tel)
        assert cached is not None
        self.assertEqual(cached["air_density_sea_level"], valid["air_density_sea_level"])
        self.assertEqual(cached["air_density_source"], "8111_ias_tas_cached")

        with game._lock:
            game.state.atmosphere_density_samples.clear()
            fallback = self._prepare(game, tel)
        assert fallback is not None
        self.assertEqual(fallback["air_density_sea_level"], 1.225)
        self.assertEqual(fallback["air_density_source"], "standard_fallback")

    def test_missing_heightmap_fails_closed(self) -> None:
        game, tel = self._alive_game(bomb_id="uk_1000lbs_gp")

        with game._lock:
            work = self._prepare(game, tel, terrain_height_at_world=None)

        self.assertIsNone(work)
        self.assertEqual(game.state.cached_bombing_unavailable_reason, "terrain_unavailable")

    def test_cross_track_error_over_100m_does_not_emit_release_window(self) -> None:
        game, tel = self._alive_game(bomb_id="uk_1000lbs_gp")
        with game._lock:
            game.state.zone_nav.bombing_target = BombingTarget(
                id="zone-a",
                kind="zone",
                name="战区 #1",
                distance=0.04,
                relative=0.0,
                x=0.502,
                y=0.46,
            )
            work = self._prepare(game, tel)

        self.assertIsNone(work)
        self.assertEqual(game.state.cached_bombing_unavailable_reason, "off_axis")
        self.assertEqual(len(game.state.atmosphere_density_samples), 1)

    def test_compute_forwards_height_profile_and_uses_along_track_timing(self) -> None:
        captured: dict = {}

        def trajectory_func(**kwargs):
            captured.update(kwargs)
            assert kwargs["terrain_altitude_at_range"](500.0) == 123.0
            return 5.0, 800.0, 200.0

        result = ccrp_scheduler.compute_bombing_calculation(
            {
                "altitude_m": 1200.0,
                "horizontal_air_speed_ms": 260.0,
                "ground_speed_ms": 220.0,
                "initial_vz_ms": -37.0,
                "target_distance_m": 4005.0,
                "target_along_track_m": 4000.0,
                "target_cross_track_m": 50.0,
                "target_kind": "zone",
                "target_name": "Zone",
                "target_alt_m": 123.0,
                "atmosphere_altitude_datum_m": 60.0,
                "release_world_x_m": 1000.0,
                "release_world_z_m": 2000.0,
                "release_direction_x": 0.0,
                "release_direction_z": 1.0,
                "terrain_height_at_world": lambda _x, _z: 123.0,
                "bomb_params": BombConfig.get_bomb_physics_params("uk_1000lbs_gp"),
                "trajectory_model_id": OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID,
                "trajectory_model_category": "freefall",
                "trajectory_model_quality": "offline_rigidbody_8111_projection",
            },
            trajectory_func=trajectory_func,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(captured["release_speed_ms"], 260.0)
        self.assertEqual(captured["initial_vz_ms"], -37.0)
        self.assertEqual(captured["atmosphere_altitude_datum_m"], 60.0)
        self.assertAlmostEqual(result["release_distance_m"], 3200.0)
        self.assertEqual(result["target_distance_m"], 4005.0)
        self.assertEqual(
            result["trajectory_model_id"],
            OFFLINE_RIGIDBODY_PROJECTION_MODEL_ID,
        )

    def test_terrain_target_altitude_is_forwarded_and_cached(self) -> None:
        game, tel = self._alive_game(bomb_id="uk_1000lbs_gp")

        with game._lock:
            work = self._prepare(
                game,
                tel,
                target_alt_m=345.25,
                terrain_height_at_world=lambda _x, _z: 345.25,
            )

        self.assertIsNotNone(work)
        assert work is not None
        result = ccrp_scheduler.compute_bombing_calculation(work)
        self.assertIsNotNone(result)
        assert result is not None
        ccrp_scheduler.apply_bombing_calculation(game.state, result)

        self.assertEqual(work["altitude_datum_source"], "terrain_pack")
        self.assertEqual(work["air_density_source"], "8111_ias_tas_filtered")
        self.assertEqual(game.state.cached_target_altitude_m, 345.25)
        self.assertEqual(game.state.cached_target_altitude_source, "terrain")
        self.assertEqual(game.state.cached_atmosphere_altitude_datum_m, 60.0)
        self.assertEqual(game.state.cached_altitude_datum_source, "terrain_pack")
        self.assertEqual(game.state.cached_atmosphere_model_id, "dagor_gamephys_atmosphere_v2")
