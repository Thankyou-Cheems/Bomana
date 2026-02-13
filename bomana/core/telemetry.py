# -*- coding: utf-8 -*-
"""Telemetry/network fetchers."""

import math
import time
from typing import Optional, Tuple, Any

import requests

from bomana.config import NetworkConfig
from bomana.core.state import TelemetryData, MapInfo, MapObjData, Zone, Airfield

# ============================================================================
# 网络请求层
# ============================================================================

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
    
    def get_json(self, url: str, budget: Budget) -> Tuple[bool, Optional[Any]]:
        """发起GET请求并解析JSON
        
        Args:
            url: 目标URL
            budget: 时间预算
        
        Returns:
            (成功标志, JSON数据或None)
        """
        rem = budget.remaining()
        if rem <= 0.0:
            return False, None
        
        # 计算超时时间
        connect_t = min(NetworkConfig.API_CONNECT_TIMEOUT, max(0.01, rem))
        read_t = min(NetworkConfig.API_READ_TIMEOUT, max(0.01, rem))
        
        try:
            r = self.session.get(url, timeout=(connect_t, read_t))
            if not r.ok:
                return False, None
            return True, r.json()
        except (requests.RequestException, ValueError):
            return False, None


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
        except (TypeError, ValueError):
            return float(default)

    @staticmethod
    def _to_optional_float(raw: Any) -> Optional[float]:
        """将8111字段值转换为可空float。"""
        if raw is None:
            return None
        if isinstance(raw, dict):
            raw = raw.get("value")
        elif isinstance(raw, (list, tuple)):
            raw = raw[0] if raw else None
        try:
            return float(raw)
        except (TypeError, ValueError):
            return None

    def _read_float(self, payload: dict, keys: Tuple[str, ...]) -> Tuple[float, bool]:
        """按候选键顺序读取数值，返回(值, 是否命中键)。"""
        for key in keys:
            if key in payload:
                value = self._to_float(payload.get(key), 0.0)
                if "rad" in key.lower():
                    value = math.degrees(value)
                return value, True
        return 0.0, False

    def _merge_attitude_fields(self, payload: dict, data: TelemetryData) -> None:
        """合并姿态字段（支持不同机型/端点键名差异）。"""
        pitch, pitch_present = self._read_float(
            payload,
            ("aviahorizon_pitch", "aviahorizon_pitch, deg", "aviahorizon_pitch, rad", "pitch", "pitch, deg"),
        )
        roll, roll_present = self._read_float(
            payload,
            ("aviahorizon_roll", "aviahorizon_roll, deg", "aviahorizon_roll, rad", "roll", "roll, deg"),
        )
        bank, bank_present = self._read_float(
            payload,
            ("bank", "bank, deg", "bank, rad", "aviahorizon_bank", "aviahorizon_bank, deg", "aviahorizon_bank, rad"),
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
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/indicators", budget)
        data.ind_ok = ok
        if ok and isinstance(j, dict):
            data.valid = bool(j.get("valid", False))
            data.type_name = str(j.get("type", "") or "").strip()
            data.compass = self._to_float(j.get("compass1") or j.get("compass"), 0.0)
            data.wing_sweep = self._to_optional_float(
                j.get("wing_sweep_indicator", j.get("wing_sweep"))
            )
            self._merge_attitude_fields(j, data)
        
        if not data.ind_ok:
            return data
        
        # 请求 /state (飞机状态)
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/state", budget)
        data.state_resp_ok = ok
        if ok and isinstance(j, dict):
            data.ias_kmh = self._to_float(j.get("IAS, km/h", 0), 0.0)
            data.vy_ms = self._to_float(j.get("Vy, m/s", 0), 0.0)
            data.fuel_kg = self._to_float(j.get("Mfuel, kg", 0), 0.0)
            
            # v5.8 新增：解析燃油管理相关字段
            data.fuel0_kg = self._to_float(j.get("Mfuel0, kg", 0), 0.0)
            data.altitude_m = self._to_float(j.get("H, m", 0), 0.0)
            data.tas_kmh = self._to_float(j.get("TAS, km/h", 0), 0.0)
            data.throttle_pct = self._to_float(j.get("throttle 1, %", 0), 0.0)
            data.mach = self._to_optional_float(j.get("M"))
            
            # v5.9.6 + v6.6.0：解析起落架状态和百分比
            gear_pct = self._to_float(j.get("gear, %", 0), 0.0)
            data.gear_pct = gear_pct  # v6.6.0: 保存原始百分比
            data.gear_down = (gear_pct > 50)  # 超过50%视为放下状态
            self._merge_attitude_fields(j, data)

        data.attitude_available = bool(
            data.state_resp_ok and
            data.attitude_pitch_present and
            (data.attitude_roll_present or data.attitude_bank_present)
        )
        
        return data


class MapInfoFetcher:
    """地图元数据获取器
    
    获取地图尺度参数，结果会缓存30秒。
    """
    def __init__(self, http: HttpJson):
        self.http = http
    
    def fetch(self, budget: Budget) -> Optional[MapInfo]:
        """获取地图元数据
        
        Args:
            budget: 时间预算
        
        Returns:
            MapInfo对象或None
        """
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/map_info.json", budget)
        if not ok or not isinstance(j, dict) or not j.get("valid", False):
            return None
        
        return MapInfo(
            valid=True,
            grid_size=j.get("grid_size", [52719.0, 55385.0]),
            grid_steps=j.get("grid_steps", [5500.0, 5500.0]),
            grid_zero=j.get("grid_zero", [0.0, 0.0]),
            map_min=j.get("map_min", [-65536.0, -65536.0]),
            map_max=j.get("map_max", [65536.0, 65536.0]),
            fetch_time=time.time()
        )


class MapObjectsFetcher:
    """地图对象获取器
    
    解析/map_obj.json，提取玩家、战区、机场信息。
    """
    def __init__(self, http: HttpJson):
        self.http = http
    
    def fetch(self, budget: Budget, map_info: Optional[MapInfo] = None) -> MapObjData:
        """获取地图对象
        
        Args:
            budget: 时间预算
            map_info: 地图元数据（为兼容保留，当前不用于格子转换）
        
        Returns:
            MapObjData对象
        """
        out = MapObjData()
        ok, j = self.http.get_json(f"{NetworkConfig.API_BASE}/map_obj.json", budget)
        if not ok:
            return out
        
        out.ok = True
        
        # 提取对象列表
        objs = j if isinstance(j, list) else j.get("objects", []) if isinstance(j, dict) else []
        out.obj_count = len(objs)
        
        zone_index = 1
        airfield_index = 1
        
        # 遍历对象
        for o in objs:
            if not isinstance(o, dict):
                continue
            
            obj_type = o.get("type", "")
            icon = o.get("icon", "")
            
            if obj_type == "aircraft" and icon == "Player":
                # 玩家飞机
                out.player_aircraft_present = True
                out.player_pos = (o.get("x", 0), o.get("y", 0))
                out.player_dx = float(o.get("dx", 0) or 0)
                out.player_dy = float(o.get("dy", 0) or 0)
                
            elif obj_type == "airfield":
                # 机场：使用跑道起止点的中心
                sx = o.get("sx")
                sy = o.get("sy")
                ex = o.get("ex")
                ey = o.get("ey")
                
                if sx is None or sy is None or ex is None or ey is None:
                    continue
                
                # 计算跑道中心点
                cx = (float(sx) + float(ex)) / 2.0
                cy = (float(sy) + float(ey)) / 2.0

                # 仅保留归一化坐标。格子坐标换算已停用。
                wx, wy = cx, cy

                # 判断归属：蓝色通道高 = 友方
                rgb = o.get("color[]", [0, 0, 0])
                is_friendly = False
                if isinstance(rgb, list) and len(rgb) >= 3:
                    r, g, b = rgb[:3]
                    is_friendly = (b > 200 and b > r)

                out.airfields.append(Airfield(
                    id=f"airfield_{airfield_index}",
                    index=airfield_index,
                    x=wx, y=wy,
                    color=o.get("color", ""),
                    is_friendly=is_friendly
                ))
                airfield_index += 1

            elif obj_type == "bombing_point":
                # 战区
                zone_x = o.get("x", 0)
                zone_y = o.get("y", 0)
                out.zones.append(Zone(
                    id=f"zone_{zone_x:.4f}_{zone_y:.4f}",
                    index=zone_index,
                    x=zone_x, y=zone_y,
                    color=o.get("color", "")
                ))
                zone_index += 1
        
        return out
