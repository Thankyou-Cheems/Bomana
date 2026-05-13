# -*- coding: utf-8 -*-
"""Regression coverage for battle-scoped timer restore."""

import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from bomana.config import FileConfig
from bomana.core.logic import GameLogic
from bomana.core.state import MapInfo, MapObjData, Phase, TelemetryData, Zone
from bomana.utils.file_utils import StateManager


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
    )


def _battle_map(zone_x: float) -> MapObjData:
    return MapObjData(
        ok=True,
        player_aircraft_present=True,
        player_pos=(0.5, 0.5),
        player_dx=0.0,
        player_dy=-1.0,
        obj_count=2,
        zones=[Zone(id="zone-a", index=1, x=zone_x, y=0.25, color="red")],
    )


def _valid_map_info() -> MapInfo:
    return MapInfo(
        valid=True,
        map_min=[0.0, 0.0],
        map_max=[100000.0, 100000.0],
        fetch_time=time.time(),
    )


class TimerRestoreGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.state_file = Path(self._tmp.name) / "state.json"
        self.state_patch = patch.object(FileConfig, "STATE_FILE", self.state_file)
        self.state_patch.start()

    def tearDown(self) -> None:
        self.state_patch.stop()
        self._tmp.cleanup()

    def _save_pending_restore(self, zone_x: float) -> str:
        signature = GameLogic._build_battle_signature(_valid_map_info(), _battle_map(zone_x))
        assert signature is not None
        StateManager.save(
            remaining_sec=600.0,
            life_index=2,
            sortie_id=4,
            battle_signature=signature,
        )
        return signature

    def test_restore_loads_pending_state_without_immediate_alive_phase(self) -> None:
        self._save_pending_restore(zone_x=0.5)
        game = GameLogic()

        self.assertTrue(game.restore_timer_state())
        self.assertEqual(Phase.IDLE, game.snapshot().phase)
        self.assertFalse(game.timer_restore_applied)

    def test_matching_battle_signature_applies_pending_restore(self) -> None:
        self._save_pending_restore(zone_x=0.5)
        game = GameLogic()
        self.assertTrue(game.restore_timer_state())
        with game._lock:
            game.state.map_info = _valid_map_info()
        game.tel = _StaticFetcher(_stable_telemetry())
        game.map = _StaticFetcher(_battle_map(zone_x=0.5))

        game.tick()
        snap = game.snapshot()

        self.assertEqual(Phase.ALIVE, snap.phase)
        self.assertEqual(2, snap.life_index)
        self.assertEqual(4, snap.sortie_id)
        self.assertTrue(game.timer_restore_applied)

    def test_mismatched_battle_signature_discards_pending_restore(self) -> None:
        self._save_pending_restore(zone_x=0.5)
        game = GameLogic()
        self.assertTrue(game.restore_timer_state())
        with game._lock:
            game.state.map_info = _valid_map_info()
        game.tel = _StaticFetcher(_stable_telemetry())
        game.map = _StaticFetcher(_battle_map(zone_x=0.75))

        game.tick()
        snap = game.snapshot()

        self.assertEqual(Phase.ARMING, snap.phase)
        self.assertIsNone(snap.life_index)
        self.assertFalse(game.timer_restore_applied)
        self.assertFalse(self.state_file.exists())


if __name__ == "__main__":
    unittest.main()
