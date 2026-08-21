"""Main Tk app container."""

import contextlib
import ctypes
import time
import tkinter as tk
import webbrowser
from enum import Enum
from tkinter import font as tkfont
from tkinter import messagebox, simpledialog
from typing import Any

from bomana.config.feature_profile import (
    ENABLE_AIRFIELDS,
    ENABLE_CCRP,
    ENABLE_CHECKLIST,
    ENABLE_FUEL,
    ENABLE_WEB_DASHBOARD,
    ENABLE_ZONES,
)
from bomana.config.settings import (
    AboutConfig,
    BombConfig,
    ChecklistConfig,
    FileConfig,
    GameConfig,
    HotkeyConfig,
    OverspeedConfig,
    PanelConfig,
    SnapConfig,
    SoundConfig,
    UIConfig,
    WeaponBallisticModelConfig,
)
from bomana.core.logic import GameLogic
from bomana.core.state import Phase, UISnapshot
from bomana.ui.debug_support import AppDebugSupport
from bomana.ui.dialogs import (
    AboutDialog,
    ChecklistEditor,
    SettingsDialog,
    WeaponSelectorDialog,
    build_weapon_selector_scope,
    persist_ballistic_model_selection,
    persist_weapon_selection,
)
from bomana.ui.icon_assets import IconManager
from bomana.ui.main_window import MainWindowBuilder
from bomana.ui.navigation_runtime import AppNavigationServices
from bomana.ui.panel_presenter import (
    build_speed_history_header_model,
    overspeed_dynamic_projection,
)
from bomana.ui.panel_renderer import AppPanelRenderer
from bomana.ui.runtime import LogicPoller, TkEventDispatcher
from bomana.ui.runtime_services import HAS_TRAY, AppRuntimeServices
from bomana.ui.snapshot_presenter import build_status_presentation
from bomana.ui.strike_encyclopedia import StrikeEncyclopediaDialog
from bomana.ui.strike_prediction import create_strike_prediction_ui
from bomana.ui.theme import Theme
from bomana.ui.tk_style import style_action_button
from bomana.ui.window_geometry import (
    apply_snap_anchor,
    capture_snap_anchor,
)
from bomana.utils.diagnostics import log_event, log_exception
from bomana.utils.file_utils import ConfigManager, resource_path
from bomana.utils.math_utils import calculate_smart_scale
from bomana.utils.sound import SoundManager
from bomana.utils.system import SingleInstanceManager, Win32, resolve_tk_font_tuple

if ENABLE_WEB_DASHBOARD:
    from bomana.web.control import (
        ControlStateProjection,
        ControlTargetState,
        PanelVisibility,
        WeaponChoice,
        WebCommandEnvelope,
    )
else:

    class ControlStateProjection:
        pass

    class ControlTargetState:
        pass

    class PanelVisibility:
        pass

    class WeaponChoice:
        pass

    class WebCommandEnvelope:
        pass


def fmt_time(sec: float | None) -> str:
    """格式化时间为 MM:SS 格式"""
    if sec is None:
        return "--:--"
    sec = max(0, int(sec))
    m, s = divmod(sec, 60)
    return f"{m:02d}:{s:02d}"


class Corner(Enum):
    """窗口角落位置枚举"""

    TOP_RIGHT = 0
    TOP_LEFT = 1
    BOTTOM_RIGHT = 2
    BOTTOM_LEFT = 3


# ============================================================================
# 主应用类
# ============================================================================


class App:
    """主应用类

    职责：
    1. 创建和管理UI窗口
    2. 启动游戏逻辑线程
    3. 处理用户交互（热键、拖动、菜单）
    4. 刷新UI显示（20fps）

    架构：
    - UI线程：tkinter主循环
    - 逻辑线程：GameLogic.tick()循环（250ms）
    - 通过UISnapshot传递数据（无锁读取）
    """

    _STARTUP_GEOMETRY_SETTLE_DELAYS_MS = (250, 750)

    def __init__(self, root: tk.Tk):
        self.root = root
        self.game = GameLogic()
        self.sound = SoundManager()
        self.dispatcher = TkEventDispatcher(root)
        self.icons = IconManager(root)
        self.logic_poller = LogicPoller(self.game, lambda: self._stop)
        self.navigation_services = AppNavigationServices(self)
        self.bombing_services = create_strike_prediction_ui(self)
        self.runtime_services = AppRuntimeServices(self)

        # 控制标志
        self._stop = False
        self._corner = Corner.TOP_RIGHT
        self._locked = True
        self._debug = False
        self._debug_force_mock = True
        self._debug_scene_index = 0
        self._debug_frame_counter = 0
        self._debug_live_available = False
        self._debug_effective_mock = False
        self._debug_scene_names = [
            "巡航导航",
            "偏航修正",
            "低油返航",
            "CCRP",
            "地面检查",
            "超速压测",
        ]
        self._alive_phases = (Phase.ALIVE, Phase.LOSS_PENDING)
        self._last_beep_sec = -1
        self._last_overspeed_sound_ts = 0.0
        self._last_overspeed_level = "unknown"
        self._zone_sound_enabled = True
        self._manual_reset_confirm_until = 0.0
        self._web_control_revision = 0
        self._web_control_signature: tuple[Any, ...] | None = None
        self._web_weapon_choices_cache_key: tuple[Any, ...] | None = None
        self._web_weapon_choices_cache: tuple[WeaponChoice, ...] = ()

        # 窗口状态
        self._user_moved = False
        self._manual_pos = None
        self._saved_monitor_index = None
        self._last_sortie_id = -1
        self._restored_state = False
        self._last_zone_destroyed_alert = False
        self._last_landed_flash = False
        self._nudge_visible = False
        self._nudge_sortie_id = -1
        self._nudge_airborne_seen = False
        self._nudge_sortie_seen = -1
        self._hotkey_broker_notice = ""
        self._hotkey_broker_action = ""
        # 初始缩放占位：_init_window_base 后会用DPI重新计算
        self.scale = float(UIConfig.UI_SCALE_MULT)
        self._hint_width_cache = {"text": "", "width": int(380 * self.scale)}

        # UI刷新控制
        self._ui_after_id = None
        self._last_ui_frame_ts = 0.0
        self._last_ui_gap_ms = 0.0
        self._last_ui_work_ms = 0.0

        # 布局可见性
        self._zone_panel_visible = False
        self._checklist_panel_visible = False

        # 性能优化: 字体缓存和Label复用池
        self._cached_fonts: dict[str, tuple] = {}
        self._zone_row_pool: list[Any] = []
        self._compact_zone_row_pool: list[Any] = []
        self._airport_row_pool: list[Any] = []
        self._compact_airport_row_pool: list[Any] = []
        self._last_layout_signature = None
        self._last_expand_ts = 0.0
        self._last_zone_recalc_ts = 0.0
        self._geometry_sync_after_id = None
        self._startup_geometry_after_id = None
        self._zone_layout_mode = None
        self._airport_layout_mode = None
        self._history_mode_layout_active = False
        self.debug_support = AppDebugSupport(self)
        self.panel_renderer = AppPanelRenderer(self)

        # 初始化流程
        self._load_config()
        self._init_window_base()
        self._apply_font_family()
        self._init_ui()
        self._finalize_window_geometry_and_styles()
        self._init_bindings()
        self._init_global_hotkeys()

        # v6.2.1: 初始化独立导航窗口（仅在战区功能启用时）
        self.navigation_services.init_window()
        self.bombing_services.init_window()

        # 恢复状态并启动
        self._restored_state = self.game.restore_timer_state()
        self.logic_poller.start()
        self.runtime_services.start_terrain_map_tracking()
        if ENABLE_WEB_DASHBOARD:
            self._publish_web_control_state(force_revision=True)
            if self.runtime_services.dashboard_autostart_enabled():
                dashboard_started = self.runtime_services.init_dashboard()
                if dashboard_started and self.runtime_services.dashboard_lan_autostart_enabled():
                    try:
                        self.runtime_services.enable_dashboard_lan()
                    except Exception as exc:
                        log_exception("web_dashboard_lan_autostart_failed", exc)
                        messagebox.showwarning(
                            "局域网网页服务未开启",
                            f"本机网页服务已启动，但自动开启局域网访问与控制失败：\n{exc}",
                            parent=self.root,
                        )
                if dashboard_started and self.runtime_services.dashboard_auto_open_enabled():
                    self._open_web_dashboard()
            self._refresh_web_access_row()
        self._update_ui()

        if HAS_TRAY:
            self._init_tray()

    def _get_weapon_catalog(self):
        """Reuse GameLogic's one validated catalog load, including its None fallback."""

        game = getattr(self, "game", None)
        if game is not None and hasattr(game, "weapon_catalog"):
            return game.weapon_catalog
        # Headless config tests and legacy embedders may not construct GameLogic.
        return None

    @staticmethod
    def _web_display_name(record: dict[str, Any]) -> str:
        value = (
            record.get("display_name_zh")
            or record.get("display_name")
            or record.get("id")
            or "未命名武器"
        )
        return " ".join(str(value).split())[:256] or "未命名武器"

    def _build_web_control_projection(
        self,
        *,
        revision: int,
        snapshot: UISnapshot | None = None,
    ) -> ControlStateProjection:
        commands = [
            "action.reset_timer",
            "action.cycle_corner",
            "state.set_locked",
            "state.set_beep_enabled",
            "config.set_panel_visibility",
            "config.set_timer_cycle_minutes",
            "navigation.set_poi",
            "network.set_lan_enabled",
        ]
        panel_targets = ["speed"]
        if ENABLE_ZONES:
            commands.append("state.set_zone_sound_enabled")
            panel_targets.append("zones")
        if ENABLE_AIRFIELDS:
            panel_targets.append("airfields")
        if ENABLE_FUEL:
            panel_targets.append("fuel")
        if ENABLE_CHECKLIST:
            panel_targets.append("checklist")
        if ENABLE_CCRP:
            commands.extend(("weapon.select", "weapon.set_ballistic_model"))
            panel_targets.append("weapon_solution")

        catalog = self._get_weapon_catalog() if ENABLE_CCRP else None
        selected_weapon_id = ""
        weapon_choices: list[WeaponChoice] = []
        if catalog is not None:
            selected_weapon_id = str(catalog.selected_weapon_id or "")[:128]
            snap = snapshot or self.game.snapshot()
            airborne = snap.phase == Phase.ALIVE and not snap.on_ground
            aircraft = str(getattr(snap, "aircraft_type_name", "") or "")
            cache_key = (id(catalog), selected_weapon_id, airborne, aircraft)
            if cache_key == getattr(self, "_web_weapon_choices_cache_key", None):
                weapon_choices.extend(getattr(self, "_web_weapon_choices_cache", ()))
            else:
                records, _note, _compatible_only = build_weapon_selector_scope(
                    catalog,
                    aircraft_type_name=aircraft,
                    airborne=airborne,
                )
                for record in records[:512]:
                    weapon_id = str(record.get("id") or "")[:128]
                    if not weapon_id:
                        continue
                    compatible = not airborne or bool(
                        aircraft and catalog.compatible(weapon_id, aircraft)
                    )
                    weapon_choices.append(
                        WeaponChoice(
                            weapon_id=weapon_id,
                            display_name=self._web_display_name(record),
                            role=(" ".join(str(record.get("role") or "unknown").split())[:64]),
                            compatible=compatible,
                            selected=weapon_id == selected_weapon_id,
                        )
                    )
                self._web_weapon_choices_cache_key = cache_key
                self._web_weapon_choices_cache = tuple(weapon_choices)

        ballistic_model = WeaponBallisticModelConfig.selected_model
        if ballistic_model not in WeaponBallisticModelConfig.VALID_MODELS:
            ballistic_model = WeaponBallisticModelConfig.DEFAULT_MODEL
        target_state = ControlTargetState(
            locked=bool(self._locked),
            beep_enabled=bool(self.sound.is_enabled()),
            zone_sound_enabled=bool(self._zone_sound_enabled) if ENABLE_ZONES else False,
            panel_visibility=PanelVisibility(
                zones=bool(ENABLE_ZONES and PanelConfig.show_zones),
                airfields=bool(ENABLE_AIRFIELDS and PanelConfig.show_airfields),
                fuel=bool(ENABLE_FUEL and PanelConfig.show_fuel),
                speed=bool(PanelConfig.show_speed),
                checklist=bool(ENABLE_CHECKLIST and PanelConfig.show_checklist),
                weapon_solution=bool(ENABLE_CCRP and PanelConfig.show_bombing),
            ),
            selected_weapon_id=selected_weapon_id,
            ballistic_model=ballistic_model,
            timer_cycle_minutes=GameConfig.cycle_minutes(),
        )
        runtime_services = getattr(self, "runtime_services", None)
        dashboard = getattr(runtime_services, "dashboard", None) if runtime_services else None
        lan_enabled = bool(dashboard is not None and dashboard.lan_enabled)
        lan_urls: tuple[str, ...] = ()
        if lan_enabled and dashboard is not None:
            lan_urls = tuple(
                str(url)[:256]
                for url in dashboard.lan_pairing_urls[:16]
                if isinstance(url, str) and url
            )
        return ControlStateProjection(
            revision=revision,
            commands=tuple(commands),
            panel_targets=tuple(panel_targets),
            state=target_state,
            weapons=tuple(weapon_choices),
            lan_enabled=lan_enabled,
            lan_pairing_urls=lan_urls,
        )

    def _publish_web_control_state(
        self,
        *,
        snapshot: UISnapshot | None = None,
        force_revision: bool = False,
    ) -> int:
        if not ENABLE_WEB_DASHBOARD:
            return 0
        if not hasattr(self, "_web_control_revision"):
            self._web_control_revision = 0
        if not hasattr(self, "_web_control_signature"):
            self._web_control_signature = None
        candidate = self._build_web_control_projection(
            revision=max(1, self._web_control_revision),
            snapshot=snapshot,
        )
        signature = (
            candidate.commands,
            candidate.panel_targets,
            candidate.state,
            candidate.weapons,
            candidate.lan_enabled,
            candidate.lan_pairing_urls,
        )
        if force_revision or self._web_control_signature != signature:
            self._web_control_revision += 1
            candidate = self._build_web_control_projection(
                revision=self._web_control_revision,
                snapshot=snapshot,
            )
            self.runtime_services.publish_dashboard_control(candidate)
            self._web_control_signature = (
                candidate.commands,
                candidate.panel_targets,
                candidate.state,
                candidate.weapons,
                candidate.lan_enabled,
                candidate.lan_pairing_urls,
            )
        return self._web_control_revision

    @property
    def nav_window(self):
        """Compatibility view for dialog code that inspects the standalone nav surface."""
        return self.navigation_services.window

    def _load_config(self):
        """加载用户配置

        加载顺序: 主题必须在UI创建前应用
        配置项: alpha/scale/theme/panels/hotkey_bindings/snap/window_position
        """
        config = ConfigManager.load()

        # 显示设置
        alpha = config.get("alpha", UIConfig.WINDOW_ALPHA)
        if isinstance(alpha, (int, float)):
            UIConfig.WINDOW_ALPHA = max(30, min(255, int(alpha)))
        # v5.9.3: 智能缩放逻辑
        # 检查是否是首次启动（没有保存的缩放配置）
        if "scale" in config:
            # 用户已经设置过缩放，使用保存的值
            scale = config.get("scale")
            if isinstance(scale, (int, float)):
                UIConfig.UI_SCALE_MULT = UIConfig.clamp_ui_scale(scale)
        else:
            # 首次启动，根据屏幕分辨率智能设置
            try:
                sw, sh = Win32.screen_size()
                # 临时获取DPI缩放（此时窗口还未创建，使用默认值1.2）
                smart_scale = calculate_smart_scale(sw, sh, 1.2)
                UIConfig.UI_SCALE_MULT = smart_scale
                log_event(
                    "smart_scale_detected",
                    screen_width=sw,
                    screen_height=sh,
                    scale=smart_scale,
                )
            except Exception as e:
                # 出错时使用默认值1.2
                UIConfig.UI_SCALE_MULT = 1.2
                log_exception("smart_scale_failed", e, fallback_scale=1.2)

        text_scale = config.get("text_scale", UIConfig.TEXT_SCALE_MULT)
        if isinstance(text_scale, (int, float)):
            UIConfig.TEXT_SCALE_MULT = UIConfig.clamp_text_scale(text_scale)

        # 主题设置（必须在UI创建前应用）
        Theme.apply_or_default(config.get("theme", Theme.DEFAULT))

        # 面板显示设置
        panels = config.get("panels", {})
        PanelConfig.show_zones = panels.get("show_zones", True)
        PanelConfig.show_airfields = panels.get("show_airfields", True)
        PanelConfig.show_fuel = panels.get("show_fuel", True)
        PanelConfig.show_speed = panels.get("show_speed", True)
        PanelConfig.speed_history_mode = panels.get("speed_history_mode", False)
        PanelConfig.show_checklist = panels.get("show_checklist", True)
        PanelConfig.show_bombing = panels.get("show_bombing", True)  # v6.0 新增
        bombing_mode = str(config.get("bombing_mode", "integrated") or "").strip().lower()
        PanelConfig.bombing_mode = (
            bombing_mode if bombing_mode in {"integrated", "standalone"} else "integrated"
        )
        PanelConfig.bombing_window_pos = None
        bombing_pos = config.get("bombing_window_pos")
        if isinstance(bombing_pos, list) and len(bombing_pos) == 2:
            PanelConfig.bombing_window_pos = tuple(bombing_pos)

        timer_minutes = GameConfig.normalize_cycle_minutes(config.get("timer_cycle_minutes"))
        GameConfig.set_cycle_minutes(
            timer_minutes if timer_minutes is not None else GameConfig.DEFAULT_CYCLE_MINUTES
        )

        # v6.2.1: 导航条模式（仅在战区功能启用时生效）
        if ENABLE_ZONES:
            PanelConfig.navigation_mode = config.get("navigation_mode", "integrated")
            nav_pos = config.get("navigation_window_pos")
            if nav_pos and isinstance(nav_pos, list) and len(nav_pos) == 2:
                PanelConfig.navigation_window_pos = tuple(nav_pos)
            # 独立导航栏宽度
            nav_width = config.get("navigation_bar_width")
            if nav_width and isinstance(nav_width, (int, float)):
                PanelConfig.navigation_bar_width = max(0.5, min(2.0, float(nav_width)))
            nav_scale = config.get("navigation_bar_scale")
            if nav_scale and isinstance(nav_scale, (int, float)):
                PanelConfig.navigation_bar_scale = PanelConfig.clamp_navigation_scale(nav_scale)
        else:
            # 精简版强制使用集成模式，忽略配置文件中的设置
            PanelConfig.navigation_mode = "integrated"

        # 武器解算沿用 CCRP 编译开关；精简构建不会触发目录懒加载。
        if ENABLE_CCRP:
            BombConfig.set_target_mode(
                BombConfig.normalize_target_mode(config.get("bombing_target_mode", "zone"))
            )
            requested_model = config.get(
                "weapon_ballistic_model",
                WeaponBallisticModelConfig.DEFAULT_MODEL,
            )
            if not WeaponBallisticModelConfig.set_selected(requested_model):
                WeaponBallisticModelConfig.set_selected(WeaponBallisticModelConfig.DEFAULT_MODEL)
            game_state = getattr(getattr(self, "game", None), "state", None)
            if game_state is not None:
                game_state.weapon_model = WeaponBallisticModelConfig.selected_model
            selected_bomb = config.get("selected_bomb", "su_fab100")
            if BombConfig.get_bomb_data(selected_bomb):
                BombConfig.selected_bomb = selected_bomb

            weapon_catalog = self._get_weapon_catalog()
            if weapon_catalog is not None:
                selected_weapon = config.get("selected_weapon")
                if not isinstance(selected_weapon, str) or not selected_weapon.strip():
                    selected_weapon = selected_bomb
                selected_weapon = str(selected_weapon).strip()
                selection_candidates = (
                    selected_weapon,
                    BombConfig.get_bomb_catalog_id(selected_weapon),
                    str(selected_bomb or "").strip(),
                    BombConfig.get_bomb_catalog_id(str(selected_bomb or "")),
                )
                for candidate in dict.fromkeys(selection_candidates):
                    if candidate and weapon_catalog.set_selected(candidate, source="manual"):
                        break

                weapon = weapon_catalog.selected_weapon or {}
                weapon_id = str(weapon.get("id") or weapon_catalog.selected_weapon_id or "")
                if weapon.get("role") == "bomb" and BombConfig.get_bomb_data(weapon_id):
                    BombConfig.selected_bomb = weapon_id

        # 根据编译开关初始化面板状态
        PanelConfig.init_from_compile_switches()

        # 快捷键设置
        HotkeyConfig.GLOBAL_HOTKEYS = config.get("global_hotkeys", HotkeyConfig.GLOBAL_HOTKEYS)
        hotkey_bindings = config.get("hotkey_bindings", {})
        if hotkey_bindings:
            HotkeyConfig.set_bindings(hotkey_bindings)

        # 吸附设置
        SnapConfig.enabled = config.get("snap_enabled", True)
        snap_dist = config.get("snap_distance", 20)
        if isinstance(snap_dist, (int, float)):
            SnapConfig.SNAP_DISTANCE = max(5, min(200, int(snap_dist)))

        # 检查清单
        self.chk_items = config.get("checklist_items", ChecklistConfig.DEFAULT_ITEMS.copy())
        self._zone_sound_enabled = config.get("zone_sound_enabled", True)
        saved_locked = config.get("locked", True)
        self._locked = saved_locked if isinstance(saved_locked, bool) else True

        # 恢复窗口位置（支持多显示器）
        saved_pos = config.get("window_position")
        if saved_pos and isinstance(saved_pos, dict):
            corner_name = saved_pos.get("corner")
            if corner_name:
                with contextlib.suppress(KeyError):
                    self._corner = Corner[corner_name]
            manual_pos = saved_pos.get("manual_pos")
            if manual_pos and isinstance(manual_pos, list) and len(manual_pos) == 2:
                self._manual_pos = tuple(manual_pos)
                self._user_moved = saved_pos.get("user_moved", False)
            # 记录显示器索引（用于多显示器支持）
            saved_monitor_index = saved_pos.get("monitor_index")
            self._saved_monitor_index = (
                saved_monitor_index if isinstance(saved_monitor_index, int) else None
            )
        else:
            self._saved_monitor_index = None

        beep_enabled = config.get("beep_enabled", False)
        self.sound.set_enabled(beep_enabled)
        SoundConfig.apply_user_config(config.get("sound_settings", {}))

        OverspeedConfig.apply_user_config(config.get("overspeed", {}))

    def _save_config(self, *, warn_on_failure: bool = False) -> bool:
        """保存用户配置"""
        config = ConfigManager.load()

        # 显示设置
        config["alpha"] = UIConfig.WINDOW_ALPHA
        config["scale"] = UIConfig.UI_SCALE_MULT
        config["text_scale"] = UIConfig.TEXT_SCALE_MULT
        config["theme"] = Theme.get_current()

        # 面板设置
        panels_config = {
            "show_zones": PanelConfig.show_zones,
            "show_airfields": PanelConfig.show_airfields,
            "show_fuel": PanelConfig.show_fuel,
            "show_speed": PanelConfig.show_speed,
            "speed_history_mode": PanelConfig.speed_history_mode,
            "show_checklist": PanelConfig.show_checklist,
        }
        # v6.0 新增：投弹预测面板（仅在CCRP启用时保存）
        if ENABLE_CCRP:
            panels_config["show_bombing"] = PanelConfig.show_bombing
        config["panels"] = panels_config
        config["timer_cycle_minutes"] = GameConfig.cycle_minutes()

        # v6.2.1: 导航条模式
        config["navigation_mode"] = PanelConfig.navigation_mode
        if PanelConfig.navigation_window_pos:
            config["navigation_window_pos"] = list(PanelConfig.navigation_window_pos)
        config["navigation_bar_width"] = PanelConfig.navigation_bar_width
        config["navigation_bar_scale"] = PanelConfig.navigation_bar_scale
        if ENABLE_CCRP:
            config["bombing_mode"] = PanelConfig.bombing_mode
            config["bombing_target_mode"] = BombConfig.normalize_target_mode(BombConfig.target_mode)
            if PanelConfig.bombing_window_pos:
                config["bombing_window_pos"] = list(PanelConfig.bombing_window_pos)
            else:
                config.pop("bombing_window_pos", None)

        # 武器选择与兼容的 CCRP 炸弹选择同时持久化。
        if ENABLE_CCRP:
            config["weapon_ballistic_model"] = WeaponBallisticModelConfig.selected_model
            weapon_catalog = self._get_weapon_catalog()
            if weapon_catalog is not None:
                selected_weapon_id = str(weapon_catalog.selected_weapon_id or "").strip()
                selected_weapon = weapon_catalog.selected_weapon or {}
                if selected_weapon.get("role") == "bomb" and BombConfig.get_bomb_data(
                    selected_weapon_id
                ):
                    BombConfig.selected_bomb = selected_weapon_id
                if selected_weapon_id:
                    config["selected_weapon"] = selected_weapon_id
            config["selected_bomb"] = BombConfig.selected_bomb
            config.pop("ccrp_tuning", None)

        # 清理旧版本实验性桌面 HUD 的遗留配置。
        config.pop("hud_enabled", None)
        config.pop("hud", None)

        # 快捷键设置
        config["global_hotkeys"] = HotkeyConfig.GLOBAL_HOTKEYS
        config["hotkey_bindings"] = HotkeyConfig.get_bindings()

        # 吸附设置
        config["snap_enabled"] = SnapConfig.enabled
        config["snap_distance"] = SnapConfig.SNAP_DISTANCE

        # 其他设置
        config["checklist_items"] = self.chk_items
        config["beep_enabled"] = self.sound.is_enabled()
        config["zone_sound_enabled"] = self._zone_sound_enabled
        config["locked"] = self._locked
        config["sound_settings"] = SoundConfig.export_user_config()
        config["overspeed"] = OverspeedConfig.export_user_config()

        # 窗口位置（包含多显示器信息）
        monitor_index = self._saved_monitor_index
        if self._manual_pos:
            monitor = Win32.get_monitor_at(self._manual_pos[0], self._manual_pos[1])
            if monitor:
                monitor_index = monitor.get("index")

        config["window_position"] = {
            "corner": self._corner.name,
            "manual_pos": list(self._manual_pos) if self._manual_pos else None,
            "user_moved": self._user_moved,
            "monitor_index": monitor_index,
        }

        saved = ConfigManager.save(config)
        if not saved and warn_on_failure:
            with contextlib.suppress(tk.TclError):
                messagebox.showerror(
                    "保存失败",
                    "配置保存失败，请检查配置文件权限或磁盘状态。",
                    parent=self.root,
                )
        return saved

    def _init_window_base(self):
        """初始化窗口基础设置"""
        self.root.title("WT Timer")

        # 加载图标
        try:
            p = resource_path(FileConfig.ICON_FILE)
            self._tk_icon = tk.PhotoImage(file=p)
            self.root.iconphoto(True, self._tk_icon)
        except tk.TclError:
            pass

        # 无边框窗口
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg=Theme.BG)

        # 临时几何（真实尺寸在UI创建后计算）
        self.root.geometry("10x10+0+0")
        self.root.update_idletasks()

        # 获取窗口句柄和DPI缩放
        # v6.6.3: 修复点击穿透问题 - 使用 GetParent 获取真正的顶层窗口句柄
        # 对于 overrideredirect(True) 的窗口，winfo_id() 返回的是内部 frame 的句柄
        # 必须使用 GetParent() 获取顶层窗口句柄，否则 WS_EX_TRANSPARENT 样式无效
        internal_id = self.root.winfo_id()
        self.hwnd = ctypes.windll.user32.GetParent(internal_id) or int(internal_id)
        self.scale = Win32.get_dpi_scale(self.hwnd) * float(UIConfig.UI_SCALE_MULT)

        with contextlib.suppress(tk.TclError):
            self.root.tk.call("tk", "scaling", float(self.scale))

        # 缓存常用字体（避免每帧重新计算）
        self._cache_fonts()

    def _cache_fonts(self):
        """缓存所有常用字体元组

        性能优化: 预计算字体避免每帧重复计算
        添加新字体时需在此方法中添加缓存项
        """
        self._cached_fonts = {
            "timer": self._scaled_font(UIConfig.FONT_TIMER),
            "life": self._scaled_font(UIConfig.FONT_LIFE),
            "cycle": self._scaled_font(UIConfig.FONT_CYCLE),
            "pill": self._scaled_font(UIConfig.FONT_PILL),
            "status": self._scaled_font(UIConfig.FONT_STATUS),
            "checklist_title": self._scaled_font(UIConfig.FONT_CHECKLIST_TITLE),
            "checklist_item": self._scaled_font(UIConfig.FONT_CHECKLIST_ITEM),
            "zone_title": self._scaled_font(UIConfig.FONT_ZONE_TITLE),
            "zone_item": self._scaled_font(UIConfig.FONT_ZONE_ITEM),
            "debug": self._scaled_font(UIConfig.FONT_DEBUG),
            "hint": self._scaled_font(UIConfig.FONT_HINT),
        }

    def _scaled_font(self, font_def: tuple, *, size_mult: float = 1.0, min_size: int = 1) -> tuple:
        """按布局缩放和独立文本缩放生成字体元组。"""
        scaled = UIConfig.scaled_font(
            font_def,
            self.scale,
            size_mult=size_mult,
            min_size=min_size,
        )
        resolved = resolve_tk_font_tuple(self.root, scaled)
        return resolved if isinstance(resolved, tuple) else scaled

    def _scaled_font_size(
        self, base_size: float, *, size_mult: float = 1.0, min_size: int = 1
    ) -> int:
        """仅返回缩放后的字号，用于 Canvas 或临时字体。"""
        return UIConfig.scaled_font_size(
            base_size,
            self.scale,
            size_mult=size_mult,
            min_size=min_size,
        )

    def _get_font(self, name: str) -> tuple:
        """获取缓存的字体"""
        return self._cached_fonts.get(name, self._scaled_font(("TkDefaultFont", 10)))

    def _apply_font_family(self) -> None:
        """Refresh cached fonts through the shared family resolver."""
        self._cache_fonts()

    def _finalize_window_geometry_and_styles(self):
        """最终确定窗口几何和样式"""
        self.root.update_idletasks()
        # Establish the real width after the 10x10 bootstrap geometry.  Rows
        # populated later in startup (Web access, hotkey notices, first game
        # snapshot) can still cause transient wrapping, so a bounded idle-time
        # convergence pass is scheduled below.
        self._recalc_size(keep_pos=False, force_shrink=True)
        self.root.update_idletasks()
        alpha = UIConfig.WINDOW_ALPHA if self._locked else min(240, UIConfig.WINDOW_ALPHA + 30)
        Win32.setup_window(self.hwnd, click_through=self._locked, alpha=alpha)
        self._schedule_startup_geometry_convergence()

    def _init_ui(self):
        """初始化 UI 布局（稳定的主窗口骨架）。"""
        MainWindowBuilder(self).build()
        self._update_hint()

    def _schedule_content_geometry_sync(self) -> None:
        """Debounce required-height growth after wrapping or row changes."""
        if self._geometry_sync_after_id is not None:
            return

        def sync() -> None:
            self._geometry_sync_after_id = None
            self._sync_content_geometry()

        self._geometry_sync_after_id = self.root.after_idle(sync)

    def _schedule_startup_geometry_convergence(self) -> None:
        """Shrink transient startup geometry after late rows and wraps settle."""
        settle_delays_ms = self._STARTUP_GEOMETRY_SETTLE_DELAYS_MS

        def settle(step: int = 0) -> None:
            self._startup_geometry_after_id = None
            try:
                self.root.update_idletasks()
                self._recalc_size(keep_pos=False, force_shrink=True)
                self.root.update_idletasks()
            except tk.TclError:
                return
            if step < len(settle_delays_ms):
                self._startup_geometry_after_id = self.root.after(
                    settle_delays_ms[step],
                    lambda: settle(step + 1),
                )

        self._startup_geometry_after_id = self.root.after_idle(settle)

    def _sync_content_geometry(self) -> None:
        """Expand when wrapped content outgrows the current frameless window."""
        try:
            self.root.update_idletasks()
            required = int(self.main_frame.winfo_reqheight()) + max(2, int(8 * self.scale))
            actual = int(self.root.winfo_height())
        except AttributeError, TypeError, ValueError, tk.TclError:
            return
        if required > actual + max(1, int(2 * self.scale)):
            self._recalc_size()

    def _rebuild_checklist(self):
        """重建紧凑、响应式的检查清单 UI（纯展示模式）。"""
        old_bind_id = getattr(self, "_checklist_wrap_bind_id", None)
        if old_bind_id:
            with contextlib.suppress(tk.TclError):
                self.chk_content_frame.unbind("<Configure>", old_bind_id)
        pending_recalc = getattr(self, "_checklist_recalc_after_id", None)
        if pending_recalc:
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(pending_recalc)
        self._checklist_recalc_after_id = None

        for widget in self.chk_content_frame.winfo_children():
            widget.destroy()

        s = self.scale

        self.chk_border_frame.pack(side="left", fill="y", padx=(0, 2))
        self.chk_content_frame.pack(side="left", fill="both", expand=True)

        font_title = self._get_font("checklist_title")
        self.chk_title = tk.Label(
            self.chk_content_frame,
            text="出击检查清单",
            font=font_title,
            fg=Theme.TEXT,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        self.chk_title.pack(fill="x", padx=int(6 * s), pady=(int(6 * s), int(2 * s)))

        font_item = self._get_font("checklist_item")
        pad_x = int(6 * s)
        marker_gap = max(3, int(3 * s))
        initial_wrap_width = int(180 * s)
        marker_labels: list[tk.Label] = []
        item_labels: list[tk.Label] = []

        # 标记与正文分列，避免窄宽度下出现“○”独占一行。
        for item in self.chk_items:
            row = tk.Frame(self.chk_content_frame, bg=Theme.GRAYPILL)
            row.pack(fill="x", padx=(pad_x, pad_x), pady=0, anchor="w")

            marker = tk.Label(
                row,
                text="○",
                font=font_item,
                fg=Theme.TEXT_DIM,
                bg=Theme.GRAYPILL,
                anchor="n",
                justify="left",
            )
            marker.pack(side="left", anchor="n", padx=(0, marker_gap))
            marker_labels.append(marker)

            item_label = tk.Label(
                row,
                text=item,
                font=font_item,
                fg=Theme.TEXT_DIM,
                bg=Theme.GRAYPILL,
                anchor="w",
                justify="left",
                wraplength=initial_wrap_width,
            )
            item_label.pack(side="left", fill="x", expand=True, anchor="n")
            item_labels.append(item_label)

        self._checklist_item_labels = item_labels

        def update_item_wrap(event=None) -> None:
            width = int(getattr(event, "width", 0) or self.chk_content_frame.winfo_width() or 0)
            if width <= 1 or not item_labels:
                return
            marker_width = max(
                (marker.winfo_reqwidth() for marker in marker_labels),
                default=int(16 * s),
            )
            wrap_width = max(40, width - (pad_x * 2) - marker_width - marker_gap)
            changed = False
            for item_label in item_labels:
                if int(float(item_label.cget("wraplength") or 0)) != wrap_width:
                    item_label.configure(wraplength=wrap_width)
                    changed = True

            if changed:
                pending = getattr(self, "_checklist_recalc_after_id", None)
                if pending:
                    with contextlib.suppress(tk.TclError):
                        self.root.after_cancel(pending)

                def recalc_after_wrap() -> None:
                    self._checklist_recalc_after_id = None
                    self._recalc_size(force_shrink=True)

                self._checklist_recalc_after_id = self.root.after_idle(recalc_after_wrap)

        self._checklist_wrap_updater = update_item_wrap
        self._checklist_wrap_bind_id = self.chk_content_frame.bind(
            "<Configure>", update_item_wrap, add="+"
        )
        self.chk_content_frame.after_idle(update_item_wrap)

    def _init_bindings(self):
        """初始化键盘/鼠标绑定

        ╔══════════════════════════════════════════════════════════════════════╗
        ║ 说明：右键菜单已移至系统托盘，窗口不再响应右键                         ║
        ╚══════════════════════════════════════════════════════════════════════╝
        """

        self.runtime_services.refresh_local_hotkey_bindings()
        self.root.bind("<Control-MouseWheel>", self._adjust_alpha)
        self.root.bind(
            "<Control-Shift-Left>",
            lambda e: self.debug_support.cycle_debug_scene(-1) if self._debug else None,
        )
        self.root.bind(
            "<Control-Shift-Right>",
            lambda e: self.debug_support.cycle_debug_scene(1) if self._debug else None,
        )
        self.root.bind(
            "<Control-Shift-m>",
            lambda e: self.debug_support.toggle_debug_mock_mode() if self._debug else None,
        )

        # 拖动相关
        self._drag = {"x": 0, "y": 0}
        self.root.bind("<Button-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._do_drag)
        self.root.bind("<ButtonRelease-1>", self._end_drag)

        # v6.6.3: 焦点保护 - 锁定状态下拒绝焦点，确保点击穿透有效
        self.root.bind("<FocusIn>", self._on_focus_in)

        # 不再绑定窗口右键菜单（功能移至系统托盘）

    def _refresh_standalone_navigation_if_visible(self, snap: UISnapshot) -> None:
        """Let the standalone navigation window clear stale content when panels hide."""
        nav_window = self.nav_window
        if nav_window and nav_window.is_visible():
            nav_window.update_display(snap)

    def _toggle_panel(self, panel_key: str):
        """切换面板显示状态"""
        current = getattr(PanelConfig, panel_key)
        target = {
            "show_zones": "zones",
            "show_airfields": "airfields",
            "show_fuel": "fuel",
            "show_speed": "speed",
            "show_checklist": "checklist",
            "show_bombing": "weapon_solution",
        }.get(panel_key)
        if target is None:
            return
        self._set_panel_visibility(target, not current, warn_on_failure=True)

    def _set_panel_visibility(
        self,
        target: str,
        enabled: bool,
        *,
        warn_on_failure: bool = False,
    ) -> bool:
        """Set one explicit panel target and roll back if persistence fails."""
        if target == "zones":
            if not ENABLE_ZONES:
                return False
            previous = PanelConfig.show_zones
            PanelConfig.show_zones = enabled
        elif target == "airfields":
            if not ENABLE_AIRFIELDS:
                return False
            previous = PanelConfig.show_airfields
            PanelConfig.show_airfields = enabled
        elif target == "fuel":
            if not ENABLE_FUEL:
                return False
            previous = PanelConfig.show_fuel
            PanelConfig.show_fuel = enabled
        elif target == "speed":
            previous = PanelConfig.show_speed
            PanelConfig.show_speed = enabled
        elif target == "checklist":
            if not ENABLE_CHECKLIST:
                return False
            previous = PanelConfig.show_checklist
            PanelConfig.show_checklist = enabled
        elif target == "weapon_solution":
            if not ENABLE_CCRP:
                return False
            previous = PanelConfig.show_bombing
            PanelConfig.show_bombing = enabled
        else:
            return False

        if not self._save_config(warn_on_failure=warn_on_failure):
            if target == "zones":
                PanelConfig.show_zones = previous
            elif target == "airfields":
                PanelConfig.show_airfields = previous
            elif target == "fuel":
                PanelConfig.show_fuel = previous
            elif target == "speed":
                PanelConfig.show_speed = previous
            elif target == "checklist":
                PanelConfig.show_checklist = previous
            else:
                PanelConfig.show_bombing = previous
            return False
        # 立即刷新布局，避免留下空白
        self._recalc_size(force_shrink=True)
        self._update_ui()
        self._refresh_tray()
        return True

    def _toggle_speed_history_mode(self):
        """切换空历速度模式。"""
        PanelConfig.speed_history_mode = not PanelConfig.speed_history_mode
        self._save_config(warn_on_failure=True)
        self._update_hint()
        self._update_ui()
        self._recalc_size(force_shrink=PanelConfig.speed_history_mode)
        self._refresh_tray()

    def _apply_speed_history_layout(self, active: bool) -> None:
        """根据历史模式切换顶部主卡布局。"""
        state_changed = self._history_mode_layout_active != active
        self._history_mode_layout_active = active

        if active:
            if self.mid_frame.winfo_manager() == "grid":
                self.mid_frame.grid_remove()
            self.navigation_services.suspend_for_history_mode(state_changed=state_changed)
            if self.top_row1.winfo_manager() == "grid":
                self.top_row1.grid_remove()
            if self.top_row2.winfo_manager() == "grid":
                self.top_row2.grid_remove()
            if self.history_mode_frame.winfo_manager() != "grid":
                self.history_mode_frame.grid(
                    row=2,
                    column=0,
                    sticky="ew",
                    padx=int(8 * self.scale),
                    pady=self._history_mode_pad_y,
                )
        else:
            self.navigation_services.restore_after_history_mode(state_changed=state_changed)
            if self.history_mode_frame.winfo_manager() == "grid":
                self.history_mode_frame.grid_remove()
            if self.top_row1.winfo_manager() != "grid":
                self.top_row1.grid(
                    row=0,
                    column=0,
                    sticky="ew",
                    padx=int(8 * self.scale),
                    pady=(int(6 * self.scale), 0),
                )
            if self.top_row2.winfo_manager() != "grid":
                pad_top, pad_bot = UIConfig.PADDING_ROW2
                self.top_row2.grid(
                    row=1,
                    column=0,
                    sticky="w",
                    pady=(
                        int(max(2, pad_top // 2) * self.scale),
                        int(pad_bot * self.scale),
                    ),
                )
            self.panel_renderer.update_mid_panel_layout()

    def _refresh_speed_history_ui(self, snap: UISnapshot, speed_level: str) -> None:
        """刷新历史模式专用头部文案。"""
        if not PanelConfig.speed_history_mode:
            return

        model = build_speed_history_header_model(snap, speed_level)
        self.history_mode_phase_lbl.config(text=model.phase_text, fg=model.phase_fg)
        self.history_mode_hint_lbl.config(text=model.hint_text)

    def _refresh_tray(self):
        """刷新系统托盘菜单状态

        调用此方法以确保托盘菜单的勾选状态与实际状态同步。
        """
        runtime_services = getattr(self, "runtime_services", None)
        if runtime_services is not None:
            runtime_services.refresh_tray()

    def _init_global_hotkeys(self):
        """初始化全局热键

        使用HotkeyConfig中配置的快捷键，支持运行时自定义。
        """
        self.runtime_services.init_global_hotkeys()

    def _on_hotkey_registration_error(self, key_names) -> None:
        unique_keys = [str(name) for name in key_names if str(name).strip()]
        if not unique_keys:
            return
        joined = "、".join(unique_keys)
        messagebox.showwarning(
            "快捷键注册失败",
            (
                "以下全局快捷键未能注册："
                f"{joined}\n\n"
                "可能原因：与其他程序或系统快捷键冲突。"
                "\n请在设置中改用其他按键。"
            ),
            parent=self.root,
        )

    def _init_tray(self):
        """初始化系统托盘

        托盘菜单根据编译开关动态生成:
        - Lite模式: 仅保留基本功能（重置/锁定/声音/退出）
        - 完整模式: 包含所有功能
        """
        self.runtime_services.init_tray()

    def _toggle_debug(self):
        self.debug_support.toggle_debug()

    def _set_zone_sound_enabled(
        self,
        enabled: bool,
        *,
        warn_on_failure: bool = False,
    ) -> bool:
        """Set the explicit zone-sound target and persist before reporting success."""
        if not ENABLE_ZONES:
            return False
        previous = self._zone_sound_enabled
        self._zone_sound_enabled = enabled
        if not self._save_config(warn_on_failure=warn_on_failure):
            self._zone_sound_enabled = previous
            return False
        self._update_hint()
        self._refresh_tray()
        if self._zone_sound_enabled:
            self.sound.play(pattern="on")
        return True

    def _toggle_zone_sound(self):
        """切换战区提示音"""
        self._set_zone_sound_enabled(
            not self._zone_sound_enabled,
            warn_on_failure=True,
        )

    def _toggle_navigation_mode(self):
        """切换导航条模式（集成/独立）

        仅在战区功能启用时可用。
        """
        self.navigation_services.toggle_mode()

    def _toggle_bombing_mode(self):
        """切换 CCRP 的主窗集成/独立显示。"""
        self.bombing_services.toggle_mode()

    def _set_bomb_target_mode(
        self,
        mode: str,
        *,
        warn_on_failure: bool = False,
    ) -> bool:
        """Persist one explicit target source and invalidate the old target solution."""
        normalized = str(mode or "").strip().lower()
        if not ENABLE_CCRP or normalized not in BombConfig.TARGET_MODES:
            return False
        previous = BombConfig.normalize_target_mode(BombConfig.target_mode)
        if previous == normalized:
            return True
        setter = getattr(self.game, "set_bombing_target_mode", None)
        applied = (
            bool(setter(normalized)) if callable(setter) else BombConfig.set_target_mode(normalized)
        )
        if not applied:
            return False
        if not self._save_config(warn_on_failure=warn_on_failure):
            if callable(setter):
                setter(previous)
            else:
                BombConfig.set_target_mode(previous)
            return False
        self._update_hint()
        self._update_ui()
        self._refresh_tray()
        log_event("bombing_target_mode_toggle", mode=normalized)
        return True

    def _toggle_bomb_target_mode(self):
        """专用按钮/热键：只在战区与兴趣点目标来源之间切换。"""
        current = BombConfig.normalize_target_mode(BombConfig.target_mode)
        target = "poi" if current == "zone" else "zone"
        self._set_bomb_target_mode(target, warn_on_failure=True)

    def _cycle_bomb_weapon(self, direction: int) -> bool:
        """Cycle compatible bomb records without opening the full weapon catalog."""
        if not ENABLE_CCRP:
            return False
        catalog = self._get_weapon_catalog()
        if catalog is None:
            return False
        snap = self.game.snapshot()
        aircraft = str(getattr(snap, "aircraft_type_name", "") or "").strip()
        airborne = snap.phase == Phase.ALIVE and not snap.on_ground
        records = catalog.for_aircraft(aircraft) if aircraft else []
        records = [
            record
            for record in records
            if record.get("role") == "bomb"
            and BombConfig.get_bomb_data(str(record.get("id") or ""))
        ]
        if not records and not airborne:
            records = [
                record
                for record in catalog.search(role="bomb")
                if BombConfig.get_bomb_data(str(record.get("id") or ""))
            ]
        if not records:
            return False

        weapon_ids = [str(record["id"]) for record in records]
        current = str(catalog.selected_weapon_id or "")
        try:
            index = weapon_ids.index(current)
        except ValueError:
            index = -1 if direction >= 0 else 0
        step = 1 if direction >= 0 else -1
        target_id = weapon_ids[(index + step) % len(weapon_ids)]
        if not persist_weapon_selection(
            catalog,
            target_id,
            WeaponBallisticModelConfig.selected_model,
        ):
            messagebox.showwarning(
                "切换投弹弹药失败",
                "无法保存新的投弹弹药选择，请检查配置文件是否可写。",
                parent=self.root,
            )
            return False
        self._update_ui()
        log_event("bomb_weapon_cycle", weapon_id=target_id, direction=int(direction))
        return True

    def _recalc_size(self, keep_pos: bool = True, force_shrink: bool = False):
        """重新计算窗口尺寸

        策略: 扩展立即响应, 收缩保守处理(避免抖动), 边界检查

        注意:
        - badge_min_width: 徽章行最小宽度(约320px)，确保起落架徽章等能完整显示

        - 双面板480px, 单面板取max(badge_min_width, hint_min_width)
        - _clamp_to_screen()确保不超出屏幕

        Args:
            keep_pos: 保持窗口位置
            force_shrink: 强制收缩
        """
        try:
            old_x = self.root.winfo_x()
            old_y = self.root.winfo_y()
            old_w = self.root.winfo_width()
            old_h = self.root.winfo_height()
        except tk.TclError:
            old_x, old_y, old_w, old_h = 0, 0, 0, 0

        # 强制刷新布局
        self.root.update_idletasks()

        # 读取实际需要的尺寸
        req_w = self.main_frame.winfo_reqwidth()
        req_h = self.main_frame.winfo_reqheight()

        # ⚠️ 徽章行最小宽度（确保主徽章、起落架和状态文本完整显示）
        # 速度信息已迁移为独立紧凑速度条，避免在徽章行里挤占空间
        badge_min_width = int(460 * self.scale)

        # ⚠️ 提示文字最小宽度（动态测量，避免浪费或截断）
        hint_min_width = int(380 * self.scale)
        try:
            hint_text = ""
            if hasattr(self, "hint_lbl") and self.hint_lbl:
                hint_text = self.hint_lbl.cget("text") or ""
            if not hint_text:
                hint_text = self._hint_text()
            cache = getattr(self, "_hint_width_cache", None)
            if cache and cache.get("text") == hint_text:
                hint_min_width = int(cache.get("width", hint_min_width))
            else:
                hint_font = tkfont.Font(font=self._get_font("hint"))
                hint_min_width = hint_font.measure(hint_text) + int(16 * self.scale)
                if cache is not None:
                    cache["text"] = hint_text
                    cache["width"] = hint_min_width
        except Exception:
            hint_min_width = int(380 * self.scale)

        # 基础最小宽度：取徽章行和提示行中较大的
        base_min_width = max(badge_min_width, hint_min_width)

        # 根据面板可见性设置最小宽度
        if self._zone_panel_visible and self._checklist_panel_visible:
            min_width = max(int(480 * self.scale), base_min_width)
        else:
            min_width = base_min_width

        new_w = max(min_width, req_w)
        new_h = req_h + int(8 * self.scale)

        # 手动拖拽后若贴边，记录贴边锚点；尺寸变化时优先保持贴边体验
        edge_anchor = None
        if keep_pos and self._user_moved and old_w > 0 and old_h > 0:
            edge_anchor = capture_snap_anchor(
                old_x,
                old_y,
                old_w,
                old_h,
                snap_enabled=SnapConfig.enabled,
                snap_distance=SnapConfig.SNAP_DISTANCE,
                monitor=Win32.get_monitor_at(old_x + old_w // 2, old_y + old_h // 2),
            )

        # 宽高双向收缩防抖：扩张立即生效，收缩需满足阈值且避开刚扩张后的冷却窗口
        now = time.monotonic()
        dw = new_w - old_w
        dh = new_h - old_h
        minor_shrink_px = max(16, int(18 * self.scale))
        shrink_cooldown_sec = 0.8

        if dw > 0 or dh > 0:
            self._last_expand_ts = now

        if not force_shrink:
            if dw < 0 and (
                abs(dw) < minor_shrink_px or (now - self._last_expand_ts) < shrink_cooldown_sec
            ):
                new_w = old_w
            if dh < 0 and (
                abs(dh) < minor_shrink_px or (now - self._last_expand_ts) < shrink_cooldown_sec
            ):
                new_h = old_h

        if new_w == old_w and new_h == old_h:
            # 同步内部缓存，避免后续geometry误用过期的self.W/self.H
            self.W = old_w
            self.H = old_h
            # 尺寸未变，但仍需检查边界（窗口可能需要重新定位）
            if keep_pos and (old_w > 0 and old_h > 0):
                clamp_margin = 0 if self._user_moved else None
                x, y = self._clamp_to_screen(old_x, old_y, margin=clamp_margin)
                if (x, y) != (old_x, old_y):
                    self.root.geometry(f"{old_w}x{old_h}+{x}+{y}")
                    if self._user_moved:
                        self._manual_pos = (x, y)
            return

        self.W = new_w
        self.H = new_h

        if keep_pos:
            if self._user_moved and self._manual_pos:
                x, y = self._manual_pos
            elif old_w > 0 and old_h > 0:
                x, y = old_x, old_y
            else:
                self._position()
                return
            # 边界检查：确保窗口不超出屏幕
            # 手动拖拽位置使用0边距，避免尺寸变化后破坏边缘吸附锚点
            if edge_anchor:
                x, y = apply_snap_anchor(x, y, self.W, self.H, edge_anchor)
            clamp_margin = 0 if self._user_moved else None
            x, y = self._clamp_to_screen(x, y, margin=clamp_margin)
            self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
            if self._user_moved:
                self._manual_pos = (x, y)
        else:
            self._position()

    def _show(self):
        """显示窗口"""
        try:
            self.root.deiconify()
            self.root.lift()
        except tk.TclError:
            pass

    def _position(self):
        """定位窗口到指定角落(支持多显示器)"""
        m = int(UIConfig.WINDOW_MARGIN * self.scale)

        # Corner placement must not depend on the transient coordinates of a
        # hidden/just-created Tk root (often 0,0 or an off-screen sentinel).
        # Use persisted monitor identity when valid, otherwise the primary.
        monitors = Win32.get_all_monitors()
        monitor = None
        saved_monitor_index = getattr(self, "_saved_monitor_index", None)
        if isinstance(saved_monitor_index, int):
            monitor = next(
                (item for item in monitors if item.get("index") == saved_monitor_index),
                None,
            )
        if monitor is None:
            monitor = next(
                (item for item in monitors if item.get("is_primary")),
                monitors[0] if monitors else None,
            )

        # 如果无法获取显示器信息，回退到主屏幕
        if not monitor:
            sw, sh = Win32.screen_size()
            monitor = {"x": 0, "y": 0, "width": sw, "height": sh}

        # 计算在当前显示器上的角落位置
        mon_x = monitor["x"]
        mon_y = monitor["y"]
        mon_w = monitor["width"]
        mon_h = monitor["height"]
        self._saved_monitor_index = monitor.get("index")

        pos = {
            Corner.TOP_RIGHT: (mon_x + mon_w - self.W - m, mon_y + m),
            Corner.TOP_LEFT: (mon_x + m, mon_y + m),
            Corner.BOTTOM_RIGHT: (mon_x + mon_w - self.W - m, mon_y + mon_h - self.H - m),
            Corner.BOTTOM_LEFT: (mon_x + m, mon_y + mon_h - self.H - m),
        }

        if self._user_moved and self._manual_pos:
            x, y = self._manual_pos
        else:
            x, y = pos[self._corner]

        # 边界检查（基于当前显示器）
        x, y = self._clamp_to_screen(x, y)
        self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")

    def _clamp_to_screen(self, x: int, y: int, margin: int | None = None) -> tuple[int, int]:
        """确保窗口位置不超出屏幕边界(支持多显示器)

        Args:
            x, y: 窗口左上角坐标

        Returns:
            调整后的(x, y)坐标
        """
        m = int(UIConfig.WINDOW_MARGIN * self.scale) if margin is None else int(margin)

        # 获取窗口中心点所在的显示器
        center_x = x + self.W // 2
        center_y = y + self.H // 2
        monitor = Win32.get_monitor_at(center_x, center_y)

        # 如果无法获取显示器信息，回退到主屏幕
        if not monitor:
            sw, sh = Win32.screen_size()
            monitor = {"x": 0, "y": 0, "width": sw, "height": sh}

        mon_x = monitor["x"]
        mon_y = monitor["y"]
        mon_w = monitor["width"]
        mon_h = monitor["height"]

        # 确保右边界不超出（优先保证窗口在屏幕内）
        if x + self.W > mon_x + mon_w - m:
            x = mon_x + mon_w - self.W - m
        # 确保左边界不超出
        if x < mon_x + m:
            x = mon_x + m
        # 确保下边界不超出
        if y + self.H > mon_y + mon_h - m:
            y = mon_y + mon_h - self.H - m
        # 确保上边界不超出
        if y < mon_y + m:
            y = mon_y + m

        return x, y

    def _set_locked_state(
        self,
        locked: bool,
        *,
        warn_on_failure: bool = False,
    ) -> bool:
        """Set and persist the explicit window lock target."""
        if self._locked == locked:
            return True
        previous = self._locked
        self._locked = locked
        if not self._save_config(warn_on_failure=warn_on_failure):
            self._locked = previous
            return False
        alpha = UIConfig.WINDOW_ALPHA if self._locked else min(240, UIConfig.WINDOW_ALPHA + 30)
        Win32.setup_window(self.hwnd, click_through=self._locked, alpha=alpha)
        self.navigation_services.apply_lock_state(locked=self._locked, alpha=alpha)
        self.bombing_services.apply_lock_state(locked=self._locked, alpha=alpha)
        self._update_hint()
        self._refresh_tray()
        return True

    def _toggle_lock(self):
        """切换锁定/解锁

        v6.0.1 优化：锁定/解锁时使用不同透明度，提供明确的视觉反馈
        - 锁定状态：使用配置的透明度（默认210）
        - 解锁状态：提高透明度到240，让窗口更明显便于拖动
        """
        self._set_locked_state(not self._locked, warn_on_failure=True)

    def _on_focus_in(self, event=None):
        """焦点保护：锁定状态下拒绝焦点

        v6.6.3: 当窗口在锁定（穿透）状态下意外获得焦点时，
        立即重新应用穿透样式，确保点击穿透功能持续有效。

        问题背景：
        - WS_EX_TRANSPARENT 只让点击穿透，但窗口仍可被激活
        - 通过 Alt+Tab、系统事件等方式激活窗口后，穿透可能失效
        - 此方法作为额外保护，配合 WS_EX_NOACTIVATE 标志使用
        """
        if self._locked:
            # 重新应用窗口样式，确保穿透标志生效
            with contextlib.suppress(Exception):
                Win32.setup_window(self.hwnd, click_through=True, alpha=UIConfig.WINDOW_ALPHA)

    def _update_lock_badge(self) -> None:
        """更新锁定状态徽章，提升可见性。"""
        if not hasattr(self, "badge_lock") or self.badge_lock is None:
            return
        if self._locked:
            self.badge_lock.set("锁定", Theme.TEXT, Theme.BLUE)
        else:
            self.badge_lock.set("可拖动", Theme.TEXT, Theme.GREEN)

    def _hint_text(self) -> str:
        """生成提示文本

        注意: 修改提示文字长度时需同步修改_recalc_size()中的hint_min_width
        根据编译开关动态生成提示内容
        """
        sound = "开" if self.sound.is_enabled() else "关"

        # 使用配置的快捷键
        k_reset = HotkeyConfig.KEY_RESET
        k_lock = HotkeyConfig.KEY_LOCK
        k_corner = HotkeyConfig.KEY_CORNER
        k_beep = HotkeyConfig.KEY_BEEP

        if self._locked:
            parts = [
                f"[{k_reset}]双击重置",
                f"[{k_lock}]解锁拖动",
                f"[{k_corner}]切换角落",
                f"[{k_beep}]提示音:{sound}",
            ]
            # 战区提示音仅在战区功能启用时显示
            if ENABLE_ZONES:
                zone_sound = "开" if self._zone_sound_enabled else "关"
                k_zones = HotkeyConfig.KEY_ZONES
                parts.append(f"[{k_zones}]战区音:{zone_sound}")
            if ENABLE_CCRP:
                target_label = "战区" if BombConfig.target_mode == "zone" else "兴趣点"
                parts.append(f"[{HotkeyConfig.KEY_BOMB_TARGET}]CCRP:{target_label}")
            base_text = "  ·  ".join(parts)
        else:
            parts = [
                "窗口可拖动",
                f"[{k_lock}]重新锁定",
                f"[{k_beep}]提示音:{sound}",
            ]
            if ENABLE_ZONES:
                zone_sound = "开" if self._zone_sound_enabled else "关"
                k_zones = HotkeyConfig.KEY_ZONES
                parts.append(f"[{k_zones}]战区音:{zone_sound}")
            if ENABLE_CCRP:
                target_label = "战区" if BombConfig.target_mode == "zone" else "兴趣点"
                parts.append(f"[{HotkeyConfig.KEY_BOMB_TARGET}]CCRP:{target_label}")
            base_text = "  ·  ".join(parts)

        prefix_parts = [text for text in (self._manual_reset_confirm_text(),) if text]
        if PanelConfig.speed_history_mode:
            history_text = "空历模式: 独立速度界面"
            prefix_parts.append(history_text)
        if prefix_parts:
            return f"{'  ·  '.join(prefix_parts)}  ·  {base_text}"
        return base_text

    def _manual_reset_confirm_text(self) -> str:
        """返回热键二次确认的弱提醒文案。"""
        if time.monotonic() >= self._manual_reset_confirm_until:
            return ""
        return f"再按一次 [{HotkeyConfig.KEY_RESET}] 确认重置"

    def _nudge_text(self) -> str:
        if self._hotkey_broker_notice:
            if self._hotkey_broker_action == "elevate":
                if self._locked:
                    return (
                        f"{self._hotkey_broker_notice} 先按 [{HotkeyConfig.KEY_LOCK}] 解锁 Bomana。"
                    )
                return f"{self._hotkey_broker_notice} 可启用匹配权限的热键。"
            return self._hotkey_broker_notice
        return "提示：如果 Bomana 对你有帮助，欢迎点一个 GitHub Star（起飞后自动隐藏）"

    def _nudge_action_text(self) -> str:
        if self._hotkey_broker_action == "elevate":
            return "启用热键"
        return "GitHub Star" if self._nudge_visible else ""

    def _set_hotkey_broker_notice(self, message: str, action: str) -> None:
        self._hotkey_broker_notice = str(message or "").strip()
        self._hotkey_broker_action = str(action or "").strip()
        self._update_hint()
        self._refresh_tray()

    def _on_nudge_action(self) -> None:
        if self._hotkey_broker_action == "elevate":
            approved = messagebox.askokcancel(
                "启用管理员热键",
                (
                    "Bomana 将只以管理员权限启动随 App 携带的固定功能热键组件。\n\n"
                    "Windows 接下来会显示 UAC。由于项目没有商业代码签名证书，"
                    "发布者会显示为“未知”。请仅在 Bomana 来自官方 GitHub Release，"
                    "并且你愿意信任本次下载时继续。\n\n"
                    "不会安装额外程序、服务、计划任务或开机启动项；关闭 Bomana 后"
                    "该组件会退出。选择取消会继续使用普通热键。"
                ),
                parent=self.root,
            )
            if not approved:
                return
            self.runtime_services.retry_hotkey_broker()
            return
        self._open_star_url()

    def _update_hint(self) -> None:
        """更新提示文本"""
        if hasattr(self, "hint_lbl") and self.hint_lbl:
            hint_fg = Theme.YELLOW if self._manual_reset_confirm_text() else Theme.TEXT_MUTED
            self.hint_lbl.config(text=self._hint_text(), fg=hint_fg)
        self._update_lock_badge()
        if hasattr(self, "_hint_width_cache") and self._hint_width_cache is not None:
            self._hint_width_cache["text"] = ""
        nudge_layout_changed = self._sync_nudge_row()
        if nudge_layout_changed and hasattr(self, "main_frame"):
            with contextlib.suppress(Exception):
                self._recalc_size(
                    force_shrink=not bool(self._hotkey_broker_notice or self._nudge_visible)
                )

    def _sync_nudge_row(self) -> bool:
        """Mirror the GitHub Star nudge state into visible widgets."""
        visible = bool(self._hotkey_broker_notice or self._nudge_visible)
        if hasattr(self, "nudge_lbl") and self.nudge_lbl:
            self.nudge_lbl.config(
                text=(self._nudge_text() if visible else ""),
                fg=(Theme.YELLOW if self._hotkey_broker_notice else Theme.TEXT_MUTED),
            )
        if hasattr(self, "star_lbl") and self.star_lbl:
            action_text = self._nudge_action_text() if visible else ""
            self.star_lbl.config(
                text=action_text,
                cursor=("hand2" if action_text else "arrow"),
            )
        if not hasattr(self, "nudge_row") or not self.nudge_row:
            return False

        current_manager = ""
        with contextlib.suppress(Exception):
            current_manager = self.nudge_row.winfo_manager()

        if visible and current_manager != "grid":
            self.nudge_row.grid()
            return True
        if not visible and current_manager == "grid":
            self.nudge_row.grid_remove()
            return True
        return False

    def _open_star_url(self) -> None:
        url = AboutConfig.GITHUB_URL
        if url:
            with contextlib.suppress(Exception):
                webbrowser.open(url)

    def _update_nav_mode_button(self):
        """更新独立导航条按钮状态显示"""
        if not ENABLE_ZONES or not hasattr(self, "standalone_btn"):
            return
        if PanelConfig.navigation_mode == "standalone":
            self.standalone_btn.config(text="独立导航窗 · 已启用")
            style_action_button(self.standalone_btn, "success")
        else:
            self.standalone_btn.config(text="打开独立导航窗")
            style_action_button(self.standalone_btn, "neutral")

    def _advance_corner(self, *, warn_on_failure: bool = False) -> bool:
        """Advance once through the fixed corner order and persist atomically."""
        corners = list(Corner)
        i = (corners.index(self._corner) + 1) % len(corners)
        previous = (self._corner, self._user_moved, self._manual_pos)
        self._corner = corners[i]
        self._user_moved = False
        self._manual_pos = None
        if not self._save_config(warn_on_failure=warn_on_failure):
            self._corner, self._user_moved, self._manual_pos = previous
            return False
        self._position()
        return True

    def _next_corner(self):
        """切换到下一个角落"""
        self._advance_corner(warn_on_failure=True)

    def _set_beep_enabled(
        self,
        enabled: bool,
        *,
        warn_on_failure: bool = False,
    ) -> bool:
        """Set and persist the explicit general sound target."""
        previous = self.sound.is_enabled()
        if previous == enabled:
            return True
        self.sound.set_enabled(enabled)
        if not self._save_config(warn_on_failure=warn_on_failure):
            self.sound.set_enabled(previous)
            return False
        self._update_hint()
        self._refresh_tray()
        if enabled:
            self.sound.play(pattern="on")
        return True

    def _toggle_beep(self):
        """切换提示音"""
        self._set_beep_enabled(
            not self.sound.is_enabled(),
            warn_on_failure=True,
        )

    def _clear_manual_reset_confirmation(self, refresh_hint: bool = False) -> None:
        """清理热键重置确认态。"""
        if self._manual_reset_confirm_until <= 0.0:
            return
        self._manual_reset_confirm_until = 0.0
        if refresh_hint:
            self._update_hint()
            self._recalc_size(force_shrink=True)

    def _manual_reset_hotkey(self):
        """处理重置热键，要求在短时间内连续按两次。"""
        now = time.monotonic()
        if now < self._manual_reset_confirm_until:
            self._manual_reset()
            return
        self._manual_reset_confirm_until = now + HotkeyConfig.RESET_CONFIRM_WINDOW_SEC
        self._update_hint()
        self._recalc_size()
        self.sound.play(pattern="tick")

    def _manual_reset(self):
        """立即执行手动重置。"""
        self._clear_manual_reset_confirmation(refresh_hint=True)
        self.game.manual_reset()
        self.sound.play(pattern="manual_reset")

    def _show_settings(self, initial_tab: str | None = None):
        """显示设置对话框

        从托盘菜单调用，不受窗口锁定状态影响。
        """
        SettingsDialog(self.root, self, initial_tab=initial_tab)

    def _set_timer_cycle_minutes(
        self,
        minutes: object,
        *,
        warn_on_failure: bool = False,
    ) -> bool:
        target = GameConfig.normalize_cycle_minutes(minutes)
        if target is None:
            return False
        previous = GameConfig.cycle_minutes()
        if not GameConfig.set_cycle_minutes(target):
            return False
        if not self._save_config(warn_on_failure=warn_on_failure):
            GameConfig.set_cycle_minutes(previous)
            return False
        publish = getattr(self, "_publish_web_control_state", None)
        if callable(publish):
            publish(force_revision=True)
        refresh_tray = getattr(self, "_refresh_tray", None)
        if callable(refresh_tray):
            refresh_tray()
        return True

    def _prompt_timer_cycle_minutes(self) -> None:
        minutes = simpledialog.askinteger(
            "自定义计时周期",
            "输入每轮分钟数（1–180）：",
            parent=self.root,
            initialvalue=GameConfig.cycle_minutes(),
            minvalue=GameConfig.MIN_CYCLE_MINUTES,
            maxvalue=GameConfig.MAX_CYCLE_MINUTES,
        )
        if minutes is not None:
            self._set_timer_cycle_minutes(minutes, warn_on_failure=True)

    def _refresh_overspeed_threshold_ui(self) -> None:
        """刷新速度条上的阈值刻度位置。"""
        markers = getattr(self, "speed_bar_markers", None)
        if not markers:
            return
        initial_ratios = overspeed_dynamic_projection(0.0).marker_ratios
        for name, relx in zip(
            ("caution", "warning", "critical"),
            initial_ratios,
            strict=True,
        ):
            marker = markers.get(name)
            if marker:
                marker.place_configure(relx=max(0.0, min(1.0, relx)))

    def apply_display_settings_runtime(
        self,
        theme_changed: bool,
        ui_scale_changed: bool,
        text_scale_changed: bool = False,
        nav_width_changed: bool = False,
        nav_scale_changed: bool = False,
    ) -> None:
        """运行时应用显示设置（主题/全局缩放/独立导航尺寸）

        通过局部重建UI避免强制重启应用。
        """
        need_main_rebuild = bool(theme_changed or ui_scale_changed or text_scale_changed)
        need_nav_rebuild = bool(need_main_rebuild or nav_width_changed or nav_scale_changed)
        if not (need_main_rebuild or need_nav_rebuild):
            return

        preserve_text_only_geometry = bool(text_scale_changed and not ui_scale_changed)
        main_geometry = None
        if preserve_text_only_geometry:
            try:
                main_geometry = (
                    self.root.winfo_x(),
                    self.root.winfo_y(),
                    self.root.winfo_width(),
                    self.root.winfo_height(),
                )
            except tk.TclError:
                main_geometry = None
        if need_main_rebuild:
            if hasattr(self, "main_frame") and self.main_frame:
                with contextlib.suppress(tk.TclError):
                    self.main_frame.destroy()

            self.root.configure(bg=Theme.BG)
            self.scale = Win32.get_dpi_scale(self.hwnd) * float(UIConfig.UI_SCALE_MULT)
            self._hint_width_cache = {"text": "", "width": int(380 * self.scale)}
            with contextlib.suppress(tk.TclError):
                self.root.tk.call("tk", "scaling", float(self.scale))
            self._cache_fonts()

            # 清理旧布局缓存，避免复用已销毁的控件引用。
            self._zone_row_pool = []
            self._compact_zone_row_pool = []
            self._airport_row_pool = []
            self._compact_airport_row_pool = []
            self._zone_panel_visible = False
            self._checklist_panel_visible = False
            self._last_layout_signature = None
            self._zone_layout_mode = None
            self._airport_layout_mode = None
            self._last_zone_recalc_ts = 0.0

            self._init_ui()
            if self._debug:
                self.debug_support.show_debug_ui()
            self._update_hint()
            self._update_nav_mode_button()
            if preserve_text_only_geometry and main_geometry:
                old_x, old_y, old_w, old_h = main_geometry
                clamp_margin = 0 if self._user_moved else None
                x, y = self._clamp_to_screen(old_x, old_y, margin=clamp_margin)
                self.W = old_w
                self.H = old_h
                self.root.geometry(f"{old_w}x{old_h}+{x}+{y}")
                if self._user_moved:
                    self._manual_pos = (x, y)
            else:
                self._recalc_size(force_shrink=True)

        if ENABLE_ZONES and need_nav_rebuild:
            self.navigation_services.rebuild_after_display_change(
                preserve_text_only_geometry=preserve_text_only_geometry,
                reset_position=bool(nav_width_changed or nav_scale_changed),
            )
        if ENABLE_CCRP and need_nav_rebuild:
            self.bombing_services.rebuild_after_display_change()

        # 重新应用窗口样式（锁定态穿透 + 透明度）
        alpha = UIConfig.WINDOW_ALPHA if self._locked else min(240, UIConfig.WINDOW_ALPHA + 30)
        Win32.setup_window(self.hwnd, click_through=self._locked, alpha=alpha)
        self.navigation_services.apply_lock_state(locked=self._locked, alpha=alpha)
        self.bombing_services.apply_lock_state(locked=self._locked, alpha=alpha)
        self._refresh_tray()

    def _edit_checklist(self):
        """编辑检查清单

        从托盘菜单调用，不受窗口锁定状态影响。
        """
        ChecklistEditor(self.root, self)

    def _show_about(self):
        """显示关于对话框"""
        AboutDialog(self.root, self)

    def _show_strike_encyclopedia(self):
        """Open or focus the edition-neutral offline strike encyclopedia."""
        current = getattr(self, "_strike_encyclopedia_dialog", None)
        if current is not None:
            with contextlib.suppress(tk.TclError):
                if current.winfo_exists():
                    current.deiconify()
                    current.lift()
                    current.focus_force()
                    return
        self._strike_encyclopedia_dialog = StrikeEncyclopediaDialog(self.root, self)

    def _complete_web_command(self, envelope: WebCommandEnvelope, reason: str) -> None:
        try:
            resulting_revision = self._publish_web_control_state(force_revision=True)
        except Exception as exc:
            log_exception("web_dashboard_control_publish_failed", exc)
            resulting_revision = max(1, self._web_control_revision)
        self.runtime_services.complete_web_command(
            envelope,
            status="succeeded" if reason == "ok" else "rejected",
            reason=reason,
            resulting_revision=resulting_revision,
        )

    def _apply_web_command(self, envelope: WebCommandEnvelope) -> str:
        """Execute one schema-validated allowlisted semantic command on Tk."""
        command = envelope.command
        if command.name == "action.reset_timer":
            if command.confirmed is not True or not hasattr(self.game, "manual_reset"):
                return "state_unavailable"
            self._manual_reset()
            return "ok"
        if command.name == "action.cycle_corner":
            return "ok" if self._advance_corner() else "persistence_failed"
        if command.name == "state.set_locked":
            if not isinstance(command.locked, bool):
                return "invalid_target"
            return "ok" if self._set_locked_state(command.locked) else "persistence_failed"
        if command.name == "state.set_beep_enabled":
            if not isinstance(command.enabled, bool):
                return "invalid_target"
            return "ok" if self._set_beep_enabled(command.enabled) else "persistence_failed"
        if command.name == "state.set_zone_sound_enabled":
            if not ENABLE_ZONES:
                return "feature_disabled"
            if not isinstance(command.enabled, bool):
                return "invalid_target"
            return "ok" if self._set_zone_sound_enabled(command.enabled) else "persistence_failed"
        if command.name == "config.set_panel_visibility":
            if not isinstance(command.enabled, bool):
                return "invalid_target"
            target = command.target
            if target == "zones" and not ENABLE_ZONES:
                return "feature_disabled"
            if target == "airfields" and not ENABLE_AIRFIELDS:
                return "feature_disabled"
            if target == "fuel" and not ENABLE_FUEL:
                return "feature_disabled"
            if target == "checklist" and not ENABLE_CHECKLIST:
                return "feature_disabled"
            if target == "weapon_solution" and not ENABLE_CCRP:
                return "feature_disabled"
            if target not in {
                "zones",
                "airfields",
                "fuel",
                "speed",
                "checklist",
                "weapon_solution",
            }:
                return "invalid_target"
            return (
                "ok"
                if self._set_panel_visibility(target, command.enabled)
                else "persistence_failed"
            )
        if command.name == "config.set_timer_cycle_minutes":
            if GameConfig.normalize_cycle_minutes(command.minutes) is None:
                return "invalid_target"
            return "ok" if self._set_timer_cycle_minutes(command.minutes) else "persistence_failed"
        if command.name == "navigation.set_poi":
            setter = getattr(self.game, "set_manual_interest_point", None)
            if not callable(setter):
                return "state_unavailable"
            return "ok" if setter(command.x, command.y) else "invalid_target"
        if command.name == "weapon.select":
            if not ENABLE_CCRP:
                return "feature_disabled"
            catalog = self._get_weapon_catalog()
            if catalog is None:
                return "state_unavailable"
            weapon_id = str(command.weapon_id or "")
            weapon = catalog.get(weapon_id)
            if not weapon:
                return "weapon_not_found"
            snap = self.game.snapshot()
            airborne = snap.phase == Phase.ALIVE and not snap.on_ground
            aircraft = str(getattr(snap, "aircraft_type_name", "") or "")
            if airborne and (not aircraft or not catalog.compatible(weapon_id, aircraft)):
                return "weapon_incompatible"
            if not persist_weapon_selection(
                catalog,
                weapon_id,
                WeaponBallisticModelConfig.selected_model,
            ):
                return "persistence_failed"
            return "ok"
        if command.name == "weapon.set_ballistic_model":
            if not ENABLE_CCRP:
                return "feature_disabled"
            model = str(command.model or "")
            if model not in WeaponBallisticModelConfig.VALID_MODELS:
                return "invalid_target"
            return "ok" if persist_ballistic_model_selection(model) else "persistence_failed"
        if command.name == "network.set_lan_enabled":
            # Only the loopback owner may open or close LAN access for this process.
            if envelope.transport != "loopback":
                return "authorization_revoked"
            if not isinstance(command.enabled, bool):
                return "invalid_target"
            dashboard = self.runtime_services.dashboard
            currently_enabled = bool(dashboard is not None and dashboard.lan_enabled)
            if command.enabled is currently_enabled:
                return "ok"
            if command.enabled:
                if command.confirmed is not True:
                    return "invalid_target"
                try:
                    self.runtime_services.enable_dashboard_lan()
                except Exception as exc:
                    log_exception("web_dashboard_lan_enable_failed", exc)
                    return "execution_failed"
                self._refresh_tray()
                self._refresh_web_access_row()
                return "ok"
            try:
                self.runtime_services.disable_dashboard_lan()
            except Exception as exc:
                log_exception("web_dashboard_lan_disable_failed", exc)
                return "execution_failed"
            self._refresh_tray()
            self._refresh_web_access_row()
            return "ok"
        return "invalid_target"

    def _execute_web_command(self, envelope: WebCommandEnvelope) -> None:
        """Reauthorize and execute a Web command exclusively on the Tk owner thread."""
        if not isinstance(envelope, WebCommandEnvelope):
            return
        if not self.runtime_services.reauthorize_web_command(envelope):
            self._complete_web_command(envelope, "authorization_revoked")
            return
        try:
            reason = self._apply_web_command(envelope)
        except Exception as exc:
            log_exception("web_dashboard_command_execution_failed", exc)
            reason = "execution_failed"
        self._complete_web_command(envelope, reason)

    def _open_web_dashboard(self) -> None:
        if not ENABLE_WEB_DASHBOARD:
            messagebox.showinfo(
                "网页驾驶舱",
                "当前通道未包含网页驾驶舱。\n请使用超级爆弹版以获得该功能。",
                parent=self.root,
            )
            return
        dashboard = self.runtime_services.dashboard
        if dashboard is None or not dashboard.is_running:
            if self.runtime_services.init_dashboard():
                self._publish_web_control_state(force_revision=True)
                self._refresh_tray()
                self._refresh_web_access_row()
            dashboard = self.runtime_services.dashboard
        url = dashboard.local_pairing_url if dashboard is not None else None
        if not url:
            messagebox.showerror(
                "网页驾驶舱",
                self.runtime_services.dashboard_error or "网页驾驶舱当前不可用。",
                parent=self.root,
            )
            return
        webbrowser.open(url)

    def _toggle_web_dashboard_lan(self) -> None:
        dashboard = self.runtime_services.dashboard
        if dashboard is not None and dashboard.lan_enabled:
            self.runtime_services.disable_dashboard_lan()
            self._refresh_tray()
            self._refresh_web_access_row()
            messagebox.showinfo(
                "网页驾驶舱",
                "本次运行的局域网访问已关闭；局域网控制会话已撤销，本机页面仍可使用。",
                parent=self.root,
            )
            return

        confirmed = messagebox.askyesno(
            "开启局域网访问与控制",
            "仅应在可信的家庭或个人局域网中开启。\n\n"
            "Bomana 不会自动修改 Windows 防火墙，也不会把数据上传到互联网。\n\n"
            "开启后，同一网络中持有新配对码的设备可查看信息，并操作 Bomana 的固定功能。"
            "不会模拟键盘、控制游戏或提供任意命令能力。\n\n"
            "是否为本次运行开启？",
            parent=self.root,
        )
        if not confirmed:
            return
        try:
            self.runtime_services.enable_dashboard_lan()
        except Exception as exc:
            messagebox.showerror("局域网访问与控制失败", str(exc), parent=self.root)
            return
        self._refresh_tray()
        self._refresh_web_access_row()
        dashboard = self.runtime_services.dashboard
        if dashboard is None:
            return
        links = dashboard.lan_pairing_urls
        link_text = "\n".join(links)
        self._copy_to_clipboard(link_text)
        messagebox.showinfo(
            "局域网访问与控制已开启",
            f"手机访问链接已复制：\n{link_text}\n\n"
            f"配对码：{dashboard.pairing_code}\n\n"
            "若手机无法连接，请在 Windows 防火墙中允许 Bomana 的专用网络访问。",
            parent=self.root,
        )

    def _refresh_web_access_row(self) -> None:
        row = getattr(self, "web_access_row", None)
        if row is None:
            return
        dashboard = self.runtime_services.dashboard
        running = bool(dashboard is not None and dashboard.is_running)
        if not running:
            with contextlib.suppress(tk.TclError):
                row.grid_remove()
            return

        port = dashboard.port
        lan_addresses = dashboard.lan_addresses
        destinations = (
            " · ".join(f"{address}:{port}" for address in lan_addresses)
            if lan_addresses
            else f"本机 127.0.0.1:{port}"
        )
        self.web_access_lbl.config(
            text=f"网页  {dashboard.pairing_code}  ·  {destinations}",
            cursor="hand2",
        )
        self.web_lan_btn.config(text="关局域网" if lan_addresses else "开局域网")
        style_action_button(self.web_lan_btn, "danger" if lan_addresses else "secondary")
        with contextlib.suppress(tk.TclError):
            if row.winfo_manager() != "grid":
                row.grid()

    def _copy_web_dashboard_link(self) -> None:
        dashboard = self.runtime_services.dashboard
        links = dashboard.lan_pairing_urls if dashboard is not None else ()
        if not links:
            messagebox.showinfo(
                "网页驾驶舱",
                "请先从主窗口或托盘为本次运行开启局域网访问。",
                parent=self.root,
            )
            return
        self._copy_to_clipboard("\n".join(links))

    def _copy_web_dashboard_pairing_code(self) -> None:
        dashboard = self.runtime_services.dashboard
        if dashboard is None:
            return
        self._copy_to_clipboard(dashboard.pairing_code)

    def _copy_to_clipboard(self, value: str) -> None:
        try:
            self.root.clipboard_clear()
            self.root.clipboard_append(str(value))
            self.root.update_idletasks()
        except tk.TclError as exc:
            log_exception("clipboard_copy_failed", exc)

    def _adjust_alpha(self, event):
        """Ctrl+滚轮调整透明度"""
        if not self._locked:
            delta = 10 if event.delta > 0 else -10
            UIConfig.WINDOW_ALPHA = max(100, min(255, UIConfig.WINDOW_ALPHA + delta))
            Win32.setup_window(self.hwnd, click_through=False, alpha=UIConfig.WINDOW_ALPHA)
            self._save_config(warn_on_failure=True)

    def _quit(self):
        """退出应用"""
        self._stop = True
        self.game.save_timer_state()
        self._save_config()

        self.runtime_services.stop()
        self.bombing_services.stop()
        self.navigation_services.stop()

        with contextlib.suppress(Exception):
            self.sound.stop(drain=False)

        SingleInstanceManager.release()
        self.root.destroy()

    def _start_drag(self, e):
        """开始拖动"""
        if self._locked:
            return
        try:
            self._drag["x"] = e.x_root - self.root.winfo_x()
            self._drag["y"] = e.y_root - self.root.winfo_y()
        except tk.TclError:
            self._drag["x"] = 0
            self._drag["y"] = 0

    def _do_drag(self, e):
        """拖动中"""
        if self._locked:
            return
        x = self.root.winfo_pointerx() - self._drag["x"]
        y = self.root.winfo_pointery() - self._drag["y"]
        self.root.geometry(f"+{x}+{y}")

    def _end_drag(self, e=None):
        """结束拖动

        窗口吸附: 边缘距屏幕<SNAP_DISTANCE时自动吸附(支持多显示器)
        """
        if self._locked:
            return
        try:
            x = int(self.root.winfo_x())
            y = int(self.root.winfo_y())

            # 应用窗口吸附
            if SnapConfig.enabled:
                w = self.root.winfo_width()
                h = self.root.winfo_height()
                new_x, new_y = Win32.snap_to_edges(x, y, w, h, SnapConfig.SNAP_DISTANCE)

                # 如果位置变化，更新窗口位置
                if (new_x, new_y) != (x, y):
                    self.root.geometry(f"+{new_x}+{new_y}")
                    x, y = new_x, new_y

            self._manual_pos = (x, y)
            self._user_moved = True
            self._save_config()
        except tk.TclError:
            pass

    def _show_bomb_selector(self):
        """显示武器选择对话框（方法名保留以兼容既有绑定）。"""
        weapon_catalog = self._get_weapon_catalog()
        if weapon_catalog is None:
            messagebox.showwarning(
                "武器目录不可用",
                "武器目录缺失或校验失败，已停用武器选择与解算。",
                parent=self.root,
            )
            return
        snap = self.game.snapshot()
        airborne = snap.phase == Phase.ALIVE and not snap.on_ground
        WeaponSelectorDialog(
            self.root,
            self,
            catalog=weapon_catalog,
            initial_weapon=weapon_catalog.selected_weapon_id,
            aircraft_type_name=str(getattr(snap, "aircraft_type_name", "") or ""),
            airborne=airborne,
        )

    def _update_ui(self):
        """UI更新循环(20fps)

        性能优化:
        - panel_renderer.update_zone_display() 返回是否需重算尺寸
        - 仅在布局结构变化时调用_recalc_size()
        - 使用缓存字体和Label复用池
        """
        if self._stop:
            return
        pending_after_id = self._ui_after_id
        self._ui_after_id = None
        if pending_after_id is not None:
            with contextlib.suppress(tk.TclError):
                self.root.after_cancel(pending_after_id)
        loop_start = time.monotonic()
        try:
            self._update_ui_frame(loop_start)
        except Exception as exc:
            self._last_ui_work_ms = max(0.0, (time.monotonic() - loop_start) * 1000.0)
            log_exception(
                "ui_update_failed",
                exc,
                ui_gap_ms=float(self._last_ui_gap_ms),
                ui_work_ms=float(self._last_ui_work_ms),
            )
        finally:
            if not self._stop:
                elapsed_ms = (time.monotonic() - loop_start) * 1000.0
                self._last_ui_work_ms = elapsed_ms
                delay = max(0, int(UIConfig.UI_REFRESH_MS - elapsed_ms))
                self._ui_after_id = self.root.after(delay, self._update_ui)

    def _update_ui_frame(self, loop_start: float) -> None:
        """Render one UI frame. Scheduling is owned by _update_ui()."""
        if self._last_ui_frame_ts > 0.0:
            self._last_ui_gap_ms = max(0.0, (loop_start - self._last_ui_frame_ts) * 1000.0)
        self._last_ui_frame_ts = loop_start
        live_snap = self.game.snapshot()
        self._restored_state = self.game.timer_restore_applied
        if self._debug:
            snap = self.debug_support.build_debug_snapshot(live_snap)
        else:
            snap = live_snap
            self._debug_effective_mock = False
            self._debug_live_available = False
        self._last_snapshot = snap

        debug_mock_mode = bool(self._debug and self._debug_effective_mock)
        self.runtime_services.publish_dashboard(snap, list(self.chk_items))
        if hasattr(self.runtime_services, "publish_dashboard_control"):
            self._publish_web_control_state(snapshot=snap)

        if not self._debug:
            # 高光时刻弱提醒：成功着陆后显示，起飞后消除（不弹窗）
            if snap.sortie_id != self._nudge_sortie_seen:
                self._nudge_sortie_seen = snap.sortie_id
                self._nudge_airborne_seen = False
                if self._nudge_visible:
                    self._nudge_visible = False
                    self._update_hint()

            if snap.phase == Phase.ALIVE and not snap.on_ground:
                self._nudge_airborne_seen = True

            if (
                snap.phase == Phase.ALIVE
                and snap.landed_flash
                and not self._last_landed_flash
                and snap.sortie_id != self._nudge_sortie_id
            ):
                self._nudge_sortie_id = snap.sortie_id
                if self._nudge_airborne_seen and not self._nudge_visible:
                    self._nudge_visible = True
                    self._update_hint()
            self._last_landed_flash = snap.landed_flash

            # 起飞后清除提示
            if self._nudge_visible and snap.phase == Phase.ALIVE and not snap.on_ground:
                self._nudge_visible = False
                self._update_hint()

            if snap.phase != Phase.ALIVE:
                self._nudge_airborne_seen = False
        else:
            self._last_landed_flash = False
            self._nudge_airborne_seen = False

        if (
            self._manual_reset_confirm_until > 0.0
            and time.monotonic() >= self._manual_reset_confirm_until
        ):
            self._clear_manual_reset_confirmation(refresh_hint=True)

        zones_enabled = ENABLE_ZONES and PanelConfig.is_effectively_enabled("zones")
        airfields_enabled = ENABLE_AIRFIELDS and PanelConfig.is_effectively_enabled("airfields")
        fuel_enabled = ENABLE_FUEL and PanelConfig.is_effectively_enabled("fuel")
        speed_enabled = PanelConfig.is_effectively_enabled("speed")
        checklist_enabled = ENABLE_CHECKLIST and PanelConfig.is_effectively_enabled("checklist")
        bombing_enabled = ENABLE_CCRP and PanelConfig.is_effectively_enabled("bombing")
        bombing_integrated = bombing_enabled and PanelConfig.bombing_mode == "integrated"
        history_mode_active = PanelConfig.speed_history_mode

        # 控制面板可见性（结合PanelConfig设置和编译开关）
        # 战区/机场/燃油/投弹面板需要任一相关面板启用
        show_zone_panel = (snap.phase in (Phase.ALIVE, Phase.LOSS_PENDING)) and (
            zones_enabled or airfields_enabled or fuel_enabled or bombing_integrated
        )
        self.panel_renderer.set_zone_panel_visible(show_zone_panel)
        if show_zone_panel:
            # update_zone_display 返回是否需要重算尺寸
            need_recalc = self.panel_renderer.update_zone_display(snap)
            if need_recalc:
                now_recalc = time.monotonic()
                # 数据抖动期节流尺寸重算，避免高频geometry震荡
                if (now_recalc - self._last_zone_recalc_ts) >= 0.25:
                    self._last_zone_recalc_ts = now_recalc
                    self._recalc_size()
        else:
            self._refresh_standalone_navigation_if_visible(snap)
        bombing_services = getattr(self, "bombing_services", None)
        if bombing_services is not None:
            bombing_services.update(
                snap,
                active=(
                    not history_mode_active and snap.phase in (Phase.ALIVE, Phase.LOSS_PENDING)
                ),
            )

        # 检查清单面板（受编译开关控制）
        show_chk = (
            checklist_enabled
            and (snap.phase == Phase.ALIVE)
            and (snap.on_ground or snap.landed_flash)
        )
        self.panel_renderer.set_checklist_visible(show_chk)
        self._apply_speed_history_layout(history_mode_active)

        # 更新计时器显示
        if history_mode_active:
            self._last_beep_sec = -1
            self.banana_progress.set_progress(0.0)
            self.banana_progress.set_color(Theme.BLUE)
        else:
            self.timer_lbl.config(text=fmt_time(snap.remaining_sec))
            if snap.remaining_sec is None:
                self.timer_lbl.config(fg=Theme.LED_DIM)
                self.banana_progress.set_progress(0.0)
                self.banana_progress.set_color(Theme.BLUE)
            else:
                remain = snap.remaining_sec
                # LED 芯片上的数字：常态红、临近琥珀、最后 10 秒亮红
                color = (
                    Theme.LED_CRIT
                    if remain <= 10
                    else Theme.LED_WARN
                    if remain <= GameConfig.FINAL_WARNING_SEC
                    else Theme.LED
                )
                bar = (
                    Theme.RED
                    if remain <= 10
                    else Theme.YELLOW
                    if remain <= GameConfig.FINAL_WARNING_SEC
                    else Theme.BLUE
                )
                self.timer_lbl.config(fg=color)
                self.banana_progress.set_progress(snap.progress)
                self.banana_progress.set_color(bar)

                # 播放警告音
                remain_int = int(remain)
                if (remain <= GameConfig.FINAL_WARNING_SEC) and (not debug_mock_mode):
                    if (
                        remain_int in SoundConfig.WARNING_SECONDS
                        and remain_int != self._last_beep_sec
                    ):
                        pattern = "warning" if remain_int in SoundConfig.MAJOR_WARNINGS else "tick"
                        self.sound.play(pattern=pattern)
                        self._last_beep_sec = remain_int
                else:
                    self._last_beep_sec = -1

        # 更新生命/周期信息
        self.life_lbl.config(
            text=(f"第{snap.life_index}次复活" if snap.life_index is not None else "未复活")
        )
        self.cycle_lbl.config(text=(f"第{snap.cycle}轮" if snap.cycle is not None else "未开始"))

        status_model = build_status_presentation(
            phase=snap.phase,
            api_down=snap.api_down,
            api_down_pending=snap.api_down_pending,
            has_life=snap.life_index is not None,
            landed_flash=snap.landed_flash,
            on_ground=snap.on_ground,
            overspeed_level=snap.overspeed_level,
        )

        # 更新徽章
        self.badge_main.set(*status_model.main_badge)
        self.badge_flight.set(*status_model.flight_badge)
        if speed_enabled:
            if self.speed_row.winfo_manager() != "grid":
                self.speed_row.grid(
                    row=3,
                    column=0,
                    sticky="ew",
                    padx=int(8 * self.scale),
                    pady=(
                        int(UIConfig.PADDING_SPEED_STRIP[0] * self.scale),
                        int(UIConfig.PADDING_SPEED_STRIP[1] * self.scale),
                    ),
                )
            speed_level = self.panel_renderer.update_speed_strip(snap, debug_mock_mode)
        else:
            speed_level = "unknown"
            if self.speed_row.winfo_manager() == "grid":
                self.speed_row.grid_remove()
            self._last_overspeed_level = "unknown"
            self._last_overspeed_sound_ts = 0.0
        self._refresh_speed_history_ui(snap, speed_level)

        # v6.6.1: 起落架徽章（集成警告和进度）
        # 显示条件：警告 或 正在移动
        show_gear_badge = snap.gear_warning or snap.gear_moving

        if show_gear_badge:
            # 确定徽章颜色和文字
            if snap.gear_moving:
                # 正在移动时：显示进度（完整中文描述）
                pct = int(snap.gear_pct)
                if snap.gear_retracting:
                    badge_text = f"正在收起{pct}%"
                    badge_bg = Theme.BLUE
                else:
                    badge_text = f"正在放下{pct}%"
                    badge_bg = Theme.YELLOW
            else:
                # 警告状态
                badge_text = "起落架"
                badge_bg = Theme.ORANGE

            self.badge_gear.set(badge_text, Theme.TEXT, badge_bg)
            if not self.badge_gear.winfo_ismapped():
                anchor_widget = (
                    self.badge_lock if hasattr(self, "badge_lock") else self.badge_flight
                )
                self.badge_gear.pack(
                    side="left",
                    padx=(int(UIConfig.SPACING_BADGE * self.scale), 0),
                    after=anchor_widget,
                )
        else:
            if self.badge_gear.winfo_ismapped():
                self.badge_gear.pack_forget()

        status_fg = Theme.YELLOW if snap.api_down else Theme.TEXT_DIM
        if speed_enabled and speed_level == "critical":
            status_fg = Theme.RED
        elif speed_enabled and speed_level == "warning" and not snap.api_down:
            status_fg = Theme.YELLOW
        self.status_txt.config(text=status_model.status_text, fg=status_fg)

        # 调试信息
        if self._debug:
            self.diag_lbl.config(text=self.debug_support.build_debug_text(live_snap, snap))
