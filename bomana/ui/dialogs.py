# -*- coding: utf-8 -*-
"""Dialogs and popups."""

import tkinter as tk
from tkinter import messagebox
import webbrowser
from tkinter import font as tkfont

from bomana.config import (
    ENABLE_ADVANCED_SETTINGS,
    ENABLE_ZONES,
    ENABLE_AIRFIELDS,
    ENABLE_FUEL,
    ENABLE_CHECKLIST,
    ENABLE_CCRP,
    UIConfig,
    PanelConfig,
    HotkeyConfig,
    SnapConfig,
    BombConfig,
    ChecklistConfig,
    BallisticPhysicsParams,
    AboutConfig,
    FileConfig,
    Theme,
)
from bomana.utils.file_utils import ConfigManager, resource_path
from bomana.utils.system import Win32

# Optional dependencies for images (match HAS_TRAY behavior)
try:
    from PIL import Image
    import pystray  # noqa: F401
    HAS_TRAY = True
except ImportError:
    HAS_TRAY = False

class _ScalableDialogMixin:
    """可缩放窗口通用逻辑（适配屏幕 + 动态字体缩放）"""
    def _fit_window_to_screen(self):
        """固定初始尺寸，适配屏幕，同时允许手动调整"""
        self.update_idletasks()
        req_w = self.winfo_reqwidth()
        req_h = self.winfo_reqheight()

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        min_w = max(520, int(req_w * 0.85))
        min_h = max(420, int(req_h * 0.85))

        max_w = max(min_w, screen_w - 120)
        max_h = max(min_h, screen_h - 120)

        init_w = min(max(req_w, min_w), max_w)
        init_h = min(max(req_h, min_h), max_h)

        self.geometry(f"{int(init_w)}x{int(init_h)}")
        self.minsize(int(min_w), int(min_h))
        self.maxsize(int(max_w), int(max_h))

    def _init_dynamic_scaling(self):
        """初始化窗口的动态字体缩放"""
        self.update_idletasks()
        self._scale_base_w = max(1, self.winfo_width())
        self._scale_base_h = max(1, self.winfo_height())
        self._last_scale = 1.0
        self._scale_after_id = None
        self._scaled_fonts = {}

        def collect(widget):
            for child in widget.winfo_children():
                collect(child)
            if "font" in widget.keys():
                try:
                    font_name = widget.cget("font")
                    if not font_name:
                        font_name = "TkDefaultFont"
                    base_font = tkfont.Font(font=font_name)
                    actual = base_font.actual()
                    base_size = actual.get("size", 10)
                    new_font = tkfont.Font(
                        family=actual.get("family", "Segoe UI"),
                        size=base_size,
                        weight=actual.get("weight", "normal"),
                        slant=actual.get("slant", "roman"),
                        underline=actual.get("underline", 0),
                        overstrike=actual.get("overstrike", 0),
                    )
                    widget.configure(font=new_font)
                    self._scaled_fonts[widget] = (new_font, base_size)
                except Exception:
                    pass

        collect(self)
        self.bind("<Configure>", self._on_scale_configure)

    def _on_scale_configure(self, event):
        if self._scale_after_id:
            try:
                self.after_cancel(self._scale_after_id)
            except Exception:
                pass
        self._scale_after_id = self.after(120, self._apply_dynamic_scale)

    def _apply_dynamic_scale(self):
        self._scale_after_id = None
        w = max(1, self.winfo_width())
        h = max(1, self.winfo_height())
        scale = (w / self._scale_base_w + h / self._scale_base_h) / 2.0
        scale = max(0.85, min(3.0, scale))
        if abs(scale - self._last_scale) < 0.01:
            return
        self._last_scale = scale

        if not self._scaled_fonts:
            self._init_dynamic_scaling()
            return

        for widget, (font_obj, base_size) in list(self._scaled_fonts.items()):
            try:
                size = int(abs(base_size) * scale)
                size = max(8, size)
                font_obj.configure(size=-size if base_size < 0 else size)
            except Exception:
                pass

class SettingsDialog(tk.Toplevel, _ScalableDialogMixin):
    """设置对话框
    
    使用选项卡组织设置项：
    - 显示：透明度、缩放、主题
    - 面板：各信息面板的显示开关
    - 快捷键：自定义热键绑定
    - 其他：吸附、全局热键等
    """
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("⚙️ 设置")
        self.resizable(True, True)
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        self._build_ui()
        self._fit_window_to_screen()
        self._init_dynamic_scaling()
        self._center_on_parent(parent)
    
    def _build_ui(self):
        # 主容器
        main = tk.Frame(self, bg=Theme.BG)
        main.pack(padx=15, pady=10, fill="both", expand=True)
        
        # 创建选项卡（使用Frame模拟，因为ttk样式在透明窗口中有问题）
        self.tab_buttons_frame = tk.Frame(main, bg=Theme.BG)
        self.tab_buttons_frame.pack(fill="x", pady=(0, 10))
        
        self.tabs = ["显示", "面板", "快捷键", "其他"]
        if ENABLE_CCRP:
            self.tabs.insert(2, "投弹")
        self.tab_frames = {}
        self.tab_btns = {}
        self.current_tab = "显示"
        
        # 选项卡按钮
        for tab in self.tabs:
            btn = tk.Button(
                self.tab_buttons_frame, text=tab, 
                bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=12, pady=4,
                command=lambda t=tab: self._switch_tab(t)
            )
            btn.pack(side="left", padx=2)
            self.tab_btns[tab] = btn
        
        # 选项卡内容容器
        self.content_frame = tk.Frame(main, bg=Theme.BG)
        self.content_frame.pack(fill="both", expand=True)
        
        # 创建各选项卡页面
        self._build_display_tab()
        self._build_panel_tab()
        if ENABLE_CCRP:
            self._build_ccrp_tab()
        self._build_hotkey_tab()
        self._build_other_tab()
        
        # 按钮行
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.pack(fill="x", pady=(15, 0))
        tk.Button(btn_frame, text="保存", command=self._save, 
                 bg=Theme.BLUE, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="right", padx=5)
        tk.Button(btn_frame, text="取消", command=self.destroy, 
                 bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="right", padx=5)
        
        # 显示第一个选项卡
        self._switch_tab("显示")
    
    def _switch_tab(self, tab_name: str):
        """切换选项卡"""
        # 隐藏所有页面
        for frame in self.tab_frames.values():
            frame.pack_forget()
        
        # 更新按钮样式
        for name, btn in self.tab_btns.items():
            if name == tab_name:
                btn.config(bg=Theme.BLUE)
            else:
                btn.config(bg=Theme.GRAYPILL)
        
        # 显示当前页面
        if tab_name in self.tab_frames:
            self.tab_frames[tab_name].pack(fill="both", expand=True)
        
        self.current_tab = tab_name
    
    def _build_display_tab(self):
        """构建显示设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["显示"] = frame
        
        row = 0
        
        # 透明度
        tk.Label(frame, text="窗口透明度:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        self.alpha_var = tk.IntVar(value=UIConfig.WINDOW_ALPHA)
        tk.Scale(frame, from_=100, to=255, orient="horizontal", length=180, 
                variable=self.alpha_var, bg=Theme.BG, fg=Theme.TEXT, 
                highlightthickness=0, troughcolor=Theme.BORDER, 
                activebackground=Theme.BLUE).grid(row=row, column=1, padx=10, pady=5)
        row += 1
        
        # 独立导航栏宽度
        tk.Label(frame, text="导航栏宽度:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        self.nav_width_var = tk.DoubleVar(value=PanelConfig.navigation_bar_width)
        tk.Scale(frame, from_=0.5, to=2.0, resolution=0.1, orient="horizontal", 
                length=180, variable=self.nav_width_var, bg=Theme.BG, fg=Theme.TEXT, 
                highlightthickness=0, troughcolor=Theme.BORDER, 
                activebackground=Theme.BLUE).grid(row=row, column=1, padx=10, pady=5)
        row += 1
        
        # 缩放
        tk.Label(frame, text="UI缩放:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        self.scale_var = tk.DoubleVar(value=UIConfig.UI_SCALE_MULT)
        tk.Scale(frame, from_=0.6, to=1.5, resolution=0.05, orient="horizontal", 
                length=180, variable=self.scale_var, bg=Theme.BG, fg=Theme.TEXT, 
                highlightthickness=0, troughcolor=Theme.BORDER, 
                activebackground=Theme.BLUE).grid(row=row, column=1, padx=10, pady=5)
        row += 1
        
        # 主题选择
        tk.Label(frame, text="颜色主题:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        theme_frame = tk.Frame(frame, bg=Theme.BG)
        theme_frame.grid(row=row, column=1, sticky="w", padx=10, pady=5)
        
        self.theme_var = tk.StringVar(value=Theme.get_current())
        for theme_name in Theme.get_theme_names():
            display_name = Theme.get_theme_display_name(theme_name)
            tk.Radiobutton(
                theme_frame, text=display_name, variable=self.theme_var, value=theme_name,
                bg=Theme.BG, fg=Theme.TEXT, selectcolor=Theme.GRAYPILL,
                activebackground=Theme.BG, activeforeground=Theme.TEXT,
                highlightthickness=0
            ).pack(anchor="w")
        row += 1
        
        # 主题提示
        tk.Label(frame, text="* 主题更改需要重启生效", bg=Theme.BG, fg=Theme.TEXT_MUTED,
                font=("Segoe UI", 8)).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))
    
    def _build_panel_tab(self):
        """构建面板设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["面板"] = frame
        
        # 如果高级设置被禁用，显示简化提示
        if not ENABLE_ADVANCED_SETTINGS:
            tk.Label(frame, text="面板设置在精简模式下不可用", 
                    bg=Theme.BG, fg=Theme.TEXT_MUTED).pack(anchor="w", pady=10)
            return
        
        tk.Label(frame, text="选择显示的信息面板:", bg=Theme.BG, fg=Theme.TEXT).pack(
            anchor="w", pady=(0, 10))
        
        # 面板开关（根据编译开关动态生成）
        self.panel_vars = {}
        panels = []
        
        if ENABLE_ZONES:
            panels.append(("show_zones", "🎯 战区导航", "显示战区位置和距离"))
        if ENABLE_AIRFIELDS:
            panels.append(("show_airfields", "🛫 机场导航", "显示友方/敌方机场"))
        if ENABLE_FUEL:
            panels.append(("show_fuel", "⛽ 燃油管理", "显示油量和返航估算"))
        if ENABLE_CHECKLIST:
            panels.append(("show_checklist", "✅ 出击检查", "显示起飞前检查清单"))
        
        if not panels:
            tk.Label(frame, text="所有扩展面板已在编译时禁用", 
                    bg=Theme.BG, fg=Theme.TEXT_MUTED).pack(anchor="w")
            return
        
        for key, label, desc in panels:
            var = tk.BooleanVar(value=getattr(PanelConfig, key))
            self.panel_vars[key] = var
            
            item_frame = tk.Frame(frame, bg=Theme.BG)
            item_frame.pack(fill="x", pady=3)
            
            tk.Checkbutton(
                item_frame, text=label, variable=var,
                bg=Theme.BG, fg=Theme.TEXT, selectcolor=Theme.GRAYPILL,
                activebackground=Theme.BG, activeforeground=Theme.TEXT,
                highlightthickness=0, anchor="w"
            ).pack(side="left")
            
            tk.Label(item_frame, text=f"  - {desc}", bg=Theme.BG, fg=Theme.TEXT_DIM,
                    font=("Segoe UI", 8)).pack(side="left")
    
    def _build_hotkey_tab(self):
        """构建快捷键设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["快捷键"] = frame
        
        tk.Label(frame, text="自定义快捷键绑定:", bg=Theme.BG, fg=Theme.TEXT).pack(
            anchor="w", pady=(0, 10))
        
        # 快捷键配置
        self.hotkey_vars = {}
        hotkeys = [
            ("reset", "重置计时器", HotkeyConfig.KEY_RESET),
            ("lock", "锁定/解锁", HotkeyConfig.KEY_LOCK),
            ("corner", "切换角落", HotkeyConfig.KEY_CORNER),
            ("beep", "声音开关", HotkeyConfig.KEY_BEEP),
            ("zones", "战区提示音", HotkeyConfig.KEY_ZONES),
        ]
        
        for key, label, current in hotkeys:
            row_frame = tk.Frame(frame, bg=Theme.BG)
            row_frame.pack(fill="x", pady=3)
            
            tk.Label(row_frame, text=f"{label}:", bg=Theme.BG, fg=Theme.TEXT, 
                    width=12, anchor="w").pack(side="left")
            
            var = tk.StringVar(value=current)
            self.hotkey_vars[key] = var
            
            # 下拉选择框
            menu_btn = tk.Menubutton(
                row_frame, textvariable=var, bg=Theme.GRAYPILL, fg=Theme.TEXT,
                bd=0, padx=10, pady=2, highlightthickness=1, 
                highlightbackground=Theme.BORDER, relief="flat"
            )
            menu_btn.pack(side="left", padx=(10, 0))
            
            menu = tk.Menu(menu_btn, tearoff=0, bg=Theme.GRAYPILL, fg=Theme.TEXT)
            for fkey in HotkeyConfig.AVAILABLE_KEYS:
                menu.add_command(label=fkey, command=lambda v=var, k=fkey: v.set(k))
            menu_btn["menu"] = menu
        
        # 提示
        tk.Label(frame, text="* 避免与游戏快捷键冲突\n* 更改后需要重启热键服务", 
                bg=Theme.BG, fg=Theme.TEXT_MUTED, font=("Segoe UI", 8),
                justify="left").pack(anchor="w", pady=(15, 0))

    def _build_ccrp_tab(self):
        """构建投弹预测设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["投弹"] = frame

        tk.Label(frame, text="CCRP校准参数（全局生效）:", bg=Theme.BG, fg=Theme.TEXT).pack(
            anchor="w", pady=(0, 10))

        defaults = BallisticPhysicsParams.get_default_tuning()

        grid = tk.Frame(frame, bg=Theme.BG)
        grid.pack(anchor="w")

        self.ccrp_range_mult_var = tk.DoubleVar(
            value=BallisticPhysicsParams.RANGE_CORRECTION_MULT)
        self.ccrp_time_mult_var = tk.DoubleVar(
            value=BallisticPhysicsParams.TIME_CORRECTION_MULT)

        row = 0

        tk.Label(grid, text="距离修正倍率:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        tk.Spinbox(
            grid, from_=0.6, to=1.6, increment=0.01, width=8,
            textvariable=self.ccrp_range_mult_var, bg=Theme.GRAYPILL, fg=Theme.TEXT,
            bd=0, highlightthickness=1, highlightbackground=Theme.BORDER
        ).grid(row=row, column=1, padx=10, pady=5, sticky="w")
        tk.Label(grid, text=f"默认 {defaults['range_correction_mult']:.2f}",
                 bg=Theme.BG, fg=Theme.TEXT_DIM, font=("Segoe UI", 8)).grid(
            row=row, column=2, sticky="w")
        row += 1

        tk.Label(grid, text="时间修正倍率:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        tk.Spinbox(
            grid, from_=0.6, to=1.6, increment=0.01, width=8,
            textvariable=self.ccrp_time_mult_var, bg=Theme.GRAYPILL, fg=Theme.TEXT,
            bd=0, highlightthickness=1, highlightbackground=Theme.BORDER
        ).grid(row=row, column=1, padx=10, pady=5, sticky="w")
        tk.Label(grid, text=f"默认 {defaults['time_correction_mult']:.2f}",
                 bg=Theme.BG, fg=Theme.TEXT_DIM, font=("Segoe UI", 8)).grid(
            row=row, column=2, sticky="w")

        tk.Label(
            frame,
            text="说明：倍率 > 1 代表提前投弹（预测更远/更久），< 1 代表延后投弹。",
            bg=Theme.BG, fg=Theme.TEXT_MUTED, font=("Segoe UI", 8)
        ).pack(anchor="w", pady=(10, 0))
    
    def _build_other_tab(self):
        """构建其他设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["其他"] = frame
        
        row = 0
        
        # 全局热键开关
        tk.Label(frame, text="全局热键:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        self.hotkeys_enabled_var = tk.BooleanVar(value=HotkeyConfig.GLOBAL_HOTKEYS)
        tk.Checkbutton(
            frame, text="启用全局热键", variable=self.hotkeys_enabled_var,
            bg=Theme.BG, fg=Theme.TEXT, selectcolor=Theme.GRAYPILL,
            activebackground=Theme.BG, activeforeground=Theme.TEXT,
            highlightthickness=0
        ).grid(row=row, column=1, sticky="w", padx=10, pady=5)
        row += 1
        
        # 窗口吸附
        tk.Label(frame, text="窗口吸附:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        self.snap_var = tk.BooleanVar(value=SnapConfig.enabled)
        tk.Checkbutton(
            frame, text="拖动时吸附到屏幕边缘", variable=self.snap_var,
            bg=Theme.BG, fg=Theme.TEXT, selectcolor=Theme.GRAYPILL,
            activebackground=Theme.BG, activeforeground=Theme.TEXT,
            highlightthickness=0
        ).grid(row=row, column=1, sticky="w", padx=10, pady=5)
        row += 1
        
        # 吸附距离
        tk.Label(frame, text="吸附距离:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5)
        self.snap_dist_var = tk.IntVar(value=SnapConfig.SNAP_DISTANCE)
        tk.Scale(frame, from_=5, to=50, orient="horizontal", length=150, 
                variable=self.snap_dist_var, bg=Theme.BG, fg=Theme.TEXT, 
                highlightthickness=0, troughcolor=Theme.BORDER, 
                activebackground=Theme.BLUE).grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1
        
        # 分隔线
        tk.Frame(frame, bg=Theme.SEPARATOR, height=1).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=10)
        row += 1
        
        # 重置按钮
        tk.Button(frame, text="重置所有设置为默认", command=self._reset_defaults,
                 bg=Theme.YELLOW, fg=Theme.BG, bd=0, padx=15, pady=5).grid(
            row=row, column=0, columnspan=2, pady=10)
    
    def _reset_defaults(self):
        """重置为默认设置"""
        if messagebox.askyesno("确认", "确定要重置所有设置为默认值吗？", parent=self):
            # 重置显示设置
            self.alpha_var.set(210)
            self.nav_width_var.set(1.0)
            self.scale_var.set(0.85)
            self.theme_var.set("dark")
            
            # 重置面板设置
            for key in self.panel_vars:
                self.panel_vars[key].set(True)
            
            # 重置快捷键
            defaults = {"reset": "F7", "lock": "F8", "corner": "F9", "beep": "F10", "zones": "F11"}
            for key, val in defaults.items():
                self.hotkey_vars[key].set(val)
            
            # 重置其他设置
            self.hotkeys_enabled_var.set(True)
            self.snap_var.set(True)
            self.snap_dist_var.set(20)

            if ENABLE_CCRP and hasattr(self, "ccrp_range_mult_var"):
                defaults = BallisticPhysicsParams.get_default_tuning()
                self.ccrp_range_mult_var.set(defaults["range_correction_mult"])
                self.ccrp_time_mult_var.set(defaults["time_correction_mult"])
    
    def _center_on_parent(self, parent):
        """居中显示"""
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _save(self):
        """保存所有设置"""
        # 收集设置值
        config = ConfigManager.load()
        
        # 显示设置
        UIConfig.WINDOW_ALPHA = self.alpha_var.get()
        PanelConfig.navigation_bar_width = self.nav_width_var.get()
        UIConfig.UI_SCALE_MULT = self.scale_var.get()
        new_theme = self.theme_var.get()
        old_theme = Theme.get_current()
        
        config['alpha'] = UIConfig.WINDOW_ALPHA
        config['scale'] = UIConfig.UI_SCALE_MULT
        config['theme'] = new_theme
        
        # 面板设置
        panel_config = {}
        for key, var in self.panel_vars.items():
            setattr(PanelConfig, key, var.get())
            panel_config[key] = var.get()
        config['panels'] = panel_config
        
        # 快捷键设置
        old_hotkeys_enabled = HotkeyConfig.GLOBAL_HOTKEYS
        HotkeyConfig.GLOBAL_HOTKEYS = self.hotkeys_enabled_var.get()
        
        hotkey_bindings = {}
        for key, var in self.hotkey_vars.items():
            hotkey_bindings[key] = var.get()
        HotkeyConfig.set_bindings(hotkey_bindings)
        
        config['global_hotkeys'] = HotkeyConfig.GLOBAL_HOTKEYS
        config['hotkey_bindings'] = hotkey_bindings
        
        # 吸附设置
        SnapConfig.enabled = self.snap_var.get()
        SnapConfig.SNAP_DISTANCE = self.snap_dist_var.get()
        config['snap_enabled'] = SnapConfig.enabled
        config['snap_distance'] = SnapConfig.SNAP_DISTANCE

        # 投弹预测调参（仅在CCRP启用时保存）
        if ENABLE_CCRP and hasattr(self, "ccrp_range_mult_var"):
            tuning = {
                "range_correction_mult": self.ccrp_range_mult_var.get(),
                "time_correction_mult": self.ccrp_time_mult_var.get(),
            }
            BallisticPhysicsParams.apply_user_tuning(tuning)
            config['ccrp_tuning'] = BallisticPhysicsParams.get_user_tuning()
        
        # 保存配置
        ConfigManager.save(config)

        # 刷新托盘菜单勾选状态
        if hasattr(self.app, "_refresh_tray"):
            self.app._refresh_tray()
        
        # 应用透明度
        Win32.setup_window(self.app.hwnd, self.app._locked, UIConfig.WINDOW_ALPHA)
        
        # 重启热键服务（如果需要）
        need_restart_hotkeys = (
            old_hotkeys_enabled != HotkeyConfig.GLOBAL_HOTKEYS or
            hotkey_bindings != HotkeyConfig.get_bindings()
        )
        if need_restart_hotkeys:
            if hasattr(self.app, '_ghk') and self.app._ghk:
                self.app._ghk.stop()
            if HotkeyConfig.GLOBAL_HOTKEYS:
                self.app._init_global_hotkeys()
                if hasattr(self.app, '_ghk') and self.app._ghk:
                    self.app._ghk.start()
            # 刷新提示文本（主窗口 + 导航窗口）
            self.app._update_hint()
            if hasattr(self.app, 'nav_window') and self.app.nav_window:
                self.app.nav_window.update_hint_text()
        
        # 应用主题（需要重启）
        theme_changed = new_theme != old_theme
        Theme.apply(new_theme)
        
        if theme_changed:
            messagebox.showinfo("设置", "设置已保存\n主题更改需要重启应用生效", parent=self)
        else:
            messagebox.showinfo("设置", "设置已保存", parent=self)
        
        self.destroy()


class ChecklistEditor(tk.Toplevel, _ScalableDialogMixin):
    """检查清单编辑器
    
    允许用户自定义起飞前的检查项目。
    """
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("编辑检查清单")
        self.resizable(True, True)
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        self._build_ui()
        self._fit_window_to_screen()
        self._init_dynamic_scaling()
        self._center_on_parent(parent)
    
    def _build_ui(self):
        main = tk.Frame(self, bg=Theme.BG)
        main.pack(padx=20, pady=15, fill="both", expand=True)
        
        tk.Label(main, text=f"每行一个检查项（最多{ChecklistConfig.MAX_ITEMS}项）:", 
                bg=Theme.BG, fg=Theme.TEXT, anchor="w").pack(fill="x", pady=(0, 5))
        
        self.text = tk.Text(main, width=40, height=10, bg=Theme.GRAYPILL, fg=Theme.TEXT, 
                           insertbackground=Theme.TEXT, bd=0, highlightthickness=1, 
                           highlightbackground=Theme.BORDER)
        self.text.pack(fill="both", expand=True)
        
        current_items = "\n".join(self.app.chk_items)
        self.text.insert("1.0", current_items)
        
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.pack(pady=(10, 0))
        tk.Button(btn_frame, text="保存", command=self._save, 
                 bg=Theme.BLUE, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="left", padx=5)
        tk.Button(btn_frame, text="恢复默认", command=self._restore_default, 
                 bg=Theme.YELLOW, fg=Theme.TEXT, bd=0, padx=15, pady=5).pack(side="left", padx=5)
        tk.Button(btn_frame, text="取消", command=self.destroy, 
                 bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=5).pack(side="left", padx=5)
    
    def _center_on_parent(self, parent):
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _save(self):
        """保存检查清单"""
        content = self.text.get("1.0", "end-1c")
        items = [line.strip() for line in content.split("\n") if line.strip()]
        
        if not items:
            messagebox.showwarning("警告", "检查清单不能为空", parent=self)
            return
        if len(items) > ChecklistConfig.MAX_ITEMS:
            messagebox.showwarning("警告", f"检查项数量不能超过{ChecklistConfig.MAX_ITEMS}个", parent=self)
            return
        
        config = ConfigManager.load()
        config['checklist_items'] = items
        ConfigManager.save(config)
        self.app.chk_items = items
        self.app._rebuild_checklist()
        
        messagebox.showinfo("成功", "检查清单已保存", parent=self)
        self.destroy()
    
    def _restore_default(self):
        """恢复默认清单"""
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(ChecklistConfig.DEFAULT_ITEMS))


class BombSelectorDialog(tk.Toplevel, _ScalableDialogMixin):
    """炸弹选择对话框"""
    
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.selected_bomb = BombConfig.selected_bomb
        self._current_category = None
        
        self.title("选择炸弹")
        self.configure(bg=Theme.BG)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()
        
        main = tk.Frame(self, bg=Theme.BG, padx=15, pady=15)
        main.pack(fill="both", expand=True)
        
        # 搜索框
        search_frame = tk.Frame(main, bg=Theme.BG)
        search_frame.pack(fill="x", pady=(0, 10))
        
        self.search_var = tk.StringVar()
        self.search_var.trace("w", lambda *args: self._on_search())
        self.search_entry = tk.Entry(
            search_frame, textvariable=self.search_var,
            bg=Theme.GRAYPILL, fg=Theme.TEXT_MUTED, bd=0, highlightthickness=1,
            highlightbackground=Theme.BORDER, font=("Segoe UI", 10)
        )
        self.search_entry.pack(fill="x", ipady=5)
        self.search_entry.insert(0, "搜索...")
        self.search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)
        
        # 分类按钮
        cat_frame = tk.Frame(main, bg=Theme.BG)
        cat_frame.pack(fill="x", pady=(0, 10))
        
        self.cat_buttons = {}
        categories = ['全部'] + BombConfig.get_categories()
        for cat in categories:
            btn = tk.Button(
                cat_frame, text=cat, 
                bg=Theme.GRAYPILL if cat != '全部' else Theme.BLUE,
                fg=Theme.TEXT, bd=0, padx=8, pady=4, font=("Segoe UI", 9),
                command=lambda c=cat: self._filter_category(c)
            )
            btn.pack(side="left", padx=2)
            self.cat_buttons[cat] = btn
        
        # 列表区域
        list_frame = tk.Frame(main, bg=Theme.GRAYPILL)
        list_frame.pack(fill="both", expand=True)
        
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        
        self.listbox = tk.Listbox(
            list_frame, width=55, height=20,
            bg=Theme.GRAYPILL, fg=Theme.TEXT, selectbackground=Theme.BLUE,
            selectforeground=Theme.TEXT, bd=0, highlightthickness=1,
            highlightbackground=Theme.BORDER, yscrollcommand=scrollbar.set, 
            font=("Consolas", 9)
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<Double-Button-1>", lambda e: self._select())
        
        # 统计
        self.stats_lbl = tk.Label(
            main, text="", bg=Theme.BG, fg=Theme.TEXT_DIM, 
            font=("Segoe UI", 9), anchor="w"
        )
        self.stats_lbl.pack(fill="x", pady=(5, 0))
        
        # 按钮
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.pack(fill="x", pady=(10, 0))
        tk.Button(
            btn_frame, text="确定", command=self._select, 
            bg=Theme.BLUE, fg=Theme.TEXT, bd=0, padx=20, pady=5
        ).pack(side="right", padx=5)
        tk.Button(
            btn_frame, text="取消", command=self.destroy, 
            bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=5
        ).pack(side="right", padx=5)
        
        self._populate_list()
        self._fit_window_to_screen()
        self._init_dynamic_scaling()
        self._center_on_parent(parent)
    
    def _on_search_focus_in(self, event):
        if self.search_entry.get() == "搜索...":
            self.search_entry.delete(0, "end")
            self.search_entry.config(fg=Theme.TEXT)
    
    def _on_search_focus_out(self, event):
        if not self.search_entry.get():
            self.search_entry.insert(0, "搜索...")
            self.search_entry.config(fg=Theme.TEXT_MUTED)
    
    def _on_search(self):
        if not hasattr(self, "listbox"):
            return
        query = self.search_var.get()
        if query == "搜索...":
            query = ""
        self._populate_list(query)
    
    def _filter_category(self, category):
        self._current_category = None if category == '全部' else category
        self.search_var.set("")
        for cat, btn in self.cat_buttons.items():
            btn.config(bg=Theme.BLUE if cat == category else Theme.GRAYPILL)
        self._populate_list()
    
    def _populate_list(self, search_query: str = ""):
        if not hasattr(self, "listbox"):
            return
        self.listbox.delete(0, "end")
        
        if search_query and search_query != "搜索...":
            bombs = BombConfig.search_bombs(search_query, limit=100)
            show_categories = False
        elif self._current_category:
            bombs = BombConfig.get_bombs_by_category(self._current_category)
            show_categories = False
        else:
            bombs = None
            show_categories = True
        
        current_index, select_index, total_count = 0, 0, 0
        
        if show_categories:
            for category in BombConfig.get_categories():
                cat_bombs = BombConfig.get_bombs_by_category(category)
                if not cat_bombs:
                    continue
                self.listbox.insert("end", f"━━━ {category} ({len(cat_bombs)}种) ━━━")
                self.listbox.itemconfig(current_index, fg=Theme.YELLOW)
                current_index += 1
                
                for bomb_id in cat_bombs:
                    bomb_data = BombConfig.get_bomb_data(bomb_id)
                    if bomb_data:
                        mass = bomb_data['mass']
                        mass_str = f"{mass/1000:.1f}t" if mass >= 1000 else f"{int(mass)}kg"
                        text = f"  {bomb_id} ({mass_str}, Cx={bomb_data.get('drag_cx', 0.04):.4f})"
                    else:
                        text = f"  {bomb_id}"
                    
                    self.listbox.insert("end", text)
                    if bomb_id == self.selected_bomb:
                        select_index = current_index
                        self.listbox.itemconfig(current_index, fg=Theme.GREEN)
                    current_index += 1
                    total_count += 1
        else:
            for bomb_id in bombs:
                bomb_data = BombConfig.get_bomb_data(bomb_id)
                if bomb_data:
                    mass = bomb_data['mass']
                    mass_str = f"{mass/1000:.1f}t" if mass >= 1000 else f"{int(mass)}kg"
                    cat = bomb_data.get('category', '?')
                    text = f"{bomb_id} ({mass_str}, Cx={bomb_data.get('drag_cx', 0.04):.4f}) [{cat}]"
                else:
                    text = bomb_id
                
                self.listbox.insert("end", text)
                if bomb_id == self.selected_bomb:
                    select_index = current_index
                    self.listbox.itemconfig(current_index, fg=Theme.GREEN)
                current_index += 1
                total_count += 1
        
        if select_index > 0:
            self.listbox.selection_set(select_index)
            self.listbox.see(select_index)
        
        self.stats_lbl.config(text=f"显示 {total_count} / {len(BombConfig.BOMB_DATABASE)} 种炸弹")
    
    def _center_on_parent(self, parent):
        self.update_idletasks()
        x = parent.winfo_x() + (parent.winfo_width() - self.winfo_width()) // 2
        y = parent.winfo_y() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f"+{x}+{y}")
    
    def _select(self):
        selection = self.listbox.curselection()
        if not selection:
            return
        
        text = self.listbox.get(selection[0]).strip()
        if text.startswith("━━"):
            return
        
        bomb_id = text.split(" (")[0].strip()
        
        if BombConfig.get_bomb_data(bomb_id):
            BombConfig.selected_bomb = bomb_id
            config = ConfigManager.load()
            config['selected_bomb'] = bomb_id
            ConfigManager.save(config)
            
            if hasattr(self.app, 'bomb_select_lbl'):
                self.app.bomb_select_lbl.config(
                    text=f"炸弹: {BombConfig.format_bomb_name(bomb_id)} (点击更换)"
                )
            
            self.destroy()


class AboutDialog(tk.Toplevel, _ScalableDialogMixin):
    """关于对话框"""
    def __init__(self, parent, app):
        super().__init__(parent)
        self.app = app
        self.title("关于 Bomana")
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        self._images = []
        
        self._build_ui()
        
        # 让窗口自适应内容大小
        self.update_idletasks()
        
        # 获取内容实际需要的尺寸
        req_width = self.winfo_reqwidth()
        req_height = self.winfo_reqheight()
        
        # 设置最小尺寸，确保不会太小
        min_width = max(800, req_width)
        min_height = max(1200, req_height)
        
        # 限制最大尺寸不超过屏幕
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        final_width = min(min_width, screen_w - 100)
        final_height = min(min_height, screen_h - 100)
        
        self.geometry(f"{final_width}x{final_height}")
        self.minsize(400, 500)
        self.resizable(True, True)  # 允许用户调整大小
        
        self._init_dynamic_scaling()
        self._center_on_parent(parent)
    
    def _build_ui(self):
        # 创建可滚动的画布（内容太多时可以滚动）
        canvas = tk.Canvas(self, bg=Theme.BG, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        
        main = tk.Frame(canvas, bg=Theme.BG)
        
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        canvas_frame = canvas.create_window((0, 0), window=main, anchor="nw")
        
        def configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # 让内容宽度跟随窗口
            canvas.itemconfig(canvas_frame, width=event.width)
        
        def configure_canvas(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        
        canvas.bind("<Configure>", configure_scroll)
        main.bind("<Configure>", configure_canvas)
        
        # 鼠标滚轮支持
        def on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        canvas.bind_all("<MouseWheel>", on_mousewheel)
        
        # 内容区域，增大padding
        content = tk.Frame(main, bg=Theme.BG)
        content.pack(fill="both", expand=True, padx=30, pady=25)
        
        # === 软件标题 ===
        title_frame = tk.Frame(content, bg=Theme.BG)
        title_frame.pack(fill="x", pady=(0, 15))
        
        try:
            icon_path = resource_path(FileConfig.ICON_FILE)
            if HAS_TRAY:
                from PIL import Image, ImageTk
                img = Image.open(icon_path).convert("RGBA")
                img = img.resize((64, 64), Image.Resampling.LANCZOS)  # 更大的图标
                self._app_icon = ImageTk.PhotoImage(img)
                icon_lbl = tk.Label(title_frame, image=self._app_icon, bg=Theme.BG)
                icon_lbl.pack(side="left", padx=(0, 15))
        except Exception:
            pass
        
        title_text_frame = tk.Frame(title_frame, bg=Theme.BG)
        title_text_frame.pack(side="left", fill="both", expand=True)
        
        tk.Label(
            title_text_frame,
            text=f"{AboutConfig.APP_NAME} v{AboutConfig.VERSION}",
            font=("Segoe UI", 20, "bold"),  # 更大字体
            fg=Theme.TEXT, bg=Theme.BG, anchor="w"
        ).pack(anchor="w")
        
        tk.Label(
            title_text_frame,
            text=AboutConfig.APP_NAME_CN,
            font=("Segoe UI", 12),  # 更大字体
            fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="w"
        ).pack(anchor="w", pady=(5, 0))
        
        # === 分隔线 ===
        tk.Frame(content, bg=Theme.SEPARATOR, height=1).pack(fill="x", pady=15)
        
        # === 项目说明 ===
        description = """本软件是一个用于战雷全真模式的辅助计时工具，
帮助玩家管理15分钟的复活周期。

核心特性：
• 仅使用官方8111接口，安全合规
• 自动检测出生/死亡/着陆状态
• 战区导航和燃油管理
• 可自定义的起飞检查清单

本软件完全开源免费，欢迎贡献代码！"""
        
        tk.Label(
            content, text=description,
            font=("Segoe UI", 11),  # 更大字体
            fg=Theme.TEXT_DIM, bg=Theme.BG,
            justify="left", anchor="w"
        ).pack(anchor="w")
        
        # === GitHub 链接 ===
        if AboutConfig.GITHUB_URL:
            link_frame = tk.Frame(content, bg=Theme.BG)
            link_frame.pack(fill="x", pady=(15, 0))
            
            tk.Label(
                link_frame, text="📦 项目主页：",
                font=("Segoe UI", 11),
                fg=Theme.TEXT_DIM, bg=Theme.BG
            ).pack(side="left")
            
            github_btn = tk.Label(
                link_frame, text=AboutConfig.GITHUB_URL,
                font=("Segoe UI", 11, "underline"),
                fg=Theme.BLUE, bg=Theme.BG, cursor="hand2"
            )
            github_btn.pack(side="left")
            github_btn.bind("<Button-1>", lambda e: self._open_url(AboutConfig.GITHUB_URL))
        
        # === 分隔线 ===
        tk.Frame(content, bg=Theme.SEPARATOR, height=1).pack(fill="x", pady=15)
        
        # === 赞助区域 ===
        tk.Label(
            content, text="❤️ 支持作者",
            font=("Segoe UI", 14, "bold"),  # 更大字体
            fg=Theme.TEXT, bg=Theme.BG, anchor="w"
        ).pack(anchor="w", pady=(0, 10))
        
        tk.Label(
            content, text="如果这个工具对你有帮助，欢迎请作者喝杯咖啡~",
            font=("Segoe UI", 11),
            fg=Theme.TEXT_DIM, bg=Theme.BG, anchor="w"
        ).pack(anchor="w", pady=(0, 15))
        
        # 赞助图片/链接区域
        sponsor_frame = tk.Frame(content, bg=Theme.BG)
        sponsor_frame.pack(fill="x", pady=(0, 15))
        
        for name, url, img_file in AboutConfig.SPONSOR_LINKS:
            self._add_sponsor_item(sponsor_frame, name, url, img_file)
        
        # === 分隔线 ===
        tk.Frame(content, bg=Theme.SEPARATOR, height=1).pack(fill="x", pady=15)
        
        # === 隐私政策 ===

        tk.Label(

            content, text="🔒 隐私说明",

            font=("Segoe UI", 14, "bold"),

            fg=Theme.TEXT, bg=Theme.BG, anchor="w"

        ).pack(anchor="w", pady=(0, 10))



        privacy_desc = """本应用收集匿名DAU数据（设备ID、版本号等）用于统计分析，不涉及个人隐私。



数据特点：

• 完全匿名化（SHA256加密，不可逆向）

• 仅统计必需（不收集IP、账号、邮箱等）

• 代码开源可审查

• 用户可禁用（见隐私政策详情）"""



        tk.Label(

            content, text=privacy_desc,

            font=("Segoe UI", 10),

            fg=Theme.TEXT_DIM, bg=Theme.BG,

            justify="left", anchor="w"

        ).pack(anchor="w", pady=(0, 10))



        privacy_link = tk.Label(

            content, text="查看完整隐私政策 →",

            font=("Segoe UI", 10, "underline"),

            fg=Theme.BLUE, bg=Theme.BG, cursor="hand2", anchor="w"

        )

        privacy_link.pack(anchor="w", pady=(0, 15))

        privacy_link.bind(

            "<Button-1>",

            lambda e: self._open_url(f"{AboutConfig.GITHUB_URL}/blob/main/PRIVACY.md")

        )

        

        # === 分隔线 ===

        tk.Frame(content, bg=Theme.SEPARATOR, height=1).pack(fill="x", pady=15)

        

        # === 版权声明 ===
        copyright_text = f"""作者：{AboutConfig.AUTHOR}

MIT License
Copyright © 2024-2026 {AboutConfig.AUTHOR}

Gaijin Entertainment AG及其子公司拥有《战争雷霆》及相关商标的所有权
本软件与Gaijin Entertainment AG无任何关联
注意！滥用本软件可能违反Gaijin用户守则
使用本软件的风险由用户自行承担"""
        
        tk.Label(
            content, text=copyright_text,
            font=("Segoe UI", 10),  # 更大字体
            fg=Theme.TEXT_MUTED, bg=Theme.BG,
            justify="left", anchor="w"
        ).pack(anchor="w", pady=(0, 15))
        
        # === 关闭按钮 ===
        tk.Button(
            content, text="关闭", command=self._close,
            font=("Segoe UI", 11),
            bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=40, pady=8
        ).pack(pady=(10, 0))
    
    def _add_sponsor_item(self, parent, name: str, url: str, img_file: str):
        item_frame = tk.Frame(parent, bg=Theme.BG)
        item_frame.pack(side="left", padx=(0, 20), pady=10)
        
        img_loaded = False
        if img_file and HAS_TRAY:
            try:
                from PIL import Image, ImageTk
                img_path = resource_path(img_file)
                img = Image.open(img_path).convert("RGBA")
                
                # 更大的图片尺寸
                target_width = AboutConfig.SPONSOR_IMAGE_WIDTH
                ratio = target_width / img.width
                new_height = int(img.height * ratio)
                img = img.resize((target_width, new_height), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(img)
                self._images.append(photo)
                
                img_lbl = tk.Label(item_frame, image=photo, bg=Theme.BG, cursor="hand2" if url else "")
                img_lbl.pack()
                if url:
                    img_lbl.bind("<Button-1>", lambda e, u=url: self._open_url(u))
                
                tk.Label(
                    item_frame, text=name,
                    font=("Segoe UI", 10),
                    fg=Theme.TEXT_DIM, bg=Theme.BG
                ).pack(pady=(5, 0))
                img_loaded = True
            except Exception:
                pass
        
        if not img_loaded:
            btn = tk.Button(
                item_frame, text=f"💝 {name}",
                font=("Segoe UI", 11),
                bg=Theme.GRAYPILL, fg=Theme.TEXT, bd=0, padx=20, pady=10,
                cursor="hand2" if url else ""
            )
            btn.pack()
            if url:
                btn.config(command=lambda u=url: self._open_url(u))
    
    def _open_url(self, url: str):
        if url:
            try:
                webbrowser.open(url)
            except Exception:
                pass
    
    def _close(self):
        # 解绑鼠标滚轮事件，防止关闭后影响其他窗口
        try:
            self.unbind_all("<MouseWheel>")
        except:
            pass
        self.destroy()
    
    def _center_on_parent(self, parent):
        self.update_idletasks()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        px = parent.winfo_x()
        py = parent.winfo_y()
        w = self.winfo_width()
        h = self.winfo_height()
        x = px + (pw - w) // 2
        y = py + (ph - h) // 2
        # 确保不超出屏幕
        x = max(0, x)
        y = max(0, y)
        self.geometry(f"+{x}+{y}")
