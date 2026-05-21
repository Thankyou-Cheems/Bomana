"""Regression coverage for transient 8111 endpoint jitter."""

import time
import unittest
from unittest import mock

from bomana.config import GameConfig
from bomana.core.logic import GameLogic
from bomana.core.state import LifeState, MapInfo, MapObjData, Phase, TelemetryData, Zone


class _StaticFetcher:
    def __init__(self, value):
        self.value = value

    def fetch(self, _budget):
        return self.value


def _stable_telemetry() -> TelemetryData:
    return TelemetryData(
        ind_ok=True,
        state_resp_ok=True,
        valid=True,
        type_name="test_plane",
        ias_kmh=320.0,
        altitude_m=1000.0,
        fuel_kg=100.0,
        fuel0_kg=120.0,
        compass=0.0,
    )


def _stable_map() -> MapObjData:
    return MapObjData(
        ok=True,
        player_aircraft_present=True,
        player_pos=(0.5, 0.5),
        player_dx=0.0,
        player_dy=-1.0,
        obj_count=2,
        zones=[
            Zone(id="zone-a", index=1, x=0.5, y=0.25, color="red"),
        ],
    )


def _valid_map_info() -> MapInfo:
    now = time.time()
    return MapInfo(
        valid=True,
        map_min=[0.0, 0.0],
        map_max=[100000.0, 100000.0],
        fetch_time=now,
    )


class GameLogic8111StabilityTests(unittest.TestCase):
    def _alive_game_with_last_good_data(self) -> GameLogic:
        game = GameLogic()
        now = time.time()
        tel = _stable_telemetry()
        mp = _stable_map()
        with game._lock:
            game.state.phase = Phase.ALIVE
            game.state.current_life = LifeState(spawn_time=now - 30.0, life_index=1)
            game.state.last_player_present_ts = now
            game.state.last_tel = tel
            game.state.last_map = mp
            game.state.map_info = _valid_map_info()
        game.tel = _StaticFetcher(TelemetryData(ind_ok=True, state_resp_ok=False, valid=True))
        game.map = _StaticFetcher(MapObjData(ok=False, error_kind="timeout"))
        return game

    def test_transient_state_and_map_failure_keeps_navigation_snapshot(self):
        game = self._alive_game_with_last_good_data()

        game.tick()
        snap = game.snapshot()

        self.assertFalse(snap.api_down)
        self.assertEqual(1, len(snap.zones))
        self.assertTrue(snap.source_debug.tel_fallback_active)
        self.assertTrue(snap.source_debug.map_fallback_active)
        self.assertEqual(1, snap.source_debug.state_failure_streak)
        self.assertEqual(1, snap.source_debug.map_failure_streak)

    def test_transient_map_fallback_skips_bombing_calculation(self):
        game = self._alive_game_with_last_good_data()

        with mock.patch("bomana.core.logic.calculate_bomb_trajectory") as calc:
            game.tick()

        calc.assert_not_called()
        self.assertFalse(game.snapshot().bombing_valid)

    def test_sustained_full_api_failure_enters_api_down(self):
        game = self._alive_game_with_last_good_data()
        old = time.time() - GameConfig.PLAYER_PRESENCE_GRACE_SEC - 1.0
        with game._lock:
            game.state.last_player_present_ts = old
            game.state.api_down_candidate_since = (
                time.time() - GameConfig.API_DOWN_CONFIRM_SEC - 0.1
            )
        game.tel = _StaticFetcher(TelemetryData(ind_ok=False, state_resp_ok=False))
        game.map = _StaticFetcher(MapObjData(ok=False, error_kind="timeout"))

        game.tick()
        snap = game.snapshot()

        self.assertTrue(snap.api_down)
        self.assertEqual(Phase.IDLE, snap.phase)
        self.assertFalse(snap.source_debug.tel_fallback_active)
        self.assertFalse(snap.source_debug.map_fallback_active)


if __name__ == "__main__":
    unittest.main()
