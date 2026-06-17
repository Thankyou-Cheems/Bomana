"""Telemetry/network fetchers."""

import math
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import requests

from bomana.config import NetworkConfig
from bomana.core.state import Airfield, MapInfo, MapObjData, TelemetryData, Zone

_NUMERIC_PARSE_ERRORS = (TypeError, ValueError)

# ============================================================================
# 网络请求层
# ============================================================================


@dataclass(frozen=True)
class FetchResult:
    """Diagnostic result for one 8111 JSON endpoint fetch."""

    endpoint: str
    ok: bool
    payload: Any | None = None
    error_kind: str = ""
    elapsed_ms: float = 0.0
    status_code: int | None = None


class Budget:
    """时间预算管理

    限制单次tick的总网络耗时，避免阻塞主循环。
    """

    def __init__(self, seconds: float):
        self.deadline = time.monotonic() + max(0.0, seconds)

    def remaining(self) -> float:
        """返回剩余时间（秒）"""
        return self.deadline - time.monotonic()


class HttpJson:
    """HTTP JSON请求封装

    使用requests库，支持超时和预算管理。
    """

    def __init__(self, session: requests.Session):
        self.session = session

    @staticmethod
    def _endpoint_label(url: str) -> str:
        path = urlparse(url).path
        return path or url

    def get_json(self, url: str, budget: Budget) -> FetchResult:
        """发起GET请求并解析JSON

        Args:
            url: 目标URL
            budget: 时间预算

        Returns:
            FetchResult，失败时包含分类诊断信息
        """
        endpoint = self._endpoint_label(url)
        start = time.monotonic()
        rem = budget.remaining()
        if rem <= 0.0:
            return FetchResult(endpoint=endpoint, ok=False, error_kind="budget_exhausted")

        # 计算超时时间
        connect_t = min(NetworkConfig.API_CONNECT_TIMEOUT, max(0.01, rem))
        read_t = min(NetworkConfig.API_READ_TIMEOUT, max(0.01, rem))

        try:
            r = self.session.get(url, timeout=(connect_t, read_t))
            if not r.ok:
                return FetchResult(
                    endpoint=endpoint,
                    ok=False,
                    error_kind="status",
                    elapsed_ms=max(0.0, (time.monotonic() - start) * 1000.0),
                    status_code=int(r.status_code),
                )
            try:
                payload = r.json()
            except ValueError:
                return FetchResult(
                    endpoint=endpoint,
                    ok=False,
                    error_kind="invalid_json",
                    elapsed_ms=max(0.0, (time.monotonic() - start) * 1000.0),
                    status_code=int(r.status_code),
                )
            return FetchResult(
                endpoint=endpoint,
                ok=True,
                payload=payload,
                elapsed_ms=max(0.0, (time.monotonic() - start) * 1000.0),
                status_code=int(r.status_code),
            )
        except requests.Timeout:
            return FetchResult(
                endpoint=endpoint,
                ok=False,
                error_kind="timeout",
                elapsed_ms=max(0.0, (time.monotonic() - start) * 1000.0),
            )
        except requests.RequestException:
            return FetchResult(
                endpoint=endpoint,
                ok=False,
                error_kind="request_error",
                elapsed_ms=max(0.0, (time.monotonic() - start) * 1000.0),
            )


class TelemetryFetcher:
    """遥测数据获取器

    负责从8111接口获取飞机状态数据。
    同时请求/indicators和/state两个端点。
    """

    def __init__(self, http: HttpJson):
        self.http = http

    @staticmethod
    def _to_float(raw: Any, default: float = 0.0) -> float:
        """将8111字段值转换为float，兼容 list/dict 包装。"""
        if raw is None:
            return float(default)
        if isinstance(raw, dict):
            raw = raw.get("value", default)
        elif isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else default
        try:
            return float(raw)
        except _NUMERIC_PARSE_ERRORS:
            return float(default)

    @staticmethod
    def _to_optional_float(raw: Any) -> float | None:
        """将8111字段值转换为可空float。"""
        if raw is None:
            return None
        if isinstance(raw, dict):
            raw = raw.get("value")
        elif isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else None
        try:
            return float(raw)
        except _NUMERIC_PARSE_ERRORS:
            return None

    def _read_float(self, payload: dict, keys: tuple[str, ...]) -> tuple[float, bool]:
        """按候选键顺序读取数值，返回(值, 是否命中键)。"""
        for key in keys:
            if key in payload:
                value = self._to_float(payload.get(key), 0.0)
                if "rad" in key.lower():
                    value = math.degrees(value)
                return value, True
        return 0.0, False

    def _read_scaled_float(
        self, payload: dict, keys: tuple[tuple[str, float], ...]
    ) -> tuple[float, bool]:
        """按候选键顺序读取数值并应用倍率，返回(值, 是否命中键)。"""
        for key, scale in keys:
            if key in payload:
                value = self._to_float(payload.get(key), 0.0)
                return value * float(scale), True
        return 0.0, False

    @staticmethod
    def _read_first_text(payload: dict, keys: tuple[str, ...]) -> str:
        for key in keys:
            if key not in payload:
                continue
            value = payload.get(key)
            if isinstance(value, dict):
                value = value.get("value", "")
            elif isinstance(value, (list, tuple)):
                value = value[0] if value else ""
            text = str(value or "").strip()
            if text:
                return text
        return ""

    def _merge_attitude_fields(self, payload: dict, data: TelemetryData) -> None:
        """合并姿态字段（支持不同机型/端点键名差异）。"""
        pitch, pitch_present = self._read_float(
            payload,
            (
                "aviahorizon_pitch",
                "aviahorizon_pitch, deg",
                "aviahorizon_pitch, rad",
                "pitch",
                "pitch, deg",
            ),
        )
        roll, roll_present = self._read_float(
            payload,
            (
                "aviahorizon_roll",
                "aviahorizon_roll, deg",
                "aviahorizon_roll, rad",
                "roll",
                "roll, deg",
            ),
        )
        bank, bank_present = self._read_float(
            payload,
            (
                "bank",
                "bank, deg",
                "bank, rad",
                "aviahorizon_bank",
                "aviahorizon_bank, deg",
                "aviahorizon_bank, rad",
            ),
        )

        if pitch_present:
            data.attitude_pitch_deg = pitch
            data.attitude_pitch_present = True
        if roll_present:
            data.attitude_roll_deg = roll
            data.attitude_roll_present = True
        if bank_present:
            data.attitude_bank_deg = bank
            data.attitude_bank_present = True

    def fetch(self, budget: Budget) -> TelemetryData:
        """获取遥测数据

        Args:
            budget: 时间预算

        Returns:
            TelemetryData对象（即使失败也返回默认值）
        """
        data = TelemetryData()

        # 请求 /indicators (飞机基本信息)
        indicators_result = self.http.get_json(f"{NetworkConfig.API_BASE}/indicators", budget)
        data.ind_ok = indicators_result.ok
        data.ind_error_kind = indicators_result.error_kind
        data.ind_elapsed_ms = indicators_result.elapsed_ms
        j = indicators_result.payload
        if indicators_result.ok and isinstance(j, dict):
            data.valid = bool(j.get("valid", False))
            data.type_name = self._read_first_text(
                j,
                ("type", "unit", "aircraft", "aircraft_type", "vehicle", "model", "name"),
            )
            data.compass, data.compass_present = self._read_float(
                j,
                (
                    "compass1",
                    "compass",
                    "compass1, deg",
                    "compass, deg",
                    "compass1, rad",
                    "compass, rad",
                ),
            )
            data.wing_sweep = self._to_optional_float(
                j.get("wing_sweep_indicator", j.get("wing_sweep", j.get("sweep")))
            )
            self._merge_attitude_fields(j, data)

        # 请求 /state (飞机状态)
        state_result = self.http.get_json(f"{NetworkConfig.API_BASE}/state", budget)
        data.state_resp_ok = state_result.ok
        data.state_error_kind = state_result.error_kind
        data.state_elapsed_ms = state_result.elapsed_ms
        j = state_result.payload
        if state_result.ok and isinstance(j, dict):
            data.ias_kmh, _ = self._read_scaled_float(
                j,
                (
                    ("IAS, km/h", 1.0),
                    ("IAS", 1.0),
                    ("ias", 1.0),
                    ("indicated_air_speed, km/h", 1.0),
                    ("indicated_air_speed", 1.0),
                    ("indicated_airspeed, km/h", 1.0),
                    ("indicated_airspeed", 1.0),
                    ("IAS, m/s", 3.6),
                    ("ias, m/s", 3.6),
                    ("indicated_air_speed, m/s", 3.6),
                    ("indicated_airspeed, m/s", 3.6),
                ),
            )
            data.vy_ms, _ = self._read_scaled_float(
                j,
                (
                    ("Vy, m/s", 1.0),
                    ("Vy", 1.0),
                    ("vy", 1.0),
                    ("vertical_speed, m/s", 1.0),
                    ("vertical_speed", 1.0),
                    ("climb_speed, m/s", 1.0),
                ),
            )
            data.fuel_kg, _ = self._read_scaled_float(
                j,
                (
                    ("Mfuel, kg", 1.0),
                    ("Mfuel", 1.0),
                    ("fuel, kg", 1.0),
                    ("fuel", 1.0),
                ),
            )

            # v5.8 新增：解析燃油管理相关字段
            data.fuel0_kg, _ = self._read_scaled_float(
                j,
                (
                    ("Mfuel0, kg", 1.0),
                    ("Mfuel0", 1.0),
                    ("fuel0, kg", 1.0),
                    ("fuel0", 1.0),
                ),
            )
            data.altitude_m, _ = self._read_scaled_float(
                j,
                (
                    ("H, m", 1.0),
                    ("H", 1.0),
                    ("altitude, m", 1.0),
                    ("altitude", 1.0),
                    ("height, m", 1.0),
                    ("height", 1.0),
                ),
            )
            data.tas_kmh, _ = self._read_scaled_float(
                j,
                (
                    ("TAS, km/h", 1.0),
                    ("TAS", 1.0),
                    ("tas", 1.0),
                    ("true_air_speed, km/h", 1.0),
                    ("true_air_speed", 1.0),
                    ("true_airspeed, km/h", 1.0),
                    ("true_airspeed", 1.0),
                    ("TAS, m/s", 3.6),
                    ("tas, m/s", 3.6),
                    ("true_air_speed, m/s", 3.6),
                    ("true_airspeed, m/s", 3.6),
                ),
            )
            data.throttle_pct, _ = self._read_scaled_float(
                j,
                (
                    ("throttle 1, %", 1.0),
                    ("throttle, %", 1.0),
                    ("throttle", 1.0),
                    ("Throttle 1, %", 1.0),
                ),
            )
            data.mach = self._to_optional_float(
                j.get("M", j.get("Mach", j.get("mach", j.get("mach_number"))))
            )

            # v5.9.6 + v6.6.0：解析起落架状态和百分比
            gear_pct, _ = self._read_scaled_float(
                j,
                (
                    ("gear, %", 1.0),
                    ("gear", 1.0),
                    ("gear_1, %", 1.0),
                    ("landing_gear, %", 1.0),
                    ("gear_down, %", 1.0),
                ),
            )
            data.gear_pct = gear_pct  # v6.6.0: 保存原始百分比
            data.gear_down = gear_pct > 50  # 超过50%视为放下状态
            self._merge_attitude_fields(j, data)

        data.attitude_available = bool(
            data.state_resp_ok
            and data.attitude_pitch_present
            and (data.attitude_roll_present or data.attitude_bank_present)
        )

        return data


class MapInfoFetcher:
    """地图元数据获取器

    获取地图尺度参数，结果会缓存30秒。
    """

    def __init__(self, http: HttpJson):
        self.http = http
        self.last_result = FetchResult(
            endpoint="/map_info.json", ok=False, error_kind="not_fetched"
        )

    def fetch(self, budget: Budget) -> MapInfo | None:
        """获取地图元数据

        Args:
            budget: 时间预算

        Returns:
            MapInfo对象或None
        """
        result = self.http.get_json(f"{NetworkConfig.API_BASE}/map_info.json", budget)
        self.last_result = result
        j = result.payload
        if not result.ok or not isinstance(j, dict) or not j.get("valid", False):
            return None

        return MapInfo(
            valid=True,
            grid_size=j.get("grid_size", [52719.0, 55385.0]),
            grid_steps=j.get("grid_steps", [5500.0, 5500.0]),
            grid_zero=j.get("grid_zero", [0.0, 0.0]),
            map_min=j.get("map_min", [-65536.0, -65536.0]),
            map_max=j.get("map_max", [65536.0, 65536.0]),
            fetch_time=time.time(),
        )


class MapObjectsFetcher:
    """地图对象获取器

    解析/map_obj.json，提取玩家、战区、机场信息。
    坐标保持8111返回的归一化地图坐标；map_info 尺度换算由逻辑层负责。
    """

    def __init__(self, http: HttpJson):
        self.http = http
        self.last_result = FetchResult(endpoint="/map_obj.json", ok=False, error_kind="not_fetched")

    @staticmethod
    def _text(value: Any) -> str:
        if isinstance(value, dict):
            value = value.get("value", "")
        elif isinstance(value, (list, tuple)):
            value = value[0] if value else ""
        return str(value or "").strip()

    @staticmethod
    def _lower_text(value: Any) -> str:
        return MapObjectsFetcher._text(value).lower()

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        if isinstance(value, dict):
            value = value.get("value")
        elif isinstance(value, (list, tuple)):
            value = value[0] if value else None
        try:
            result = float(value)
        except _NUMERIC_PARSE_ERRORS:
            return None
        return result if math.isfinite(result) else None

    @staticmethod
    def _first_float(o: dict, keys: tuple[str, ...]) -> float | None:
        for key in keys:
            if key in o:
                value = MapObjectsFetcher._float_or_none(o.get(key))
                if value is not None:
                    return value
        return None

    @staticmethod
    def _extract_objects(payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in ("objects", "map_objects", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        return []

    @staticmethod
    def _read_rgb(o: dict) -> tuple[float, float, float] | None:
        value = o.get("color[]", o.get("color_rgb", o.get("rgb")))
        if isinstance(value, dict):
            value = value.get("value")
        if isinstance(value, (list, tuple)) and len(value) >= 3:
            try:
                return float(value[0]), float(value[1]), float(value[2])
            except _NUMERIC_PARSE_ERRORS:
                return None

        text = MapObjectsFetcher._text(o.get("color", ""))
        if text.startswith("#") and len(text) >= 7:
            try:
                return (
                    float(int(text[1:3], 16)),
                    float(int(text[3:5], 16)),
                    float(int(text[5:7], 16)),
                )
            except ValueError:
                return None
        return None

    @staticmethod
    def _is_friendly_airfield(o: dict) -> bool:
        side = MapObjectsFetcher._lower_text(o.get("side", o.get("team", o.get("army"))))
        color_name = MapObjectsFetcher._lower_text(o.get("color", ""))
        if side in {"friendly", "ally", "allied", "blue", "team_a", "1"}:
            return True
        if side in {"enemy", "hostile", "red", "team_b", "2"}:
            return False
        if "blue" in color_name or color_name in {"#0000ff", "0x0000ff"}:
            return True
        if "red" in color_name:
            return False

        rgb = MapObjectsFetcher._read_rgb(o)
        if rgb is None:
            return False
        r, g, b = rgb
        return bool(b >= 120 and b >= (r + 30) and b >= (g + 10))

    @staticmethod
    def _is_player_object(o: dict) -> bool:
        obj_type = MapObjectsFetcher._lower_text(o.get("type", ""))
        icon = MapObjectsFetcher._lower_text(o.get("icon", ""))
        name = MapObjectsFetcher._lower_text(o.get("name", o.get("label", "")))
        if o.get("is_player") is True or o.get("player") is True:
            return True
        return bool(
            obj_type in {"aircraft", "plane", "player", "player_aircraft"}
            and (icon == "player" or name == "player" or "player" in icon)
        )

    @staticmethod
    def _is_airfield_object(o: dict) -> bool:
        obj_type = MapObjectsFetcher._lower_text(o.get("type", ""))
        icon = MapObjectsFetcher._lower_text(o.get("icon", ""))
        return obj_type in {"airfield", "airport", "runway"} or icon in {
            "airfield",
            "airport",
            "runway",
        }

    @staticmethod
    def _is_zone_object(o: dict) -> bool:
        obj_type = MapObjectsFetcher._lower_text(o.get("type", ""))
        icon = MapObjectsFetcher._lower_text(o.get("icon", ""))
        return bool(
            obj_type
            in {
                "bombing_point",
                "bombingpoint",
                "bombing point",
                "bomb_target",
                "bomb_target_point",
            }
            or "bombing" in icon
            or "bomb_target" in icon
        )

    def fetch(self, budget: Budget) -> MapObjData:
        """获取地图对象

        Args:
            budget: 时间预算

        Returns:
            MapObjData对象
        """
        out = MapObjData()
        result = self.http.get_json(f"{NetworkConfig.API_BASE}/map_obj.json", budget)
        self.last_result = result
        out.error_kind = result.error_kind
        out.elapsed_ms = result.elapsed_ms
        j = result.payload
        if not result.ok:
            return out

        out.ok = True

        # 提取对象列表
        objs = self._extract_objects(j)
        out.obj_count = len(objs)

        zone_index = 1
        airfield_index = 1

        # 遍历对象
        for o in objs:
            if not isinstance(o, dict):
                continue

            if self._is_player_object(o):
                # 玩家飞机
                px = self._first_float(o, ("x", "X", "pos_x", "position_x"))
                py = self._first_float(o, ("y", "Y", "pos_y", "position_y"))
                if px is None or py is None:
                    continue
                out.player_aircraft_present = True
                out.player_pos = (px, py)
                out.player_dx = self._first_float(o, ("dx", "DX", "vel_x", "vx")) or 0.0
                out.player_dy = self._first_float(o, ("dy", "DY", "vel_y", "vy")) or 0.0

            elif self._is_airfield_object(o):
                # 机场：使用跑道起止点的中心
                sx = self._first_float(o, ("sx", "start_x", "runway_start_x"))
                sy = self._first_float(o, ("sy", "start_y", "runway_start_y"))
                ex = self._first_float(o, ("ex", "end_x", "runway_end_x"))
                ey = self._first_float(o, ("ey", "end_y", "runway_end_y"))

                if sx is not None and sy is not None and ex is not None and ey is not None:
                    # 计算跑道中心点
                    cx = (sx + ex) / 2.0
                    cy = (sy + ey) / 2.0
                else:
                    cx = self._first_float(o, ("x", "X", "pos_x", "position_x"))
                    cy = self._first_float(o, ("y", "Y", "pos_y", "position_y"))
                    if cx is None or cy is None:
                        continue

                # 仅保留归一化坐标。距离/方位的米制尺度换算在 GameLogic 中完成。
                wx, wy = cx, cy

                # 判断归属：优先 side/team 字段，回退到蓝色通道启发式。
                is_friendly = self._is_friendly_airfield(o)

                out.airfields.append(
                    Airfield(
                        id=f"airfield_{airfield_index}",
                        index=airfield_index,
                        x=wx,
                        y=wy,
                        color=o.get("color", ""),
                        is_friendly=is_friendly,
                    )
                )
                airfield_index += 1

            elif self._is_zone_object(o):
                # 战区
                zone_x = self._first_float(o, ("x", "X", "pos_x", "position_x"))
                zone_y = self._first_float(o, ("y", "Y", "pos_y", "position_y"))
                if zone_x is None or zone_y is None:
                    continue
                out.zones.append(
                    Zone(
                        id=f"zone_{zone_x:.4f}_{zone_y:.4f}",
                        index=zone_index,
                        x=zone_x,
                        y=zone_y,
                        color=o.get("color", ""),
                    )
                )
                zone_index += 1

        return out
