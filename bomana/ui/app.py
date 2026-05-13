# -*- coding: utf-8 -*-
"""Main Tk app container."""

import ctypes
import time
import tkinter as tk
import webbrowser
from enum import Enum
from tkinter import font as tkfont
from tkinter import messagebox
from typing import Any, Dict, List, Optional, Tuple

from bomana.config import (
    ENABLE_AIRFIELDS,
    ENABLE_CCRP,
    ENABLE_CHECKLIST,
    ENABLE_FUEL,
    ENABLE_ZONES,
    AboutConfig,
    BallisticPhysicsParams,
    BombConfig,
    ChecklistConfig,
    FileConfig,
    GameConfig,
    HotkeyConfig,
    HUDConfig,
    OverspeedConfig,
    PanelConfig,
    SnapConfig,
    SoundConfig,
    Theme,
    UIConfig,
)
from bomana.core.logic import GameLogic
from bomana.core.state import Phase, UISnapshot
from bomana.ui.debug_support import AppDebugSupport
from bomana.ui.dialogs import AboutDialog, BombSelectorDialog, ChecklistEditor, SettingsDialog
from bomana.ui.main_window import MainWindowBuilder
from bomana.ui.nav_window import NavigationWindow
from bomana.ui.panel_renderer import AppPanelRenderer
from bomana.ui.runtime import LogicPoller, TkEventDispatcher
from bomana.ui.runtime_services import HAS_TRAY, AppRuntimeServices
from bomana.utils.diagnostics import log_event, log_exception
from bomana.utils.file_utils import ConfigManager, resource_path
from bomana.utils.math_utils import calculate_smart_scale
from bomana.utils.sound import SoundManager
from bomana.utils.system import SingleInstanceManager, Win32, select_ui_font_family


def fmt_time(sec: Optional[float]) -> str:
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

    def __init__(self, root: tk.Tk):
        self.root = root
        self.game = GameLogic()
        self.sound = SoundManager()
        self.dispatcher = TkEventDispatcher(root)
        self.logic_poller = LogicPoller(self.game, lambda: self._stop)
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
            "投弹窗口",
            "地面检查",
            "超速压测",
        ]
        self._alive_phases = (Phase.ALIVE, Phase.LOSS_PENDING)
        self._last_beep_sec = -1
        self._last_overspeed_sound_ts = 0.0
        self._last_overspeed_level = "unknown"
        self._zone_sound_enabled = True
        self._manual_reset_confirm_until = 0.0

        # 窗口状态
        self._user_moved = False
        self._manual_pos = None
        self._last_sortie_id = -1
        self._restored_state = False
        self._last_zone_destroyed_alert = False
        self._last_landed_flash = False
        self._nudge_visible = False
        self._nudge_sortie_id = -1
        self._nudge_airborne_seen = False
        self._nudge_sortie_seen = -1
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
        self._cached_fonts: Dict[str, tuple] = {}
        self._zone_row_pool: List[Any] = []
        self._compact_zone_row_pool: List[Any] = []
        self._airport_row_pool: List[Any] = []
        self._compact_airport_row_pool: List[Any] = []
        self._last_layout_signature = None
        self._last_expand_ts = 0.0
        self._last_zone_recalc_ts = 0.0
        self._zone_layout_mode = None
        self._airport_layout_mode = None
        self._history_mode_layout_active = False
        self._history_mode_nav_was_visible = False
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
        if ENABLE_ZONES:
            self.nav_window = NavigationWindow(self)
            if PanelConfig.navigation_mode == "standalone":
                self.nav_window.show()
        else:
            self.nav_window = None

        # v6.8.0: 初始化 HUD 叠加层（按配置决定是否显示）
        if HUDConfig.enabled:
            if not self._show_hud_overlay():
                HUDConfig.enabled = False

        # 恢复状态并启动
        self._restored_state = self.game.restore_timer_state()
        self.logic_poller.start()
        self._update_ui()

        if HAS_TRAY:
            self._init_tray()

    @property
    def hud_overlay(self):
        """Compatibility view for dialog code that inspects the active HUD surface."""
        return self.runtime_services.hud_overlay

    def _load_config(self):
        """加载用户配置

        加载顺序: 主题必须在UI创建前应用
        配置项: alpha/scale/theme/panels/hud/hotkey_bindings/snap/window_position
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
        theme_name = config.get("theme", "fluent_dark")
        Theme.apply(theme_name)

        # 面板显示设置
        panels = config.get("panels", {})
        PanelConfig.show_zones = panels.get("show_zones", True)
        PanelConfig.show_airfields = panels.get("show_airfields", True)
        PanelConfig.show_fuel = panels.get("show_fuel", True)
        PanelConfig.show_speed = panels.get("show_speed", True)
        PanelConfig.speed_history_mode = panels.get("speed_history_mode", False)
        PanelConfig.show_checklist = panels.get("show_checklist", True)
        PanelConfig.show_bombing = panels.get("show_bombing", True)  # v6.0 新增

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
        else:
            # 精简版强制使用集成模式，忽略配置文件中的设置
            PanelConfig.navigation_mode = "integrated"

        # v6.0 新增：炸弹选择（仅在CCRP启用时）
        if ENABLE_CCRP:
            selected_bomb = config.get("selected_bomb", "su_fab100")
            if BombConfig.get_bomb_data(selected_bomb):
                BombConfig.selected_bomb = selected_bomb
            tuning = config.get("ccrp_tuning", {})
            BallisticPhysicsParams.apply_user_tuning(tuning)

        # 根据编译开关初始化面板状态
        PanelConfig.init_from_compile_switches()

        # HUD 设置（缺省字段自动回退，兼容旧配置）
        hud_enabled = config.get("hud_enabled", HUDConfig.enabled)
        if isinstance(hud_enabled, (bool, int)):
            HUDConfig.enabled = bool(hud_enabled)
        HUDConfig.apply_dict(config.get("hud", {}))

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

        # 恢复窗口位置（支持多显示器）
        saved_pos = config.get("window_position")
        if saved_pos and isinstance(saved_pos, dict):
            corner_name = saved_pos.get("corner")
            if corner_name:
                try:
                    self._corner = Corner[corner_name]
                except KeyError:
                    pass
            manual_pos = saved_pos.get("manual_pos")
            if manual_pos and isinstance(manual_pos, list) and len(manual_pos) == 2:
                self._manual_pos = tuple(manual_pos)
                self._user_moved = saved_pos.get("user_moved", False)
            # 记录显示器索引（用于多显示器支持）
            self._saved_monitor_index = saved_pos.get("monitor_index", 0)
        else:
            self._saved_monitor_index = 0

        beep_enabled = config.get("beep_enabled", False)
        self.sound.set_enabled(beep_enabled)
        SoundConfig.apply_user_config(config.get("sound_settings", {}))

        OverspeedConfig.apply_user_config(config.get("overspeed", {}))

    def _save_config(self):
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

        # v6.2.1: 导航条模式
        config["navigation_mode"] = PanelConfig.navigation_mode
        if PanelConfig.navigation_window_pos:
            config["navigation_window_pos"] = list(PanelConfig.navigation_window_pos)
        config["navigation_bar_width"] = PanelConfig.navigation_bar_width

        # v6.0 新增：炸弹选择（仅在CCRP启用时保存）
        if ENABLE_CCRP:
            config["selected_bomb"] = BombConfig.selected_bomb
            config["ccrp_tuning"] = BallisticPhysicsParams.get_user_tuning()

        # HUD 设置
        config["hud_enabled"] = HUDConfig.enabled
        config["hud"] = HUDConfig.to_dict()

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
        config["sound_settings"] = SoundConfig.export_user_config()
        config["overspeed"] = OverspeedConfig.export_user_config()

        # 窗口位置（包含多显示器信息）
        monitor_index = 0
        if self._manual_pos:
            monitor = Win32.get_monitor_at(self._manual_pos[0], self._manual_pos[1])
            if monitor:
                monitor_index = monitor.get("index", 0)

        config["window_position"] = {
            "corner": self._corner.name,
            "manual_pos": list(self._manual_pos) if self._manual_pos else None,
            "user_moved": self._user_moved,
            "monitor_index": monitor_index,
        }

        ConfigManager.save(config)

    def _init_window_base(self):
        """初始化窗口基础设置"""
        self.root.title("WT Timer")

        # 加载图标
        try:
            p = resource_path(FileConfig.ICON_FILE)
            self._tk_icon = tk.PhotoImage(file=p)
            self.root.iconphoto(True, self._tk_icon)
        except tk.TclError, FileNotFoundError:
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

        try:
            self.root.tk.call("tk", "scaling", float(self.scale))
        except tk.TclError:
            pass

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
        return UIConfig.scaled_font(
            font_def,
            self.scale,
            size_mult=size_mult,
            min_size=min_size,
        )

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
        return self._cached_fonts.get(name, ("Segoe UI", 10))

    def _select_font_family(self) -> str:
        """Pick an available UI font family."""
        return select_ui_font_family(self.root)

    def _apply_font_family(self) -> None:
        """Apply a unified UI font family."""
        fam = self._select_font_family()
        if not fam:
            return
        font_keys = [
            "FONT_TIMER",
            "FONT_LIFE",
            "FONT_CYCLE",
            "FONT_PILL",
            "FONT_STATUS",
            "FONT_CHECKLIST_TITLE",
            "FONT_CHECKLIST_ITEM",
            "FONT_ZONE_TITLE",
            "FONT_ZONE_ITEM",
            "FONT_DEBUG",
            "FONT_HINT",
        ]
        for key in font_keys:
            val = getattr(UIConfig, key, None)
            if isinstance(val, (list, tuple)) and len(val) >= 2:
                new_val = (fam, val[1], *val[2:])
                setattr(UIConfig, key, new_val)

    def _finalize_window_geometry_and_styles(self):
        """最终确定窗口几何和样式"""
        self.root.update_idletasks()
        req_w = self.root.winfo_reqwidth()
        req_h = self.root.winfo_reqheight()
        self.W = req_w
        self.H = req_h
        self._position()
        self.root.update_idletasks()
        Win32.setup_window(self.hwnd, click_through=True, alpha=UIConfig.WINDOW_ALPHA)

    def _init_ui(self):
        """初始化 UI 布局（稳定的主窗口骨架）。"""
        MainWindowBuilder(self).build()

    def _rebuild_checklist(self):
        """重建检查清单UI（纯展示模式）"""
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
        wrap_width = int(180 * s)

        # 使用 Label + ○ 符号（纯展示，无交互）
        for item in self.chk_items:
            lbl = tk.Label(
                self.chk_content_frame,
                text=f"○ {item}",
                font=font_item,
                fg=Theme.TEXT_DIM,
                bg=Theme.GRAYPILL,
                anchor="w",
                justify="left",
                wraplength=wrap_width,
            )
            lbl.pack(fill="x", padx=(pad_x, pad_x), pady=1, anchor="w")

    def _init_bindings(self):
        """初始化键盘/鼠标绑定

        ╔══════════════════════════════════════════════════════════════════════╗
        ║ 说明：右键菜单已移至系统托盘，窗口不再响应右键                         ║
        ╚══════════════════════════════════════════════════════════════════════╝
        """

        self.root.bind(f"<{HotkeyConfig.KEY_LOCK}>", lambda e: self._toggle_lock())
        self.root.bind(f"<{HotkeyConfig.KEY_CORNER}>", lambda e: self._next_corner())
        self.root.bind(f"<{HotkeyConfig.KEY_BEEP}>", lambda e: self._toggle_beep())
        self.root.bind(f"<{HotkeyConfig.KEY_ZONES}>", lambda e: self._toggle_zone_sound())
        self.root.bind("<Control-MouseWheel>", self._adjust_alpha)
        self.root.bind(
            "<Control-Shift-Left>", lambda e: self._cycle_debug_scene(-1) if self._debug else None
        )
        self.root.bind(
            "<Control-Shift-Right>", lambda e: self._cycle_debug_scene(1) if self._debug else None
        )
        self.root.bind(
            "<Control-Shift-m>", lambda e: self._toggle_debug_mock_mode() if self._debug else None
        )

        # 拖动相关
        self._drag = {"x": 0, "y": 0}
        self.root.bind("<Button-1>", self._start_drag)
        self.root.bind("<B1-Motion>", self._do_drag)
        self.root.bind("<ButtonRelease-1>", self._end_drag)

        # v6.6.3: 焦点保护 - 锁定状态下拒绝焦点，确保点击穿透有效
        self.root.bind("<FocusIn>", self._on_focus_in)

        # 不再绑定窗口右键菜单（功能移至系统托盘）

    def _toggle_panel(self, panel_key: str):
        """切换面板显示状态"""
        current = getattr(PanelConfig, panel_key)
        setattr(PanelConfig, panel_key, not current)
        self._save_config()
        # 立即刷新布局，避免留下空白
        self._recalc_size(force_shrink=True)
        self._update_ui()
        self._refresh_tray()

    def _toggle_speed_history_mode(self):
        """切换空历速度模式。"""
        PanelConfig.speed_history_mode = not PanelConfig.speed_history_mode
        self._save_config()
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
            if state_changed and self.nav_window:
                self._history_mode_nav_was_visible = bool(self.nav_window.is_visible())
            if self.nav_window and self.nav_window.is_visible():
                self.nav_window.hide()
            if self.top_row1.winfo_manager() == "grid":
                self.top_row1.grid_remove()
            if self.top_row2.winfo_manager() == "grid":
                self.top_row2.grid_remove()
            if self.progress_frame.winfo_manager() == "grid":
                self.progress_frame.grid_remove()
            if self.history_mode_frame.winfo_manager() != "grid":
                self.history_mode_frame.grid(
                    row=2,
                    column=0,
                    sticky="ew",
                    padx=int(8 * self.scale),
                    pady=self._history_mode_pad_y,
                )
        else:
            if state_changed:
                if (
                    self.nav_window
                    and self._history_mode_nav_was_visible
                    and ENABLE_ZONES
                    and PanelConfig.navigation_mode == "standalone"
                ):
                    self.nav_window.show()
                self._history_mode_nav_was_visible = False
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
                    sticky="ew",
                    padx=int(8 * self.scale),
                    pady=(int(pad_top * self.scale), int(pad_bot * self.scale)),
                )
            if self.progress_frame.winfo_manager() != "grid":
                pad_top, pad_bot = UIConfig.PADDING_PROGRESS
                self.progress_frame.grid(
                    row=4,
                    column=0,
                    sticky="ew",
                    padx=int(8 * self.scale),
                    pady=(int(pad_top * self.scale), int(pad_bot * self.scale)),
                )
            self._update_mid_panel_layout()

    def _refresh_speed_history_ui(self, snap: UISnapshot, speed_level: str) -> None:
        """刷新历史模式专用头部文案。"""
        if not PanelConfig.speed_history_mode:
            return

        if snap.api_down:
            phase_text = "8111 离线"
            phase_fg = Theme.YELLOW
        elif snap.phase == Phase.ALIVE and not snap.on_ground:
            phase_text = "飞行中"
            phase_fg = Theme.GREEN if speed_level not in ("warning", "critical") else Theme.YELLOW
        elif snap.phase == Phase.ALIVE:
            phase_text = "地面待命"
            phase_fg = Theme.TEXT_DIM
        elif snap.phase == Phase.LOSS_PENDING:
            phase_text = "状态切换中"
            phase_fg = Theme.YELLOW
        else:
            phase_text = "等待进入战局"
            phase_fg = Theme.TEXT_MUTED

        aircraft_text = self._format_aircraft_type_label(
            str(getattr(snap, "aircraft_type_name", "") or "")
        )
        self.history_mode_phase_lbl.config(text=phase_text, fg=phase_fg)
        self.history_mode_hint_lbl.config(
            text=f"计时和导航已隐藏，当前机型：{aircraft_text}",
        )

    def _refresh_tray(self):
        """刷新系统托盘菜单状态

        调用此方法以确保托盘菜单的勾选状态与实际状态同步。
        """
        self.runtime_services.refresh_tray()

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

    def _show_debug_ui(self) -> None:
        self.debug_support.show_debug_ui()

    def _hide_debug_ui(self) -> None:
        self.debug_support.hide_debug_ui()

    def _toggle_debug_mock_mode(self) -> None:
        self.debug_support.toggle_debug_mock_mode()

    def _cycle_debug_scene(self, delta: int) -> None:
        self.debug_support.cycle_debug_scene(delta)

    def _update_debug_controls(self) -> None:
        self.debug_support.update_debug_controls()

    @staticmethod
    def _debug_direction(relative_deg: float) -> str:
        return AppDebugSupport.debug_direction(relative_deg)

    def _debug_live_snapshot_available(self, snap: UISnapshot) -> bool:
        return self.debug_support.debug_live_snapshot_available(snap)

    def _build_debug_snapshot(self, base_snap: UISnapshot) -> UISnapshot:
        return self.debug_support.build_debug_snapshot(base_snap)

    def _build_debug_mock_snapshot(self, base_snap: UISnapshot) -> UISnapshot:
        return self.debug_support.build_debug_mock_snapshot(base_snap)

    def _build_debug_text(self, live_snap: UISnapshot, render_snap: UISnapshot) -> str:
        return self.debug_support.build_debug_text(live_snap, render_snap)

    @staticmethod
    def _format_aircraft_type_label(raw: str) -> str:
        return AppPanelRenderer.format_aircraft_type_label(raw)

    def _update_speed_strip(self, snap: UISnapshot, debug_mock_mode: bool) -> str:
        return self.panel_renderer.update_speed_strip(snap, debug_mock_mode)

    def _toggle_zone_sound(self):
        """切换战区提示音"""
        self._zone_sound_enabled = not self._zone_sound_enabled
        self._update_hint()
        self._save_config()
        self._refresh_tray()
        if self._zone_sound_enabled:
            self.sound.play(pattern="on")

    def _ensure_hud_overlay(self) -> bool:
        """确保 HUD 叠加层实例可用。"""
        return self.runtime_services.ensure_hud_overlay()

    def _show_hud_overlay(self) -> bool:
        """显示 HUD 叠加层。"""
        return self.runtime_services.show_hud_overlay()

    def _update_hud_overlay(self, snap: UISnapshot) -> None:
        """在 UI 刷新中更新 HUD 叠加层。"""
        self.runtime_services.update_hud_overlay(snap)

    def _toggle_hud(self):
        """切换 HUD 叠加层开关。"""
        self.runtime_services.toggle_hud()

    def _toggle_navigation_mode(self):
        """切换导航条模式（集成/独立）

        仅在战区功能启用时可用。
        """
        if not ENABLE_ZONES or not self.nav_window:
            return

        self._reset_navigation_layout_state()
        if PanelConfig.navigation_mode == "integrated":
            PanelConfig.navigation_mode = "standalone"
            self.nav_window.clear_display()
            self.nav_window.show()
        else:
            PanelConfig.navigation_mode = "integrated"
            self.nav_window.hide()
        self._update_nav_mode_button()
        self._save_config()
        # 先刷新布局，再强制收缩，避免残留空白
        self._update_ui()
        self._recalc_size(force_shrink=True)
        self._refresh_tray()
        log_event("navigation_mode_toggle", mode=PanelConfig.navigation_mode)

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
            edge_anchor = self._capture_snap_anchor(old_x, old_y, old_w, old_h)

        # 宽高双向收缩防抖：扩张立即生效，收缩需满足阈值且避开刚扩张后的冷却窗口
        now = time.monotonic()
        dw = new_w - old_w
        dh = new_h - old_h
        minor_shrink_px = max(16, int(18 * self.scale))
        shrink_cooldown_sec = 0.8

        if dw > 0 or dh > 0:
            self._last_expand_ts = now

        if not force_shrink:
            if dw < 0:
                if abs(dw) < minor_shrink_px or (now - self._last_expand_ts) < shrink_cooldown_sec:
                    new_w = old_w
            if dh < 0:
                if abs(dh) < minor_shrink_px or (now - self._last_expand_ts) < shrink_cooldown_sec:
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
                x, y = self._apply_snap_anchor(x, y, self.W, self.H, edge_anchor)
            clamp_margin = 0 if self._user_moved else None
            x, y = self._clamp_to_screen(x, y, margin=clamp_margin)
            self.root.geometry(f"{self.W}x{self.H}+{x}+{y}")
            if self._user_moved:
                self._manual_pos = (x, y)
        else:
            self._position()

    def _capture_snap_anchor(self, x: int, y: int, w: int, h: int) -> Optional[Dict[str, Any]]:
        """捕获窗口当前贴边锚点（仅在手动拖拽场景使用）。"""
        if not SnapConfig.enabled:
            return None
        monitor = Win32.get_monitor_at(x + w // 2, y + h // 2)
        if not monitor:
            return None

        mon_x = monitor["x"]
        mon_y = monitor["y"]
        mon_w = monitor["width"]
        mon_h = monitor["height"]
        threshold = max(1, int(SnapConfig.SNAP_DISTANCE))

        left_gap = x - mon_x
        right_gap = (mon_x + mon_w) - (x + w)
        top_gap = y - mon_y
        bottom_gap = (mon_y + mon_h) - (y + h)

        horizontal = None
        vertical = None

        if abs(left_gap) <= threshold:
            horizontal = ("left", left_gap)
        elif abs(right_gap) <= threshold:
            horizontal = ("right", right_gap)

        if abs(top_gap) <= threshold:
            vertical = ("top", top_gap)
        elif abs(bottom_gap) <= threshold:
            vertical = ("bottom", bottom_gap)

        if not horizontal and not vertical:
            return None
        return {"monitor": monitor, "horizontal": horizontal, "vertical": vertical}

    def _apply_snap_anchor(
        self, x: int, y: int, w: int, h: int, anchor: Dict[str, Any]
    ) -> Tuple[int, int]:
        """按捕获的贴边锚点修正新尺寸下的位置。"""
        monitor = anchor.get("monitor") or {}
        mon_x = int(monitor.get("x", 0))
        mon_y = int(monitor.get("y", 0))
        mon_w = int(monitor.get("width", 0))
        mon_h = int(monitor.get("height", 0))

        horizontal = anchor.get("horizontal")
        vertical = anchor.get("vertical")

        if horizontal and mon_w > 0:
            edge, gap = horizontal
            gap = int(gap)
            if edge == "left":
                x = mon_x + gap
            elif edge == "right":
                x = mon_x + mon_w - w - gap

        if vertical and mon_h > 0:
            edge, gap = vertical
            gap = int(gap)
            if edge == "top":
                y = mon_y + gap
            elif edge == "bottom":
                y = mon_y + mon_h - h - gap

        return x, y

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

        # 获取当前窗口所在的显示器
        try:
            current_x = self.root.winfo_x()
            current_y = self.root.winfo_y()
        except tk.TclError:
            current_x, current_y = 0, 0

        # 如果窗口位置有效，获取该位置所在的显示器
        if (current_x, current_y) != (0, 0):
            monitor = Win32.get_monitor_at(current_x, current_y)
        else:
            # 否则使用主显示器
            monitors = Win32.get_all_monitors()
            monitor = next(
                (m for m in monitors if m.get("is_primary")), monitors[0] if monitors else None
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

    def _clamp_to_screen(self, x: int, y: int, margin: Optional[int] = None) -> Tuple[int, int]:
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

    def _toggle_lock(self):
        """切换锁定/解锁

        v6.0.1 优化：锁定/解锁时使用不同透明度，提供明确的视觉反馈
        - 锁定状态：使用配置的透明度（默认210）
        - 解锁状态：提高透明度到240，让窗口更明显便于拖动
        """
        self._locked = not self._locked
        # 解锁时提高不透明度，让用户更容易看到可拖动区域
        alpha = UIConfig.WINDOW_ALPHA if self._locked else min(240, UIConfig.WINDOW_ALPHA + 30)
        Win32.setup_window(self.hwnd, click_through=self._locked, alpha=alpha)
        if self.nav_window:
            self.nav_window.apply_window_styles(click_through=self._locked, alpha=alpha)
        self.runtime_services.apply_hud_lock_state(self._locked)
        self._update_hint()
        self._refresh_tray()

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
            try:
                Win32.setup_window(self.hwnd, click_through=True, alpha=UIConfig.WINDOW_ALPHA)
            except Exception:
                pass

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
            base_text = "  ·  ".join(parts)

        confirm_text = self._manual_reset_confirm_text()
        if PanelConfig.speed_history_mode:
            history_text = "空历模式: 独立速度界面"
            if confirm_text:
                return f"{confirm_text}  ·  {history_text}  ·  {base_text}"
            return f"{history_text}  ·  {base_text}"
        if confirm_text:
            return f"{confirm_text}  ·  {base_text}"
        return base_text

    def _manual_reset_confirm_text(self) -> str:
        """返回热键二次确认的弱提醒文案。"""
        if time.monotonic() >= self._manual_reset_confirm_until:
            return ""
        return f"再按一次 [{HotkeyConfig.KEY_RESET}] 确认重置"

    def _nudge_text(self) -> str:
        return "提示：如果 Bomana 对你有帮助，欢迎点一个 GitHub Star（起飞后自动隐藏）"

    def _update_hint(self) -> None:
        """更新提示文本"""
        if hasattr(self, "hint_lbl") and self.hint_lbl:
            hint_fg = Theme.YELLOW if self._manual_reset_confirm_text() else Theme.TEXT_MUTED
            self.hint_lbl.config(text=self._hint_text(), fg=hint_fg)
        self._update_lock_badge()
        if hasattr(self, "_hint_width_cache") and self._hint_width_cache is not None:
            self._hint_width_cache["text"] = ""
        if hasattr(self, "nudge_lbl") and self.nudge_lbl:
            self.nudge_lbl.config(text=(self._nudge_text() if self._nudge_visible else ""))
        if hasattr(self, "star_lbl") and self.star_lbl:
            self.star_lbl.config(
                text=("GitHub Star" if self._nudge_visible else ""),
                cursor=("hand2" if self._nudge_visible else "arrow"),
            )

    def _open_star_url(self) -> None:
        url = AboutConfig.GITHUB_URL
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass

    def _update_nav_mode_button(self):
        """更新独立导航条按钮状态显示"""
        if not ENABLE_ZONES or not hasattr(self, "standalone_btn"):
            return
        if PanelConfig.navigation_mode == "standalone":
            self.standalone_btn.config(text="独立导航窗: 已启用", fg=Theme.GREEN, bg=Theme.BG)
        else:
            self.standalone_btn.config(text="切换独立导航窗", fg=Theme.TEXT_MUTED, bg=Theme.BG)

    def _next_corner(self):
        """切换到下一个角落"""
        corners = list(Corner)
        i = (corners.index(self._corner) + 1) % len(corners)
        self._corner = corners[i]
        self._user_moved = False
        self._manual_pos = None
        self._position()
        self._save_config()

    def _toggle_beep(self):
        """切换提示音"""
        enabled = not self.sound.is_enabled()
        self.sound.set_enabled(enabled)
        self._update_hint()
        self._save_config()
        self._refresh_tray()
        if enabled:
            self.sound.play(pattern="on")

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

    def _show_settings(self, initial_tab: Optional[str] = None):
        """显示设置对话框

        从托盘菜单调用，不受窗口锁定状态影响。
        """
        SettingsDialog(self.root, self, initial_tab=initial_tab)

    def _refresh_overspeed_threshold_ui(self) -> None:
        """刷新速度条上的阈值刻度位置。"""
        markers = getattr(self, "speed_bar_markers", None)
        if not markers:
            return
        for name, relx in (
            ("caution", OverspeedConfig.CAUTION_RATIO),
            ("warning", OverspeedConfig.WARNING_RATIO),
            ("critical", OverspeedConfig.CRITICAL_RATIO),
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
    ) -> None:
        """运行时应用显示设置（主题/缩放/导航宽度）

        通过局部重建UI避免强制重启应用。
        """
        need_main_rebuild = bool(theme_changed or ui_scale_changed or text_scale_changed)
        need_nav_rebuild = bool(need_main_rebuild or nav_width_changed)
        if not (need_main_rebuild or need_nav_rebuild):
            return

        nav_was_visible = False
        preserve_text_only_geometry = bool(text_scale_changed and not ui_scale_changed)
        main_geometry = None
        nav_geometry = None
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
        if ENABLE_ZONES and need_nav_rebuild and getattr(self, "nav_window", None):
            try:
                nav_was_visible = bool(self.nav_window.is_visible())
            except Exception:
                nav_was_visible = False
            if preserve_text_only_geometry and nav_was_visible:
                try:
                    nav_geometry = (
                        self.nav_window.window.winfo_x(),
                        self.nav_window.window.winfo_y(),
                        self.nav_window.window.winfo_width(),
                        self.nav_window.window.winfo_height(),
                    )
                except Exception:
                    nav_geometry = None
            try:
                self.nav_window.destroy()
            except Exception:
                pass
            self.nav_window = None

        if need_main_rebuild:
            if hasattr(self, "main_frame") and self.main_frame:
                try:
                    self.main_frame.destroy()
                except tk.TclError:
                    pass

            self.root.configure(bg=Theme.BG)
            self.scale = Win32.get_dpi_scale(self.hwnd) * float(UIConfig.UI_SCALE_MULT)
            self._hint_width_cache = {"text": "", "width": int(380 * self.scale)}
            try:
                self.root.tk.call("tk", "scaling", float(self.scale))
            except tk.TclError:
                pass
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
                self._show_debug_ui()
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
            self.nav_window = NavigationWindow(self)
            if PanelConfig.navigation_mode == "standalone" and nav_was_visible:
                self.nav_window.show()
                if preserve_text_only_geometry and nav_geometry:
                    nav_x, nav_y, nav_w, nav_h = nav_geometry
                    self.nav_window.window.geometry(f"{nav_w}x{nav_h}+{nav_x}+{nav_y}")

        # 重新应用窗口样式（锁定态穿透 + 透明度）
        alpha = UIConfig.WINDOW_ALPHA if self._locked else min(240, UIConfig.WINDOW_ALPHA + 30)
        Win32.setup_window(self.hwnd, click_through=self._locked, alpha=alpha)
        if ENABLE_ZONES and getattr(self, "nav_window", None):
            self.nav_window.apply_window_styles(click_through=self._locked, alpha=alpha)
        self.runtime_services.refresh_hud_after_display_change(
            ui_scale_changed=ui_scale_changed,
            text_scale_changed=text_scale_changed,
            locked=self._locked,
        )
        self._refresh_tray()

    def _edit_checklist(self):
        """编辑检查清单

        从托盘菜单调用，不受窗口锁定状态影响。
        """
        ChecklistEditor(self.root, self)

    def _show_about(self):
        """显示关于对话框"""
        AboutDialog(self.root, self)

    def _adjust_alpha(self, event):
        """Ctrl+滚轮调整透明度"""
        if not self._locked:
            delta = 10 if event.delta > 0 else -10
            UIConfig.WINDOW_ALPHA = max(100, min(255, UIConfig.WINDOW_ALPHA + delta))
            Win32.setup_window(self.hwnd, click_through=False, alpha=UIConfig.WINDOW_ALPHA)
            self._save_config()

    def _quit(self):
        """退出应用"""
        self._stop = True
        self.game.save_timer_state()
        self._save_config()

        self.runtime_services.stop()

        try:
            self.sound.stop(drain=False)
        except Exception:
            pass

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

    def _update_mid_panel_layout(self):
        self.panel_renderer.update_mid_panel_layout()

    def _set_zone_panel_visible(self, visible: bool):
        self.panel_renderer.set_zone_panel_visible(visible)

    def _update_tape_info_labels(self, targets_info: list, primary_zone):
        self.panel_renderer.update_tape_info_labels(targets_info, primary_zone)

    def _set_checklist_visible(self, visible: bool):
        self.panel_renderer.set_checklist_visible(visible)

    def _update_zone_display(self, snap: UISnapshot):
        return self.panel_renderer.update_zone_display(snap)

    def _reset_navigation_layout_state(self):
        self.panel_renderer.reset_navigation_layout_state()

    def _update_fuel_display(self, snap: UISnapshot, font_item):
        _ = font_item
        self.panel_renderer.update_fuel_display(snap)

    def _update_bombing_display(self, snap: UISnapshot, font_item):
        _ = font_item
        self.panel_renderer.update_bombing_display(snap)

    def _show_bomb_selector(self):
        """显示炸弹选择对话框"""
        BombSelectorDialog(self.root, self)

    def _update_ui(self):
        """UI更新循环(20fps)

        性能优化:
        - _update_zone_display()返回是否需重算尺寸
        - 仅在布局结构变化时调用_recalc_size()
        - 使用缓存字体和Label复用池
        """
        if self._stop:
            return
        self._ui_after_id = None
        loop_start = time.monotonic()
        if self._last_ui_frame_ts > 0.0:
            self._last_ui_gap_ms = max(0.0, (loop_start - self._last_ui_frame_ts) * 1000.0)
        self._last_ui_frame_ts = loop_start
        live_snap = self.game.snapshot()
        if self._debug:
            snap = self._build_debug_snapshot(live_snap)
        else:
            snap = live_snap
            self._debug_effective_mock = False
            self._debug_live_available = False

        debug_mock_mode = bool(self._debug and self._debug_effective_mock)

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

            if snap.phase == Phase.ALIVE and snap.landed_flash and not self._last_landed_flash:
                if snap.sortie_id != self._nudge_sortie_id:
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
        history_mode_active = PanelConfig.speed_history_mode

        # 控制面板可见性（结合PanelConfig设置和编译开关）
        # 战区/机场/燃油/投弹面板需要任一相关面板启用
        show_zone_panel = (snap.phase in (Phase.ALIVE, Phase.LOSS_PENDING)) and (
            zones_enabled or airfields_enabled or fuel_enabled or bombing_enabled
        )
        self._set_zone_panel_visible(show_zone_panel)
        if show_zone_panel:
            # _update_zone_display 返回是否需要重算尺寸
            need_recalc = self._update_zone_display(snap)
            if need_recalc:
                now_recalc = time.monotonic()
                # 数据抖动期节流尺寸重算，避免高频geometry震荡
                if (now_recalc - self._last_zone_recalc_ts) >= 0.25:
                    self._last_zone_recalc_ts = now_recalc
                    self._recalc_size()

        # 检查清单面板（受编译开关控制）
        show_chk = (
            checklist_enabled
            and (snap.phase == Phase.ALIVE)
            and (snap.on_ground or snap.landed_flash)
        )
        self._set_checklist_visible(show_chk)
        self._apply_speed_history_layout(history_mode_active)

        # 更新计时器显示
        if history_mode_active:
            self._last_beep_sec = -1
            self.bar_fill.place(relwidth=0)
            self.bar_fill.config(bg=Theme.BLUE)
        else:
            self.timer_lbl.config(text=fmt_time(snap.remaining_sec))
            if snap.remaining_sec is None:
                self.timer_lbl.config(fg=Theme.TEXT_MUTED)
                self.bar_fill.place(relwidth=0)
                self.bar_fill.config(bg=Theme.BLUE)
            else:
                remain = snap.remaining_sec
                color = (
                    Theme.RED
                    if remain <= 10
                    else Theme.YELLOW
                    if remain <= GameConfig.FINAL_WARNING_SEC
                    else Theme.TEXT
                )
                bar = (
                    Theme.RED
                    if remain <= 10
                    else Theme.YELLOW
                    if remain <= GameConfig.FINAL_WARNING_SEC
                    else Theme.BLUE
                )
                self.timer_lbl.config(fg=color)
                self.bar_fill.place(relwidth=snap.progress)
                self.bar_fill.config(bg=bar)

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

        # 更新徽章
        self.badge_main.set(*snap.main_badge)
        self.badge_flight.set(*snap.flight_badge)
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
            speed_level = self._update_speed_strip(snap, debug_mock_mode)
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
                badge_text = "⚠起落架"
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
        self.status_txt.config(text=snap.status_text, fg=status_fg)

        # 调试信息
        if self._debug:
            self.diag_lbl.config(text=self._build_debug_text(live_snap, snap))

        # HUD 叠加层更新（v6.8.0）
        self._update_hud_overlay(snap)

        # 继续下一帧（基于实际耗时补偿）
        elapsed_ms = (time.monotonic() - loop_start) * 1000.0
        self._last_ui_work_ms = elapsed_ms
        delay = max(0, int(UIConfig.UI_REFRESH_MS - elapsed_ms))
        if not self._stop:
            self._ui_after_id = self.root.after(delay, self._update_ui)
