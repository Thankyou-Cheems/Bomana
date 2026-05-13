"""Map object parsing and coordinate contract tests."""

import math
import unittest

from bomana.config import ZoneConfig
from bomana.core.logic import GameLogic
from bomana.core.state import MapInfo
from bomana.core.telemetry import Budget, FetchResult, MapObjectsFetcher


class FakeHttp:
    def __init__(self, payload):
        self.payload = payload

    def get_json(self, url, budget):
        return FetchResult(endpoint="/map_obj.json", ok=True, payload=self.payload, elapsed_ms=1.0)


class MapObjectsContractTests(unittest.TestCase):
    def test_fetch_parses_normalized_player_zones_and_airfields(self):
        fetcher = MapObjectsFetcher(
            FakeHttp(
                [
                    {
                        "type": "aircraft",
                        "icon": "player",
                        "x": 0.25,
                        "y": 0.75,
                        "dx": 0.01,
                        "dy": -0.02,
                    },
                    {"type": "bombing_point", "x": 0.6, "y": 0.4, "color": "red"},
                    {
                        "type": "airfield",
                        "sx": 0.1,
                        "sy": 0.2,
                        "ex": 0.3,
                        "ey": 0.4,
                        "side": "blue",
                    },
                ]
            )
        )

        data = fetcher.fetch(Budget(1.0))

        self.assertTrue(data.ok)
        self.assertEqual(data.obj_count, 3)
        self.assertTrue(data.player_aircraft_present)
        self.assertEqual(data.player_pos, (0.25, 0.75))
        self.assertEqual((data.player_dx, data.player_dy), (0.01, -0.02))
        self.assertEqual(len(data.zones), 1)
        self.assertEqual((data.zones[0].x, data.zones[0].y), (0.6, 0.4))
        self.assertEqual(len(data.airfields), 1)
        self.assertEqual((data.airfields[0].x, data.airfields[0].y), (0.2, 0.30000000000000004))
        self.assertTrue(data.airfields[0].is_friendly)

    def test_map_info_axis_scale_uses_map_bounds(self):
        map_info = MapInfo(valid=True, map_min=[-1000.0, -500.0], map_max=[1000.0, 500.0])

        self.assertEqual(GameLogic._map_axis_scale_m(map_info), (2000.0, 1000.0))

    def test_bearing_and_distance_apply_axis_specific_meter_scale(self):
        scale = (2000.0, 1000.0)

        bearing, distance_norm = GameLogic._bearing_distance_norm(0.0, 0.0, 0.5, -0.5, scale)

        self.assertAlmostEqual(bearing, math.degrees(math.atan2(1000.0, 500.0)), places=6)
        expected_km = math.hypot(1000.0, 500.0) / 1000.0
        self.assertAlmostEqual(distance_norm * ZoneConfig.DISTANCE_SCALE, expected_km, places=6)


if __name__ == "__main__":
    unittest.main()
