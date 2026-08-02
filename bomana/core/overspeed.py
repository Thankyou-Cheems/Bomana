"""Overspeed model identification and alert grading."""

from dataclasses import dataclass
from typing import Any

from bomana.config.settings import OverspeedConfig
from bomana.utils.file_utils import load_json_resource

_NUMERIC_PARSE_ERRORS = (TypeError, ValueError)
_SEQUENCE_NUMERIC_PARSE_ERRORS = (TypeError, ValueError, IndexError)

LimitValue = float | list[list[float]]


@dataclass(frozen=True)
class OverspeedDecision:
    """超速判定结果（逻辑层 -> UI）。"""

    level: str = "unknown"  # unknown/safe/caution/warning/critical
    plane_type: str = ""
    resolved_fm: str = ""
    ias_kmh: float = 0.0
    tas_kmh: float = 0.0
    mach: float | None = None
    ias_limit_kmh: float | None = None
    mach_limit: float | None = None
    ias_ratio: float | None = None  # IAS / ias_limit_kmh
    mach_margin: float | None = None  # mach_limit - mach
    caution_ratio: float = 0.94
    warning_ratio: float = 0.97
    critical_ratio: float = 0.992
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
        self.database_source = ""
        self.unit_to_fm: dict[str, str] = {}
        self.fm_limits: dict[str, dict[str, LimitValue]] = {}
        self._fm_alias: dict[str, str] = {}
        self._aircraft_entries: list[dict[str, Any]] = []
        self._load()

    @staticmethod
    def _normalize_name(name: str) -> str:
        return str(name or "").strip().lower()

    @staticmethod
    def _normalize_fm_reference(value: object) -> str:
        """Normalize Datamine ``fmFile`` references, including legacy /fm paths."""

        text = str(value or "").strip().replace("\\", "/")
        while text.startswith("/"):
            text = text[1:]
        if text.lower().startswith("fm/"):
            text = text[3:]
        lower_text = text.lower()
        if lower_text.endswith(".blkx"):
            text = text[:-5]
        elif lower_text.endswith(".blk"):
            text = text[:-4]
        return text.strip()

    @classmethod
    def _name_variants(cls, name: str) -> list[str]:
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
    def _parse_limit_value(raw: Any) -> LimitValue | None:
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
                    except _SEQUENCE_NUMERIC_PARSE_ERRORS:
                        return None
                pairs.sort(key=lambda x: x[0])
                return pairs
            if len(raw) >= 2 and len(raw) % 2 == 0:
                pairs = []
                for i in range(0, len(raw), 2):
                    try:
                        pairs.append([float(raw[i]), float(raw[i + 1])])
                    except _NUMERIC_PARSE_ERRORS:
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
                            except _NUMERIC_PARSE_ERRORS:
                                return None
                        pairs.sort(key=lambda x: x[0])
                        return pairs
        return None

    @staticmethod
    def _format_aircraft_label(name: str) -> str:
        text = str(name or "").strip().replace("_", " ").replace("  ", " ")
        return text or "未知机型"

    @staticmethod
    def _normalize_search_text(text: str) -> str:
        return str(text or "").lower().replace("_", "").replace("-", "").replace(" ", "")

    @staticmethod
    def _interpolate(points: list[list[float]], sweep: float | None) -> float | None:
        if not points:
            return None

        # 与 WTSpeeder 保持一致：后掠角缺失时取“最大后掠”端限制，减少误报。
        if sweep is None:
            return float(points[-1][1])

        try:
            x = float(sweep)
        except _NUMERIC_PARSE_ERRORS:
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
        result = load_json_resource(
            [OverspeedConfig.LIMITS_FILE],
            missing_error_prefix="limits file not found",
            parse_error_prefix="limits json parse failed",
        )
        if result.error:
            self.load_error = result.error
            return
        if not isinstance(result.payload, dict):
            self.load_error = "limits json schema invalid"
            return

        self.database_source = str(result.path or "")
        payload = result.payload
        unit_map = payload.get("unit_to_fm", {})
        fm_map = payload.get("fm_speed_limits", {})
        if not isinstance(unit_map, dict) or not isinstance(fm_map, dict):
            self.load_error = "limits json schema invalid"
            return

        for unit_name, fm_name in unit_map.items():
            u = self._normalize_name(unit_name)
            f = self._normalize_fm_reference(fm_name)
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

        for fm_name in self.fm_limits:
            for alias in self._name_variants(fm_name):
                self._fm_alias[self._normalize_name(alias)] = fm_name

        fm_to_units: dict[str, set[str]] = {}
        for unit_name, fm_name in self.unit_to_fm.items():
            resolved = self._fm_alias.get(self._normalize_name(fm_name), str(fm_name or "").strip())
            if not resolved:
                continue
            fm_to_units.setdefault(resolved, set()).add(str(unit_name or "").strip())

        self._aircraft_entries = []
        for fm_name in sorted(self.fm_limits.keys()):
            aliases = sorted(alias for alias in fm_to_units.get(fm_name, set()) if alias)
            search_parts = [fm_name, self._format_aircraft_label(fm_name), *aliases]
            self._aircraft_entries.append(
                {
                    "fm_name": fm_name,
                    "display_name": self._format_aircraft_label(fm_name),
                    "aliases": aliases,
                    "search_text": " ".join(search_parts),
                }
            )

        self.loaded = bool(self.fm_limits and self.unit_to_fm)
        if not self.loaded and not self.load_error:
            self.load_error = "limits database empty"

    def resolve_fm_name(self, plane_type: str) -> str | None:
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

    def _value_by_sweep(self, value: LimitValue | None, sweep: float | None) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, list):
            return self._interpolate(value, sweep)
        return None

    def get_limits(
        self, plane_type: str, wing_sweep: float | None
    ) -> tuple[str | None, float | None, float | None]:
        resolved = self.resolve_fm_name(plane_type)
        if resolved is None:
            return None, None, None

        row = self.fm_limits.get(resolved, {})
        ias_limit = self._value_by_sweep(row.get("ias"), wing_sweep)
        mach_limit = self._value_by_sweep(row.get("mach"), wing_sweep)
        return resolved, ias_limit, mach_limit

    def get_aircraft_entries(self) -> list[dict[str, Any]]:
        return [
            {
                "fm_name": entry["fm_name"],
                "display_name": entry["display_name"],
                "aliases": list(entry["aliases"]),
            }
            for entry in self._aircraft_entries
        ]

    def get_aircraft_entry(self, fm_name: str) -> dict[str, Any] | None:
        key = str(fm_name or "").strip()
        for entry in self._aircraft_entries:
            if entry["fm_name"] == key:
                return {
                    "fm_name": entry["fm_name"],
                    "display_name": entry["display_name"],
                    "aliases": list(entry["aliases"]),
                }
        return None

    def search_aircraft(self, query: str, limit: int = 100) -> list[str]:
        if not query:
            return [entry["fm_name"] for entry in self._aircraft_entries[:limit]]

        normalized_query = self._normalize_search_text(query)
        results: list[str] = []
        for entry in self._aircraft_entries:
            search_text = str(entry.get("search_text", "") or "")
            if (
                normalized_query in self._normalize_search_text(search_text)
                or str(query or "").lower() in search_text.lower()
            ):
                results.append(entry["fm_name"])
                if len(results) >= limit:
                    break
        return results


class OverspeedAnalyzer:
    """IAS/Mach 双通道超速分级判定。"""

    def __init__(self):
        self.db = SpeedLimitDatabase()

    def evaluate(
        self,
        plane_type: str,
        ias_kmh: float,
        tas_kmh: float,
        mach: float | None,
        wing_sweep: float | None,
        enabled: bool = True,
    ) -> OverspeedDecision:
        if not OverspeedConfig.ENABLED or not enabled:
            return OverspeedDecision(level="unknown", plane_type=plane_type, reason="disabled")

        if not self.db.loaded:
            return OverspeedDecision(
                level="unknown", plane_type=plane_type, reason=self.db.load_error or "db_not_loaded"
            )

        ias = float(ias_kmh or 0.0)
        tas = float(tas_kmh or 0.0)
        mach_val = None
        if mach is not None:
            try:
                mach_val = float(mach)
            except _NUMERIC_PARSE_ERRORS:
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
        mach_margin = (
            (mach_limit - mach_val) if (mach_limit is not None and mach_val is not None) else None
        )

        thresholds = OverspeedConfig.get_thresholds_for_aircraft(resolved)

        crit_ias = bool(ias_ratio is not None and ias_ratio >= thresholds["critical_ratio"])
        warn_ias = bool(ias_ratio is not None and ias_ratio >= thresholds["warning_ratio"])
        caut_ias = bool(ias_ratio is not None and ias_ratio >= thresholds["caution_ratio"])

        crit_mach = bool(
            mach_margin is not None and mach_margin <= thresholds["mach_critical_margin"]
        )
        warn_mach = bool(
            mach_margin is not None and mach_margin <= thresholds["mach_warning_margin"]
        )
        caut_mach = bool(
            mach_margin is not None and mach_margin <= thresholds["mach_caution_margin"]
        )

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
            caution_ratio=thresholds["caution_ratio"],
            warning_ratio=thresholds["warning_ratio"],
            critical_ratio=thresholds["critical_ratio"],
            reason=reason,
        )
