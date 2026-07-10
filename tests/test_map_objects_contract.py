"""Map object parsing and coordinate contract tests."""

import gzip
import json
import math
import time
import unittest
from pathlib import Path

from bomana.config.settings import ZoneConfig
from bomana.core import navigation
from bomana.core.logic import GameLogic
from bomana.core.state import (
    AirContact,
    InterestPoint,
    MapInfo,
    MapObjData,
    Phase,
    TelemetryData,
    Zone,
)
from bomana.core.telemetry import Budget, FetchResult, MapObjectsFetcher


class FakeHttp:
    def __init__(self, payload):
        self.payload = payload

    def get_json(self, url, budget):
        return FetchResult(endpoint="/map_obj.json", ok=True, payload=self.payload, elapsed_ms=1.0)


class MapObjectsContractTests(unittest.TestCase):
    def test_fetch_prefers_yellow_ownship_and_keeps_only_hostile_aircraft(self):
        fetcher = MapObjectsFetcher(
            FakeHttp(
                [
                    {
                        "type": "aircraft",
                        "icon": "Player",
                        "color": "#faC81E",
                        "color[]": [250, 200, 30],
                        "x": 0.2,
                        "y": 0.3,
                    },
                    {
                        "type": "aircraft",
                        "icon": "Fighter",
                        "color": "#f00C00",
                        "color[]": [240, 12, 0],
                        "x": 0.6,
                        "y": 0.1,
                    },
                    {
                        "type": "aircraft",
                        "icon": "Fighter",
                        "color": "#174DFF",
                        "color[]": [23, 77, 255],
                        "x": 0.4,
                        "y": 0.2,
                    },
                    {
                        "type": "aircraft",
                        "icon": "Player",
                        "color": "#043FFF",
                        "color[]": [4, 63, 255],
                        "x": 0.9,
                        "y": 0.9,
                    },
                    {
                        "type": "aircraft",
                        "icon": "Fighter",
                        "color": "#faC81E",
                        "color[]": [250, 200, 30],
                        "x": 0.8,
                        "y": 0.8,
                    },
                ]
            )
        )

        data = fetcher.fetch(Budget(1.0))

        self.assertEqual(data.player_pos, (0.2, 0.3))
        self.assertEqual(len(data.hostile_air_contacts), 1)
        self.assertEqual(
            (data.hostile_air_contacts[0].x, data.hostile_air_contacts[0].y), (0.6, 0.1)
        )
        self.assertEqual(data.hostile_air_contacts[0].icon, "Fighter")

    def test_fetch_prefers_explicit_self_over_color_heuristic(self):
        fetcher = MapObjectsFetcher(
            FakeHttp(
                [
                    {
                        "type": "aircraft",
                        "icon": "Player",
                        "color[]": [250, 200, 30],
                        "x": 0.2,
                        "y": 0.3,
                    },
                    {
                        "type": "aircraft",
                        "icon": "Player",
                        "is_player": True,
                        "color[]": [4, 63, 255],
                        "x": 0.4,
                        "y": 0.5,
                    },
                ]
            )
        )

        data = fetcher.fetch(Budget(1.0))

        self.assertEqual(data.player_pos, (0.4, 0.5))

    def test_hostile_aircraft_contacts_are_current_response_only(self):
        fetcher = MapObjectsFetcher(
            FakeHttp(
                [
                    {"type": "aircraft", "icon": "Player", "color": "yellow", "x": 0.2, "y": 0.3},
                    {"type": "aircraft", "icon": "Fighter", "color": "red", "x": 0.6, "y": 0.1},
                ]
            )
        )

        first = fetcher.fetch(Budget(1.0))
        fetcher.http = FakeHttp(
            [{"type": "aircraft", "icon": "Player", "color": "yellow", "x": 0.2, "y": 0.3}]
        )
        second = fetcher.fetch(Budget(1.0))

        self.assertEqual(len(first.hostile_air_contacts), 1)
        self.assertEqual(second.hostile_air_contacts, [])

    def test_real_fixture_blue_squad_player_does_not_overwrite_yellow_ownship(self):
        fixture = Path(__file__).parent / "fixtures/8111/full_sortie_20260710.jsonl.gz"
        yellow_player = None
        blue_player = None
        with gzip.open(fixture, "rt", encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                response = record.get("responses", {}).get("/map_obj.json", {})
                objects = response.get("payload") if response.get("ok") else None
                if not isinstance(objects, list):
                    continue
                players = [
                    item
                    for item in objects
                    if isinstance(item, dict)
                    and item.get("type") == "aircraft"
                    and item.get("icon") == "Player"
                ]
                if yellow_player is None:
                    yellow_player = next(
                        (item for item in players if item.get("color") == "#faC81E"),
                        None,
                    )
                if blue_player is None:
                    blue_player = next(
                        (item for item in players if item.get("color") == "#043FFF"),
                        None,
                    )
                if yellow_player is not None and blue_player is not None:
                    break

        self.assertIsNotNone(yellow_player)
        self.assertIsNotNone(blue_player)
        assert yellow_player is not None
        assert blue_player is not None
        expected_position = (yellow_player["x"], yellow_player["y"])
        data = MapObjectsFetcher(FakeHttp([yellow_player, blue_player])).fetch(Budget(1.0))
        self.assertEqual(data.player_pos, expected_position)
        self.assertEqual(data.hostile_air_contacts, [])

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
        self.assertEqual(data.interest_points, [])

    def test_fetch_parses_point_of_interest_only_by_type(self):
        fetcher = MapObjectsFetcher(
            FakeHttp(
                [
                    {
                        "type": "point_of_interest",
                        "id": "nav-1",
                        "name": "Convoy marker",
                        "x": 0.15,
                        "y": 0.35,
                        "icon": "bomb_target",
                    },
                    {
                        "type": "aircraft",
                        "icon": "point_of_interest",
                        "x": 0.2,
                        "y": 0.4,
                    },
                    {"type": "point_of_interest", "x": 0.25, "y": 0.45, "label": "Smoke"},
                    {"type": "point_of_interest", "x": "bad", "y": 0.5},
                ]
            )
        )

        data = fetcher.fetch(Budget(1.0))

        self.assertTrue(data.ok)
        self.assertEqual(data.obj_count, 4)
        self.assertEqual(len(data.interest_points), 2)
        self.assertEqual(data.interest_points[0].id, "poi_nav-1")
        self.assertEqual(data.interest_points[0].name, "Convoy marker")
        self.assertEqual((data.interest_points[0].x, data.interest_points[0].y), (0.15, 0.35))
        self.assertEqual(data.interest_points[1].id, "poi_0.250000_0.450000")
        self.assertEqual(data.interest_points[1].name, "Smoke")

    def test_map_info_axis_scale_uses_map_bounds(self):
        map_info = MapInfo(valid=True, map_min=[-1000.0, -500.0], map_max=[1000.0, 500.0])

        self.assertEqual(navigation.map_axis_scale_m(map_info), (2000.0, 1000.0))

    def test_bearing_and_distance_apply_axis_specific_meter_scale(self):
        scale = (2000.0, 1000.0)

        bearing, distance_norm = navigation.bearing_distance_norm(0.0, 0.0, 0.5, -0.5, scale)

        self.assertAlmostEqual(bearing, math.degrees(math.atan2(1000.0, 500.0)), places=6)
        expected_km = math.hypot(1000.0, 500.0) / 1000.0
        self.assertAlmostEqual(distance_norm * ZoneConfig.DISTANCE_SCALE, expected_km, places=6)

    def test_snapshot_builds_nearest_interest_point_display_without_zone_target(self):
        logic = GameLogic()
        distance_norm = 0.1 / ZoneConfig.DISTANCE_SCALE

        with logic._lock:
            logic.state.last_tel = TelemetryData(
                ind_ok=True,
                state_resp_ok=True,
                valid=True,
                type_name="test_plane",
                ias_kmh=300.0,
                compass=0.0,
                compass_present=True,
            )
            logic.state.last_map = MapObjData(
                ok=True,
                player_aircraft_present=True,
                player_pos=(0.0, 0.0),
                obj_count=3,
                interest_points=[
                    InterestPoint(id="far", index=1, x=0.0, y=-0.5, name="Far marker"),
                    InterestPoint(id="near", index=2, x=0.0, y=-0.1, name="Near marker"),
                ],
            )
            logic.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[1000.0, 1000.0],
            )
            logic.state.zone_nav.player_heading = 0.0
            logic.state.zone_nav.ground_speed = distance_norm / 10.0

        snapshot = logic.snapshot()

        self.assertIsNone(logic.state.zone_nav.target_zone)
        self.assertFalse(snapshot.has_target)
        self.assertIsNotNone(snapshot.interest_point)
        point = snapshot.interest_point
        assert point is not None
        self.assertEqual(point.id, "near")
        self.assertEqual(point.name, "Near marker")
        self.assertTrue(point.is_target)
        self.assertAlmostEqual(point.distance_km, 0.1, places=6)
        self.assertAlmostEqual(point.relative, 0.0, places=6)
        self.assertEqual(point.direction, "前")
        self.assertEqual(point.ete_str, "00:10")
        self.assertTrue(point.cdi_indicator)
        self.assertTrue(point.cdi_color)

    def test_zone_navigation_uses_forward_poi_as_bombing_target(self):
        logic = GameLogic()
        tel = TelemetryData(
            ind_ok=True,
            state_resp_ok=True,
            valid=True,
            type_name="test_plane",
            ias_kmh=300.0,
            vy_ms=5.0,
            compass=0.0,
            compass_present=True,
        )
        mp = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            zones=[Zone(id="zone-a", index=1, x=0.5, y=0.2)],
            interest_points=[InterestPoint(id="poi-forward", index=1, x=0.5, y=0.45, name="Smoke")],
        )

        with logic._lock:
            logic.state.phase = Phase.ALIVE
            logic.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[1000.0, 1000.0],
            )
            logic._update_zone_navigation_locked(mp, tel, time.time())

        self.assertIsNotNone(logic.state.zone_nav.target_zone)
        self.assertEqual(logic.state.zone_nav.target_zone.id, "zone-a")
        self.assertIsNotNone(logic.state.zone_nav.bombing_target)
        target = logic.state.zone_nav.bombing_target
        assert target is not None
        self.assertEqual(target.kind, "poi")
        self.assertEqual(target.id, "poi-forward")
        self.assertEqual(target.name, "Smoke")

    def test_zone_navigation_keeps_zone_bombing_target_when_poi_outside_heading_gate(self):
        logic = GameLogic()
        tel = TelemetryData(
            ind_ok=True,
            state_resp_ok=True,
            valid=True,
            type_name="test_plane",
            ias_kmh=300.0,
            vy_ms=5.0,
            compass=0.0,
            compass_present=True,
        )
        mp = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            zones=[Zone(id="zone-a", index=1, x=0.5, y=0.2)],
            interest_points=[InterestPoint(id="poi-side", index=1, x=0.95, y=0.5, name="Side")],
        )

        with logic._lock:
            logic.state.phase = Phase.ALIVE
            logic.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[1000.0, 1000.0],
            )
            logic._update_zone_navigation_locked(mp, tel, time.time())

        self.assertIsNotNone(logic.state.zone_nav.bombing_target)
        target = logic.state.zone_nav.bombing_target
        assert target is not None
        self.assertEqual(target.kind, "zone")
        self.assertEqual(target.id, "zone-a")

    def test_aam_target_prefers_smallest_forward_relative_angle_then_distance(self):
        logic = GameLogic()
        mp = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            hostile_air_contacts=[
                AirContact(id="near-offset", index=1, x=0.51, y=0.45, name="Near"),
                AirContact(id="far-aligned", index=2, x=0.5, y=0.2, name="Aligned"),
                AirContact(id="behind", index=3, x=0.5, y=0.8, name="Behind"),
            ],
        )
        with logic._lock:
            logic.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[1000.0, 1000.0],
            )
            logic.state.zone_nav.player_heading = 0.0
            target = logic._select_weapon_target_locked({"role": "aam"}, mp)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.id, "far-aligned")
        self.assertEqual(target.kind, "aircraft")
        self.assertEqual(target.name, "Aligned")


if __name__ == "__main__":
    unittest.main()
