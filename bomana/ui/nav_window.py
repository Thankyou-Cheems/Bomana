# -*- coding: utf-8 -*-
"""Standalone navigation window."""

import ctypes
import tkinter as tk

from bomana.config import UIConfig, Theme, HotkeyConfig, PanelConfig, ZoneConfig
from bomana.utils.math_utils import (
    calculate_heading_tape_scale,
    get_cdi_tolerance,
    calculate_zone_turn_indicator,
    calculate_zone_status,
    calculate_airfield_turn_indicator,
    calculate_airfield_status,
    format_distance_ete,
)
from bomana.ui.widgets import HeadingTape
from bomana.utils.system import Win32

# ============================================================================
# 独立导航窗口
# ============================================================================

class NavigationWindow:
    """独立导航条窗口
    
    v6.2.1新增：可拖动的独立导航窗口，方便放置在屏幕任意位置
    
    特性:
    - 无边框透明窗口
    - 支持拖动
    - 关闭时隐藏而非退出
    - 位置自动保存
    - 与主窗口数据同步
    """
    
    def __init__(self, parent_app):
        """初始化独立导航窗口
        
        Args:
            parent_app: 主App实例，用于访问游戏数据和配置
        """
        self.app = parent_app
        self.root = parent_app.root
        self.scale = parent_app.scale
        self._visible = False
        self._drag_data = {"x": 0, "y": 0}
        
        # 创建顶层窗口
        # 定义透明键颜色（用于背景透明，内容不透明）
        self._transparent_color = "#010101"  # 接近黑色但不影响正常UI
        
        self.window = tk.Toplevel(self.root)
        self.window.title("导航条")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        # 窗口背景设置为透明键颜色
        self.window.configure(bg=self._transparent_color)
        
        # 初始隐藏
        self.window.withdraw()
        
        # 获取窗口句柄
        self.window.update_idletasks()  # 确保窗口已创建
        # v6.6.3: 兼容 overrideredirect 的真实句柄获取
        internal_id = self.window.winfo_id()
        self.hwnd = ctypes.windll.user32.GetParent(internal_id) or int(internal_id)
        
        # 使用Win32 API设置分层窗口：背景透明，内容保持不透明 + 点击穿透
        self.apply_window_styles(click_through=self.app._locked, alpha=UIConfig.WINDOW_ALPHA)
        
        # 初始化UI
        self._init_ui()
        
        # 绑定事件
        self._init_bindings()
        
        # 恢复位置
        self._restore_position()
    
    def apply_window_styles(self, click_through: bool, alpha: int):
        """设置分层窗口属性 + 点击穿透
        
        使用透明键颜色实现背景透明、内容不透明的效果，
        同时根据锁定状态启用点击穿透。
        """
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_NOACTIVATE = 0x08000000
        WS_EX_TOPMOST = 0x00000008
        WS_EX_TOOLWINDOW = 0x00000080
        LWA_COLORKEY = 0x1
        LWA_ALPHA = 0x2
        
        try:
            user32 = ctypes.windll.user32
            # 获取当前样式并添加分层窗口样式
            style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
            style |= (WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW)
            if click_through:
                style |= (WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            else:
                style &= ~(WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, style)
            
            # 将透明键颜色转换为COLORREF (BGR格式)
            color_hex = self._transparent_color.lstrip('#')
            r, g, b = int(color_hex[0:2], 16), int(color_hex[2:4], 16), int(color_hex[4:6], 16)
            colorref = r | (g << 8) | (b << 16)
            
            # 同时应用透明键和整体透明度
            alpha = int(alpha)
            user32.SetLayeredWindowAttributes(self.hwnd, colorref, alpha, LWA_COLORKEY | LWA_ALPHA)
        except (OSError, AttributeError):
            # 降级：使用Tkinter的alpha属性
            self.window.attributes("-alpha", alpha / 255.0)
    
    def update_transparency(self):
        """更新窗口透明度（响应透明度配置变化）"""
        self.apply_window_styles(click_through=self.app._locked, alpha=UIConfig.WINDOW_ALPHA)
    
    def _init_ui(self):
        """初始化导航条UI
        
        v6.6.1: 紧凑布局 - 清晰图例，保留状态行
        """
        s = self.scale
        pad = int(4 * s)
        
        # 主框架
        self.main_frame = tk.Frame(self.window, bg=Theme.GRAYPILL)
        self.main_frame.pack(fill="both", expand=True, padx=2, pady=2)
        
        # 内容区域
        self.content_frame = tk.Frame(self.main_frame, bg=Theme.GRAYPILL)
        self.content_frame.pack(fill="both", expand=True)
        
        # v6.6.1: 紧凑标题栏（标题 + 图例 + 提示 + 容差 + HDG + 关闭）
        self.title_bar = tk.Frame(self.content_frame, bg=Theme.GRAYPILL)
        self.title_bar.pack(fill="x", padx=pad, pady=(pad, 0))
        
        font_title = (UIConfig.FONT_ZONE_TITLE[0], int(UIConfig.FONT_ZONE_TITLE[1]*s*0.85))
        legend_font = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s*0.7))
        hint_font = (UIConfig.FONT_HINT[0], int(UIConfig.FONT_HINT[1]*s*0.7))
        
        # 左侧：标题 🎯 导航
        self.title_lbl = tk.Label(
            self.title_bar, text="🎯 导航", font=font_title,
            fg=Theme.TEXT, bg=Theme.GRAYPILL, anchor="w"
        )
        self.title_lbl.pack(side="left")
        
        # 图例（带文字说明，更清晰）
        legend_frame = tk.Frame(self.title_bar, bg=Theme.GRAYPILL)
        legend_frame.pack(side="left", padx=(int(6*s), 0))
        legend_kwargs = {
            "font": legend_font,
            "bg": Theme.GRAYPILL,
            "anchor": "center",
            "height": 1,
            "pady": 0,
        }
        tk.Label(legend_frame, text="⊚战区", fg=Theme.RED, **legend_kwargs).pack(side="left")
        tk.Label(legend_frame, text="✈友", fg=Theme.BLUE, **legend_kwargs).pack(side="left", padx=(int(4*s), 0))
        tk.Label(legend_frame, text="✈敌", fg=Theme.ORANGE, **legend_kwargs).pack(side="left", padx=(int(4*s), 0))
        
        # 解锁提示（动态引用按键配置）
        self.hint_lbl = tk.Label(
            self.title_bar, text=f"{HotkeyConfig.KEY_LOCK}解锁后可拖动", font=hint_font,
            fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w"
        )
        self.hint_lbl.pack(side="left", padx=(int(8*s), 0))
        
        # 右侧：关闭按钮
        self.close_btn = tk.Label(
            self.title_bar, text="✕", font=font_title,
            fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, cursor="hand2"
        )
        self.close_btn.pack(side="right")
        self.close_btn.bind("<Button-1>", lambda e: self.hide())
        self.close_btn.bind("<Enter>", lambda e: self.close_btn.config(fg=Theme.RED))
        self.close_btn.bind("<Leave>", lambda e: self.close_btn.config(fg=Theme.TEXT_MUTED))
        
        # 航向显示
        font_hdg = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s*0.9))
        self.heading_lbl = tk.Label(
            self.title_bar, text="---°", font=font_hdg,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="e"
        )
        self.heading_lbl.pack(side="right", padx=(0, int(4*s)))
        
        # 容差显示
        self.zone_tolerance_legend = tk.Label(
            self.title_bar, text="", font=hint_font,
            fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="center"
        )
        self.zone_tolerance_legend.pack(side="right", padx=(0, int(4*s)))
        
        # 航向带容器
        self.tape_frame = tk.Frame(self.content_frame, bg=Theme.GRAYPILL)
        self.tape_frame.pack(fill="x", padx=pad, pady=(int(2*s), 0))
        
        # 航向带
        width_mult = PanelConfig.navigation_bar_width
        tape_width = int(ZoneConfig.HEADING_TAPE_WIDTH * s * 1.2 * width_mult)
        tape_height = int(ZoneConfig.HEADING_TAPE_HEIGHT * s)
        self.heading_tape = HeadingTape(
            self.tape_frame,
            width=tape_width,
            height=tape_height
        )
        self.heading_tape.pack(fill="x", expand=True)
        
        # v6.6.1: 保留状态行（显示偏航和ETE信息）
        status_font = (UIConfig.FONT_ZONE_ITEM[0], int(UIConfig.FONT_ZONE_ITEM[1]*s*0.9))
        
        # 战区状态行
        self.zone_row = tk.Frame(self.content_frame, bg=Theme.GRAYPILL)
        # 初始不pack，由update_display控制
        
        self._zone_row_left_spacer = tk.Frame(self.zone_row, bg=Theme.GRAYPILL)
        self._zone_row_left_spacer.pack(side="left", fill="x", expand=True)
        
        self._zone_row_center = tk.Frame(self.zone_row, bg=Theme.GRAYPILL)
        self._zone_row_center.pack(side="left")
        
        self._zone_row_right_spacer = tk.Frame(self.zone_row, bg=Theme.GRAYPILL)
        self._zone_row_right_spacer.pack(side="left", fill="x", expand=True)
        
        self.zone_label = tk.Label(
            self._zone_row_center, text="⊚战区:", font=status_font,
            fg=Theme.RED, bg=Theme.GRAYPILL, anchor="w"
        )
        self.zone_label.pack(side="left")
        
        self.zone_turn = tk.Label(
            self._zone_row_center, text="", font=status_font,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.zone_turn.pack(side="left", padx=(int(4*s), 0))
        
        self.zone_status = tk.Label(
            self._zone_row_center, text="", font=status_font,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.zone_status.pack(side="left", padx=(int(6*s), 0))
        
        self.zone_info = tk.Label(
            self._zone_row_center, text="", font=status_font,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.zone_info.pack(side="left", padx=(int(6*s), 0))
        
        self.zone_tolerance = tk.Label(
            self._zone_row_center, text="", font=status_font,
            fg=Theme.TEXT_MUTED, bg=Theme.GRAYPILL, anchor="w"
        )
        # 不pack，容差已在标题栏显示
        
        # 友方机场状态行
        self.friendly_row = tk.Frame(self.content_frame, bg=Theme.GRAYPILL)
        # 初始不pack，由update_display控制
        
        self._friendly_row_left_spacer = tk.Frame(self.friendly_row, bg=Theme.GRAYPILL)
        self._friendly_row_left_spacer.pack(side="left", fill="x", expand=True)
        
        self._friendly_row_center = tk.Frame(self.friendly_row, bg=Theme.GRAYPILL)
        self._friendly_row_center.pack(side="left")
        
        self._friendly_row_right_spacer = tk.Frame(self.friendly_row, bg=Theme.GRAYPILL)
        self._friendly_row_right_spacer.pack(side="left", fill="x", expand=True)
        
        self.friendly_label = tk.Label(
            self._friendly_row_center, text="✈友方:", font=status_font,
            fg=Theme.BLUE, bg=Theme.GRAYPILL, anchor="w"
        )
        self.friendly_label.pack(side="left")
        
        self.friendly_turn = tk.Label(
            self._friendly_row_center, text="", font=status_font,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.friendly_turn.pack(side="left", padx=(int(4*s), 0))
        
        self.friendly_status = tk.Label(
            self._friendly_row_center, text="", font=status_font,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.friendly_status.pack(side="left", padx=(int(6*s), 0))
        
        self.friendly_info = tk.Label(
            self._friendly_row_center, text="", font=status_font,
            fg=Theme.TEXT_DIM, bg=Theme.GRAYPILL, anchor="w"
        )
        self.friendly_info.pack(side="left", padx=(int(6*s), 0))
        

    
    def _init_bindings(self):
        """初始化事件绑定"""
        # 全窗口拖动
        self._bind_drag_recursive(self.window)
        
        # 右键菜单
        self.window.bind("<Button-3>", self._show_context_menu)
        
        # 窗口关闭事件（点X或Alt+F4）
        self.window.protocol("WM_DELETE_WINDOW", self.hide)
        self.window.bind("<FocusIn>", self._on_focus_in)
    
    def _bind_drag_recursive(self, widget):
        widget.bind("<Button-1>", self._on_drag_start, add="+")
        widget.bind("<B1-Motion>", self._on_drag_motion, add="+")
        for child in widget.winfo_children():
            self._bind_drag_recursive(child)

    def _on_drag_start(self, event):
        """开始拖动（仅在主窗口解锁时允许）"""
        if self.app._locked:
            return
        self._drag_data["x"] = event.x_root
        self._drag_data["y"] = event.y_root
        self._drag_data["win_x"] = self.window.winfo_x()
        self._drag_data["win_y"] = self.window.winfo_y()
    
    def _on_drag_motion(self, event):
        """拖动中（仅在主窗口解锁时允许）"""
        if self.app._locked:
            return
        dx = event.x_root - self._drag_data["x"]
        dy = event.y_root - self._drag_data["y"]
        x = self._drag_data["win_x"] + dx
        y = self._drag_data["win_y"] + dy
        self.window.geometry(f"+{x}+{y}")
        # 保存位置
        PanelConfig.navigation_window_pos = (x, y)
    
    def _show_context_menu(self, event):
        """显示右键菜单"""
        menu = tk.Menu(self.window, tearoff=0)
        menu.add_command(label="🔄 切换到集成模式", command=self._switch_to_integrated)
        menu.add_separator()
        menu.add_command(label="📍 重置位置", command=self._reset_position)
        
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()
    
    def _switch_to_integrated(self):
        """切换到集成模式"""
        PanelConfig.navigation_mode = "integrated"
        self.hide()
        self.app._save_config()
        self.app._update_nav_mode_button()
        self.app._refresh_tray()
        # 强制触发UI刷新，确保投弹预测等面板正确显示
        self.app.root.after(50, self.app._recalc_size)
    
    def _reset_position(self):
        """重置窗口位置到屏幕中央"""
        sw, sh = Win32.screen_size()
        w = self.window.winfo_width()
        h = self.window.winfo_height()
        x = (sw - w) // 2
        y = 50  # 靠近顶部
        self.window.geometry(f"+{x}+{y}")
        PanelConfig.navigation_window_pos = (x, y)
    
    def _restore_position(self):
        """恢复保存的窗口位置"""
        if PanelConfig.navigation_window_pos:
            x, y = PanelConfig.navigation_window_pos
            # 确保在屏幕范围内
            sw, sh = Win32.screen_size()
            x = max(0, min(x, sw - 100))
            y = max(0, min(y, sh - 50))
            self.window.geometry(f"+{x}+{y}")
        else:
            self._reset_position()
    
    def show(self):
        """显示窗口"""
        if not self._visible:
            self._visible = True
            self.window.deiconify()
            self.window.lift()
            alpha = UIConfig.WINDOW_ALPHA if self.app._locked else min(240, UIConfig.WINDOW_ALPHA + 30)
            self.apply_window_styles(click_through=self.app._locked, alpha=alpha)
    
    def hide(self):
        """隐藏窗口"""
        if self._visible:
            self._visible = False
            self.window.withdraw()
    
    def is_visible(self):
        """返回窗口是否可见"""
        return self._visible
    
    def update_hint_text(self):
        """更新提示文本（当热键配置变更时调用）"""
        if hasattr(self, 'hint_lbl') and self.hint_lbl:
            self.hint_lbl.config(text=f"{HotkeyConfig.KEY_LOCK}解锁后可拖动")

    def _on_focus_in(self, event=None):
        """Focus guard to keep click-through when locked."""
        if self.app._locked:
            try:
                self.apply_window_styles(click_through=True, alpha=UIConfig.WINDOW_ALPHA)
            except Exception:
                pass
    
    def update_display(self, snap: 'UISnapshot', targets: list, targets_info: list, primary_zone):
        """更新导航显示
        
        v6.6.1: 恢复状态行显示（偏航和ETE信息）
        
        Args:
            snap: UI快照
            targets: 航向带目标列表
            targets_info: 目标信息列表
            primary_zone: 主目标战区
        """
        if not self._visible:
            return
        
        # 更新航向
        if snap.player_heading > 0:
            self.heading_lbl.config(text=f"{int(snap.player_heading):03d}°")
        else:
            self.heading_lbl.config(text="---°")
        
        # 更新航向带
        if snap.player_heading > 0:
            if targets:
                primary_dist = primary_zone.distance_km if primary_zone else 10.0
                self.heading_tape.update_tape_multi(snap.player_heading, targets, primary_dist)
            else:
                self.heading_tape.update_tape_multi(snap.player_heading, [], 10.0)
        else:
            self.heading_tape.clear()
        
        # 更新战区状态行
        zone_info = next((t for t in targets_info if t['type'] == 'zone'), None)
        if primary_zone:
            tolerance = get_cdi_tolerance(primary_zone.distance_km)
            scale = calculate_heading_tape_scale(primary_zone.distance_km)
            rel = primary_zone.relative
            abs_rel = abs(rel)
            
            # 计算转向指示和状态
            turn_text, turn_color = calculate_zone_turn_indicator(rel, tolerance)
            dev_text, dev_color = calculate_zone_status(abs_rel, tolerance)
            
            # 距离和ETE
            ete_str = zone_info.get('ete_str') if zone_info else None
            info_text = format_distance_ete(primary_zone.distance_km, ete_str)
            
            # 容差显示在标题栏
            tol_text = f"±{tolerance:.0f}° {scale:.1f}x"
            
            self.zone_turn.config(text=turn_text, fg=turn_color)
            self.zone_status.config(text=dev_text, fg=dev_color)
            self.zone_info.config(text=info_text, fg=Theme.RED)
            self.zone_tolerance_legend.config(text=tol_text)
            self.zone_row.pack(fill="x", padx=int(4*self.scale), pady=(int(2*self.scale), 0))
        else:
            self.zone_row.pack_forget()
            self.zone_tolerance_legend.config(text="")
        
        # 更新友方机场状态行
        friendly_info = next((t for t in targets_info if t['type'] == 'friendly'), None)
        if friendly_info:
            rel = friendly_info['relative']
            abs_rel = abs(rel)
            dist = friendly_info['distance_km']
            
            # 计算转向指示和状态
            turn_text, turn_color = calculate_airfield_turn_indicator(rel)
            status_text, status_color = calculate_airfield_status(abs_rel)
            
            # 距离和ETE
            info_text = format_distance_ete(dist, friendly_info.get('ete_str'))
            
            self.friendly_turn.config(text=turn_text, fg=turn_color)
            self.friendly_status.config(text=status_text, fg=status_color)
            self.friendly_info.config(text=info_text, fg=Theme.BLUE)
            self.friendly_row.pack(fill="x", padx=int(4*self.scale), pady=(int(1*self.scale), int(4*self.scale)))
        else:
            self.friendly_row.pack_forget()
