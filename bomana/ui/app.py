# -*- coding: utf-8 -*-        - hint_min_width: 提示文字最小宽度，根据编译开关动态计算
"""Main Tk app container."""

import ctypes
import os
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import font as tkfont
from enum import Enum
from typing import Optional, Tuple, Any, List, Dict

from bomana.config import (
    __title__,
    ENABLE_CCRP,
    ENABLE_ZONES,
    ENABLE_AIRFIELDS,
    ENABLE_FUEL,
    ENABLE_CHECKLIST,
    ENABLE_ADVANCED_SETTINGS,
    UIConfig,
    ZoneConfig,
    PanelConfig,
    HUDConfig,
    HotkeyConfig,
    SnapConfig,
    BombConfig,
    ChecklistConfig,
    SoundConfig,
    GameConfig,
    NetworkConfig,
    OverspeedConfig,
    BallisticPhysicsParams,
    Theme,
    AboutConfig,
)
from bomana.core.logic import GameLogic
from bomana.core.state import UISnapshot, Phase
from bomana.utils.file_utils import ConfigManager, resource_path
from bomana.config import FileConfig
from bomana.utils.system import Win32, GlobalHotkeys, SingleInstanceManager, select_ui_font_family
from bomana.utils.sound import SoundManager
from bomana.utils.math_utils import calculate_smart_scale
from bomana.ui.debug_support import AppDebugSupport
from bomana.ui.widgets import Pill, HeadingTape
from bomana.ui.dialogs import SettingsDialog, ChecklistEditor, BombSelectorDialog, AboutDialog
from bomana.ui.nav_window import NavigationWindow
from bomana.ui.hud_overlay import HUDOverlay
from bomana.ui.panel_renderer import AppPanelRenderer

try:
    from PIL import Image
    import pystray
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

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
        
        # 布局可见性
        self._zone_panel_visible = False
        self._checklist_panel_visible = False
        
        # 性能优化: 字体缓存和Label复用池
        self._cached_fonts: Dict[str, tuple] = {}
        self._zone_label_pool: List[tk.Label] = []
        self._airport_label_pool: List[tk.Label] = []
        self._last_layout_signature = None
        self._last_expand_ts = 0.0
        self._last_zone_recalc_ts = 0.0
        self._zone_layout_mode = None
        self._airport_layout_mode = None
        self.hud_overlay = None
        self._hud_monitor_refresh_ts = 0.0
        self._hud_last_target = None
        self._hud_target_hold_sec = 1.2
        self._hud_render_error_count = 0
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
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._update_ui()

        if HAS_TRAY:
            self._init_tray()

    def _load_config(self):
        """加载用户配置
        
        加载顺序: 主题必须在UI创建前应用
        配置项: alpha/scale/theme/panels/hud/hotkey_bindings/snap/window_position
        """
        config = ConfigManager.load()
        
        # 显示设置
        alpha = config.get('alpha', UIConfig.WINDOW_ALPHA)
        if isinstance(alpha, (int, float)):
            UIConfig.WINDOW_ALPHA = max(30, min(255, int(alpha)))
        # v5.9.3: 智能缩放逻辑
        # 检查是否是首次启动（没有保存的缩放配置）
        if 'scale' in config:
            # 用户已经设置过缩放，使用保存的值
            scale = config.get('scale')
            if isinstance(scale, (int, float)):
                UIConfig.UI_SCALE_MULT = max(0.6, min(2.5, float(scale)))
        else:
            # 首次启动，根据屏幕分辨率智能设置
            try:
                sw, sh = Win32.screen_size()
                # 临时获取DPI缩放（此时窗口还未创建，使用默认值1.2）
                smart_scale = calculate_smart_scale(sw, sh, 1.2)
                UIConfig.UI_SCALE_MULT = smart_scale
                print(f"[智能缩放] 检测到屏幕分辨率 {sw}x{sh}，设置缩放为 {smart_scale:.2f}x")
            except Exception as e:
                # 出错时使用默认值1.2
                UIConfig.UI_SCALE_MULT = 1.2
                print(f"[智能缩放] 检测失败，使用默认缩放1.2x: {e}")
        
        # 主题设置（必须在UI创建前应用）
        theme_name = config.get('theme', 'fluent_dark')
        Theme.apply(theme_name)
        
        # 面板显示设置
        panels = config.get('panels', {})
        PanelConfig.show_zones = panels.get('show_zones', True)
        PanelConfig.show_airfields = panels.get('show_airfields', True)
        PanelConfig.show_fuel = panels.get('show_fuel', True)
        PanelConfig.show_speed = panels.get('show_speed', True)
        PanelConfig.speed_history_mode = panels.get('speed_history_mode', False)
        PanelConfig.show_checklist = panels.get('show_checklist', True)
        PanelConfig.show_bombing = panels.get('show_bombing', True)  # v6.0 新增
        
        # v6.2.1: 导航条模式（仅在战区功能启用时生效）
        if ENABLE_ZONES:
            PanelConfig.navigation_mode = config.get('navigation_mode', 'integrated')
            nav_pos = config.get('navigation_window_pos')
            if nav_pos and isinstance(nav_pos, list) and len(nav_pos) == 2:
                PanelConfig.navigation_window_pos = tuple(nav_pos)
            # 独立导航栏宽度
            nav_width = config.get('navigation_bar_width')
            if nav_width and isinstance(nav_width, (int, float)):
                PanelConfig.navigation_bar_width = max(0.5, min(2.0, float(nav_width)))
        else:
            # 精简版强制使用集成模式，忽略配置文件中的设置
            PanelConfig.navigation_mode = 'integrated'
        
        # v6.0 新增：炸弹选择（仅在CCRP启用时）
        if ENABLE_CCRP:
            selected_bomb = config.get('selected_bomb', 'su_fab100sv')
            if BombConfig.get_bomb_data(selected_bomb):
                BombConfig.selected_bomb = selected_bomb
            tuning = config.get('ccrp_tuning', {})
            BallisticPhysicsParams.apply_user_tuning(tuning)
        
        # 根据编译开关初始化面板状态
        PanelConfig.init_from_compile_switches()

        # HUD 设置（缺省字段自动回退，兼容旧配置）
        hud_enabled = config.get('hud_enabled', HUDConfig.enabled)
        if isinstance(hud_enabled, (bool, int)):
            HUDConfig.enabled = bool(hud_enabled)
        HUDConfig.apply_dict(config.get('hud', {}))
        
        # 快捷键设置
        HotkeyConfig.GLOBAL_HOTKEYS = config.get('global_hotkeys', HotkeyConfig.GLOBAL_HOTKEYS)
        hotkey_bindings = config.get('hotkey_bindings', {})
        if hotkey_bindings:
            HotkeyConfig.set_bindings(hotkey_bindings)
        
        # 吸附设置
        SnapConfig.enabled = config.get('snap_enabled', True)
        snap_dist = config.get('snap_distance', 20)
        if isinstance(snap_dist, (int, float)):
            SnapConfig.SNAP_DISTANCE = max(5, min(200, int(snap_dist)))
        
        # 检查清单
        self.chk_items = config.get('checklist_items', ChecklistConfig.DEFAULT_ITEMS.copy())
        self._zone_sound_enabled = config.get('zone_sound_enabled', True)
        
        # 恢复窗口位置（支持多显示器）
        saved_pos = config.get('window_position')
        if saved_pos and isinstance(saved_pos, dict):
            corner_name = saved_pos.get('corner')
            if corner_name:
                try:
                    self._corner = Corner[corner_name]
                except KeyError:
                    pass
            manual_pos = saved_pos.get('manual_pos')
            if manual_pos and isinstance(manual_pos, list) and len(manual_pos) == 2:
                self._manual_pos = tuple(manual_pos)
                self._user_moved = saved_pos.get('user_moved', False)
            # 记录显示器索引（用于多显示器支持）
            self._saved_monitor_index = saved_pos.get('monitor_index', 0)
        else:
            self._saved_monitor_index = 0
        
        beep_enabled = config.get('beep_enabled', False)
        self.sound.set_enabled(beep_enabled)

    def _save_config(self):
        """保存用户配置"""
        config = ConfigManager.load()
        
        # 显示设置
        config['alpha'] = UIConfig.WINDOW_ALPHA
        config['scale'] = UIConfig.UI_SCALE_MULT
        config['theme'] = Theme.get_current()
        
        # 面板设置
        panels_config = {
            'show_zones': PanelConfig.show_zones,
            'show_airfields': PanelConfig.show_airfields,
            'show_fuel': PanelConfig.show_fuel,
            'show_speed': PanelConfig.show_speed,
            'speed_history_mode': PanelConfig.speed_history_mode,
            'show_checklist': PanelConfig.show_checklist,
        }
        # v6.0 新增：投弹预测面板（仅在CCRP启用时保存）
        if ENABLE_CCRP:
            panels_config['show_bombing'] = PanelConfig.show_bombing
        config['panels'] = panels_config
        
        # v6.2.1: 导航条模式
        config['navigation_mode'] = PanelConfig.navigation_mode
        if PanelConfig.navigation_window_pos:
            config['navigation_window_pos'] = list(PanelConfig.navigation_window_pos)
        config['navigation_bar_width'] = PanelConfig.navigation_bar_width
        
        # v6.0 新增：炸弹选择（仅在CCRP启用时保存）
        if ENABLE_CCRP:
            config['selected_bomb'] = BombConfig.selected_bomb
            config['ccrp_tuning'] = BallisticPhysicsParams.get_user_tuning()

        # HUD 设置
        config['hud_enabled'] = HUDConfig.enabled
        config['hud'] = HUDConfig.to_dict()
        
        # 快捷键设置
        config['global_hotkeys'] = HotkeyConfig.GLOBAL_HOTKEYS
        config['hotkey_bindings'] = HotkeyConfig.get_bindings()
        
        # 吸附设置
        config['snap_enabled'] = SnapConfig.enabled
        config['snap_distance'] = SnapConfig.SNAP_DISTANCE
        
        # 其他设置
        config['checklist_items'] = self.chk_items
        config['beep_enabled'] = self.sound.is_enabled()
        config['zone_sound_enabled'] = self._zone_sound_enabled
        
        # 窗口位置（包含多显示器信息）
        monitor_index = 0
        if self._manual_pos:
            monitor = Win32.get_monitor_at(self._manual_pos[0], self._manual_pos[1])
            if monitor:
                monitor_index = monitor.get('index', 0)
        
        config['window_position'] = {
            'corner': self._corner.name,
            'manual_pos': list(self._manual_pos) if self._manual_pos else None,
            'user_moved': self._user_moved,
            'monitor_index': monitor_index,
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
        except (tk.TclError, FileNotFoundError):
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
        s = self.scale
        self._cached_fonts = {
            'timer': (UIConfig.FONT_TIMER[0], int(UIConfig.FONT_TIMER[1]*s), UIConfig.FONT_TIMER[2]),
            'life': (UIConfig.FONT_LIFE[0], int(UIConfig.FONT_LIFE[1]*s), UIConfig.FONT_LIFE[2]),
            'cycle': (UIConfig.FONT_CYCLE[0], int(UIConfig.FONT_CYCLE[1]*s)),
            'pill': (UIConfig.FONT_PILL[0], int(UIConfig.FONT_PILL[1]*s), UIConfig.FONT_PILL[2]),
            'status': (UIConfig.FONT_STATUS[0], int(UIConfig.FONT_STATUS[1]*s)),
            'checklist_title': (UIConfig.FONT_CHECKLIST_TITLE[0], int(UIConfig.FONT_CHECKLIST_TITLE[1]*s), UIConfig.FONT_CHECKLIST_TITLE[2]),
            'checklist_item': (UIConfig.FONT_CHECKLIST_ITEM[0], int(UIConfig.FONT_CHECKLIST_ITEM[1]*s)),
            'zone_title': (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s), UIConfig.FONT_ZONE_TITLE[2]),
            'zone_item': (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s)),
            'debug': (UIConfig.FONT_DEBUG[0], int(UIConfig.FONT_DEBUG[1]*s)),
            'hint': (UIConfig.FONT_HINT[0], int(UIConfig.FONT_HINT[1]*s)),
        }
    
    def _get_font(self, name: str) -> tuple:
        """获取缓存的字体"""
        return self._cached_fonts.get(name, ('Segoe UI', 10))

    def _hide_label_pool(self, pool: List[tk.Label], start: int = 0) -> None:
        """隐藏标签池中从start开始的已显示标签。"""
        for lbl in pool[start:]:
            try:
                if lbl.winfo_ismapped():
                    lbl.pack_forget()
            except tk.TclError:
                continue

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
        pad = int(UIConfig.WINDOW_PADDING * self.scale)
        self.W = req_w + pad
        self.H = req_h + pad
        self._position()
        self.root.update_idletasks()
        Win32.setup_window(self.hwnd, click_through=True, alpha=UIConfig.WINDOW_ALPHA)

    def _init_ui(self):
        """初始化 UI 布局（Fluent 风格层级）。"""
        s = self.scale
        pad_x, pad_y = UIConfig.PADDING_MAIN

        # 外层壳：边框 + 内容表面，模拟 Fluent 的分层容器
        self.main_frame = tk.Frame(self.root, bg=Theme.BORDER, bd=0, highlightthickness=0)
        self.main_frame.pack(fill="both", expand=True, padx=int(pad_x*s), pady=int(pad_y*s))

        inset = max(1, int(1 * s))
        self.surface_frame = tk.Frame(self.main_frame, bg=Theme.BG, bd=0, highlightthickness=0)
        self.surface_frame.pack(fill="both", expand=True, padx=inset, pady=inset)

        # === 底部区域（操作提示卡）===
        self.bottom_card = tk.Frame(
            self.surface_frame,
            bg=Theme.GRAYPILL,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.SEPARATOR,
            highlightcolor=Theme.SEPARATOR,
        )
        self.bottom_card.pack(side="bottom", fill="x", pady=(int(4*s), 0), padx=int(1*s))

        bottom_frame = tk.Frame(self.bottom_card, bg=Theme.GRAYPILL)
        bottom_frame.pack(fill="x", padx=int(6*s), pady=int(4*s))

        self.hint_row = tk.Frame(bottom_frame, bg=Theme.GRAYPILL)
        self.hint_row.pack(side="bottom", fill="x")

        font_hint = (UIConfig.FONT_HINT[0], int(UIConfig.FONT_HINT[1]*s))
        self.hint_lbl = tk.Label(
            self.hint_row, text=self._hint_text(),
            font=font_hint, fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL
        )
        self.hint_lbl.pack(side="left", fill="x", expand=True)

        self.nudge_row = tk.Frame(bottom_frame, bg=Theme.GRAYPILL)
        self.nudge_row.columnconfigure(0, weight=1)

        nudge_wrap = int(420 * s)
        self.nudge_lbl = tk.Label(
            self.nudge_row, text=self._nudge_text(),
            font=font_hint, fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL,
            anchor="w", justify="left", wraplength=nudge_wrap
        )
        self.nudge_lbl.grid(row=0, column=0, sticky="ew")

        self.star_lbl = tk.Label(
            self.nudge_row, text="GitHub Star",
            font=font_hint, fg=Theme.BLUE, bg=Theme.BG, cursor="hand2",
            padx=int(8*s), pady=max(1, int(1*s))
        )
        self.star_lbl.bind("<Button-1>", lambda e: self._open_star_url())
        self.star_lbl.bind("<Enter>", lambda e: self.star_lbl.config(fg=Theme.TEXT, bg=Theme.BORDER))
        self.star_lbl.bind("<Leave>", lambda e: self.star_lbl.config(fg=Theme.BLUE, bg=Theme.BG))
        self.star_lbl.grid(row=0, column=1, sticky="e", padx=(int(8*s), 0))

        font_debug = (UIConfig.FONT_DEBUG[0], int(UIConfig.FONT_DEBUG[1]*s))
        self.diag_lbl = tk.Label(
            bottom_frame, text="",
            font=font_debug, fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL,
            anchor="w", justify="left",
            wraplength=int(UIConfig.DEBUG_WRAP_LENGTH*s)
        )
        self.debug_ctrl_row = tk.Frame(bottom_frame, bg=Theme.GRAYPILL)
        btn_pad_x = int(6 * s)
        btn_pad_y = max(1, int(1 * s))
        debug_btn_font = font_hint

        self.debug_source_btn = tk.Label(
            self.debug_ctrl_row,
            text="数据源: 模拟",
            font=debug_btn_font,
            fg=Theme.GREEN,
            bg=Theme.BG,
            cursor="hand2",
            padx=btn_pad_x,
            pady=btn_pad_y,
        )
        self.debug_source_btn.pack(side="left")
        self.debug_source_btn.bind("<Button-1>", lambda e: self._toggle_debug_mock_mode())
        self.debug_source_btn.bind(
            "<Enter>",
            lambda e: self.debug_source_btn.config(bg=Theme.BORDER, fg=Theme.TEXT),
        )
        self.debug_source_btn.bind("<Leave>", lambda e: self._update_debug_controls())

        self.debug_prev_btn = tk.Label(
            self.debug_ctrl_row,
            text="◀",
            font=debug_btn_font,
            fg=Theme.TEXT,
            bg=Theme.BG,
            cursor="hand2",
            padx=btn_pad_x,
            pady=btn_pad_y,
        )
        self.debug_prev_btn.pack(side="left", padx=(int(6*s), 0))
        self.debug_prev_btn.bind("<Button-1>", lambda e: self._cycle_debug_scene(-1))
        self.debug_prev_btn.bind("<Enter>", lambda e: self.debug_prev_btn.config(bg=Theme.BORDER))
        self.debug_prev_btn.bind("<Leave>", lambda e: self.debug_prev_btn.config(bg=Theme.BG))

        self.debug_scene_lbl = tk.Label(
            self.debug_ctrl_row,
            text="",
            font=debug_btn_font,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        self.debug_scene_lbl.pack(side="left", padx=(int(6*s), int(4*s)))

        self.debug_next_btn = tk.Label(
            self.debug_ctrl_row,
            text="▶",
            font=debug_btn_font,
            fg=Theme.TEXT,
            bg=Theme.BG,
            cursor="hand2",
            padx=btn_pad_x,
            pady=btn_pad_y,
        )
        self.debug_next_btn.pack(side="left")
        self.debug_next_btn.bind("<Button-1>", lambda e: self._cycle_debug_scene(1))
        self.debug_next_btn.bind("<Enter>", lambda e: self.debug_next_btn.config(bg=Theme.BORDER))
        self.debug_next_btn.bind("<Leave>", lambda e: self.debug_next_btn.config(bg=Theme.BG))

        self.debug_hint_lbl = tk.Label(
            self.debug_ctrl_row,
            text="提示: 无 8111 数据时将自动使用模拟场景",
            font=debug_btn_font,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        self.debug_hint_lbl.pack(side="right", fill="x", expand=True)
        self._update_debug_controls()

        # === 顶部区域（主信息卡）===
        self.top_frame = tk.Frame(
            self.surface_frame,
            bg=Theme.GRAYPILL,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.SEPARATOR,
            highlightcolor=Theme.SEPARATOR,
        )
        self.top_frame.pack(side="top", fill="x", pady=(0, int(4*s)), padx=int(1*s))

        top_content = tk.Frame(self.top_frame, bg=Theme.GRAYPILL)
        top_content.pack(fill="x", padx=int(8*s), pady=int(6*s))

        # 第一行：计时器 + 复活信息
        row1 = tk.Frame(top_content, bg=Theme.GRAYPILL)
        row1.pack(fill="x")
        font_timer = (UIConfig.FONT_TIMER[0], int(UIConfig.FONT_TIMER[1]*s), UIConfig.FONT_TIMER[2])
        self.timer_lbl = tk.Label(
            row1, text="--:--", font=font_timer,
            fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w"
        )
        self.timer_lbl.pack(side="left")

        right = tk.Frame(row1, bg=Theme.GRAYPILL)
        right.pack(side="right", padx=(int(12*s), 0))
        font_life = (UIConfig.FONT_LIFE[0], int(UIConfig.FONT_LIFE[1]*s), UIConfig.FONT_LIFE[2])
        self.life_lbl = tk.Label(
            right, text="未复活", font=font_life,
            fg=Theme.BLUE, bg=Theme.GRAYPILL, anchor="e"
        )
        self.life_lbl.pack(anchor="e")
        font_cycle = (UIConfig.FONT_CYCLE[0], int(UIConfig.FONT_CYCLE[1]*s))
        self.cycle_lbl = tk.Label(
            right, text="未开始", font=font_cycle,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="e"
        )
        self.cycle_lbl.pack(anchor="e", pady=(int(2*s), 0))

        # 第二行：状态徽章
        row2 = tk.Frame(top_content, bg=Theme.GRAYPILL)
        pad_top, pad_bot = UIConfig.PADDING_ROW2
        row2.pack(fill="x", pady=(int(pad_top*s), int(pad_bot*s)))
        pill_font = (UIConfig.FONT_PILL[0], int(UIConfig.FONT_PILL[1]*s), UIConfig.FONT_PILL[2])
        self.badge_main = Pill(row2, text="IDLE", fg=Theme.TEXT, bg=Theme.BG, font=pill_font)
        self.badge_main.pack(side="left")
        self.badge_flight = Pill(row2, text="—", fg=Theme.TEXT_DIM, bg=Theme.BG, font=pill_font)
        self.badge_flight.pack(side="left", padx=(int(UIConfig.SPACING_BADGE*s), 0))
        self.badge_lock = Pill(row2, text="锁定", fg=Theme.TEXT, bg=Theme.BLUE, font=pill_font)
        self.badge_lock.pack(side="left", padx=(int(UIConfig.SPACING_BADGE*s), 0))
        self._update_lock_badge()

        # v5.9.6 新增：起落架警告徽章（v6.6.1: 集成进度条）
        self.badge_gear = Pill(row2, text="", fg=Theme.TEXT, bg=Theme.ORANGE, font=pill_font)
        self.gear_progress_bar = tk.Frame(self.badge_gear, bg=Theme.BLUE, height=int(3*s))

        font_status = (UIConfig.FONT_STATUS[0], int(UIConfig.FONT_STATUS[1]*s))
        self.status_txt = tk.Label(
            row2, text="等待中", font=font_status,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="e"
        )
        self.status_txt.pack(side="right")

        # 第三行：紧凑速度指示条（常驻，接近极限时显著变色）
        self.speed_row = tk.Frame(top_content, bg=Theme.GRAYPILL)
        pad_top, pad_bot = UIConfig.PADDING_SPEED_STRIP
        self.speed_row.pack(fill="x", pady=(int(pad_top*s), int(pad_bot*s)))
        speed_font = (UIConfig.FONT_HINT[0], int(UIConfig.FONT_HINT[1]*s))
        speed_model_font = (UIConfig.FONT_HINT[0], max(7, int(UIConfig.FONT_HINT[1]*s*0.92)))
        self.speed_header_row = tk.Frame(self.speed_row, bg=Theme.GRAYPILL)
        self.speed_header_row.pack(fill="x")
        self.speed_meta_frame = tk.Frame(self.speed_header_row, bg=Theme.GRAYPILL)
        self.speed_meta_frame.pack(side="left", fill="x", expand=True)
        self.speed_state_lbl = tk.Label(
            self.speed_meta_frame,
            text="速度监视",
            font=speed_font,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        self.speed_state_lbl.pack(anchor="w")
        self.speed_model_lbl = tk.Label(
            self.speed_meta_frame,
            text="机型未识别",
            font=speed_model_font,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        self.speed_model_lbl.pack(anchor="w")
        self.speed_value_lbl = tk.Label(
            self.speed_header_row,
            text="--",
            font=speed_font,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        self.speed_value_lbl.pack(side="right")

        speed_bar_height = max(8, int(UIConfig.SPEED_STRIP_HEIGHT * s))
        speed_bar_thickness = max(3, int(UIConfig.SPEED_STRIP_THICKNESS * s))
        self.speed_bar_host = tk.Frame(self.speed_row, bg=Theme.GRAYPILL, height=speed_bar_height)
        self.speed_bar_host.pack(fill="x", pady=(max(1, int(2*s)), 0))
        self.speed_bar_host.pack_propagate(False)
        self.speed_bar_bg = tk.Frame(self.speed_bar_host, bg=Theme.SEPARATOR, height=speed_bar_thickness)
        self.speed_bar_bg.place(relx=0, rely=0.5, relwidth=1, anchor="w")
        self.speed_bar_fill = tk.Frame(self.speed_bar_bg, bg=Theme.GREEN, height=speed_bar_thickness)
        self.speed_bar_fill.place(relx=0, rely=0, relwidth=0, relheight=1)
        self.speed_bar_markers = {}
        for name, relx, color in (
            ("caution", OverspeedConfig.CAUTION_RATIO, Theme.BLUE),
            ("warning", OverspeedConfig.WARNING_RATIO, Theme.YELLOW),
            ("critical", OverspeedConfig.CRITICAL_RATIO, Theme.RED),
        ):
            marker = tk.Frame(
                self.speed_bar_bg,
                bg=color,
                width=max(1, int(2*s)),
                height=max(speed_bar_thickness + 2, int(7*s)),
            )
            marker.place(relx=max(0.0, min(1.0, relx)), rely=0.5, anchor="center")
            self.speed_bar_markers[name] = marker

        # 进度条
        bar_height = int(UIConfig.PROGRESS_BAR_HEIGHT * s)
        bar_frame = tk.Frame(top_content, bg=Theme.GRAYPILL, height=bar_height)
        pad_top, pad_bot = UIConfig.PADDING_PROGRESS
        bar_frame.pack(fill="x", pady=(int(pad_top*s), int(pad_bot*s)))
        bar_frame.pack_propagate(False)
        bar_thickness = int(UIConfig.PROGRESS_BAR_THICKNESS * s)
        self.bar_bg = tk.Frame(bar_frame, bg=Theme.SEPARATOR, height=bar_thickness)
        self.bar_bg.place(relx=0, rely=0.5, relwidth=1, anchor="w")
        self.bar_fill = tk.Frame(self.bar_bg, bg=Theme.BLUE, height=bar_thickness)
        self.bar_fill.place(relx=0, rely=0, relwidth=0, relheight=1)

        # === 中间内容区域 ===
        self.mid_frame = tk.Frame(self.surface_frame, bg=Theme.BG)
        self.mid_frame.pack(side="top", fill="x", pady=(0, int(4*s)))
        self.mid_frame.columnconfigure(0, weight=1)
        self.mid_frame.columnconfigure(1, weight=1)

        self.zone_frame = tk.Frame(
            self.mid_frame,
            bg=Theme.GRAYPILL,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.SEPARATOR,
            highlightcolor=Theme.SEPARATOR,
        )
        self._init_zone_ui()

        self.chk_frame = tk.Frame(
            self.mid_frame,
            bg=Theme.GRAYPILL,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.SEPARATOR,
            highlightcolor=Theme.SEPARATOR,
        )
        self.chk_border_frame = tk.Frame(self.chk_frame, bg=Theme.BORDER, width=max(1, int(1*s)))
        self.chk_content_frame = tk.Frame(self.chk_frame, bg=Theme.GRAYPILL)
        self._rebuild_checklist()

    def _init_zone_ui(self):
        """初始化战区导航UI
        
        v6.1更新: 新增航向带(Heading Tape)组件
        
        使用Grid布局确保区块顺序固定:
        Row 0: zone_header_frame (标题+HDG)
        Row 1: heading_tape_frame (航向带) - v6.1新增
        Row 2: zone_alert_lbl (摧毁警告)
        Row 3: zone_list_frame (战区列表)
        Row 4: airport_title_lbl (机场标题)
        Row 5: airport_list_frame (机场列表)
        Row 6: fuel_title_lbl (燃油标题)
        Row 7: fuel_info_frame (燃油信息)
        Row 8: bombing_title_lbl (投弹标题)
        Row 9: bombing_info_frame (投弹信息)
        
        使用grid_remove()/grid()切换可见性,保持行号不变
        """
        s = self.scale
        pad_x = int(8*s)
        
        # 配置grid列宽
        self.zone_frame.columnconfigure(0, weight=1)
        
        # Row 0: 标题栏（始终显示）
        self.zone_header_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.zone_header_frame.grid(row=0, column=0, sticky="ew", padx=pad_x, pady=(int(4*s), int(2*s)))
        
        font_title = (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s), UIConfig.FONT_ZONE_TITLE[2])
        self.zone_title = tk.Label(self.zone_header_frame, text="导航面板", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.zone_title.pack(side="left")
        
        # 独立导航条模式按钮
        font_btn = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s))
        self.standalone_btn = tk.Label(
            self.zone_header_frame, text="切换独立导航窗", font=font_btn,
            fg=Theme.TEXT_MUTED, bg=Theme.BG, cursor="hand2",
            padx=int(6*s), pady=max(1, int(1*s))
        )
        self.standalone_btn.pack(side="left", padx=(int(10*s), 0))
        self.standalone_btn.bind("<Button-1>", lambda e: self._toggle_navigation_mode())
        self.standalone_btn.bind("<Enter>", lambda e: self.standalone_btn.config(
            fg=(Theme.BLUE if PanelConfig.navigation_mode != "standalone" else Theme.GREEN),
            bg=Theme.BORDER))
        self.standalone_btn.bind("<Leave>", lambda e: self._update_nav_mode_button())
        self._update_nav_mode_button()
        
        font_heading = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s))
        font_item = font_heading
        self.heading_lbl = tk.Label(self.zone_header_frame, text="航向: ---°", font=font_heading, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="e")
        self.heading_lbl.pack(side="right")
        
        # Row 1: v6.2重构 - 统一航向带(显示战区+机场+被摧毁目标)
        if ZoneConfig.HEADING_TAPE_ENABLED:
            self.heading_tape_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
            self.heading_tape_frame.grid(row=1, column=0, sticky="ew", padx=pad_x, pady=(int(1*s), int(2*s)))
            
            tape_width = int(ZoneConfig.HEADING_TAPE_WIDTH * s)
            tape_height = int(ZoneConfig.HEADING_TAPE_HEIGHT * s)
            self.heading_tape = HeadingTape(
                self.heading_tape_frame, 
                width=tape_width, 
                height=tape_height
            )
            self.heading_tape.pack(fill="x", expand=True)
            
            # 图例行 - v6.2.2: 优化为紧凑单行布局
            self.tape_legend_row = tk.Frame(self.heading_tape_frame, bg=Theme.GRAYPILL)
            self.tape_legend_row.pack(fill="x", pady=(int(1*s), 0))
            
            # 使用更小字体和紧凑间距
            legend_font = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s*0.85))
            legend_text = "⊚战区  ✈友方机场  ✈敌方机场  ✕摧毁目标"
            
            # v6.4: 图例行分为左侧图例和右侧阈值显示
            legend_left = tk.Label(
                self.tape_legend_row, text=legend_text, font=legend_font,
                fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w"
            )
            legend_left.pack(side="left", fill="x", expand=True)
            
            # 角度阈值显示（移至图例行右侧）
            self.tape_tolerance_legend = tk.Label(
                self.tape_legend_row, text="", font=legend_font,
                fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="e"
            )
            self.tape_tolerance_legend.pack(side="right", padx=(0, int(4*s)))
            
            # v6.2.1: 战区状态提示行
            self.tape_zone_row = tk.Frame(self.heading_tape_frame, bg=Theme.GRAYPILL)
            self.tape_zone_row.pack(fill="x", pady=(int(2*s), 0))
            
            status_font = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s*0.95))
            
            # 战区标签
            self.tape_zone_label = tk.Label(
                self.tape_zone_row, text="⊚战区:", font=status_font,
                fg=Theme.RED, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_zone_label.pack(side="left")
            
            # 战区转向指示
            self.tape_zone_turn = tk.Label(
                self.tape_zone_row, text="", font=status_font,
                fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_zone_turn.pack(side="left", padx=(int(6*s), 0))
            
            # 战区状态描述
            self.tape_zone_status = tk.Label(
                self.tape_zone_row, text="", font=status_font,
                fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_zone_status.pack(side="left", padx=(int(8*s), 0))
            
            # 战区距离/ETE信息
            self.tape_zone_info = tk.Label(
                self.tape_zone_row, text="", font=status_font,
                fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_zone_info.pack(side="left", padx=(int(8*s), 0))
            
            # v6.4: 战区容差已移至图例行，保留变量引用
            self.tape_zone_tolerance = tk.Label(
                self.tape_zone_row, text="", font=status_font,
                fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="e"
            )
            # 不再pack，让状态行布局更居中
            
            # v6.2.1: 友方机场状态提示行
            self.tape_friendly_row = tk.Frame(self.heading_tape_frame, bg=Theme.GRAYPILL)
            self.tape_friendly_row.pack(fill="x", pady=(int(1*s), 0))
            
            # 友方机场标签
            self.tape_friendly_label = tk.Label(
                self.tape_friendly_row, text="✈友方:", font=status_font,
                fg=Theme.BLUE, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_friendly_label.pack(side="left")
            
            # 友方机场转向指示
            self.tape_friendly_turn = tk.Label(
                self.tape_friendly_row, text="", font=status_font,
                fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_friendly_turn.pack(side="left", padx=(int(6*s), 0))
            
            # 友方机场状态
            self.tape_friendly_status = tk.Label(
                self.tape_friendly_row, text="", font=status_font,
                fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_friendly_status.pack(side="left", padx=(int(8*s), 0))
            
            # 友方机场距离/ETE
            self.tape_friendly_info = tk.Label(
                self.tape_friendly_row, text="", font=status_font,
                fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.tape_friendly_info.pack(side="left", padx=(int(8*s), 0))
            
            # 保留旧变量兼容
            self.tape_turn_lbl = self.tape_zone_turn
            self.tape_deviation_lbl = self.tape_zone_status
            self.tape_tolerance_lbl = self.tape_zone_tolerance
            self.tape_info_container = None
            self._tape_info_labels = []
        else:
            self.heading_tape = None
            self.tape_info_container = None
            self._tape_info_labels = []
            self.tape_turn_lbl = None
            self.tape_deviation_lbl = None
            self.tape_tolerance_lbl = None
            self.tape_zone_row = None
            self.tape_friendly_row = None
            self.tape_friendly_turn = None
            self.tape_friendly_info = None
            self.tape_friendly_status = None
            self.tape_zone_info = None
        
        # Row 2: 被摧毁警告标签（动态显示）
        font_alert = (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s), UIConfig.FONT_ZONE_TITLE[2])
        self.zone_alert_lbl = tk.Label(self.zone_frame, text="", font=font_alert, fg=Theme.RED, bg=Theme.GRAYPILL, anchor="w")
        # 初始不显示，由_update_zone_display控制
        
        # v6.6.1: Row 3: 紧凑模式两栏容器（战区+机场并排）
        self.compact_nav_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.compact_nav_frame.grid_propagate(True)
        self.compact_nav_frame.columnconfigure(0, weight=1)
        self.compact_nav_frame.columnconfigure(1, weight=1)
        # 紧凑模式 - 左栏：战区
        self.compact_zone_frame = tk.Frame(self.compact_nav_frame, bg=Theme.GRAYPILL)
        self.compact_zone_frame.grid(row=0, column=0, sticky="nsew", padx=(0, int(4*s)))
        self.compact_zone_title = tk.Label(self.compact_zone_frame, text="战区", font=font_title, fg=Theme.RED, bg=Theme.GRAYPILL, anchor="w")
        self.compact_zone_title.pack(fill="x")
        self.compact_zone_list = tk.Frame(self.compact_zone_frame, bg=Theme.GRAYPILL)
        self.compact_zone_list.pack(fill="x")
        # 紧凑模式 - 右栏：机场
        self.compact_airport_frame = tk.Frame(self.compact_nav_frame, bg=Theme.GRAYPILL)
        self.compact_airport_frame.grid(row=0, column=1, sticky="nsew", padx=(int(4*s), 0))
        self.compact_airport_title = tk.Label(self.compact_airport_frame, text="机场", font=font_title, fg=Theme.BLUE, bg=Theme.GRAYPILL, anchor="w")
        self.compact_airport_title.pack(fill="x")
        self.compact_airport_list = tk.Frame(self.compact_airport_frame, bg=Theme.GRAYPILL)
        self.compact_airport_list.pack(fill="x")
        # 紧凑模式标签池
        self._compact_zone_label_pool = []
        self._compact_airport_label_pool = []
        
        # Row 3: 战区列表容器（完整模式）
        self.zone_list_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.zone_list_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(4*s)))

        # Row 4: 机场标题
        self.airport_title_lbl = tk.Label(self.zone_frame, text="机场导航", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.airport_title_lbl.grid(row=4, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))

        # v6.2: 移除独立的机场航向带（已合并到主航向带）
        # 保留变量引用以兼容
        self.airport_tape_frame = None
        self.friendly_heading_tape = None
        self.enemy_heading_tape = None

        # Row 6: 机场列表容器
        self.airport_list_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.airport_list_frame.grid(row=6, column=0, sticky="ew", padx=pad_x, pady=(0, int(4*s)))

        # Row 7: 燃油标题
        self.fuel_title_lbl = tk.Label(self.zone_frame, text="燃油管理", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.fuel_title_lbl.grid(row=7, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))
        
        # Row 8: 燃油信息容器
        self.fuel_info_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.fuel_info_frame.grid(row=8, column=0, sticky="ew", padx=pad_x, pady=(0, int(4*s)))
        # v6.1.1: 移除旧的CDI字符指示器（已被航向带替代）
        # 保留变量引用以兼容旧代码，但不再使用
        self.zone_cdi_lbl = None
        self.friendly_cdi_lbl = None
        self.enemy_cdi_lbl = None
        
        # 燃油主信息行
        self.fuel_main_lbl = tk.Label(
            self.fuel_info_frame, 
            text="-- kg (--%)  ⏱️ --:--",
            font=font_item, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.fuel_main_lbl.pack(fill="x")
        
        # 油耗率和高度行
        self.fuel_detail_lbl = tk.Label(
            self.fuel_info_frame,
            text="油耗 --kg/min │ 高度 --m",
            font=font_item, fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w"
        )
        self.fuel_detail_lbl.pack(fill="x")
        
        # 返航估算行
        self.fuel_return_lbl = tk.Label(
            self.fuel_info_frame,
            text="🏠 返航: --",
            font=font_item, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.fuel_return_lbl.pack(fill="x")
        
        # === v6.0 新增：投弹预测区域（仅在ENABLE_CCRP启用时创建）===
        if ENABLE_CCRP:
            # Row 9: 投弹预测标题 (v6.1.1: 行号调整)
            self.bombing_title_lbl = tk.Label(
                self.zone_frame, 
                text="投弹预测", 
                font=font_title, 
                fg=Theme.TEXT, 
                bg=Theme.GRAYPILL, 
                anchor="w"
            )
            self.bombing_title_lbl.grid(row=9, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))
            
            # Row 10: 投弹预测信息容器
            self.bombing_info_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
            self.bombing_info_frame.grid(row=10, column=0, sticky="ew", padx=pad_x, pady=(0, int(6*s)))
            
            # 当前炸弹行（可点击选择）
            self.bomb_select_lbl = tk.Label(
                self.bombing_info_frame,
                text=f"炸弹: {BombConfig.format_bomb_name(BombConfig.selected_bomb)} (点击更换)",
                font=font_item, fg=Theme.BLUE, bg=Theme.GRAYPILL, anchor="w", cursor="hand2"
            )
            self.bomb_select_lbl.pack(fill="x")
            self.bomb_select_lbl.bind("<Button-1>", lambda e: self._show_bomb_selector())
            self.bomb_select_lbl.bind("<Enter>", lambda e: self.bomb_select_lbl.config(fg=Theme.TEXT, bg=Theme.BG))
            self.bomb_select_lbl.bind("<Leave>", lambda e: self.bomb_select_lbl.config(fg=Theme.BLUE, bg=Theme.GRAYPILL))
            
            # 弹道信息行
            self.bomb_trajectory_lbl = tk.Label(
                self.bombing_info_frame,
                text="弹道: -- m │ 飞行: -- s",
                font=font_item, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
            )
            self.bomb_trajectory_lbl.pack(fill="x")
            
            # 投弹时机行（大号显示）
            font_release = (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s*1.2), UIConfig.FONT_ZONE_TITLE[2])
            self.bomb_release_lbl = tk.Label(
                self.bombing_info_frame,
                text="⏱️ 等待目标",
                font=font_release, fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w"
            )
            self.bomb_release_lbl.pack(fill="x", pady=(int(4*s), 0))

    def _rebuild_checklist(self):
        """重建检查清单UI（纯展示模式）"""
        for widget in self.chk_content_frame.winfo_children(): 
            widget.destroy()
        
        s = self.scale
        
        self.chk_border_frame.pack(side="left", fill="y", padx=(0, 2))
        self.chk_content_frame.pack(side="left", fill="both", expand=True)

        font_title = (UIConfig.FONT_CHECKLIST_TITLE[0], int(UIConfig.FONT_CHECKLIST_TITLE[1]*s), UIConfig.FONT_CHECKLIST_TITLE[2])
        self.chk_title = tk.Label(self.chk_content_frame, text="出击检查清单", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.chk_title.pack(fill="x", padx=int(6*s), pady=(int(6*s), int(2*s)))

        font_item = (UIConfig.FONT_CHECKLIST_ITEM[0], int(UIConfig.FONT_CHECKLIST_ITEM[1]*s))
        pad_x = int(6*s)
        wrap_width = int(180*s)
        
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
                wraplength=wrap_width
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
        self.root.bind("<Control-Shift-Left>", lambda e: self._cycle_debug_scene(-1) if self._debug else None)
        self.root.bind("<Control-Shift-Right>", lambda e: self._cycle_debug_scene(1) if self._debug else None)
        self.root.bind("<Control-Shift-m>", lambda e: self._toggle_debug_mock_mode() if self._debug else None)
        
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
        self._recalc_size(force_shrink=True)
        self._update_ui()
        self._refresh_tray()
    
    def _refresh_tray(self):
        """刷新系统托盘菜单状态
        
        调用此方法以确保托盘菜单的勾选状态与实际状态同步。
        """
        if HAS_TRAY and hasattr(self, 'tray') and self.tray:
            try:
                self.tray.update_menu()
            except Exception:
                pass

    def _init_global_hotkeys(self):
        """初始化全局热键
        
        使用HotkeyConfig中配置的快捷键，支持运行时自定义。
        """
        self._ghk = None
        if not os.name == "nt" or not HotkeyConfig.GLOBAL_HOTKEYS:
            return
        
        # 使用配置的快捷键
        hotkeys = [
            (HotkeyConfig.HK_ID_RESET, HotkeyConfig.get_vk(HotkeyConfig.KEY_RESET), self._manual_reset_hotkey),
            (HotkeyConfig.HK_ID_LOCK, HotkeyConfig.get_vk(HotkeyConfig.KEY_LOCK), self._toggle_lock),
            (HotkeyConfig.HK_ID_CORNER, HotkeyConfig.get_vk(HotkeyConfig.KEY_CORNER), self._next_corner),
            (HotkeyConfig.HK_ID_BEEP, HotkeyConfig.get_vk(HotkeyConfig.KEY_BEEP), self._toggle_beep),
            (HotkeyConfig.HK_ID_ZONES, HotkeyConfig.get_vk(HotkeyConfig.KEY_ZONES), self._toggle_zone_sound),
        ]
        self._ghk = GlobalHotkeys(self.root, hotkeys)
        self._ghk.start()

    def _init_tray(self):
        """初始化系统托盘
        
        托盘菜单根据编译开关动态生成:
        - Lite模式: 仅保留基本功能（重置/锁定/声音/退出）
        - 完整模式: 包含所有功能
        """
        # 保存self引用供嵌套函数使用
        app = self
        
        def icon():
            # Prefer configured icon; fallback to .ico for better Windows compatibility.
            candidates = [FileConfig.ICON_FILE, "app.ico"]
            for name in candidates:
                try:
                    p = resource_path(name)
                    if os.path.exists(p):
                        return Image.open(p).convert("RGBA")
                except Exception:
                    continue
            return Image.new("RGBA", (64, 64), Theme.BLUE)
        
        # 回调函数（需要在主线程执行）
        def do_reset(icon, item):
            app.root.after(0, app._manual_reset)
        
        def do_lock(icon, item):
            app.root.after(0, app._toggle_lock)
        
        def do_corner(icon, item):
            app.root.after(0, app._next_corner)
        
        def do_beep(icon, item):
            app.root.after(0, app._toggle_beep)
        
        def do_zone_sound(icon, item):
            app.root.after(0, app._toggle_zone_sound)

        def do_edit_checklist(icon, item):
            app.root.after(0, app._edit_checklist)
        
        def do_settings(icon, item):
            app.root.after(0, app._show_settings)
        
        def do_debug(icon, item):
            app.root.after(0, app._toggle_debug)
        
        def do_quit(icon, item):
            app.root.after(0, app._quit)

        def do_about(icon, item):
            app.root.after(0, app._show_about)
        
        def do_star(icon, item):
            app.root.after(0, app._open_star_url)

        # 状态检查函数
        def is_locked(item):
            return app._locked
        
        def is_beep_on(item):
            return app.sound.is_enabled()
        
        def is_zone_sound_on(item):
            return app._zone_sound_enabled

        def is_debug_on(item):
            return app._debug
        
        # 构建菜单项列表
        menu_items = [
            pystray.MenuItem("🔄 立即重置计时器", do_reset),
            pystray.MenuItem(f"🔓 锁定/解锁 ({HotkeyConfig.KEY_LOCK})", do_lock, checked=is_locked),
            pystray.MenuItem(f"📍 切换角落 ({HotkeyConfig.KEY_CORNER})", do_corner),
            pystray.Menu.SEPARATOR,
        ]
        
        # 面板子菜单（仅在有可配置面板时显示）
        if ENABLE_ADVANCED_SETTINGS:
            # 面板开关回调
            def toggle_zone(icon, item):
                app.root.after(0, lambda: app._toggle_panel('show_zones'))
            
            def toggle_airfield(icon, item):
                app.root.after(0, lambda: app._toggle_panel('show_airfields'))
            
            def toggle_fuel(icon, item):
                app.root.after(0, lambda: app._toggle_panel('show_fuel'))

            def toggle_speed(icon, item):
                app.root.after(0, lambda: app._toggle_panel('show_speed'))

            def toggle_speed_history(icon, item):
                app.root.after(0, app._toggle_speed_history_mode)

            def toggle_checklist(icon, item):
                app.root.after(0, lambda: app._toggle_panel('show_checklist'))
            
            def toggle_bombing(icon, item):
                app.root.after(0, lambda: app._toggle_panel('show_bombing'))
            
            def is_zone_panel(item):
                return PanelConfig.is_effectively_enabled('zones')
            
            def is_airfield_panel(item):
                return PanelConfig.is_effectively_enabled('airfields')
            
            def is_fuel_panel(item):
                return PanelConfig.is_effectively_enabled('fuel')

            def is_speed_panel(item):
                return PanelConfig.is_effectively_enabled('speed')

            def is_speed_history_mode(item):
                return PanelConfig.speed_history_mode

            def is_checklist_panel(item):
                return PanelConfig.is_effectively_enabled('checklist')
            
            def is_bombing_panel(item):
                return PanelConfig.is_effectively_enabled('bombing')
            
            panel_items = []
            if ENABLE_ZONES:
                panel_items.append(pystray.MenuItem("🎯 战区导航", toggle_zone, checked=is_zone_panel))
            if ENABLE_AIRFIELDS:
                panel_items.append(pystray.MenuItem("🛫 机场导航", toggle_airfield, checked=is_airfield_panel))
            if ENABLE_FUEL:
                panel_items.append(pystray.MenuItem("⛽ 燃油管理", toggle_fuel, checked=is_fuel_panel))
            panel_items.append(pystray.MenuItem("⚡ 速度监视", toggle_speed, checked=is_speed_panel))
            panel_items.append(pystray.MenuItem("🕰 历史模式(仅速度)", toggle_speed_history, checked=is_speed_history_mode))
            if ENABLE_CCRP:
                panel_items.append(pystray.MenuItem("💣 投弹预测", toggle_bombing, checked=is_bombing_panel))
            if ENABLE_CHECKLIST:
                panel_items.append(pystray.MenuItem("✅ 出击检查", toggle_checklist, checked=is_checklist_panel))
            
            if panel_items:
                panel_menu = pystray.Menu(*panel_items)
                menu_items.append(pystray.MenuItem("📊 显示面板", panel_menu))
            
            # v6.2.1: 导航条模式切换
            if ENABLE_ZONES:
                def toggle_nav_mode(icon, item):
                    app.root.after(0, app._toggle_navigation_mode)
                
                def is_standalone_nav(item):
                    return PanelConfig.navigation_mode == "standalone"
                
                menu_items.append(pystray.MenuItem("🧭 独立导航窗口", toggle_nav_mode, checked=is_standalone_nav))
            
            menu_items.append(pystray.Menu.SEPARATOR)
        
        # 声音设置
        menu_items.append(pystray.MenuItem(f"🔊 声音 ({HotkeyConfig.KEY_BEEP})", do_beep, checked=is_beep_on))
        
        # 战区提示音（仅在战区功能启用时显示）
        if ENABLE_ZONES:
            menu_items.append(pystray.MenuItem(f"🔔 战区提示音 ({HotkeyConfig.KEY_ZONES})", do_zone_sound, checked=is_zone_sound_on))
        
        # 检查清单编辑（仅在检查清单功能启用时显示）
        if ENABLE_CHECKLIST:
            menu_items.append(pystray.MenuItem("📝 编辑检查清单", do_edit_checklist))
        
        # 设置（仅在高级设置启用时显示）
        if ENABLE_ADVANCED_SETTINGS:
            menu_items.append(pystray.MenuItem("⚙️ 设置", do_settings))
        
        menu_items.append(pystray.Menu.SEPARATOR)
        menu_items.append(pystray.MenuItem("⭐ 给作者点个Star", do_star))
        menu_items.append(pystray.MenuItem("🐛 Debug模式", do_debug, checked=is_debug_on))
        menu_items.append(pystray.MenuItem("ℹ️ 关于", do_about))
        menu_items.append(pystray.MenuItem("❌ 退出", do_quit))
        
        # 主菜单
        menu = pystray.Menu(*menu_items)
        
        self.tray = pystray.Icon(__title__, icon(), __title__, menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

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
        if self.hud_overlay:
            return True
        try:
            self.hud_overlay = HUDOverlay(self)
            self.hud_overlay.set_lock_state(self._locked)
            self._hud_monitor_refresh_ts = 0.0
            return True
        except Exception as e:
            self.hud_overlay = None
            print(f"[HUD] 初始化失败: {e}")
            return False

    def _show_hud_overlay(self) -> bool:
        """显示 HUD 叠加层。"""
        if not self._ensure_hud_overlay():
            return False
        try:
            self.hud_overlay.show()
            self.hud_overlay.set_lock_state(self._locked)
            self._hud_monitor_refresh_ts = 0.0
            return True
        except Exception as e:
            print(f"[HUD] 显示失败: {e}")
            return False

    def _update_hud_overlay(self, snap: UISnapshot) -> None:
        """在 UI 刷新中更新 HUD 叠加层。"""
        overlay = self.hud_overlay
        if not HUDConfig.enabled:
            if overlay and overlay.is_visible():
                overlay.hide()
            self._hud_last_target = None
            return

        if not self._show_hud_overlay():
            HUDConfig.enabled = False
            self._update_hint()
            self._save_config()
            self._refresh_tray()
            self._hud_last_target = None
            return

        overlay = self.hud_overlay
        if not overlay:
            return

        try:
            now = time.monotonic()
            if (now - self._hud_monitor_refresh_ts) >= 0.35:
                self._hud_monitor_refresh_ts = now
                overlay.refresh_monitor_geometry()

            target_zone = None
            secondary_targets = []
            secondary_limit = max(2, int(getattr(ZoneConfig, "MAX_DISPLAY_ZONES", 6)))
            if snap.phase in (Phase.ALIVE, Phase.LOSS_PENDING):
                target_zone = next((z for z in snap.zones if z.is_target), None)
                if target_zone is None and snap.zones:
                    target_zone = min(snap.zones, key=lambda z: abs(z.relative))
                if snap.zones:
                    for zone in sorted(snap.zones, key=lambda z: abs(z.relative)):
                        if target_zone is not None and zone.id == target_zone.id:
                            continue
                        secondary_targets.append(
                            {
                                "relative": float(zone.relative),
                                "distance": float(zone.distance_km),
                                "label": "",
                            }
                        )
                        if len(secondary_targets) >= secondary_limit:
                            break

            if target_zone:
                self._hud_last_target = {
                    "ts": now,
                    "relative": float(target_zone.relative),
                    "distance": float(target_zone.distance_km),
                    "pitch": float(getattr(snap, "attitude_pitch_deg", 0.0) or 0.0),
                    "roll": float(getattr(snap, "attitude_roll_deg", 0.0) or 0.0),
                    "fallback": bool(getattr(snap, "hud_attitude_fallback", True)),
                    "heading": float(getattr(snap, "player_heading", 0.0) or 0.0),
                    "altitude": float(getattr(snap, "altitude_m", 0.0) or 0.0),
                    "secondary_targets": list(secondary_targets),
                }
                overlay.clear_standby()
                overlay.update_target(
                    has_target=True,
                    relative_deg=self._hud_last_target["relative"],
                    distance_km=self._hud_last_target["distance"],
                    attitude_pitch_deg=self._hud_last_target["pitch"],
                    attitude_roll_deg=self._hud_last_target["roll"],
                    attitude_fallback=self._hud_last_target["fallback"],
                    heading_deg=self._hud_last_target["heading"],
                    own_altitude_m=self._hud_last_target["altitude"],
                    secondary_targets=self._hud_last_target["secondary_targets"],
                )
            else:
                can_hold = False
                if self._hud_last_target and snap.phase in (Phase.ALIVE, Phase.LOSS_PENDING) and not snap.api_down:
                    age = now - float(self._hud_last_target.get("ts", 0.0))
                    can_hold = age <= self._hud_target_hold_sec

                if can_hold:
                    cached = self._hud_last_target
                    heading = float(getattr(snap, "player_heading", cached.get("heading", 0.0)) or 0.0)
                    altitude = float(getattr(snap, "altitude_m", cached.get("altitude", 0.0)) or 0.0)
                    pitch = float(getattr(snap, "attitude_pitch_deg", cached.get("pitch", 0.0)) or 0.0)
                    roll = float(getattr(snap, "attitude_roll_deg", cached.get("roll", 0.0)) or 0.0)
                    fallback = bool(getattr(snap, "hud_attitude_fallback", cached.get("fallback", True)))
                    cached["heading"] = heading
                    cached["altitude"] = altitude
                    cached["pitch"] = pitch
                    cached["roll"] = roll
                    cached["fallback"] = fallback
                    overlay.clear_standby()
                    overlay.update_target(
                        has_target=True,
                        relative_deg=float(cached["relative"]),
                        distance_km=float(cached["distance"]),
                        attitude_pitch_deg=pitch,
                        attitude_roll_deg=roll,
                        attitude_fallback=fallback,
                        heading_deg=heading,
                        own_altitude_m=altitude,
                        secondary_targets=list(cached.get("secondary_targets", [])),
                    )
                else:
                    overlay.clear_target()
                    if snap.api_down:
                        overlay.show_standby("8111 DELAY")
                    elif snap.api_down_pending:
                        overlay.show_standby("8111 PENDING")
                    elif snap.phase not in (Phase.ALIVE, Phase.LOSS_PENDING):
                        overlay.show_standby("HUD STANDBY")
                    else:
                        overlay.show_standby("NO TARGET")

            if self._hud_render_error_count > 0:
                self._hud_render_error_count = 0
                overlay.update_transparency()
        except Exception as e:
            self._hud_render_error_count += 1
            if self._hud_render_error_count in (1, 10, 30):
                print(f"[HUD] 渲染降级: {e}")
            degraded_alpha = max(60, int(HUDConfig.alpha * 0.55))
            try:
                overlay.apply_window_styles(click_through=self._locked, alpha=degraded_alpha)
                overlay.show_standby("HUD DEGRADED")
            except Exception:
                pass

    def _toggle_hud(self):
        """切换 HUD 叠加层开关。"""
        HUDConfig.enabled = not HUDConfig.enabled
        if HUDConfig.enabled:
            if not self._show_hud_overlay():
                HUDConfig.enabled = False
            else:
                self._hud_render_error_count = 0
        else:
            if self.hud_overlay:
                self.hud_overlay.hide()
            self._hud_last_target = None

        self._update_hint()
        self._save_config()
        self._refresh_tray()
        if HUDConfig.enabled:
            self.sound.play(pattern="on")

    def _toggle_navigation_mode(self):
        """切换导航条模式（集成/独立）
        
        仅在战区功能启用时可用。
        """
        if not ENABLE_ZONES or not self.nav_window:
            return
        
        if PanelConfig.navigation_mode == "integrated":
            PanelConfig.navigation_mode = "standalone"
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
        
        pad = int(UIConfig.WINDOW_PADDING * self.scale)
        
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
        
        new_w = max(min_width, req_w + pad)
        new_h = req_h + pad + int(8 * self.scale)

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
            elif (old_w > 0 and old_h > 0):
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

    def _apply_snap_anchor(self, x: int, y: int, w: int, h: int, anchor: Dict[str, Any]) -> Tuple[int, int]:
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
            monitor = next((m for m in monitors if m.get("is_primary")), monitors[0] if monitors else None)
        
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
        if self.hud_overlay:
            self.hud_overlay.set_lock_state(self._locked)
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
            history_text = "空历模式: 仅速度提醒"
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
            self.nudge_lbl.config(text=self._nudge_text())
        if hasattr(self, "nudge_row") and self.nudge_row:
            was_mapped = self.nudge_row.winfo_ismapped()
            if self._nudge_visible:
                if not self.nudge_row.winfo_ismapped():
                    self.nudge_row.pack(side="bottom", fill="x")
            else:
                if self.nudge_row.winfo_ismapped():
                    self.nudge_row.pack_forget()
            if was_mapped != self.nudge_row.winfo_ismapped():
                self._recalc_size()

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
        self.sound.play(*SoundConfig.BEEP_TICK)

    def _manual_reset(self):
        """立即执行手动重置。"""
        self._clear_manual_reset_confirmation(refresh_hint=True)
        self.game.manual_reset()
        self.sound.play(*SoundConfig.BEEP_MANUAL_RESET)

    def _show_settings(self):
        """显示设置对话框
        
        从托盘菜单调用，不受窗口锁定状态影响。
        """
        SettingsDialog(self.root, self)

    def apply_display_settings_runtime(
        self,
        theme_changed: bool,
        scale_changed: bool,
        nav_width_changed: bool = False,
    ) -> None:
        """运行时应用显示设置（主题/缩放/导航宽度）

        通过局部重建UI避免强制重启应用。
        """
        need_main_rebuild = bool(theme_changed or scale_changed)
        need_nav_rebuild = bool(need_main_rebuild or nav_width_changed)
        if not (need_main_rebuild or need_nav_rebuild):
            return

        nav_was_visible = False
        if ENABLE_ZONES and need_nav_rebuild and getattr(self, "nav_window", None):
            try:
                nav_was_visible = bool(self.nav_window.is_visible())
            except Exception:
                nav_was_visible = False
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
            self._zone_label_pool = []
            self._airport_label_pool = []
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
            self._recalc_size(force_shrink=True)

        if ENABLE_ZONES and need_nav_rebuild:
            self.nav_window = NavigationWindow(self)
            if PanelConfig.navigation_mode == "standalone" and nav_was_visible:
                self.nav_window.show()

        # 重新应用窗口样式（锁定态穿透 + 透明度）
        alpha = UIConfig.WINDOW_ALPHA if self._locked else min(240, UIConfig.WINDOW_ALPHA + 30)
        Win32.setup_window(self.hwnd, click_through=self._locked, alpha=alpha)
        if ENABLE_ZONES and getattr(self, "nav_window", None):
            self.nav_window.apply_window_styles(click_through=self._locked, alpha=alpha)
        if self.hud_overlay:
            self.hud_overlay.set_lock_state(self._locked)
            self.hud_overlay.update_transparency()
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
        
        try:
            if getattr(self, "_ghk", None):
                self._ghk.stop()
        except:
            pass
        
        if HAS_TRAY and hasattr(self, "tray"):
            try:
                self.tray.stop()
            except:
                pass

        if self.hud_overlay:
            try:
                self.hud_overlay.destroy()
            except Exception:
                pass
            self.hud_overlay = None
        
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

    def _poll_loop(self):
        """逻辑轮询循环(独立线程)
        
        优化: 使用轻量级is_api_down属性而非完整snapshot()决定轮询间隔
        """
        while not self._stop:
            loop_start = time.monotonic()
            try:
                self.game.tick()
            except Exception:
                time.sleep(NetworkConfig.BACKOFF_MAX)
                continue
            # 使用轻量级属性替代完整snapshot
            interval = NetworkConfig.BACKOFF_MAX if self.game.is_api_down else NetworkConfig.POLL_INTERVAL
            elapsed = time.monotonic() - loop_start
            time.sleep(max(0.0, interval - elapsed))

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

            if (snap.phase == Phase.ALIVE and snap.landed_flash and not self._last_landed_flash):
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

        if self._manual_reset_confirm_until > 0.0 and time.monotonic() >= self._manual_reset_confirm_until:
            self._clear_manual_reset_confirmation(refresh_hint=True)

        zones_enabled = ENABLE_ZONES and PanelConfig.is_effectively_enabled("zones")
        airfields_enabled = ENABLE_AIRFIELDS and PanelConfig.is_effectively_enabled("airfields")
        fuel_enabled = ENABLE_FUEL and PanelConfig.is_effectively_enabled("fuel")
        speed_enabled = PanelConfig.is_effectively_enabled("speed")
        checklist_enabled = ENABLE_CHECKLIST and PanelConfig.is_effectively_enabled("checklist")
        bombing_enabled = ENABLE_CCRP and PanelConfig.is_effectively_enabled("bombing")

        # 控制面板可见性（结合PanelConfig设置和编译开关）
        # 战区/机场/燃油/投弹面板需要任一相关面板启用
        show_zone_panel = (
            (snap.phase in (Phase.ALIVE, Phase.LOSS_PENDING)) and
            (not snap.api_down) and
            (
                zones_enabled or
                airfields_enabled or
                fuel_enabled or
                bombing_enabled
            )
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
            checklist_enabled and
            (snap.phase == Phase.ALIVE) and 
            (snap.on_ground or snap.landed_flash) and 
            (not snap.api_down)
        )
        self._set_checklist_visible(show_chk)

        # 更新计时器显示
        self.timer_lbl.config(text=fmt_time(snap.remaining_sec))
        if snap.remaining_sec is None:
            self.timer_lbl.config(fg=Theme.TEXT_MUTED)
            self.bar_fill.place(relwidth=0)
            self.bar_fill.config(bg=Theme.BLUE)
        else:
            remain = snap.remaining_sec
            color = Theme.RED if remain <= 10 else Theme.YELLOW if remain <= GameConfig.FINAL_WARNING_SEC else Theme.TEXT
            bar = Theme.RED if remain <= 10 else Theme.YELLOW if remain <= GameConfig.FINAL_WARNING_SEC else Theme.BLUE
            self.timer_lbl.config(fg=color)
            self.bar_fill.place(relwidth=snap.progress)
            self.bar_fill.config(bg=bar)
            
            # 播放警告音
            remain_int = int(remain)
            if (remain <= GameConfig.FINAL_WARNING_SEC) and (not debug_mock_mode):
                if remain_int in SoundConfig.WARNING_SECONDS and remain_int != self._last_beep_sec:
                    pattern = "warning" if remain_int in SoundConfig.MAJOR_WARNINGS else "tick"
                    self.sound.play(pattern=pattern)
                    self._last_beep_sec = remain_int
            else:
                self._last_beep_sec = -1

        # 更新生命/周期信息
        self.life_lbl.config(text=(f"第{snap.life_index}次复活" if snap.life_index is not None else "未复活"))
        self.cycle_lbl.config(text=(f"第{snap.cycle}轮" if snap.cycle is not None else "未开始"))
        
        # 更新徽章
        self.badge_main.set(*snap.main_badge)
        self.badge_flight.set(*snap.flight_badge)
        if speed_enabled:
            if not self.speed_row.winfo_ismapped():
                self.speed_row.pack(
                    fill="x",
                    pady=(
                        int(UIConfig.PADDING_SPEED_STRIP[0] * self.scale),
                        int(UIConfig.PADDING_SPEED_STRIP[1] * self.scale),
                    ),
                    before=self.bar_bg.master,
                )
            speed_level = self._update_speed_strip(snap, debug_mock_mode)
        else:
            speed_level = "unknown"
            if self.speed_row.winfo_ismapped():
                self.speed_row.pack_forget()
            self._last_overspeed_level = "unknown"
            self._last_overspeed_sound_ts = 0.0
        
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
                anchor_widget = self.badge_lock if hasattr(self, "badge_lock") else self.badge_flight
                self.badge_gear.pack(
                    side="left",
                    padx=(int(UIConfig.SPACING_BADGE*self.scale), 0),
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
        delay = max(0, int(UIConfig.UI_REFRESH_MS - elapsed_ms))
        if not self._stop:
            self._ui_after_id = self.root.after(delay, self._update_ui)
