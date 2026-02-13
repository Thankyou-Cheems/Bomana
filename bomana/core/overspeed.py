# -*- coding: utf-8 -*-
"""Overspeed model identification and alert grading."""

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from bomana.config import OverspeedConfig
from bomana.utils.file_utils import resource_path

LimitValue = Union[float, List[List[float]]]


@dataclass(frozen=True)
class OverspeedDecision:
    """超速判定结果（逻辑层 -> UI）。"""
    level: str = "unknown"                 # unknown/safe/caution/warning/critical
    plane_type: str = ""
    resolved_fm: str = ""
    ias_kmh: float = 0.0
    tas_kmh: float = 0.0
    mach: Optional[float] = None
    ias_limit_kmh: Optional[float] = None
    mach_limit: Optional[float] = None
    ias_ratio: Optional[float] = None      # IAS / ias_limit_kmh
    mach_margin: Optional[float] = None    # mach_limit - mach
    reason: str = ""


class SpeedLimitDatabase:
    """
    机型限速数据库。

    关键识别链路（与 WTSpeeder 一致）：
    `/indicators.type` -> unit_to_fm -> fm_speed_limits(ias/mach)。
    """

    def __init__(self):
        self.loaded = False
        self.load_error = ""
        self.unit_to_fm: Dict[str, str] = {}
        self.fm_limits: Dict[str, Dict[str, LimitValue]] = {}
        self._fm_alias: Dict[str, str] = {}
        self._load()

    @staticmethod
    def _normalize_name(name: str) -> str:
        return str(name or "").strip().lower()

    @classmethod
    def _name_variants(cls, name: str) -> List[str]:
        raw = str(name or "").strip()
        if not raw:
            return []
        lower = raw.lower()
        variants = {
            raw,
            lower,
            raw.replace("-", "_"),
            raw.replace("_", "-"),
            lower.replace("-", "_"),
            lower.replace("_", "-"),
        }
        return [v for v in variants if v]

    @staticmethod
    def _parse_limit_value(raw: Any) -> Optional[LimitValue]:
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, list):
            # 支持 [[sweep, limit], ...] 和 [sweep0, limit0, ...] 两种格式。
            if not raw:
                return None
            if all(isinstance(item, list) and len(item) >= 2 for item in raw):
                pairs = []
                for item in raw:
                    try:
                        pairs.append([float(item[0]), float(item[1])])
                    except (TypeError, ValueError, IndexError):
                        return None
                pairs.sort(key=lambda x: x[0])
                return pairs
            if len(raw) >= 2 and len(raw) % 2 == 0:
                pairs = []
                for i in range(0, len(raw), 2):
                    try:
                        pairs.append([float(raw[i]), float(raw[i + 1])])
                    except (TypeError, ValueError):
                        return None
                pairs.sort(key=lambda x: x[0])
                return pairs
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return None
            try:
                return float(text)
            except ValueError:
                if "," in text:
                    parts = [p.strip() for p in text.split(",") if p.strip()]
                    if len(parts) >= 2 and len(parts) % 2 == 0:
                        pairs = []
                        for i in range(0, len(parts), 2):
                            try:
                                pairs.append([float(parts[i]), float(parts[i + 1])])
                            except (TypeError, ValueError):
                                return None
                        pairs.sort(key=lambda x: x[0])
                        return pairs
        return None

    @staticmethod
    def _interpolate(points: List[List[float]], sweep: Optional[float]) -> Optional[float]:
        if not points:
            return None

        # 与 WTSpeeder 保持一致：后掠角缺失时取“最大后掠”端限制，减少误报。
        if sweep is None:
            return float(points[-1][1])

        try:
            x = float(sweep)
        except (TypeError, ValueError):
            return float(points[-1][1])

        if x <= points[0][0]:
            return float(points[0][1])
        if x >= points[-1][0]:
            return float(points[-1][1])

        for i in range(len(points) - 1):
            x0, y0 = points[i]
            x1, y1 = points[i + 1]
            if x0 <= x <= x1:
                if x1 == x0:
                    return float(y0)
                t = (x - x0) / (x1 - x0)
                return float(y0 + (y1 - y0) * t)
        return float(points[-1][1])

    def _load(self) -> None:
        path = Path(resource_path(OverspeedConfig.LIMITS_FILE))
        if not path.exists():
            self.load_error = f"limits file not found: {path}"
            return

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            self.load_error = f"limits json parse failed: {exc}"
            return

        unit_map = payload.get("unit_to_fm", {})
        fm_map = payload.get("fm_speed_limits", {})
        if not isinstance(unit_map, dict) or not isinstance(fm_map, dict):
            self.load_error = "limits json schema invalid"
            return

        for unit_name, fm_name in unit_map.items():
            u = self._normalize_name(unit_name)
            f = str(fm_name or "").strip()
            if u and f:
                self.unit_to_fm[u] = f

        for fm_name, raw in fm_map.items():
            if not isinstance(raw, dict):
                continue
            ias = self._parse_limit_value(raw.get("ias"))
            mach = self._parse_limit_value(raw.get("mach"))
            if ias is None and mach is None:
                continue
            name = str(fm_name or "").strip()
            if not name:
                continue
            self.fm_limits[name] = {}
            if ias is not None:
                self.fm_limits[name]["ias"] = ias
            if mach is not None:
                self.fm_limits[name]["mach"] = mach

        for fm_name in self.fm_limits.keys():
            for alias in self._name_variants(fm_name):
                self._fm_alias[self._normalize_name(alias)] = fm_name

        self.loaded = bool(self.fm_limits and self.unit_to_fm)
        if not self.loaded and not self.load_error:
            self.load_error = "limits database empty"

    def resolve_fm_name(self, plane_type: str) -> Optional[str]:
        raw = str(plane_type or "").strip()
        if not raw:
            return None

        for alias in self._name_variants(raw):
            key = self._normalize_name(alias)
            mapped = self.unit_to_fm.get(key)
            if mapped:
                resolved = self._fm_alias.get(self._normalize_name(mapped), mapped)
                if resolved in self.fm_limits:
                    return resolved

        for alias in self._name_variants(raw):
            resolved = self._fm_alias.get(self._normalize_name(alias))
            if resolved and resolved in self.fm_limits:
                return resolved

        return None

    def _value_by_sweep(self, value: Optional[LimitValue], sweep: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, list):
            return self._interpolate(value, sweep)
        return None

    def get_limits(self, plane_type: str, wing_sweep: Optional[float]) -> Tuple[Optional[str], Optional[float], Optional[float]]:
        resolved = self.resolve_fm_name(plane_type)
        if resolved is None:
            return None, None, None

        row = self.fm_limits.get(resolved, {})
        ias_limit = self._value_by_sweep(row.get("ias"), wing_sweep)
        mach_limit = self._value_by_sweep(row.get("mach"), wing_sweep)
        return resolved, ias_limit, mach_limit


class OverspeedAnalyzer:
    """IAS/Mach 双通道超速分级判定。"""

    def __init__(self):
        self.db = SpeedLimitDatabase()

    def evaluate(
        self,
        plane_type: str,
        ias_kmh: float,
        tas_kmh: float,
        mach: Optional[float],
        wing_sweep: Optional[float],
        enabled: bool = True,
    ) -> OverspeedDecision:
        if not OverspeedConfig.ENABLED or not enabled:
            return OverspeedDecision(level="unknown", plane_type=plane_type, reason="disabled")

        if not self.db.loaded:
            return OverspeedDecision(level="unknown", plane_type=plane_type, reason=self.db.load_error or "db_not_loaded")

        ias = float(ias_kmh or 0.0)
        tas = float(tas_kmh or 0.0)
        mach_val = None
        if mach is not None:
            try:
                mach_val = float(mach)
            except (TypeError, ValueError):
                mach_val = None

        resolved, ias_limit, mach_limit = self.db.get_limits(plane_type, wing_sweep)
        if resolved is None:
            return OverspeedDecision(
                level="unknown",
                plane_type=plane_type,
                ias_kmh=ias,
                tas_kmh=tas,
                mach=mach_val,
                reason="fm_not_found",
            )

        if ias_limit is None and mach_limit is None:
            return OverspeedDecision(
                level="unknown",
                plane_type=plane_type,
                resolved_fm=resolved,
                ias_kmh=ias,
                tas_kmh=tas,
                mach=mach_val,
                reason="limit_missing",
            )

        ias_ratio = (ias / ias_limit) if (ias_limit and ias_limit > 0.0) else None
        mach_margin = (mach_limit - mach_val) if (mach_limit is not None and mach_val is not None) else None

        crit_ias = bool(ias_ratio is not None and ias_ratio >= OverspeedConfig.CRITICAL_RATIO)
        warn_ias = bool(ias_ratio is not None and ias_ratio >= OverspeedConfig.WARNING_RATIO)
        caut_ias = bool(ias_ratio is not None and ias_ratio >= OverspeedConfig.CAUTION_RATIO)

        crit_mach = bool(mach_margin is not None and mach_margin <= OverspeedConfig.MACH_CRITICAL_MARGIN)
        warn_mach = bool(mach_margin is not None and mach_margin <= OverspeedConfig.MACH_WARNING_MARGIN)
        caut_mach = bool(mach_margin is not None and mach_margin <= OverspeedConfig.MACH_CAUTION_MARGIN)

        if crit_ias or crit_mach:
            level = "critical"
            reason = "ias+mach" if crit_ias and crit_mach else ("ias" if crit_ias else "mach")
        elif warn_ias or warn_mach:
            level = "warning"
            reason = "ias+mach" if warn_ias and warn_mach else ("ias" if warn_ias else "mach")
        elif caut_ias or caut_mach:
            level = "caution"
            reason = "ias+mach" if caut_ias and caut_mach else ("ias" if caut_ias else "mach")
        else:
            level = "safe"
            reason = "safe"

        return OverspeedDecision(
            level=level,
            plane_type=str(plane_type or ""),
            resolved_fm=resolved,
            ias_kmh=ias,
            tas_kmh=tas,
            mach=mach_val,
            ias_limit_kmh=ias_limit,
            mach_limit=mach_limit,
            ias_ratio=ias_ratio,
            mach_margin=mach_margin,
            reason=reason,
        )
