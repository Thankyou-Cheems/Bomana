"""Regression coverage for transient 8111 endpoint jitter."""

import time
from unittest import mock

from bomana.config.settings import GameConfig
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
        zones=[Zone(id="zone-a", index=1, x=0.5, y=0.25, color="red")],
    )


def _empty_zone_map() -> MapObjData:
    return MapObjData(
        ok=True,
        player_aircraft_present=True,
        player_pos=(0.5, 0.5),
        player_dx=0.0,
        player_dy=-1.0,
        obj_count=1,
        zones=[],
    )


def _valid_map_info() -> MapInfo:
    return MapInfo(
        valid=True,
        map_min=[0.0, 0.0],
        map_max=[100000.0, 100000.0],
        fetch_time=time.time(),
    )


def _alive_game_with_last_good_data() -> GameLogic:
    game = GameLogic()
    now = time.time()
    with game._lock:
        game.state.phase = Phase.ALIVE
        game.state.current_life = LifeState(spawn_time=now - 30.0, life_index=1)
        game.state.last_player_present_ts = now
        game.state.last_tel = _stable_telemetry()
        game.state.last_map = _stable_map()
        game.state.map_info = _valid_map_info()
    game.tel = _StaticFetcher(TelemetryData(ind_ok=True, state_resp_ok=False, valid=True))
    game.map = _StaticFetcher(MapObjData(ok=False, error_kind="timeout"))
    return game


def test_transient_state_and_map_failure_keeps_navigation_snapshot() -> None:
    game = _alive_game_with_last_good_data()

    game.tick()
    snap = game.snapshot()

    assert not snap.api_down
    assert len(snap.zones) == 1
    assert snap.source_debug.tel_fallback_active
    assert snap.source_debug.map_fallback_active
    assert snap.source_debug.state_failure_streak == 1
    assert snap.source_debug.map_failure_streak == 1


def test_transient_map_fallback_skips_bombing_calculation() -> None:
    game = _alive_game_with_last_good_data()

    with mock.patch("bomana.core.logic.calculate_bomb_trajectory") as calc:
        game.tick()

    calc.assert_not_called()
    assert not game.snapshot().bombing_valid


def test_sustained_full_api_failure_enters_api_down() -> None:
    game = _alive_game_with_last_good_data()
    with game._lock:
        game.state.last_player_present_ts = time.time() - GameConfig.PLAYER_PRESENCE_GRACE_SEC - 1.0
        game.state.api_down_candidate_since = time.time() - GameConfig.API_DOWN_CONFIRM_SEC - 0.1
    game.tel = _StaticFetcher(TelemetryData(ind_ok=False, state_resp_ok=False))
    game.map = _StaticFetcher(MapObjData(ok=False, error_kind="timeout"))

    game.tick()
    snap = game.snapshot()

    assert snap.api_down
    assert snap.phase == Phase.IDLE
    assert not snap.source_debug.tel_fallback_active
    assert not snap.source_debug.map_fallback_active


def test_final_zone_disappearance_reports_destroyed() -> None:
    game = GameLogic()
    now = time.time()
    with game._lock:
        game.state.map_info = _valid_map_info()
        game._update_zone_navigation_locked(_stable_map(), _stable_telemetry(), now)
        game._update_zone_navigation_locked(_empty_zone_map(), _stable_telemetry(), now + 1.0)
    snap = game.snapshot()

    assert snap.zone_destroyed_alert
    assert snap.destroyed_zone_count == 1
    assert "1" in snap.destroyed_zone_text
