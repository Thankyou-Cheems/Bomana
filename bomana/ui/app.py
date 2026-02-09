# -*- coding: utf-8 -*-        - hint_min_width: 提示文字最小宽度，根据编译开关动态计算
"""Main Tk app container."""

import ctypes
import os
import threading
import time
import tkinter as tk
import locale
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
    HotkeyConfig,
    SnapConfig,
    BombConfig,
    ChecklistConfig,
    SoundConfig,
    GameConfig,
    NetworkConfig,
    FuelConfig,
    BallisticPhysicsParams,
    Theme,
    AboutConfig,
)
from bomana.core.logic import GameLogic
from bomana.core.state import UISnapshot, Phase
from bomana.utils.file_utils import ConfigManager, resource_path
from bomana.config import FileConfig
from bomana.utils.system import Win32, GlobalHotkeys, SingleInstanceManager
from bomana.utils.sound import SoundManager
from bomana.utils.math_utils import (
    calculate_smart_scale,
    calculate_heading_tape_scale,
    get_cdi_tolerance,
    calculate_zone_turn_indicator,
    calculate_zone_status,
    calculate_airfield_turn_indicator,
    calculate_airfield_status,
    format_distance_ete,
)
from bomana.ui.widgets import Pill, HeadingTape
from bomana.ui.dialogs import SettingsDialog, ChecklistEditor, BombSelectorDialog, AboutDialog
from bomana.ui.nav_window import NavigationWindow

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
        self._last_beep_sec = -1
        self._zone_sound_enabled = True

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
        self._hint_width_cache = {"text": "", "width": int(320 * self.scale)}

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

        # 恢复状态并启动
        self._restored_state = self.game.restore_timer_state()
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._update_ui()

        if HAS_TRAY:
            self._init_tray()

    def _load_config(self):
        """加载用户配置
        
        加载顺序: 主题必须在UI创建前应用
        配置项: alpha/scale/theme/panels/hotkey_bindings/snap/window_position
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
                UIConfig.UI_SCALE_MULT = max(0.6, min(1.5, float(scale)))
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
        theme_name = config.get('theme', 'dark')
        Theme.apply(theme_name)
        
        # 面板显示设置
        panels = config.get('panels', {})
        PanelConfig.show_zones = panels.get('show_zones', True)
        PanelConfig.show_airfields = panels.get('show_airfields', True)
        PanelConfig.show_fuel = panels.get('show_fuel', True)
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
        preferred_latin = [
            "Segoe UI Variable",
            "Segoe UI",
            "Arial",
            "Helvetica",
        ]
        preferred_cjk = [
            "Microsoft YaHei UI",
            "Microsoft YaHei",
            "Noto Sans CJK SC",
            "PingFang SC",
            "Source Han Sans SC",
            "WenQuanYi Micro Hei",
        ]
        loc = locale.getdefaultlocale()[0] or ""
        try:
            fams = set(tkfont.families(self.root))
        except Exception:
            return ""
        if os.name == "nt":
            for fam in preferred_cjk:
                if fam in fams:
                    return fam
            for fam in preferred_latin:
                if fam in fams:
                    return fam
        else:
            if loc.startswith(("zh", "ja", "ko")):
                for fam in preferred_cjk:
                    if fam in fams:
                        return fam
            for fam in preferred_latin:
                if fam in fams:
                    return fam
            for fam in preferred_cjk:
                if fam in fams:
                    return fam
        return ""

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
        """初始化UI布局
        
        结构：
        - main_frame: 主容器
          - bottom_frame: 底部（提示/调试）
          - top_frame: 顶部（计时器/徽章/进度条）
          - mid_frame: 中部（战区/检查清单）
        """
        s = self.scale
        self.main_frame = tk.Frame(self.root, bg=Theme.BG)
        pad_x, pad_y = UIConfig.PADDING_MAIN
        self.main_frame.pack(fill="both", expand=True, padx=int(pad_x*s), pady=int(pad_y*s))

        # === 底部区域 ===
        bottom_frame = tk.Frame(self.main_frame, bg=Theme.BG)
        bottom_frame.pack(side="bottom", fill="x")

        self.hint_row = tk.Frame(bottom_frame, bg=Theme.BG)
        self.hint_row.pack(side="bottom", fill="x")

        font_hint = (UIConfig.FONT_HINT[0], int(UIConfig.FONT_HINT[1]*s))
        self.hint_lbl = tk.Label(
            self.hint_row, text=self._hint_text(),
            font=font_hint, fg=Theme.TEXT_MUTED, bg=Theme.BG
        )
        self.hint_lbl.pack(side="left", fill="x", expand=True)

        self.nudge_row = tk.Frame(bottom_frame, bg=Theme.BG)
        self.nudge_row.columnconfigure(0, weight=1)

        nudge_wrap = int(380 * s)
        self.nudge_lbl = tk.Label(
            self.nudge_row, text=self._nudge_text(),
            font=font_hint, fg=Theme.TEXT_MUTED, bg=Theme.BG,
            anchor="w", justify="left", wraplength=nudge_wrap
        )
        self.nudge_lbl.grid(row=0, column=0, sticky="ew")

        self.star_lbl = tk.Label(
            self.nudge_row, text="⭐ Star",
            font=font_hint, fg=Theme.TEXT, bg=Theme.BG, cursor="hand2"
        )
        self.star_lbl.bind("<Button-1>", lambda e: self._open_star_url())
        self.star_lbl.bind("<Enter>", lambda e: self.star_lbl.config(fg=Theme.YELLOW))
        self.star_lbl.bind("<Leave>", lambda e: self.star_lbl.config(fg=Theme.TEXT))
        self.star_lbl.grid(row=0, column=1, sticky="e", padx=(int(8*s), 0))

        font_debug = (UIConfig.FONT_DEBUG[0], int(UIConfig.FONT_DEBUG[1]*s))
        self.diag_lbl = tk.Label(
            bottom_frame, text="",
            font=font_debug, fg=Theme.TEXT_MUTED, bg=Theme.BG, 
            anchor="w", justify="left",
            wraplength=int(UIConfig.DEBUG_WRAP_LENGTH*s)
        )

        # === 顶部区域 ===
        self.top_frame = tk.Frame(self.main_frame, bg=Theme.BG)
        self.top_frame.pack(side="top", fill="x")

        # 第一行：计时器
        row1 = tk.Frame(self.top_frame, bg=Theme.BG)
        row1.pack(fill="x")
        font_timer = (UIConfig.FONT_TIMER[0], int(UIConfig.FONT_TIMER[1]*s), UIConfig.FONT_TIMER[2])
        self.timer_lbl = tk.Label(row1, text="--:--", font=font_timer, fg=Theme.TEXT_MUTED, bg=Theme.BG, anchor="w")
        self.timer_lbl.pack(side="left")
        
        # 右侧信息
        right = tk.Frame(row1, bg=Theme.BG)
        right.pack(side="right", padx=(int(14*s), 0))
        font_life = (UIConfig.FONT_LIFE[0], int(UIConfig.FONT_LIFE[1]*s), UIConfig.FONT_LIFE[2])
        self.life_lbl = tk.Label(right, text="未复活", font=font_life, fg=Theme.BLUE, bg=Theme.BG, anchor="e")
        self.life_lbl.pack(anchor="e")
        font_cycle = (UIConfig.FONT_CYCLE[0], int(UIConfig.FONT_CYCLE[1]*s))
        self.cycle_lbl = tk.Label(right, text="未开始", font=font_cycle, fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="e")
        self.cycle_lbl.pack(anchor="e", pady=(int(2*s), 0))

        # 第二行：徽章
        row2 = tk.Frame(self.top_frame, bg=Theme.BG)
        pad_top, pad_bot = UIConfig.PADDING_ROW2
        row2.pack(fill="x", pady=(int(pad_top*s), int(pad_bot*s)))
        pill_font = (UIConfig.FONT_PILL[0], int(UIConfig.FONT_PILL[1]*s), UIConfig.FONT_PILL[2])
        self.badge_main = Pill(row2, text="IDLE", fg=Theme.TEXT, bg=Theme.GRAYPILL, font=pill_font)
        self.badge_main.pack(side="left")
        self.badge_flight = Pill(row2, text="—", fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, font=pill_font)
        self.badge_flight.pack(side="left", padx=(int(UIConfig.SPACING_BADGE*s), 0))
        # v5.9.6 新增：起落架警告徽章（v6.6.1: 集成进度条）
        self.badge_gear = Pill(row2, text="", fg=Theme.TEXT, bg=Theme.ORANGE, font=pill_font)
        # v6.6.1: 在徽章内部添加进度条指示器
        self.gear_progress_bar = tk.Frame(self.badge_gear, bg=Theme.BLUE, height=int(3*s))
        # 初始隐藏
        
        font_status = (UIConfig.FONT_STATUS[0], int(UIConfig.FONT_STATUS[1]*s))
        self.status_txt = tk.Label(row2, text="等待中", font=font_status, fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="e")
        self.status_txt.pack(side="right")

        # 进度条
        bar_height = int(UIConfig.PROGRESS_BAR_HEIGHT * s)
        bar_frame = tk.Frame(self.top_frame, bg=Theme.BG, height=bar_height)
        pad_top, pad_bot = UIConfig.PADDING_PROGRESS
        bar_frame.pack(fill="x", pady=(int(pad_top*s), int(pad_bot*s)))
        bar_frame.pack_propagate(False)
        bar_thickness = int(UIConfig.PROGRESS_BAR_THICKNESS * s)
        self.bar_bg = tk.Frame(bar_frame, bg=Theme.BORDER, height=bar_thickness)
        self.bar_bg.place(relx=0, rely=0.5, relwidth=1, anchor="w")
        self.bar_fill = tk.Frame(self.bar_bg, bg=Theme.BLUE, height=bar_thickness)
        self.bar_fill.place(relx=0, rely=0, relwidth=0, relheight=1)

        # === 中间内容区域 ===
        self.mid_frame = tk.Frame(self.main_frame, bg=Theme.BG)
        self.mid_frame.pack(side="top", fill="x", pady=(0, int(8*s)))
        self.mid_frame.columnconfigure(0, weight=1)
        self.mid_frame.columnconfigure(1, weight=1)

        # 战区导航框架
        self.zone_frame = tk.Frame(self.mid_frame, bg=Theme.GRAYPILL, bd=0, highlightthickness=0)
        self._init_zone_ui()

        # 检查清单框架
        self.chk_frame = tk.Frame(self.mid_frame, bg=Theme.GRAYPILL, bd=0, highlightthickness=0)
        self.chk_border_frame = tk.Frame(self.chk_frame, bg=Theme.SEPARATOR, width=1)
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
        self.zone_header_frame.grid(row=0, column=0, sticky="ew", padx=pad_x, pady=(int(6*s), int(2*s)))
        
        font_title = (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s), UIConfig.FONT_ZONE_TITLE[2])
        self.zone_title = tk.Label(self.zone_header_frame, text="🎯 战区导航", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.zone_title.pack(side="left")
        
        # 独立导航条模式按钮
        font_btn = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s))
        self.standalone_btn = tk.Label(
            self.zone_header_frame, text="⧉独立导航条", font=font_btn,
            fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, cursor="hand2"
        )
        self.standalone_btn.pack(side="left", padx=(int(10*s), 0))
        self.standalone_btn.bind("<Button-1>", lambda e: self._toggle_navigation_mode())
        self.standalone_btn.bind("<Enter>", lambda e: self.standalone_btn.config(
            fg=(Theme.BLUE if PanelConfig.navigation_mode != "standalone" else Theme.GREEN)))
        self.standalone_btn.bind("<Leave>", lambda e: self._update_nav_mode_button())
        self._update_nav_mode_button()
        
        font_heading = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s))
        font_item = font_heading
        self.heading_lbl = tk.Label(self.zone_header_frame, text="HDG: ---", font=font_heading, fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="e")
        self.heading_lbl.pack(side="right")
        
        # Row 1: v6.2重构 - 统一航向带(显示战区+机场+被摧毁目标)
        if ZoneConfig.HEADING_TAPE_ENABLED:
            self.heading_tape_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
            self.heading_tape_frame.grid(row=1, column=0, sticky="ew", padx=pad_x, pady=(int(2*s), int(4*s)))
            
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
            legend_text = "⊚战区  ✈友方  ✈敌方  ✕摧毁"
            
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
        self.compact_zone_title = tk.Label(self.compact_zone_frame, text="⊚ 战区", font=font_title, fg=Theme.RED, bg=Theme.GRAYPILL, anchor="w")
        self.compact_zone_title.pack(fill="x")
        self.compact_zone_list = tk.Frame(self.compact_zone_frame, bg=Theme.GRAYPILL)
        self.compact_zone_list.pack(fill="x")
        # 紧凑模式 - 右栏：机场
        self.compact_airport_frame = tk.Frame(self.compact_nav_frame, bg=Theme.GRAYPILL)
        self.compact_airport_frame.grid(row=0, column=1, sticky="nsew", padx=(int(4*s), 0))
        self.compact_airport_title = tk.Label(self.compact_airport_frame, text="✈ 机场", font=font_title, fg=Theme.BLUE, bg=Theme.GRAYPILL, anchor="w")
        self.compact_airport_title.pack(fill="x")
        self.compact_airport_list = tk.Frame(self.compact_airport_frame, bg=Theme.GRAYPILL)
        self.compact_airport_list.pack(fill="x")
        # 紧凑模式标签池
        self._compact_zone_label_pool = []
        self._compact_airport_label_pool = []
        
        # Row 3: 战区列表容器（完整模式）
        self.zone_list_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.zone_list_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(10*s)))

        # Row 4: 机场标题
        self.airport_title_lbl = tk.Label(self.zone_frame, text="🛫 机场导航", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.airport_title_lbl.grid(row=4, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))

        # v6.2: 移除独立的机场航向带（已合并到主航向带）
        # 保留变量引用以兼容
        self.airport_tape_frame = None
        self.friendly_heading_tape = None
        self.enemy_heading_tape = None

        # Row 6: 机场列表容器
        self.airport_list_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.airport_list_frame.grid(row=6, column=0, sticky="ew", padx=pad_x, pady=(0, int(10*s)))

        # Row 7: 燃油标题
        self.fuel_title_lbl = tk.Label(self.zone_frame, text="⛽ 燃油管理", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.fuel_title_lbl.grid(row=7, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))
        
        # Row 8: 燃油信息容器
        self.fuel_info_frame = tk.Frame(self.zone_frame, bg=Theme.GRAYPILL)
        self.fuel_info_frame.grid(row=8, column=0, sticky="ew", padx=pad_x, pady=(0, int(6*s)))
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
                text="💣 投弹预测", 
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
        self.chk_title = tk.Label(self.chk_content_frame, text="✅ 出击检查", font=font_title, fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w")
        self.chk_title.pack(fill="x", padx=int(6*s), pady=(int(6*s), int(2*s)))

        font_item = (UIConfig.FONT_CHECKLIST_ITEM[0], int(UIConfig.FONT_CHECKLIST_ITEM[1]*s))
        pad_x = int(6*s)
        wrap_width = int(140*s)
        
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
            (HotkeyConfig.HK_ID_RESET, HotkeyConfig.get_vk(HotkeyConfig.KEY_RESET), self._manual_reset),
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
            pystray.MenuItem(f"🔄 重置计时器 ({HotkeyConfig.KEY_RESET})", do_reset),
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
            
            def toggle_checklist(icon, item):
                app.root.after(0, lambda: app._toggle_panel('show_checklist'))
            
            def toggle_bombing(icon, item):
                app.root.after(0, lambda: app._toggle_panel('show_bombing'))
            
            def is_zone_panel(item):
                return PanelConfig.show_zones
            
            def is_airfield_panel(item):
                return PanelConfig.show_airfields
            
            def is_fuel_panel(item):
                return PanelConfig.show_fuel
            
            def is_checklist_panel(item):
                return PanelConfig.show_checklist
            
            def is_bombing_panel(item):
                return PanelConfig.show_bombing
            
            panel_items = []
            if ENABLE_ZONES:
                panel_items.append(pystray.MenuItem("🎯 战区导航", toggle_zone, checked=is_zone_panel))
            if ENABLE_AIRFIELDS:
                panel_items.append(pystray.MenuItem("🛫 机场导航", toggle_airfield, checked=is_airfield_panel))
            if ENABLE_FUEL:
                panel_items.append(pystray.MenuItem("⛽ 燃油管理", toggle_fuel, checked=is_fuel_panel))
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
        """切换调试模式"""
        self._debug = not self._debug
        if self._debug:
            self.diag_lbl.pack(side="bottom", fill="x", pady=(0, int(UIConfig.SPACING_DEBUG*self.scale)), before=self.hint_row)
        else:
            self.diag_lbl.pack_forget()
        self._recalc_size()
        self._refresh_tray()

    def _toggle_zone_sound(self):
        """切换战区提示音"""
        self._zone_sound_enabled = not self._zone_sound_enabled
        self._update_hint()
        self._save_config()
        self._refresh_tray()
        if self._zone_sound_enabled:
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
        
        # ⚠️ 徽章行最小宽度（确保起落架徽章等能完整显示）
        # 徽章行包含: badge_main + badge_flight + badge_gear(可选) + status_txt
        # 估算: 80 + 80 + 100 + 60 = 320px 基础宽度
        badge_min_width = int(320 * self.scale)
        
        # ⚠️ 提示文字最小宽度（动态测量，避免浪费或截断）
        hint_min_width = int(320 * self.scale)
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
            hint_min_width = int(320 * self.scale)
        
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

    def _hint_text(self) -> str:
        """生成提示文本
        
        注意: 修改提示文字长度时需同步修改_recalc_size()中的hint_min_width
        根据编译开关动态生成提示内容
        """
        sound = "🔊开" if self.sound.is_enabled() else "🔇关"
        
        # 使用配置的快捷键
        k_reset = HotkeyConfig.KEY_RESET
        k_lock = HotkeyConfig.KEY_LOCK
        k_corner = HotkeyConfig.KEY_CORNER
        k_beep = HotkeyConfig.KEY_BEEP

        if self._locked:
            parts = [f"{k_reset}重置", f"{k_lock}解锁", f"{k_corner}角落", f"{k_beep}声音({sound})"]
            # 战区提示音仅在战区功能启用时显示
            if ENABLE_ZONES:
                zone_sound = "🔔开" if self._zone_sound_enabled else "🔕关"
                k_zones = HotkeyConfig.KEY_ZONES
                parts.append(f"{k_zones}战区({zone_sound})")
            return " │ ".join(parts)
        else:
            parts = ["拖动移动", f"{k_lock}锁定", f"{k_beep}声音({sound})"]
            if ENABLE_ZONES:
                zone_sound = "🔔开" if self._zone_sound_enabled else "🔕关"
                k_zones = HotkeyConfig.KEY_ZONES
                parts.append(f"{k_zones}战区({zone_sound})")
            return " │ ".join(parts)

    def _nudge_text(self) -> str:
        return "✨ 炸弹，爽！如果觉得好用，给项目点个 Star 支持一下（起飞自动隐藏）"

    def _update_hint(self) -> None:
        """更新提示文本"""
        if hasattr(self, "hint_lbl") and self.hint_lbl:
            self.hint_lbl.config(text=self._hint_text())
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
            self.standalone_btn.config(text="⧉独立导航条(已开启)", fg=Theme.GREEN)
        else:
            self.standalone_btn.config(text="⧉独立导航条", fg=Theme.TEXT_MUTED)

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

    def _manual_reset(self):
        """手动重置计时器（F7）"""
        self.game.manual_reset()
        self.sound.play(*SoundConfig.BEEP_MANUAL_RESET)

    def _show_settings(self):
        """显示设置对话框
        
        从托盘菜单调用，不受窗口锁定状态影响。
        """
        SettingsDialog(self.root, self)

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
        """更新中间面板布局（战区/检查清单）"""
        self.zone_frame.grid_forget()
        self.chk_frame.grid_forget()
        
        self.mid_frame.rowconfigure(0, weight=1)
        
        if self._zone_panel_visible and self._checklist_panel_visible:
            if not self.mid_frame.winfo_ismapped():
                self.mid_frame.pack(side="top", fill="x", pady=(0, int(8*self.scale)), after=self.top_frame)
            self.zone_frame.grid(row=0, column=0, sticky="new", padx=(0, int(2*self.scale)))
            self.chk_frame.grid(row=0, column=1, sticky="new", padx=(int(2*self.scale), 0))
            if not self.chk_border_frame.winfo_ismapped():
                self.chk_border_frame.pack(side="left", fill="y", padx=(0, 2), before=self.chk_content_frame)
            self._recalc_size()
        elif self._zone_panel_visible:
            if not self.mid_frame.winfo_ismapped():
                self.mid_frame.pack(side="top", fill="x", pady=(0, int(8*self.scale)), after=self.top_frame)
            self.zone_frame.grid(row=0, column=0, columnspan=2, sticky="new")
            self._recalc_size()
        elif self._checklist_panel_visible:
            if not self.mid_frame.winfo_ismapped():
                self.mid_frame.pack(side="top", fill="x", pady=(0, int(8*self.scale)), after=self.top_frame)
            self.chk_frame.grid(row=0, column=0, columnspan=2, sticky="new")
            self.chk_border_frame.pack_forget()
            self._recalc_size()
        else:
            self.mid_frame.pack_forget()
            self._recalc_size(force_shrink=True)

    def _set_zone_panel_visible(self, visible: bool):
        """设置战区面板可见性"""
        if self._zone_panel_visible != visible:
            self._zone_panel_visible = visible
            self._update_mid_panel_layout()
    def _update_tape_info_labels(self, targets_info: list, primary_zone):
        """更新航向带下方的状态提示（战区+友方机场）
        
        v6.2.1: 分两行显示战区和友方机场的状态
        v6.2.2: 统一格式，战区添加距离/ETE，机场添加状态描述
        v6.5: 重构 - 使用工具函数复用导航逻辑
        
        Args:
            targets_info: 目标信息列表
            primary_zone: 主目标战区（用于计算容差）
        """
        # === 更新战区状态提示 ===
        zone_info = next((t for t in targets_info if t['type'] == 'zone'), None)
        if primary_zone and self.tape_turn_lbl and self.tape_deviation_lbl and self.tape_tolerance_lbl:
            tolerance = get_cdi_tolerance(primary_zone.distance_km)
            scale = calculate_heading_tape_scale(primary_zone.distance_km)
            rel = primary_zone.relative
            abs_rel = abs(rel)
            
            # v6.5: 使用工具函数计算转向指示和状态
            turn_text, turn_color = calculate_zone_turn_indicator(rel, tolerance)
            dev_text, dev_color = calculate_zone_status(abs_rel, tolerance)
            
            # 距离和ETE
            ete_str = zone_info.get('ete_str') if zone_info else None
            info_text = format_distance_ete(primary_zone.distance_km, ete_str)
            
            # v6.4: 容差移至图例行
            tol_text = f"±{tolerance:.1f}° {scale:.1f}x"
            
            self.tape_turn_lbl.config(text=turn_text, fg=turn_color)
            self.tape_deviation_lbl.config(text=dev_text, fg=dev_color)
            if hasattr(self, 'tape_zone_info') and self.tape_zone_info:
                self.tape_zone_info.config(text=info_text, fg=Theme.RED)
            # 更新图例行的容差显示
            if hasattr(self, 'tape_tolerance_legend') and self.tape_tolerance_legend:
                self.tape_tolerance_legend.config(text=tol_text)
            self.tape_tolerance_lbl.config(text="")
            
            if self.tape_zone_row:
                self.tape_zone_row.pack(fill="x", pady=(int(2*self.scale), 0))
        elif self.tape_turn_lbl and self.tape_deviation_lbl and self.tape_tolerance_lbl:
            # 无战区目标时隐藏战区行
            self.tape_turn_lbl.config(text="", fg=Theme.TEXT_MUTED)
            self.tape_deviation_lbl.config(text="无目标", fg=Theme.TEXT_MUTED)
            if hasattr(self, 'tape_zone_info') and self.tape_zone_info:
                self.tape_zone_info.config(text="")
            self.tape_tolerance_lbl.config(text="")
            if self.tape_zone_row:
                self.tape_zone_row.pack_forget()
        
        # === 更新友方机场状态提示 ===
        friendly_info = next((t for t in targets_info if t['type'] == 'friendly'), None)
        if friendly_info and self.tape_friendly_turn and self.tape_friendly_info:
            rel = friendly_info['relative']
            abs_rel = abs(rel)
            dist = friendly_info['distance_km']
            
            # v6.5: 使用工具函数计算转向指示和状态
            turn_text, turn_color = calculate_airfield_turn_indicator(rel)
            status_text, status_color = calculate_airfield_status(abs_rel)
            
            # 距离和ETE
            info_text = format_distance_ete(dist, friendly_info.get('ete_str'))
            
            self.tape_friendly_turn.config(text=turn_text, fg=turn_color)
            if hasattr(self, 'tape_friendly_status') and self.tape_friendly_status:
                self.tape_friendly_status.config(text=status_text, fg=status_color)
            self.tape_friendly_info.config(text=info_text, fg=Theme.BLUE)
            
            if self.tape_friendly_row:
                self.tape_friendly_row.pack(fill="x", pady=(int(1*self.scale), 0))
        elif self.tape_friendly_row:
            # 无友方机场时隐藏该行
            self.tape_friendly_row.pack_forget()

    def _set_checklist_visible(self, visible: bool):
        """设置检查清单可见性"""
        if self._checklist_panel_visible != visible:
            self._checklist_panel_visible = visible
            self._update_mid_panel_layout()

    def _update_zone_display(self, snap: UISnapshot):
        """更新战区显示
        
        性能优化(每50ms调用):
        - 使用pack_forget()而非destroy()
        - Label复用池避免频繁创建
        - 字体缓存(_get_font)
        - 仅在布局签名变化时调用_recalc_size()
        """
        s = self.scale
        font_item = self._get_font('zone_item')
        pad_x = int(8*s)
        
        # 更新航向显示
        if snap.player_heading > 0:
            self.heading_lbl.config(text=f"HDG: {int(snap.player_heading):03d}°")
        else:
            self.heading_lbl.config(text="HDG: ---")
        
        zone_count = 0
        airport_count = 0
        
        # === 战区导航区块（根据编译开关和PanelConfig.show_zones控制）===
        if ENABLE_ZONES and PanelConfig.show_zones:
            # 使用grid显示（行号固定，顺序不会乱）
            self.zone_header_frame.grid(row=0, column=0, sticky="ew", padx=pad_x, pady=(int(6*s), int(2*s)))
            self.zone_list_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(10*s)))
            
            # v6.2: 更新统一航向带（战区+机场+被摧毁）
            if self.heading_tape is not None and snap.player_heading > 0:
                targets = []
                active_targets_info = []  # 用于生成文字信息
                
                # v6.3: 添加所有战区（目标和非目标）
                target_zone = next((z for z in snap.zones if z.is_target), None)
                for zone in snap.zones:
                    is_target = zone.is_target
                    targets.append({
                        'type': 'zone',
                        'relative': zone.relative,
                        'distance_km': zone.distance_km,
                        'is_primary': is_target,
                        'is_target': is_target  # 新增字段用于区分目标/非目标
                    })
                    # 只有目标战区才添加到active_targets_info
                    if is_target:
                        active_targets_info.append({
                            'type': 'zone',
                            'name': '战区',
                            'icon': '⊚',
                            'relative': zone.relative,
                            'distance_km': zone.distance_km,
                            'ete_str': zone.ete_str if hasattr(zone, 'ete_str') else '',
                            'color': Theme.RED
                        })
                
                # 添加被摧毁的战区
                if snap.zone_destroyed_alert and hasattr(self.game.state.zone_nav, 'destroyed_zones'):
                    for dz in self.game.state.zone_nav.destroyed_zones:
                        if hasattr(dz, 'relative'):
                            targets.append({
                                'type': 'destroyed',
                                'relative': dz.relative,
                                'distance_km': dz.distance * ZoneConfig.DISTANCE_SCALE,
                                'is_primary': False
                            })
                
                # v6.3: 添加所有友方机场
                if snap.friendly_airfield:
                    af = snap.friendly_airfield
                    is_in_front = abs(af.relative) <= 90
                    targets.append({
                        'type': 'friendly',
                        'relative': af.relative,
                        'distance_km': af.distance_km,
                        'is_primary': False,
                        'is_target': is_in_front  # 前方180°视为活动目标
                    })
                    if is_in_front:
                        active_targets_info.append({
                            'type': 'friendly',
                            'name': '友方',
                            'icon': '✈',
                            'relative': af.relative,
                            'distance_km': af.distance_km,
                            'ete_str': af.ete_str,
                            'color': Theme.BLUE
                        })
                
                # v6.3: 添加所有敌方机场
                if snap.enemy_airfields:
                    for af in snap.enemy_airfields:
                        is_in_front = abs(af.relative) <= 90
                        targets.append({
                            'type': 'enemy',
                            'relative': af.relative,
                            'distance_km': af.distance_km,
                            'is_primary': False,
                            'is_target': is_in_front  # 前方180°视为活动目标
                        })
                        if af.is_target and is_in_front:
                            active_targets_info.append({
                                'type': 'enemy',
                                'name': '敌方',
                                'icon': '✈',
                                'relative': af.relative,
                                'distance_km': af.distance_km,
                                'ete_str': af.ete_str,
                                'color': Theme.ORANGE
                            })
                
                # 更新航向带
                primary_dist = target_zone.distance_km if target_zone else 10.0
                self.heading_tape.update_tape_multi(snap.player_heading, targets, primary_dist)
                
                # 更新目标信息文字（所有前方目标）
                self._update_tape_info_labels(active_targets_info, target_zone)
                
                # v6.2.1: 根据导航模式决定是否显示集成航向带
                if PanelConfig.navigation_mode == "integrated":
                    self.heading_tape_frame.grid(row=1, column=0, sticky="ew", padx=pad_x, pady=(int(2*s), int(4*s)))
                else:
                    self.heading_tape_frame.grid_remove()
                
                # v6.2.1: 更新独立导航窗口
                if hasattr(self, 'nav_window') and self.nav_window and self.nav_window.is_visible():
                    self.nav_window.update_display(snap, targets, active_targets_info, target_zone)
            elif self.heading_tape is not None:
                self.heading_tape.clear()
                if self.tape_info_container:
                    for lbl in self._tape_info_labels:
                        lbl.pack_forget()
                # 集成模式下保持航向带容器常驻，避免瞬时无航向数据导致整行闪烁
                if PanelConfig.navigation_mode == "integrated":
                    self.heading_tape_frame.grid(row=1, column=0, sticky="ew", padx=pad_x, pady=(int(2*s), int(4*s)))
                
                # v6.2.1: 独立窗口也需要清空
                if hasattr(self, 'nav_window') and self.nav_window and self.nav_window.is_visible():
                    self.nav_window.update_display(snap, [], [], None)
            
            # 战区被摧毁警告（row=2）
            if snap.zone_destroyed_alert:
                alert_text = "💥 战区被摧毁："
                if getattr(snap, "destroyed_zone_text", ""):
                    alert_text += snap.destroyed_zone_text
                else:
                    alert_text = "💥 战区已摧毁!"
                wrap = max(int(220*s), self.zone_frame.winfo_width() - int(16*s))
                self.zone_alert_lbl.config(text=alert_text, wraplength=wrap, justify="left")
                self.zone_alert_lbl.grid(row=2, column=0, sticky="ew", padx=pad_x, pady=(0, int(4*s)))
                if snap.should_play_destroyed_sound and not self._last_zone_destroyed_alert and self._zone_sound_enabled:
                    self.sound.play(pattern="zone_destroyed")
                self._last_zone_destroyed_alert = True
            else:
                self.zone_alert_lbl.grid_remove()
                self._last_zone_destroyed_alert = False
            
            # v6.6.1: 根据导航模式选择布局
            is_compact = (PanelConfig.navigation_mode == "standalone")
            zone_layout_mode = "compact" if is_compact else "full"
            if self._zone_layout_mode != zone_layout_mode:
                # 仅在布局模式切换时清空显示池，避免每帧反复重排
                self._hide_label_pool(self._zone_label_pool)
                self._hide_label_pool(self._compact_zone_label_pool)
                self._zone_layout_mode = zone_layout_mode
            
            if is_compact:
                # 紧凑模式：显示紧凑布局，隐藏完整布局
                self.compact_nav_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(10*s)))
                self.zone_list_frame.grid_remove()
                airfields_enabled = ENABLE_AIRFIELDS and PanelConfig.show_airfields
                if airfields_enabled:
                    self.compact_airport_frame.grid(row=0, column=1, sticky="nsew", padx=(int(4*s), 0))
                    self.compact_zone_frame.grid(row=0, column=0, columnspan=1, sticky="nsew", padx=(0, int(4*s)))
                else:
                    self.compact_airport_frame.grid_remove()
                    self.compact_zone_frame.grid(row=0, column=0, columnspan=2, sticky="nsew", padx=(0, 0))
            else:
                # 完整模式：显示战区列表，隐藏紧凑布局
                self.compact_nav_frame.grid_remove()
                self.zone_list_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(10*s)))
            
            # 准备战区数据
            zone_count = len(snap.zones) if snap.zones else 1
            
            if is_compact:
                # 紧凑模式：使用紧凑战区标签池
                target_frame = self.compact_zone_list
                label_pool = self._compact_zone_label_pool
            else:
                # 完整模式：使用原战区标签池
                target_frame = self.zone_list_frame
                label_pool = self._zone_label_pool
            
            # 确保池中有足够的标签
            while len(label_pool) < zone_count:
                lbl = tk.Label(target_frame, text="", font=font_item, 
                              fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w")
                label_pool.append(lbl)
            
            # 更新并显示战区标签
            idx = 0
            if not snap.zones:
                lbl = label_pool[idx]
                lbl.config(text="无战区", fg=Theme.TEXT_MUTED)
                if not lbl.winfo_ismapped():
                    lbl.pack(fill="x")
                idx += 1
            else:
                for zone in snap.zones:
                    marker = "➤" if zone.is_target else "○"
                    dist_text = f"{zone.distance_km:.1f}km" if zone.distance_km < 10 else f"{int(zone.distance_km)}km"
                    
                    if is_compact:
                        # 紧凑格式 - 无相对角度
                        text = f"{marker} {zone.direction} {dist_text}"
                    else:
                        # 完整格式 - 带相对角度
                        rel_sign = "+" if zone.relative > 0 else ""
                        if zone.is_target:
                            rel_text = f"{rel_sign}{zone.relative:.2f}°"
                        else:
                            rel_text = f"{rel_sign}{int(zone.relative)}°"
                        text = f"{marker} {zone.direction} {dist_text}  ({rel_text})"
                    
                    fg = Theme.GREEN if zone.is_target and not snap.is_deviating else Theme.ORANGE if zone.is_target else Theme.TEXT_DIM
                    
                    lbl = label_pool[idx]
                    lbl.config(text=text, fg=fg)
                    if not lbl.winfo_ismapped():
                        lbl.pack(fill="x")
                    idx += 1
            self._hide_label_pool(label_pool, idx)
        else:
            # 隐藏战区区块（使用grid_remove保持行号）
            self.zone_header_frame.grid_remove()
            self.zone_list_frame.grid_remove()
            self.compact_nav_frame.grid_remove()
            self.zone_alert_lbl.grid_remove()
            self._hide_label_pool(self._zone_label_pool)
            self._hide_label_pool(self._compact_zone_label_pool)
            self._zone_layout_mode = None

        # === 机场导航区块（根据编译开关和PanelConfig.show_airfields控制）===
        if ENABLE_AIRFIELDS and PanelConfig.show_airfields:
            is_compact = (PanelConfig.navigation_mode == "standalone")
            airport_layout_mode = "compact" if is_compact else "full"
            if self._airport_layout_mode != airport_layout_mode:
                self._hide_label_pool(self._airport_label_pool)
                self._hide_label_pool(self._compact_airport_label_pool)
                self._airport_layout_mode = airport_layout_mode
            
            if is_compact:
                # 紧凑模式：显示两栏布局，隐藏完整布局
                self.compact_nav_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(10*s)))
                self.airport_title_lbl.grid_remove()
                self.airport_list_frame.grid_remove()
                target_frame = self.compact_airport_list
                label_pool = self._compact_airport_label_pool
            else:
                # 完整模式：显示完整布局
                self.airport_title_lbl.grid(row=4, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))
                self.airport_list_frame.grid(row=6, column=0, sticky="ew", padx=pad_x, pady=(0, int(10*s)))
                target_frame = self.airport_list_frame
                label_pool = self._airport_label_pool
            
            # 计算需要的机场标签数量
            airport_count = 0
            if snap.friendly_airfield:
                airport_count += 1
            if snap.enemy_airfields:
                airport_count += len(snap.enemy_airfields)
            if airport_count == 0:
                airport_count = 1
            
            # 确保池中有足够的标签
            while len(label_pool) < airport_count:
                lbl = tk.Label(target_frame, text="", font=font_item,
                              fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w")
                label_pool.append(lbl)
            
            # 更新并显示机场标签
            ap_idx = 0
            
            if snap.friendly_airfield:
                af = snap.friendly_airfield
                dist_text = f"{af.distance_km:.1f}km" if af.distance_km < 10 else f"{int(af.distance_km)}km"
                if is_compact:
                    text = f"🟢 {af.direction} {dist_text}"
                else:
                    rel_sign = "+" if af.relative > 0 else ""
                    rel_text = f"{rel_sign}{int(af.relative)}°"
                    text = f"🟢 ➤ {af.direction} {dist_text}  ({rel_text})"
                lbl = label_pool[ap_idx]
                lbl.config(text=text, fg=Theme.GREEN)
                if not lbl.winfo_ismapped():
                    lbl.pack(fill="x")
                ap_idx += 1
            
            if snap.enemy_airfields:
                for af in snap.enemy_airfields:
                    marker = "➤" if af.is_target else "○"
                    dist_text = f"{af.distance_km:.1f}km" if af.distance_km < 10 else f"{int(af.distance_km)}km"
                    if is_compact:
                        text = f"🔴 {af.direction} {dist_text}"
                    else:
                        rel_sign = "+" if af.relative > 0 else ""
                        rel_text = f"{rel_sign}{int(af.relative)}°"
                        text = f"🔴 {marker} {af.direction} {dist_text}  ({rel_text})"
                    fg = Theme.ORANGE if af.is_target else Theme.TEXT_DIM
                    lbl = label_pool[ap_idx]
                    lbl.config(text=text, fg=fg)
                    if not lbl.winfo_ismapped():
                        lbl.pack(fill="x")
                    ap_idx += 1
            
            if ap_idx == 0:
                lbl = label_pool[0]
                lbl.config(text="无数据", fg=Theme.TEXT_MUTED)
                if not lbl.winfo_ismapped():
                    lbl.pack(fill="x")
                ap_idx = 1
            self._hide_label_pool(label_pool, ap_idx)
        else:
            # 隐藏机场区块（使用grid_remove保持行号）
            self.airport_title_lbl.grid_remove()
            if self.airport_tape_frame:
                self.airport_tape_frame.grid_remove()
            self.airport_list_frame.grid_remove()
            self._hide_label_pool(self._airport_label_pool)
            self._hide_label_pool(self._compact_airport_label_pool)
            self._airport_layout_mode = None
        
        # === 燃油信息区块（根据编译开关和PanelConfig.show_fuel控制）===
        if ENABLE_FUEL and PanelConfig.show_fuel:
            # 使用grid显示（行号固定）- v6.1.1: 调整行号
            self.fuel_title_lbl.grid(row=7, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))
            self.fuel_info_frame.grid(row=8, column=0, sticky="ew", padx=pad_x, pady=(0, int(6*s)))
            self._update_fuel_display(snap, font_item)
        else:
            # 隐藏燃油区块（使用grid_remove保持行号）
            self.fuel_title_lbl.grid_remove()
            self.fuel_info_frame.grid_remove()
        
        # === v6.0 新增：投弹预测区块（仅在ENABLE_CCRP启用时处理）===
        if ENABLE_CCRP:
            if PanelConfig.show_bombing:
                # v6.1.1: 调整行号
                self.bombing_title_lbl.grid(row=9, column=0, sticky="ew", padx=pad_x, pady=(0, int(2*s)))
                self.bombing_info_frame.grid(row=10, column=0, sticky="ew", padx=pad_x, pady=(0, int(6*s)))
                self._update_bombing_display(snap, font_item)
            else:
                self.bombing_title_lbl.grid_remove()
                self.bombing_info_frame.grid_remove()
        
        # 智能触发尺寸重算：基于“布局签名”而非单一数量，减少漏判和误判
        layout_signature = (
            PanelConfig.navigation_mode,
            bool(ENABLE_ZONES and PanelConfig.show_zones),
            bool(ENABLE_AIRFIELDS and PanelConfig.show_airfields),
            bool(ENABLE_FUEL and PanelConfig.show_fuel),
            bool(ENABLE_CCRP and PanelConfig.show_bombing),
            bool(snap.zone_destroyed_alert),
            int(zone_count),
            int(airport_count),
            bool(self.heading_tape is not None and PanelConfig.navigation_mode == "integrated"),
        )
        if layout_signature != self._last_layout_signature:
            self._last_layout_signature = layout_signature
            return True  # 需要重算尺寸
        return False  # 不需要重算

    def _update_fuel_display(self, snap: UISnapshot, font_item):
        """更新燃油信息显示（v5.8 新增）"""
        # 燃油主信息：油量、百分比、剩余时间
        if snap.fuel_kg > 0:
            # 油量和百分比
            fuel_text = f"{int(snap.fuel_kg)}kg ({snap.fuel_percent:.0f}%)"
            
            # 剩余飞行时间
            if snap.fuel_time_remaining_str:
                fuel_text += f"  ⏱️ {snap.fuel_time_remaining_str}"
            else:
                fuel_text += "  ⏱️ 计算中..."
            
            # 根据百分比设置颜色
            if snap.fuel_percent <= FuelConfig.DANGER_PERCENT:
                fuel_color = Theme.RED
            elif snap.fuel_percent <= FuelConfig.WARNING_PERCENT:
                fuel_color = Theme.YELLOW
            else:
                fuel_color = Theme.TEXT
            
            self.fuel_main_lbl.config(text=fuel_text, fg=fuel_color)
        else:
            self.fuel_main_lbl.config(text="-- kg (--%)", fg=Theme.TEXT_MUTED)
        
        # 油耗率和高度
        if snap.fuel_rate_stable and snap.fuel_rate_kg_min > 0:
            rate_text = f"油耗 {snap.fuel_rate_kg_min:.0f}kg/min"
        else:
            rate_text = "油耗 --"
        
        if snap.altitude_m > 0:
            alt_text = f"高度 {int(snap.altitude_m)}m"
        else:
            alt_text = "高度 --"
        
        self.fuel_detail_lbl.config(text=f"{rate_text} │ {alt_text}")
        
        # 返航估算
        if snap.return_status != "unknown" and snap.return_fuel_needed_kg > 0:
            needed_text = f"需~{int(snap.return_fuel_needed_kg)}kg"
            
            # 计算返航油量占比
            if snap.fuel_initial_kg > 0:
                return_percent = (snap.return_fuel_needed_kg / snap.fuel_initial_kg) * 100
                needed_text += f" ({return_percent:.0f}%)"
            
            # 状态标识
            if snap.return_status == "safe":
                status_icon = "✅ 充足"
                return_color = Theme.GREEN
            elif snap.return_status == "warning":
                status_icon = "⚠️ 注意"
                return_color = Theme.YELLOW
            else:  # danger
                status_icon = "🔴 不足!"
                return_color = Theme.RED
            
            return_text = f"🏠 返航: {needed_text}  {status_icon}"
            self.fuel_return_lbl.config(text=return_text, fg=return_color)
        elif snap.friendly_distance_km > 0:
            self.fuel_return_lbl.config(
                text=f"🏠 返航: 距离{snap.friendly_distance_km:.0f}km (估算中...)", 
                fg=Theme.TEXT_MUTED
            )
        else:
            self.fuel_return_lbl.config(text="🏠 返航: 无机场数据", fg=Theme.TEXT_MUTED)

    def _update_bombing_display(self, snap: UISnapshot, font_item):
        """更新投弹预测信息显示（v6.0新增）"""
        self.bomb_select_lbl.config(text=f"炸弹: {BombConfig.format_bomb_name(snap.bomb_name)} (点击更换)")
        
        if snap.bombing_valid:
            bomb_range_km = snap.bomb_range_m / 1000.0
            trajectory_text = f"弹道: {bomb_range_km:.2f}km │ 飞行: {snap.bomb_flight_time:.1f}s"
            self.bomb_trajectory_lbl.config(text=trajectory_text, fg=Theme.TEXT_DIM)
            
            status = snap.release_status
            dist_m = snap.release_distance_m
            if dist_m > 1000:
                dist_str = f"{dist_m/1000:.2f}km"
            elif dist_m > 100:
                dist_str = f"{int(dist_m)}m"
            else:
                dist_str = f"{dist_m:.0f}m"
            
            if status == "ready":
                time_str = f"{snap.time_to_release:.2f}s"
                release_text = f"💣 投弹! {time_str} ({dist_str})"
                release_color = Theme.GREEN
            elif status == "approaching":
                time_str = f"{snap.time_to_release:.1f}s"
                release_text = f"⏱️ {time_str} ({dist_str})"
                release_color = Theme.YELLOW
            elif status == "passed":
                release_text = f"❌ 已飞过 {dist_str}"
                release_color = Theme.RED
            elif status == "too_far":
                time_str = f"{snap.time_to_release:.0f}s"
                release_text = f"🎯 {dist_str} ({time_str})"
                release_color = Theme.TEXT_DIM
            else:
                release_text = "⏳ 计算中..."
                release_color = Theme.TEXT_MUTED
            
            self.bomb_release_lbl.config(text=release_text, fg=release_color)
        else:
            self.bomb_trajectory_lbl.config(text="弹道: -- km │ 飞行: -- s", fg=Theme.TEXT_MUTED)
            
            if snap.on_ground:
                release_text = "🛫 请起飞"
            elif snap.altitude_m <= 50:
                release_text = "📈 请爬升"
            elif not snap.has_target:
                release_text = "🎯 无目标战区"
            else:
                release_text = "↻ 请对准目标"
            
            self.bomb_release_lbl.config(text=release_text, fg=Theme.TEXT_MUTED)

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
        snap = self.game.snapshot()
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

        # 控制面板可见性（结合PanelConfig设置和编译开关）
        # 战区/机场/燃油/投弹面板需要任一相关面板启用
        show_zone_panel = (
            (snap.phase in (Phase.ALIVE, Phase.LOSS_PENDING)) and
            (not snap.api_down) and
            (
                (ENABLE_ZONES and PanelConfig.show_zones) or
                (ENABLE_AIRFIELDS and PanelConfig.show_airfields) or
                (ENABLE_FUEL and PanelConfig.show_fuel) or
                (ENABLE_CCRP and PanelConfig.show_bombing)
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
            ENABLE_CHECKLIST and
            (snap.phase == Phase.ALIVE) and 
            (snap.on_ground or snap.landed_flash) and 
            (not snap.api_down) and
            PanelConfig.show_checklist
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
            if remain <= GameConfig.FINAL_WARNING_SEC:
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
                self.badge_gear.pack(side="left", padx=(int(UIConfig.SPACING_BADGE*self.scale), 0), after=self.badge_flight)
        else:
            if self.badge_gear.winfo_ismapped():
                self.badge_gear.pack_forget()
        
        self.status_txt.config(text=snap.status_text, fg=(Theme.YELLOW if snap.api_down else Theme.TEXT_DIM))

        # 调试信息
        if self._debug:
            debug_text = snap.diag_text
            if self._restored_state and snap.phase == Phase.ALIVE:
                debug_text += "\n🔄 已从保存状态恢复计时"
            debug_text += f"\n战区: {len(snap.zones)}个"
            if snap.has_target:
                debug_text += f" | 目标偏离: {int(snap.deviation_angle)}°"
            self.diag_lbl.config(text=debug_text)

        # 继续下一帧（基于实际耗时补偿）
        elapsed_ms = (time.monotonic() - loop_start) * 1000.0
        delay = max(0, int(UIConfig.UI_REFRESH_MS - elapsed_ms))
        if not self._stop:
            self._ui_after_id = self.root.after(delay, self._update_ui)
