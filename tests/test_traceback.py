# enforces: docs/specs/runtime-8111-boundary.md R8111-17..R8111-18 R8111-20

import pytest

from bomana.config.settings import GameConfig
from bomana.core import lifecycle
from bomana.core.logic import GameLogic
from bomana.core.state import (
    GameState,
    LifeState,
    MapInfo,
    MapObjData,
    Phase,
    TelemetryData,
    TracebackSite,
)


class _FakeClock:
    def __init__(self, now: float):
        self.now = now

    def time(self) -> float:
        return self.now


class _StaticFetcher:
    def __init__(self, value):
        self.value = value

    def fetch(self, _budget):
        return self.value


def _telemetry() -> TelemetryData:
    return TelemetryData(
        ind_ok=True,
        state_resp_ok=True,
        valid=True,
        type_name="traceback_test_plane",
        ias_kmh=500.0,
        altitude_m=1200.0,
        fuel_kg=100.0,
        fuel0_kg=120.0,
        compass=90.0,
        compass_present=True,
    )


def _player_map(x: float = 0.25, y: float = 0.42) -> MapObjData:
    return MapObjData(
        ok=True,
        player_aircraft_present=True,
        player_pos=(x, y),
        player_dx=1.0,
        player_dy=0.0,
        obj_count=3,
    )


def _absent_map() -> MapObjData:
    return MapObjData(ok=True, player_aircraft_present=False, obj_count=2)


def _alive_game(clock: _FakeClock) -> GameLogic:
    game = GameLogic(clock=clock)
    tel = _telemetry()
    mp = _player_map()
    game.tel = _StaticFetcher(tel)
    game.map = _StaticFetcher(mp)
    with game._lock:
        game.state.phase = Phase.ALIVE
        game.state.current_life = LifeState(spawn_time=clock.now - 20.0, life_index=1)
        game.state.last_player_present_ts = clock.now
        game.state.last_tel = tel
        game.state.last_map = mp
        game.state.map_info = MapInfo(
            valid=True,
            map_min=[0.0, 0.0],
            map_max=[100000.0, 100000.0],
            fetch_time=clock.now,
        )
    return game


def test_traceback_confirms_last_raw_position_only_when_loss_reaches_wait_next() -> None:
    clock = _FakeClock(100.0)
    game = _alive_game(clock)

    game.tick()
    clock.now = 100.1
    game.map.value = _absent_map()
    game.tick()

    with game._lock:
        assert game.state.phase == Phase.ALIVE
        assert game.state.traceback.pending_site == TracebackSite(
            x=0.25,
            y=0.42,
            captured_at=100.0,
            life_index=1,
        )
        assert game.state.traceback.confirmed_site is None

    clock.now = 100.0 + GameConfig.PLAYER_PRESENCE_GRACE_SEC + 0.2
    game.tick()
    with game._lock:
        assert game.state.phase == Phase.LOSS_PENDING
        assert game.state.traceback.confirmed_site is None

    clock.now += GameConfig.DEAD_CONFIRM_SEC + 0.01
    game.tick()
    with game._lock:
        assert game.state.phase == Phase.WAIT_NEXT
        assert game.state.traceback.confirmed_site == TracebackSite(
            x=0.25,
            y=0.42,
            captured_at=100.0,
            life_index=1,
        )
        assert game.state.traceback.pending_site is None
        assert game.state.traceback.valid_absence_since is None


def test_traceback_failure_empty_frame_and_player_recovery_cancel_pending_absence() -> None:
    clock = _FakeClock(200.0)
    game = _alive_game(clock)

    with game._lock:
        game._update_traceback_observation_locked(_player_map(0.3, 0.4), 200.0)
        game._update_traceback_observation_locked(_absent_map(), 200.1)
        assert game.state.traceback.pending_site is not None

        game._update_traceback_observation_locked(MapObjData(ok=False, error_kind="timeout"), 200.2)
        assert game.state.traceback.pending_site is None
        assert game.state.traceback.valid_absence_since is None

        game._update_traceback_observation_locked(_absent_map(), 200.3)
        game._update_traceback_observation_locked(MapObjData(ok=True, obj_count=0), 200.4)
        assert game.state.traceback.pending_site is None
        assert game.state.traceback.valid_absence_since is None

        game._update_traceback_observation_locked(_absent_map(), 200.5)
        game._update_traceback_observation_locked(_player_map(0.31, 0.41), 200.6)
        assert game.state.traceback.pending_site is None
        assert game.state.traceback.valid_absence_since is None
        assert game.state.traceback.last_confirmed_pos == (0.31, 0.41)


def test_traceback_respawn_preserves_confirmed_site_but_battle_resets_clear_it() -> None:
    state = GameState(
        phase=Phase.WAIT_NEXT,
        current_life=LifeState(spawn_time=10.0, life_index=1),
    )
    site = TracebackSite(x=0.4, y=0.6, captured_at=20.0, life_index=1)
    state.traceback.confirmed_site = site
    state.traceback.last_confirmed_pos = (0.5, 0.5)
    state.traceback.last_confirmed_ts = 21.0
    state.traceback.valid_absence_since = 22.0
    state.traceback.pending_site = site

    lifecycle.start_new_life(state, 30.0)

    assert state.current_life is not None
    assert state.current_life.life_index == 2
    assert state.traceback.confirmed_site is site
    assert state.traceback.last_confirmed_pos is None
    assert state.traceback.last_confirmed_ts == 0.0
    assert state.traceback.valid_absence_since is None
    assert state.traceback.pending_site is None

    lifecycle.prepare_new_battle_context(state)
    assert state.traceback.confirmed_site is None

    state.traceback.confirmed_site = site
    lifecycle.reset_life_state(state)
    assert state.traceback.confirmed_site is None


def test_snapshot_projects_confirmed_traceback_only_with_current_player_position() -> None:
    clock = _FakeClock(300.0)
    game = _alive_game(clock)
    with game._lock:
        game.state.last_map = _player_map(0.5, 0.5)
        game.state.zone_nav.player_heading = 90.0
        game.state.traceback.confirmed_site = TracebackSite(
            x=0.6,
            y=0.5,
            captured_at=290.0,
            life_index=1,
        )

    point = game.snapshot().traceback_point

    assert point is not None
    assert point.id == "traceback-life-1"
    assert point.name == "上次坠毁点"
    assert point.distance_km == pytest.approx(10.0)
    assert point.relative == 0.0

    with game._lock:
        game.state.last_map = _absent_map()
    assert game.snapshot().traceback_point is None
