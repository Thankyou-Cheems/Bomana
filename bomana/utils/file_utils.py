"""File/config helpers."""

import contextlib
import json
import math
import os
import sys
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bomana.config.feature_profile import (
    ENABLE_ADVANCED_SETTINGS,
    ENABLE_AIRFIELDS,
    ENABLE_CCRP,
    ENABLE_CHECKLIST,
    ENABLE_FUEL,
    ENABLE_WEB_DASHBOARD,
    ENABLE_ZONES,
)
from bomana.config.settings import (
    FileConfig,
    GameConfig,
)
from bomana.utils.diagnostics import log_event, log_exception


def _report_persistence_error(action: str, path: Path, exc: Exception) -> None:
    """Emit persistence diagnostics without changing tolerant runtime behavior."""
    log_exception(
        "persistence_error",
        exc,
        action=action,
        path=str(path),
    )
    try:
        log_path = FileConfig.CONFIG_FILE.with_name(".wttimer_persistence.log")
        with open(log_path, "a", encoding="utf-8") as f:
            msg = f"[Persistence] {action} failed for {path}: {exc}"
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except OSError:
        pass


def atomic_write_json(path: Path, payload: Any, *, ensure_ascii: bool = False) -> None:
    """Atomically write JSON by replacing the target from the same directory."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as f:
            temp_path = Path(f.name)
            json.dump(payload, f, indent=2, ensure_ascii=ensure_ascii)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            with contextlib.suppress(FileNotFoundError):
                temp_path.unlink()


def resource_path(rel_path: str) -> str:
    """获取资源文件的绝对路径

    支持PyInstaller打包，打包后资源在_MEIPASS临时目录。

    Args:
        rel_path: 相对路径（如 "bomana/assets/branding/app.ico"）

    Returns:
        绝对路径字符串
    """
    runtime_root = os.environ.get("BOMANA_RUNTIME_ROOT", "").strip()
    module_root = str(Path(__file__).resolve().parents[2])
    cwd_root = os.getcwd()
    candidates = []
    if runtime_root:
        candidates.append(runtime_root)
    # Prefer the actual app/module directory before PyInstaller temp roots.
    for base in (module_root, cwd_root):
        if base and base not in candidates:
            candidates.append(base)
    if hasattr(sys, "_MEIPASS"):
        mei_root = str(sys._MEIPASS)
        if mei_root and mei_root not in candidates:
            candidates.append(mei_root)
    if not candidates:
        candidates.append(module_root)

    for base in candidates:
        full_path = os.path.join(base, rel_path)
        if os.path.exists(full_path):
            return full_path
    return os.path.join(candidates[0], rel_path)


@dataclass(slots=True)
class JsonResourceLoadResult:
    """Resolved JSON resource metadata and payload."""

    payload: Any | None = None
    path: Path | None = None
    source_label: str = ""
    error: str = ""


def resolve_existing_resource(rel_paths: Sequence[str]) -> tuple[Path | None, str]:
    """Resolve the first existing runtime-aware resource path from a list of candidates."""
    seen: set[Path] = set()
    first_candidate: Path | None = None
    first_label = ""

    for rel_path in rel_paths:
        candidate = Path(resource_path(rel_path))
        if first_candidate is None:
            first_candidate = candidate
            first_label = rel_path
        if candidate in seen:
            continue
        seen.add(candidate)
        if candidate.exists():
            return candidate, rel_path
    return first_candidate, first_label


def load_json_resource(
    rel_paths: Sequence[str],
    *,
    missing_error_prefix: str,
    parse_error_prefix: str,
) -> JsonResourceLoadResult:
    """Load JSON from a runtime-aware resource path with consistent diagnostics."""
    path, label = resolve_existing_resource(rel_paths)
    if path is None or not path.exists():
        return JsonResourceLoadResult(
            path=path,
            source_label=label,
            error=f"{missing_error_prefix}: {path}" if path is not None else missing_error_prefix,
        )

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return JsonResourceLoadResult(
            path=path,
            source_label=label,
            error=f"{parse_error_prefix}: {exc}",
        )

    return JsonResourceLoadResult(
        payload=payload,
        path=path,
        source_label=label,
        error="",
    )


class ConfigManager:
    """配置文件管理器

    负责从JSON文件读写用户配置，如窗口位置、透明度等。
    v6.0.1: 新增配置版本管理，自动迁移旧配置
    """

    @staticmethod
    def _current_compile_switches() -> dict[str, bool]:
        return {
            "ENABLE_CCRP": ENABLE_CCRP,
            "ENABLE_ZONES": ENABLE_ZONES,
            "ENABLE_AIRFIELDS": ENABLE_AIRFIELDS,
            "ENABLE_FUEL": ENABLE_FUEL,
            "ENABLE_CHECKLIST": ENABLE_CHECKLIST,
            "ENABLE_ADVANCED_SETTINGS": ENABLE_ADVANCED_SETTINGS,
            "ENABLE_WEB_DASHBOARD": ENABLE_WEB_DASHBOARD,
        }

    @staticmethod
    def load() -> dict[str, Any]:
        """加载配置文件

        Returns:
            配置字典，加载失败返回空字典
        """
        if FileConfig.CONFIG_FILE.exists():
            try:
                with open(FileConfig.CONFIG_FILE, encoding="utf-8") as f:
                    config = json.load(f)
                if not isinstance(config, dict):
                    raise ValueError("config root must be a JSON object")
                # 配置版本迁移仅更新内存对象；显式保存路径负责落盘。
                old_version = config.get("config_version", 1)
                config, changed = ConfigManager._migrate_config(config)
                if changed:
                    log_event(
                        "config_migrated",
                        path=str(FileConfig.CONFIG_FILE),
                        from_version=old_version,
                        to_version=config.get("config_version", old_version),
                    )
                return config
            except (json.JSONDecodeError, TypeError, ValueError, OSError) as exc:
                _report_persistence_error("config load", FileConfig.CONFIG_FILE, exc)
        return {}

    @staticmethod
    def _migrate_config(config: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """配置版本迁移

        处理旧版本配置的兼容性问题，自动升级配置结构
        v6.1.1: 添加编译开关状态记简版/完整版配置冲突
        """
        version = config.get("config_version", 1)
        changed = False

        panels_raw = config.get("panels", {})
        if isinstance(panels_raw, dict):
            panels = panels_raw
        else:
            panels = {}
            config["panels"] = panels
            changed = True

        # v1 -> v2: 添加投弹面板配置
        if version < 2:
            if "show_bombing" not in panels:
                panels["show_bombing"] = True
                changed = True
            config["panels"] = panels
            config["config_version"] = 2
            changed = True

        # v2 -> v3: 添加编译开关状态记录
        if version < 3:
            config["config_version"] = 3
            changed = True

        # 检查编译开关是否变化（精简版 <-> 完整版切换）
        saved_switches_raw = config.get("compile_switches")
        has_saved_switches = isinstance(saved_switches_raw, dict)
        saved_switches = saved_switches_raw if has_saved_switches else {}
        current_switches = ConfigManager._current_compile_switches()

        # 如果某个功能从禁用变为启用，重置该面板为默认显示
        switches_changed = False

        if has_saved_switches:
            for switch_name, current_enabled in current_switches.items():
                was_enabled = saved_switches.get(switch_name)
                if current_enabled and was_enabled is False:
                    # 功能从禁用变为启用，重置对应面板为显示
                    panel_key = {
                        "ENABLE_CCRP": "show_bombing",
                        "ENABLE_ZONES": "show_zones",
                        "ENABLE_AIRFIELDS": "show_airfields",
                        "ENABLE_FUEL": "show_fuel",
                        "ENABLE_CHECKLIST": "show_checklist",
                    }.get(switch_name)
                    if panel_key:
                        panels[panel_key] = True
                        switches_changed = True
                        changed = True

        if switches_changed:
            config["panels"] = panels

        # 更新保存的编译开关状态
        if saved_switches != current_switches:
            config["compile_switches"] = current_switches
            changed = True

        return config, changed

    @staticmethod
    def save(config: dict[str, Any]) -> bool:
        """保存配置文件

        Args:
            config: 配置字典
        """
        try:
            # 确保保存时带有版本号
            config["config_version"] = FileConfig.CONFIG_VERSION
            config["compile_switches"] = ConfigManager._current_compile_switches()
            atomic_write_json(FileConfig.CONFIG_FILE, config, ensure_ascii=False)
            return True
        except (TypeError, ValueError, OSError) as exc:
            _report_persistence_error("config save", FileConfig.CONFIG_FILE, exc)
            return False


class StateManager:
    """状态文件管理器

    保存/恢复当前计时状态，支持应用重启后继续计时。
    原理：记录剩余时间和保存时刻，重启后计算实际流逝时间。
    """

    @staticmethod
    def save(
        remaining_sec: float,
        life_index: int,
        sortie_id: int,
        battle_signature: str,
    ) -> None:
        """保存当前状态

        Args:
            remaining_sec: 剩余秒数
            life_index: 复活次数
            sortie_id: 出击次数（补给计数器）
            battle_signature: 当前战局上下文指纹
        """
        state_data = {
            "remaining_sec": remaining_sec,
            "save_timestamp": time.time(),
            "life_index": life_index,
            "sortie_id": sortie_id,
            "battle_signature": battle_signature,
            "battle_signature_version": 1,
            "cycle_seconds": GameConfig.CYCLE_SECONDS,
        }
        try:
            atomic_write_json(FileConfig.STATE_FILE, state_data, ensure_ascii=False)
        except (TypeError, ValueError, OSError) as exc:
            _report_persistence_error("state save", FileConfig.STATE_FILE, exc)

    @staticmethod
    def _read_finite_float(data: dict[str, Any], key: str) -> float:
        value = float(data.get(key, 0.0))
        if not math.isfinite(value):
            raise ValueError(f"{key} must be finite")
        return value

    @staticmethod
    def _normalize_optional_int(data: dict[str, Any], key: str) -> None:
        if key in data and data[key] is not None:
            data[key] = int(data[key])

    @staticmethod
    def load() -> dict[str, Any] | None:
        """加载并计算恢复后的状态

        Returns:
            包含计算后状态的字典，或None（如果无法恢复）
        """
        if not FileConfig.STATE_FILE.exists():
            return None
        try:
            with open(FileConfig.STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("state root must be a JSON object")

            # 提取保存时的剩余时间和时间戳
            saved_remaining = StateManager._read_finite_float(data, "remaining_sec")
            save_time = StateManager._read_finite_float(data, "save_timestamp")
            StateManager._normalize_optional_int(data, "life_index")
            StateManager._normalize_optional_int(data, "sortie_id")
            data["remaining_sec"] = saved_remaining
            data["save_timestamp"] = save_time

            raw_cycle_seconds = data.get("cycle_seconds")
            if raw_cycle_seconds is None:
                saved_cycle_seconds = GameConfig.LEGACY_CYCLE_SECONDS
                if GameConfig.CYCLE_SECONDS != GameConfig.LEGACY_CYCLE_SECONDS:
                    return None
            else:
                if isinstance(raw_cycle_seconds, bool) or not isinstance(raw_cycle_seconds, int):
                    raise ValueError("cycle_seconds must be an integer")
                saved_cycle_seconds = raw_cycle_seconds
                if saved_cycle_seconds != GameConfig.CYCLE_SECONDS:
                    return None
            data["cycle_seconds"] = saved_cycle_seconds

            # 计算实际流逝的时间
            now = time.time()
            elapsed_since_save = now - save_time
            new_remaining = saved_remaining - elapsed_since_save

            # 如果过期太久（超过一个完整周期），放弃恢复
            if new_remaining < -GameConfig.CYCLE_SECONDS:
                return None

            # 如果时间为负（已进入下一周期），计算新周期的剩余时间
            if new_remaining < 0:
                overshoot = abs(new_remaining)
                new_remaining = GameConfig.CYCLE_SECONDS - overshoot

            # 反推出生时间
            data["computed_remaining"] = new_remaining
            data["computed_spawn_time"] = now - (GameConfig.CYCLE_SECONDS - new_remaining)

            return data
        except (json.JSONDecodeError, TypeError, ValueError, KeyError, OSError) as exc:
            _report_persistence_error("state load", FileConfig.STATE_FILE, exc)
            return None

    @staticmethod
    def clear(report_error: bool = True) -> None:
        """清除状态文件"""
        try:
            if FileConfig.STATE_FILE.exists():
                FileConfig.STATE_FILE.unlink()
        except OSError as exc:
            if report_error:
                _report_persistence_error("state clear", FileConfig.STATE_FILE, exc)
