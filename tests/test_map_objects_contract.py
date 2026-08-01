"""Map object parsing and coordinate contract tests."""

import gzip
import json
import math
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from bomana.config.settings import BombConfig, ZoneConfig
from bomana.core import navigation
from bomana.core.logic import GameLogic
from bomana.core.state import (
    AirContact,
    HostileUnit,
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
    def setUp(self) -> None:
        self._previous_bomb_target_mode = BombConfig.target_mode
        BombConfig.target_mode = "zone"

    def tearDown(self) -> None:
        BombConfig.target_mode = self._previous_bomb_target_mode

    def test_fetch_prefers_yellow_ownship_and_classifies_all_hostile_units(self):
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
                        "dx": 0.6,
                        "dy": -0.8,
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
                    {
                        "type": "ground_model",
                        "icon": "LightTank",
                        "color": "red",
                        "x": 0.7,
                        "y": 0.4,
                    },
                    {
                        "type": "naval_model",
                        "icon": "Destroyer",
                        "side": "enemy",
                        "x": 0.3,
                        "y": 0.7,
                    },
                    {
                        "type": "ground_model",
                        "icon": "Frigate",
                        "color": "red",
                        "x": 0.32,
                        "y": 0.72,
                    },
                    {
                        "type": "unknown_model",
                        "side": "hostile",
                        "name": "Unknown contact",
                        "x": 0.1,
                        "y": 0.9,
                    },
                    {
                        "type": "ground_model",
                        "icon": "MediumTank",
                        "color": "blue",
                        "x": 0.1,
                        "y": 0.2,
                    },
                    {
                        "type": "capture_zone",
                        "icon": "capture_zone",
                        "color": "red",
                        "x": 0.5,
                        "y": 0.5,
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
        self.assertEqual(
            (data.hostile_air_contacts[0].dx, data.hostile_air_contacts[0].dy),
            (0.6, -0.8),
        )
        self.assertEqual(
            [unit.kind for unit in data.hostile_units],
            ["aircraft", "ground", "naval", "naval", "unit"],
        )
        self.assertEqual(
            [(unit.x, unit.y) for unit in data.hostile_units],
            [(0.6, 0.1), (0.7, 0.4), (0.3, 0.7), (0.32, 0.72), (0.1, 0.9)],
        )
        self.assertEqual(data.hostile_air_contacts[0].id, data.hostile_units[0].id)

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
        self.assertEqual(len(first.hostile_units), 1)
        self.assertEqual(second.hostile_units, [])

    def test_snapshot_projects_only_current_hostile_units_to_tactical_map(self):
        logic = GameLogic()
        with logic._lock:
            logic.state.current_hostile_units = [
                HostileUnit(
                    id="hostile-ground-1",
                    index=1,
                    kind="ground",
                    x=0.25,
                    y=0.75,
                    name="LightTank",
                )
            ]

        points = {point.id: point for point in logic.snapshot().map_points}
        self.assertEqual(points["hostile-ground-1"].kind, "hostile_ground")
        self.assertEqual(points["hostile-ground-1"].label, "LightTank")
        self.assertEqual(points["hostile-ground-1"].color, "enemy")

        with logic._lock:
            logic.state.current_hostile_units = []
        self.assertNotIn(
            "hostile-ground-1",
            {point.id for point in logic.snapshot().map_points},
        )

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

    def test_real_fixture_red_ground_models_are_units_not_map_features(self):
        fixture = Path(__file__).parent / "fixtures/8111/full_sortie_20260710.jsonl.gz"
        payload = None
        with gzip.open(fixture, "rt", encoding="utf-8") as stream:
            for line in stream:
                record = json.loads(line)
                response = record.get("responses", {}).get("/map_obj.json", {})
                candidate = response.get("payload") if response.get("ok") else None
                has_ownship = isinstance(candidate, list) and any(
                    isinstance(item, dict)
                    and item.get("type") == "aircraft"
                    and item.get("icon") == "Player"
                    and item.get("color") == "#faC81E"
                    for item in candidate
                )
                has_hostile_ground = isinstance(candidate, list) and any(
                    isinstance(item, dict)
                    and item.get("type") == "ground_model"
                    and item.get("color") == "#f00C00"
                    and 0.0 <= item.get("x", -1.0) <= 1.0
                    and 0.0 <= item.get("y", -1.0) <= 1.0
                    for item in candidate
                )
                if has_ownship and has_hostile_ground:
                    payload = candidate
                    break

        self.assertIsNotNone(payload)
        assert payload is not None
        expected_ground_count = sum(
            1
            for item in payload
            if isinstance(item, dict)
            and item.get("type") == "ground_model"
            and item.get("color") == "#f00C00"
            and 0.0 <= item.get("x", -1.0) <= 1.0
            and 0.0 <= item.get("y", -1.0) <= 1.0
        )
        data = MapObjectsFetcher(FakeHttp(payload)).fetch(Budget(1.0))

        self.assertEqual(len(data.hostile_units), expected_ground_count)
        self.assertEqual({unit.kind for unit in data.hostile_units}, {"ground"})
        self.assertGreater(len(data.zones), 0)

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

    def test_web_manual_poi_enters_the_existing_navigation_and_ccrp_path(self):
        logic = GameLogic()
        tel = TelemetryData(
            ind_ok=True,
            state_resp_ok=True,
            valid=True,
            type_name="test_plane",
            ias_kmh=300.0,
            compass=0.0,
            compass_present=True,
        )
        raw_map = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            obj_count=2,
            zones=[Zone(id="zone-a", index=1, x=0.5, y=0.2)],
        )
        with logic._lock:
            logic.state.phase = Phase.ALIVE
            logic.state.last_map = raw_map
            logic.state.last_tel = tel
            logic.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[1000.0, 1000.0],
            )

        with patch("bomana.core.logic.ENABLE_CCRP", True):
            self.assertTrue(logic.set_manual_interest_point(0.5, 0.35))

        self.assertEqual(
            [point.id for point in logic.state.last_map.interest_points],
            ["poi_web_manual"],
        )
        immediate_snapshot = logic.snapshot()
        self.assertEqual(immediate_snapshot.bombing_target_mode, "poi")
        self.assertEqual(immediate_snapshot.interest_point.id, "poi_web_manual")
        with logic._lock:
            merged = logic._merge_manual_interest_point_locked(raw_map, raw_map)
            logic.state.last_map = merged
            logic._update_zone_navigation_locked(merged, tel, time.time())

        self.assertEqual(raw_map.interest_points, [])
        self.assertEqual(BombConfig.target_mode, "poi")
        self.assertEqual([point.id for point in merged.interest_points], ["poi_web_manual"])
        target = logic.state.zone_nav.bombing_target
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(
            (target.kind, target.id, target.name), ("poi", "poi_web_manual", "自定 POI")
        )
        snapshot = logic.snapshot()
        self.assertEqual(snapshot.interest_point.id, "poi_web_manual")
        map_target = next(point for point in snapshot.map_points if point.id == "poi_web_manual")
        self.assertTrue(map_target.is_target)

    def test_native_poi_immediately_replaces_an_active_web_manual_poi(self):
        logic = GameLogic()
        initial_map = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            obj_count=1,
        )
        with logic._lock:
            logic.state.phase = Phase.ALIVE
            logic.state.last_map = initial_map
            logic.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[1000.0, 1000.0],
            )
        self.assertTrue(logic.set_manual_interest_point(0.4, 0.3))

        native = InterestPoint(id="poi_native", index=1, x=0.7, y=0.2, name="Game POI")
        native_map = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            obj_count=2,
            interest_points=[native],
        )
        with logic._lock:
            merged = logic._merge_manual_interest_point_locked(initial_map, native_map)

        self.assertIsNone(logic._manual_interest_point)
        self.assertEqual(merged.interest_points, [native])
        self.assertEqual(native_map.interest_points, [native])

    def test_web_manual_poi_is_a_noop_when_native_poi_already_exists(self):
        logic = GameLogic()
        native = InterestPoint(id="poi_native", index=1, x=0.7, y=0.2, name="Game POI")
        native_map = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            obj_count=2,
            interest_points=[native],
        )
        with logic._lock:
            logic.state.phase = Phase.ALIVE
            logic.state.last_map = native_map
            logic.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[1000.0, 1000.0],
            )

        with patch("bomana.core.logic.ENABLE_CCRP", True):
            self.assertTrue(logic.set_manual_interest_point(0.4, 0.3))

        self.assertIsNone(logic._manual_interest_point)
        self.assertEqual(logic.state.last_map.interest_points, [native])
        self.assertEqual(BombConfig.target_mode, "poi")

    def test_web_manual_poi_survives_zone_changes_but_clears_on_map_change_and_hangar(self):
        logic = GameLogic()
        initial_map = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            obj_count=2,
            zones=[Zone(id="zone-a", index=1, x=0.4, y=0.3)],
        )
        with logic._lock:
            logic.state.phase = Phase.ALIVE
            logic.state.last_map = initial_map
            logic.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[1000.0, 1000.0],
            )
        self.assertTrue(logic.set_manual_interest_point(0.4, 0.3))

        changed_map = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            obj_count=2,
            zones=[Zone(id="zone-b", index=1, x=0.8, y=0.7)],
        )
        with logic._lock:
            merged = logic._merge_manual_interest_point_locked(changed_map, changed_map)
        self.assertIsNotNone(logic._manual_interest_point)
        self.assertEqual([point.id for point in merged.interest_points], ["poi_web_manual"])

        with logic._lock:
            logic.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[2000.0, 1000.0],
            )
            merged = logic._merge_manual_interest_point_locked(changed_map, changed_map)
        self.assertIsNone(logic._manual_interest_point)
        self.assertEqual(merged.interest_points, [])

        with logic._lock:
            logic.state.phase = Phase.ALIVE
            logic.state.last_map = initial_map
        self.assertTrue(logic.set_manual_interest_point(0.4, 0.3))
        with logic._lock:
            logic.state.phase = Phase.HANGAR
            merged = logic._merge_manual_interest_point_locked(initial_map, initial_map)
        self.assertIsNone(logic._manual_interest_point)
        self.assertEqual(merged.interest_points, [])

    def test_web_manual_poi_rejects_invalid_or_non_battle_coordinates(self):
        logic = GameLogic()
        for x, y in (
            (True, 0.5),
            (0.5, False),
            (float("nan"), 0.5),
            (0.5, float("inf")),
            (-0.001, 0.5),
            (0.5, 1.001),
        ):
            self.assertFalse(logic.set_manual_interest_point(x, y))
        self.assertFalse(logic.set_manual_interest_point(0.5, 0.5))

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
        BombConfig.target_mode = "poi"
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
            logic.state.last_map = mp
            logic.state.last_tel = tel
            logic.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[1000.0, 1000.0],
            )
            logic._update_zone_navigation_locked(mp, tel, time.time())

        self.assertIsNone(logic.state.zone_nav.target_zone)
        self.assertTrue(all(not zone.is_target for zone in logic.state.zone_nav.zones))
        self.assertIsNotNone(logic.state.zone_nav.bombing_target)
        target = logic.state.zone_nav.bombing_target
        assert target is not None
        self.assertEqual(target.kind, "poi")
        self.assertEqual(target.id, "poi-forward")
        self.assertEqual(target.name, "Smoke")
        map_target = next(point for point in logic.snapshot().map_points if point.id == target.id)
        self.assertTrue(map_target.is_target)

    def test_poi_mode_keeps_an_off_axis_manual_poi_as_the_explicit_target(self):
        BombConfig.target_mode = "poi"
        logic = GameLogic()
        tel = TelemetryData(
            ind_ok=True,
            state_resp_ok=True,
            valid=True,
            type_name="test_plane",
            ias_kmh=300.0,
            compass=0.0,
            compass_present=True,
        )
        manual = InterestPoint(
            id=logic.MANUAL_POI_ID,
            index=1,
            x=0.9,
            y=0.5,
            name="自定 POI",
        )
        mp = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            zones=[Zone(id="zone-a", index=1, x=0.5, y=0.2)],
            interest_points=[manual],
        )

        with logic._lock:
            logic.state.phase = Phase.ALIVE
            logic.state.last_map = mp
            logic.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[1000.0, 1000.0],
            )
            logic._update_zone_navigation_locked(mp, tel, time.time())

        self.assertIsNone(logic.state.zone_nav.target_zone)
        target = logic.state.zone_nav.bombing_target
        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual((target.kind, target.id), ("poi", logic.MANUAL_POI_ID))
        self.assertAlmostEqual(abs(target.relative), 90.0, places=6)
        snapshot = logic.snapshot()
        self.assertEqual(snapshot.interest_point.id, logic.MANUAL_POI_ID)
        self.assertTrue(snapshot.has_bombing_target)

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

    def test_poi_mode_never_falls_back_to_overlapping_zone(self):
        BombConfig.target_mode = "poi"
        logic = GameLogic()
        tel = TelemetryData(
            ind_ok=True,
            state_resp_ok=True,
            valid=True,
            type_name="test_plane",
            ias_kmh=300.0,
            compass=0.0,
            compass_present=True,
        )
        mp = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            zones=[Zone(id="zone-a", index=1, x=0.5, y=0.2)],
            interest_points=[],
        )

        with logic._lock:
            logic.state.phase = Phase.ALIVE
            logic.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[1000.0, 1000.0],
            )
            logic._update_zone_navigation_locked(mp, tel, time.time())

        self.assertIsNone(logic.state.zone_nav.target_zone)
        self.assertTrue(all(not zone.is_target for zone in logic.state.zone_nav.zones))
        self.assertIsNone(logic.state.zone_nav.bombing_target)
        snapshot = logic.snapshot()
        self.assertEqual(snapshot.bombing_target_mode, "poi")
        self.assertFalse(snapshot.has_bombing_target)

    def test_aam_target_prefers_smallest_forward_relative_angle_then_distance(self):
        logic = GameLogic()
        mp = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            hostile_air_contacts=[
                AirContact(id="near-offset", index=1, x=0.51, y=0.45, name="Near"),
                AirContact(
                    id="far-aligned",
                    index=2,
                    x=0.5,
                    y=0.2,
                    name="Aligned",
                    dx=0.0,
                    dy=1.0,
                ),
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
        self.assertAlmostEqual(target.aspect_cosine, -1.0)

    def test_aam_target_can_use_current_poi_with_unknown_motion(self):
        logic = GameLogic()
        mp = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            hostile_air_contacts=[
                AirContact(id="offset-hostile", index=1, x=0.55, y=0.45, name="Offset")
            ],
            interest_points=[
                InterestPoint(id="radar-poi", index=2, x=0.5, y=0.2, name="Radar Point")
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
        self.assertEqual(target.id, "radar-poi")
        self.assertEqual(target.kind, "poi")
        self.assertEqual(target.name, "Radar Point")
        self.assertIsNone(target.aspect_cosine)

    def test_aam_navigation_pauses_zone_and_ground_target_preference(self):
        logic = GameLogic()
        tel = TelemetryData(
            ind_ok=True,
            state_resp_ok=True,
            valid=True,
            type_name="test_plane",
            ias_kmh=300.0,
            compass=0.0,
            compass_present=True,
        )
        mp = MapObjData(
            ok=True,
            player_aircraft_present=True,
            player_pos=(0.5, 0.5),
            zones=[Zone(id="zone-a", index=1, x=0.5, y=0.2)],
            interest_points=[
                InterestPoint(id="radar-poi", index=2, x=0.5, y=0.3, name="Radar Point")
            ],
        )

        with logic._lock:
            logic.state.phase = Phase.ALIVE
            logic.state.map_info = MapInfo(
                valid=True,
                map_min=[0.0, 0.0],
                map_max=[1000.0, 1000.0],
            )
            logic._update_zone_navigation_locked(
                mp,
                tel,
                time.time(),
                zone_targeting_enabled=False,
            )

        self.assertEqual(len(logic.state.zone_nav.zones), 1)
        self.assertFalse(logic.state.zone_nav.zones[0].is_target)
        self.assertIsNone(logic.state.zone_nav.target_zone)
        self.assertIsNone(logic.state.zone_nav.bombing_target)


if __name__ == "__main__":
    unittest.main()
