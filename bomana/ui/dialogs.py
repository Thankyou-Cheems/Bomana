"""Dialogs and popups."""

import contextlib
import shutil
import time
import tkinter as tk
import webbrowser
from importlib.util import find_spec
from pathlib import Path
from tkinter import filedialog, messagebox
from tkinter import font as tkfont
from typing import ClassVar

from bomana.config.feature_profile import (
    ENABLE_ADVANCED_SETTINGS,
    ENABLE_AIRFIELDS,
    ENABLE_CCRP,
    ENABLE_CHECKLIST,
    ENABLE_FUEL,
    ENABLE_ZONES,
)
from bomana.config.settings import (
    AboutConfig,
    BombConfig,
    ChecklistConfig,
    FileConfig,
    HotkeyConfig,
    OverspeedConfig,
    PanelConfig,
    SnapConfig,
    SoundConfig,
    UIConfig,
    WeaponBallisticModelConfig,
)
from bomana.core.overspeed import SpeedLimitDatabase
from bomana.core.weapon_catalog import WeaponCatalog, get_weapon_catalog
from bomana.ui.dialog_presenter import (
    build_panel_option_specs,
    format_aircraft_override_label,
    format_overspeed_override_summary,
)
from bomana.ui.panel_presenter import format_weapon_selection_label
from bomana.ui.settings_form import (
    apply_settings_payload_to_config,
    build_settings_save_payload,
    collect_hotkey_bindings,
    collect_overspeed_thresholds,
)
from bomana.ui.settings_runtime import SettingsRuntimeMixin
from bomana.ui.text_utils import bind_existing_label_wraps, scaled_control_length
from bomana.ui.theme import Theme
from bomana.ui.tk_style import style_action_button, style_clickable_surface
from bomana.utils.file_utils import ConfigManager, resource_path
from bomana.utils.system import Win32, resolve_tk_font_tuple

# Optional dependencies for images (match HAS_TRAY behavior).
HAS_TRAY = find_spec("PIL") is not None and find_spec("pystray") is not None
_NUMERIC_PARSE_ERRORS = (TypeError, ValueError, tk.TclError)


def build_weapon_selector_scope(
    catalog,
    *,
    aircraft_type_name: str,
    airborne: bool,
) -> tuple[list[dict], str, bool]:
    """Return selector records, scope annotation, and compatible-only state."""
    all_records = list(catalog.search(""))
    aircraft_name = " ".join(str(aircraft_type_name or "").split())
    if not airborne:
        return all_records, "未在飞行中：显示全部武器", False

    compatible_records = list(catalog.for_aircraft(aircraft_name)) if aircraft_name else []
    if compatible_records:
        return compatible_records, f"当前机型 {aircraft_name}：仅显示兼容武器", True
    if aircraft_name:
        note = f"未匹配 {aircraft_name} 的武器预设：显示全部（兼容性未验证）"
    else:
        note = "当前机型未识别：显示全部（兼容性未验证）"
    return all_records, note, False


def persist_ballistic_model_selection(value: str) -> bool:
    """Apply one validated ballistic model and persist it as one semantic action."""

    normalized = str(value or "").strip().lower()
    if normalized not in WeaponBallisticModelConfig.VALID_MODELS:
        return False
    previous = WeaponBallisticModelConfig.selected_model
    if not WeaponBallisticModelConfig.set_selected(normalized):
        return False
    config = ConfigManager.load()
    if not isinstance(config, dict):
        config = {}
    config["weapon_ballistic_model"] = normalized
    if ConfigManager.save(config):
        return True
    WeaponBallisticModelConfig.set_selected(previous)
    return False


def persist_weapon_selection(catalog, weapon_id: str, ballistic_model: str) -> bool:
    """Apply and persist an exact catalog selection, rolling runtime state back on failure."""

    weapon_id = str(weapon_id or "").strip()
    weapon = catalog.get(weapon_id) if catalog is not None and weapon_id else None
    model = str(ballistic_model or "").strip().lower()
    if not weapon or model not in WeaponBallisticModelConfig.VALID_MODELS:
        return False

    previous_weapon = str(getattr(catalog, "selected_weapon_id", "") or "")
    previous_model = WeaponBallisticModelConfig.selected_model
    if not WeaponBallisticModelConfig.set_selected(model):
        return False
    if not catalog.set_selected(weapon_id, source="manual"):
        WeaponBallisticModelConfig.set_selected(previous_model)
        return False

    config = ConfigManager.load()
    if not isinstance(config, dict):
        config = {}
    config["selected_weapon"] = weapon_id
    config["weapon_ballistic_model"] = model
    is_ccrp_bomb = weapon.get("role") == "bomb" and BombConfig.get_bomb_data(weapon_id)
    if is_ccrp_bomb:
        config["selected_bomb"] = weapon_id
    if not ConfigManager.save(config):
        if previous_weapon:
            catalog.set_selected(previous_weapon, source="manual")
        WeaponBallisticModelConfig.set_selected(previous_model)
        return False

    if is_ccrp_bomb:
        BombConfig.selected_bomb = weapon_id
    return True


class _ScalableDialogMixin:
    """可缩放窗口通用逻辑（适配屏幕 + 稳定字体初始化）"""

    def _create_action_button(
        self,
        parent: tk.Widget,
        text: str,
        command,
        variant: str = "neutral",
        width: int = 10,
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            bd=0,
            relief="flat",
            width=width,
            padx=10,
            pady=5,
            cursor="hand2",
        )
        style_action_button(button, variant)
        return button

    def _prepare_responsive_dialog_controls(self) -> None:
        """Convert legacy fixed dialog hints into responsive Tk behavior."""
        bind_existing_label_wraps(
            self,
            minimum_from_current=lambda wraplength: max(100, min(180, int(wraplength * 0.45))),
            margin=24,
        )

        try:
            ui_scale = float(UIConfig.UI_SCALE_MULT)
        except _NUMERIC_PARSE_ERRORS:
            ui_scale = 1.0

        def prepare(widget: tk.Misc) -> None:
            for child in widget.winfo_children():
                prepare(child)

            if isinstance(widget, tk.Scale):
                with contextlib.suppress(tk.TclError, ValueError):
                    length = int(float(widget.cget("length") or 0))
                    if length > 0 and str(widget.cget("orient")) == "horizontal":
                        widget.configure(length=scaled_control_length(length, ui_scale))

        prepare(self)

    def _fit_window_to_screen(self):
        """固定初始尺寸，适配屏幕，同时允许手动调整"""
        self.update_idletasks()
        req_w = self.winfo_reqwidth()
        req_h = self.winfo_reqheight()

        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()

        available_w = max(360, screen_w - 120)
        available_h = max(320, screen_h - 120)

        min_w = min(max(520, int(req_w * 0.85)), available_w)
        min_h = min(max(420, int(req_h * 0.85)), available_h)

        max_w = max(min_w, available_w)
        max_h = max(min_h, available_h)

        init_w = min(max(req_w, min_w), max_w)
        init_h = min(max(req_h, min_h), max_h)

        self.geometry(f"{int(init_w)}x{int(init_h)}")
        self.minsize(int(min_w), int(min_h))
        self.maxsize(int(max_w), int(max_h))

    def _init_dynamic_scaling(self):
        """按当前文本缩放配置初始化字体，不再随窗口尺寸反复重算。"""
        self.update_idletasks()

        def collect(widget):
            for child in widget.winfo_children():
                collect(child)
            if "font" in widget:
                try:
                    font_name = widget.cget("font")
                    if not font_name:
                        font_name = "TkDefaultFont"
                    base_font = tkfont.Font(font=font_name)
                    actual = base_font.actual()
                    base_size = actual.get("size", 10)
                    scaled_size = UIConfig.scaled_font_size(abs(base_size), 1.0, min_size=1)
                    if base_size < 0:
                        scaled_size = -scaled_size
                    font_tuple = resolve_tk_font_tuple(
                        self,
                        (
                            actual.get("family", "TkDefaultFont"),
                            scaled_size,
                            actual.get("weight", "normal"),
                        ),
                    )
                    family = font_tuple[0] if isinstance(font_tuple, tuple) else "TkDefaultFont"
                    new_font = tkfont.Font(
                        family=family,
                        size=scaled_size,
                        weight=actual.get("weight", "normal"),
                        slant=actual.get("slant", "roman"),
                        underline=actual.get("underline", 0),
                        overstrike=actual.get("overstrike", 0),
                    )
                    widget.configure(font=new_font)
                except Exception:
                    pass

        collect(self)
        self._prepare_responsive_dialog_controls()

    def _clamp_to_visible_screen(self, x, y):
        """将窗口左上角坐标钳制在当前可见屏幕范围内。"""
        self.update_idletasks()

        win_w = max(1, int(self.winfo_width()))
        win_h = max(1, int(self.winfo_height()))

        # 优先使用虚拟根坐标，兼容多显示器；若异常则回退到主屏尺寸。
        root_x = int(getattr(self, "winfo_vrootx", lambda: 0)())
        root_y = int(getattr(self, "winfo_vrooty", lambda: 0)())
        root_w = int(getattr(self, "winfo_vrootwidth", self.winfo_screenwidth)())
        root_h = int(getattr(self, "winfo_vrootheight", self.winfo_screenheight)())

        if root_w <= 0:
            root_w = int(self.winfo_screenwidth())
        if root_h <= 0:
            root_h = int(self.winfo_screenheight())

        min_x = root_x
        min_y = root_y
        max_x = root_x + max(0, root_w - win_w)
        max_y = root_y + max(0, root_h - win_h)

        safe_x = max(min_x, min(int(x), max_x))
        safe_y = max(min_y, min(int(y), max_y))
        return safe_x, safe_y

    def _center_dialog_on_parent(self, parent):
        """以父窗口为中心定位，并确保窗口不会超出屏幕。"""
        self.update_idletasks()

        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        ww = self.winfo_width()
        wh = self.winfo_height()

        x = px + (pw - ww) // 2
        y = py + (ph - wh) // 2
        x, y = self._clamp_to_visible_screen(x, y)
        self.geometry(f"+{x}+{y}")


class _ScopedMousewheelBinding:
    """Own a bind_all mousewheel callback and remove only that callback."""

    def __init__(self, owner: tk.Misc, bind_widget: tk.Misc, callback):
        self.owner = owner
        self.bind_widget = bind_widget
        self.callback = callback
        self._funcid: str | None = None
        self._closed = False

        bind_widget.bind("<Enter>", self._activate, add="+")
        bind_widget.bind("<Leave>", self._deactivate, add="+")
        owner.bind("<Destroy>", self._on_owner_destroy, add="+")

    def _activate(self, _event=None) -> None:
        if self._closed or self._funcid is not None:
            return
        self._funcid = self.bind_widget.bind_all("<MouseWheel>", self.callback, add="+")

    def _deactivate(self, _event=None) -> None:
        funcid = self._funcid
        self._funcid = None
        if not funcid:
            return
        with contextlib.suppress(Exception):
            self.bind_widget._root()._unbind(("bind", "all", "<MouseWheel>"), funcid)

    def _on_owner_destroy(self, event) -> None:
        if event.widget is self.owner:
            self.cleanup()

    def cleanup(self) -> None:
        self._closed = True
        self._deactivate()


class SettingsDialog(tk.Toplevel, _ScalableDialogMixin, SettingsRuntimeMixin):
    """设置对话框

    使用选项卡组织设置项：
    - 显示：透明度、缩放、主题
    - 面板：各信息面板的显示开关
    - 快捷键：自定义热键绑定
    - 其他：吸附、全局热键等
    """

    def __init__(self, parent, app, initial_tab: str | None = None):
        super().__init__(parent)
        self.app = app
        self.initial_tab = initial_tab or "显示"
        self.title("设置")
        self.resizable(True, True)
        self.configure(bg=Theme.BG)
        self.transient(parent)
        self.grab_set()
        self._build_ui()
        self._fit_window_to_screen()
        self._init_dynamic_scaling()
        self._center_on_parent(parent)

    def _style_tab_button(self, name: str, active: bool) -> None:
        btn = self.tab_btns.get(name)
        if not btn:
            return
        if active:
            btn.configure(
                bg=Theme.BLUE,
                fg=Theme.TEXT,
                highlightbackground=Theme.BLUE,
                activebackground=Theme.BLUE,
                activeforeground=Theme.TEXT,
            )
        else:
            btn.configure(
                bg=Theme.GRAYPILL,
                fg=Theme.TEXT_DIM,
                highlightbackground=Theme.BORDER,
                activebackground=Theme.SEPARATOR,
                activeforeground=Theme.TEXT,
            )

    def _on_tab_hover(self, tab_name: str, hover: bool) -> None:
        if tab_name == self.current_tab:
            self._style_tab_button(tab_name, active=True)
            return
        btn = self.tab_btns.get(tab_name)
        if not btn:
            return
        if hover:
            btn.configure(
                bg=Theme.SEPARATOR,
                fg=Theme.TEXT,
                highlightbackground=Theme.BLUE,
            )
        else:
            self._style_tab_button(tab_name, active=False)

    def _build_ui(self):
        # Fluent 外层边框 + 内容表面，保持与主界面一致的分层节奏。
        shell = tk.Frame(self, bg=Theme.BORDER, bd=0, highlightthickness=0)
        shell.pack(padx=15, pady=12, fill="both", expand=True)
        main = tk.Frame(shell, bg=Theme.BG, bd=0, highlightthickness=0)
        main.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(main, bg=Theme.BG)
        header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(
            header,
            text="设置",
            font=("Segoe UI", 14, "bold"),
            bg=Theme.BG,
            fg=Theme.TEXT,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            header,
            text="显示、面板、快捷键与行为偏好",
            font=("Segoe UI", 9),
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        # 创建选项卡（使用 Frame 模拟，避免 ttk 在透明窗口中的样式冲突）
        tab_shell = tk.Frame(main, bg=Theme.SEPARATOR, bd=0, highlightthickness=0)
        tab_shell.pack(fill="x", padx=12, pady=(4, 10))
        self.tab_buttons_frame = tk.Frame(tab_shell, bg=Theme.BG, bd=0, highlightthickness=0)
        self.tab_buttons_frame.pack(fill="x", padx=1, pady=1)

        self.tabs = ["显示", "面板"]
        if ENABLE_CCRP:
            self.tabs.append("CCRP")
        self.tabs.extend(["空速", "音效", "快捷键", "其他"])
        self.tab_frames = {}
        self.tab_btns = {}
        self.current_tab = "显示"
        self.overspeed_override_map = OverspeedConfig.get_aircraft_overrides()

        # 选项卡按钮
        for tab in self.tabs:
            btn = tk.Button(
                self.tab_buttons_frame,
                text=tab,
                bg=Theme.GRAYPILL,
                fg=Theme.TEXT_DIM,
                bd=0,
                relief="flat",
                padx=14,
                pady=5,
                cursor="hand2",
                activebackground=Theme.SEPARATOR,
                activeforeground=Theme.TEXT,
                highlightthickness=1,
                highlightbackground=Theme.BORDER,
                highlightcolor=Theme.BORDER,
                command=lambda t=tab: self._switch_tab(t),
            )
            btn.pack(side="left", padx=2)
            self.tab_btns[tab] = btn
            btn.bind("<Enter>", lambda _e, t=tab: self._on_tab_hover(t, True), add="+")
            btn.bind("<Leave>", lambda _e, t=tab: self._on_tab_hover(t, False), add="+")

        # 选项卡内容容器
        content_shell = tk.Frame(main, bg=Theme.SEPARATOR, bd=0, highlightthickness=0)
        content_shell.pack(fill="both", expand=True, padx=12)
        content_body = tk.Frame(content_shell, bg=Theme.BG, bd=0, highlightthickness=0)
        content_body.pack(fill="both", expand=True, padx=1, pady=1)
        self._content_canvas = tk.Canvas(
            content_body,
            bg=Theme.BG,
            bd=0,
            highlightthickness=0,
            yscrollincrement=18,
        )
        self._content_scrollbar = tk.Scrollbar(
            content_body,
            orient="vertical",
            command=self._content_canvas.yview,
            troughcolor=Theme.BG,
            bg=Theme.GRAYPILL,
            activebackground=Theme.SEPARATOR,
            bd=0,
            highlightthickness=0,
        )
        self._content_canvas.configure(yscrollcommand=self._content_scrollbar.set)
        self._content_scrollbar.pack(side="right", fill="y")
        self._content_canvas.pack(side="left", fill="both", expand=True)
        self.content_frame = tk.Frame(self._content_canvas, bg=Theme.BG, bd=0, highlightthickness=0)
        self._content_window = self._content_canvas.create_window(
            (0, 0), window=self.content_frame, anchor="nw"
        )

        def _sync_content_scrollregion(_event=None):
            bbox = self._content_canvas.bbox("all")
            if bbox:
                self._content_canvas.configure(scrollregion=bbox)

        def _sync_content_width(event):
            self._content_canvas.itemconfigure(self._content_window, width=event.width)
            _sync_content_scrollregion()

        self.content_frame.bind("<Configure>", _sync_content_scrollregion, add="+")
        self._content_canvas.bind("<Configure>", _sync_content_width, add="+")
        self._content_mousewheel_binding = _ScopedMousewheelBinding(
            self,
            self._content_canvas,
            self._on_content_mousewheel,
        )

        # 创建各选项卡页面
        self._build_display_tab()
        self._build_panel_tab()
        if ENABLE_CCRP:
            self._build_ccrp_tab()
        self._build_overspeed_tab()
        self._build_sound_tab()
        self._build_hotkey_tab()
        self._build_other_tab()

        # 按钮行
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.pack(fill="x", padx=12, pady=(10, 10))
        self._create_action_button(btn_frame, "保存", self._save, variant="primary", width=9).pack(
            side="right"
        )
        self._create_action_button(
            btn_frame, "取消", self.destroy, variant="neutral", width=9
        ).pack(side="right", padx=(0, 8))

        # 显示第一个选项卡
        self._switch_tab(self.initial_tab if self.initial_tab in self.tabs else "显示")

    def _on_content_mousewheel(self, event):
        if hasattr(self, "_content_canvas"):
            self._content_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _cleanup_content_mousewheel_binding(self) -> None:
        binding = getattr(self, "_content_mousewheel_binding", None)
        if binding is not None:
            binding.cleanup()

    def destroy(self) -> None:
        self._cleanup_content_mousewheel_binding()
        super().destroy()

    def _switch_tab(self, tab_name: str):
        """切换选项卡"""
        # 隐藏所有页面
        for frame in self.tab_frames.values():
            frame.pack_forget()

        # 更新按钮样式
        for name, _btn in self.tab_btns.items():
            self._style_tab_button(name, active=(name == tab_name))

        # 显示当前页面
        if tab_name in self.tab_frames:
            self.tab_frames[tab_name].pack(fill="both", expand=True)
            self.update_idletasks()
            if hasattr(self, "_content_canvas"):
                self._content_canvas.yview_moveto(0.0)

        self.current_tab = tab_name

    def _build_display_tab(self):
        """构建显示设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["显示"] = frame

        row = 0

        # 透明度
        tk.Label(frame, text="窗口透明度:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5
        )
        self.alpha_var = tk.IntVar(value=UIConfig.WINDOW_ALPHA)
        tk.Scale(
            frame,
            from_=100,
            to=255,
            orient="horizontal",
            length=180,
            variable=self.alpha_var,
            bg=Theme.BG,
            fg=Theme.TEXT,
            highlightthickness=0,
            troughcolor=Theme.BORDER,
            activebackground=Theme.BLUE,
        ).grid(row=row, column=1, padx=10, pady=5)
        row += 1

        # 独立导航栏宽度
        tk.Label(frame, text="独立导航宽度:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5
        )
        self.nav_width_var = tk.DoubleVar(value=PanelConfig.navigation_bar_width)
        tk.Scale(
            frame,
            from_=0.5,
            to=2.0,
            resolution=0.1,
            orient="horizontal",
            length=180,
            variable=self.nav_width_var,
            bg=Theme.BG,
            fg=Theme.TEXT,
            highlightthickness=0,
            troughcolor=Theme.BORDER,
            activebackground=Theme.BLUE,
        ).grid(row=row, column=1, padx=10, pady=5)
        row += 1

        tk.Label(frame, text="独立导航缩放:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5
        )
        self.nav_scale_var = tk.DoubleVar(value=PanelConfig.navigation_bar_scale)
        tk.Scale(
            frame,
            from_=0.5,
            to=2.0,
            resolution=0.05,
            orient="horizontal",
            length=180,
            variable=self.nav_scale_var,
            bg=Theme.BG,
            fg=Theme.TEXT,
            highlightthickness=0,
            troughcolor=Theme.BORDER,
            activebackground=Theme.BLUE,
        ).grid(row=row, column=1, padx=10, pady=5)
        row += 1

        # 缩放
        tk.Label(frame, text="UI缩放:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5
        )
        self.scale_var = tk.DoubleVar(value=UIConfig.UI_SCALE_MULT)
        tk.Scale(
            frame,
            from_=0.6,
            to=2.5,
            resolution=0.05,
            orient="horizontal",
            length=180,
            variable=self.scale_var,
            bg=Theme.BG,
            fg=Theme.TEXT,
            highlightthickness=0,
            troughcolor=Theme.BORDER,
            activebackground=Theme.BLUE,
        ).grid(row=row, column=1, padx=10, pady=5)
        row += 1

        tk.Label(frame, text="文本缩放:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5
        )
        self.text_scale_var = tk.DoubleVar(value=float(UIConfig.TEXT_SCALE_MULT))
        tk.Scale(
            frame,
            from_=0.75,
            to=2.5,
            resolution=0.05,
            orient="horizontal",
            length=180,
            variable=self.text_scale_var,
            bg=Theme.BG,
            fg=Theme.TEXT,
            highlightthickness=0,
            troughcolor=Theme.BORDER,
            activebackground=Theme.BLUE,
        ).grid(row=row, column=1, padx=10, pady=5)
        row += 1

        # 主题选择
        tk.Label(frame, text="颜色主题:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5
        )
        theme_frame = tk.Frame(frame, bg=Theme.BG)
        theme_frame.grid(row=row, column=1, sticky="w", padx=10, pady=5)

        self.theme_var = tk.StringVar(value=Theme.get_current())
        for theme_name in Theme.get_theme_names():
            display_name = Theme.get_theme_display_name(theme_name)
            tk.Radiobutton(
                theme_frame,
                text=display_name,
                variable=self.theme_var,
                value=theme_name,
                bg=Theme.BG,
                fg=Theme.TEXT,
                selectcolor=Theme.GRAYPILL,
                activebackground=Theme.BG,
                activeforeground=Theme.TEXT,
                highlightthickness=0,
            ).pack(anchor="w")
        row += 1

        # 主题提示
        tk.Label(
            frame,
            text="* 主题与UI缩放保存后立即生效",
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            font=("Segoe UI", 8),
            justify="left",
        ).grid(row=row, column=0, columnspan=2, sticky="w", pady=(10, 0))

    def _build_panel_tab(self):
        """构建面板设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["面板"] = frame

        # 如果高级设置被禁用，显示简化提示
        if not ENABLE_ADVANCED_SETTINGS:
            tk.Label(
                frame, text="面板设置在精简模式下不可用", bg=Theme.BG, fg=Theme.TEXT_MUTED
            ).pack(anchor="w", pady=10)
            return

        tk.Label(frame, text="选择显示的信息面板:", bg=Theme.BG, fg=Theme.TEXT).pack(
            anchor="w", pady=(0, 10)
        )

        self.panel_vars = {}
        panels = build_panel_option_specs(
            enable_ccrp=ENABLE_CCRP,
            enable_zones=ENABLE_ZONES,
            enable_airfields=ENABLE_AIRFIELDS,
            enable_fuel=ENABLE_FUEL,
            enable_checklist=ENABLE_CHECKLIST,
        )

        if not panels:
            tk.Label(
                frame, text="所有扩展面板已在编译时禁用", bg=Theme.BG, fg=Theme.TEXT_MUTED
            ).pack(anchor="w")
            return

        for spec in panels:
            var = tk.BooleanVar(value=getattr(PanelConfig, spec.key))
            self.panel_vars[spec.key] = var

            item_frame = tk.Frame(frame, bg=Theme.BG)
            item_frame.pack(fill="x", pady=3)

            checkbutton = tk.Checkbutton(
                item_frame,
                text=spec.label,
                variable=var,
                bg=Theme.BG,
                fg=Theme.TEXT,
                selectcolor=Theme.GRAYPILL,
                activebackground=Theme.BG,
                activeforeground=Theme.TEXT,
                highlightthickness=0,
                anchor="w",
            )
            image = (
                self.app.icons.photo(spec.icon, 18) if getattr(self.app, "icons", None) else None
            )
            if image is not None:
                checkbutton.config(image=image, compound="left", padx=4)
                checkbutton._bomana_icon_image = image
            checkbutton.pack(side="left")

            tk.Label(
                item_frame,
                text=f"  - {spec.description}",
                bg=Theme.BG,
                fg=Theme.TEXT_DIM,
                font=("Segoe UI", 8),
            ).pack(side="left")

    def _build_overspeed_tab(self):
        """构建空速预警设置页。"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["空速"] = frame

        warn_frame = tk.Frame(
            frame,
            bg=Theme.GRAYPILL,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.SEPARATOR,
        )
        warn_frame.pack(fill="x", pady=(0, 12))
        tk.Label(
            warn_frame,
            text="监视逻辑",
            bg=Theme.GRAYPILL,
            fg=Theme.TEXT,
            anchor="w",
            padx=8,
            font=("Segoe UI", 9, "bold"),
        ).pack(fill="x", pady=(8, 2))
        tk.Label(
            warn_frame,
            text="常规飞行主要看 IAS；高速或高空时再看 Mach。",
            bg=Theme.GRAYPILL,
            fg=Theme.TEXT,
            justify="left",
            anchor="w",
            padx=8,
            wraplength=620,
        ).pack(fill="x")
        tk.Label(
            warn_frame,
            text="两边任意一项先到线，就按更高一级提示。",
            bg=Theme.GRAYPILL,
            fg=Theme.TEXT_DIM,
            justify="left",
            anchor="w",
            padx=8,
            wraplength=620,
        ).pack(fill="x", pady=(0, 8))

        defaults = OverspeedConfig.get_default_thresholds()
        global_thresholds = OverspeedConfig.get_global_thresholds()
        self.overspeed_vars = {
            "caution_ratio": tk.DoubleVar(value=global_thresholds["caution_ratio"]),
            "warning_ratio": tk.DoubleVar(value=global_thresholds["warning_ratio"]),
            "critical_ratio": tk.DoubleVar(value=global_thresholds["critical_ratio"]),
            "mach_caution_margin": tk.DoubleVar(value=global_thresholds["mach_caution_margin"]),
            "mach_warning_margin": tk.DoubleVar(value=global_thresholds["mach_warning_margin"]),
            "mach_critical_margin": tk.DoubleVar(value=global_thresholds["mach_critical_margin"]),
        }

        grid = tk.Frame(frame, bg=Theme.BG)
        grid.pack(anchor="w")

        threshold_rows = [
            (
                "IAS 提示线",
                "caution_ratio",
                "达到 IAS 限速的比例",
                defaults["caution_ratio"],
                0.001,
            ),
            (
                "IAS 警告线",
                "warning_ratio",
                "达到 IAS 限速的比例",
                defaults["warning_ratio"],
                0.001,
            ),
            (
                "IAS 危险线",
                "critical_ratio",
                "达到 IAS 限速的比例",
                defaults["critical_ratio"],
                0.001,
            ),
            (
                "Mach 提示线",
                "mach_caution_margin",
                "距 Mach 限速还剩多少",
                defaults["mach_caution_margin"],
                0.005,
            ),
            (
                "Mach 警告线",
                "mach_warning_margin",
                "距 Mach 限速还剩多少",
                defaults["mach_warning_margin"],
                0.005,
            ),
            (
                "Mach 危险线",
                "mach_critical_margin",
                "距 Mach 限速还剩多少",
                defaults["mach_critical_margin"],
                0.005,
            ),
        ]

        for row, (label, key, suffix, default_value, step) in enumerate(threshold_rows):
            tk.Label(grid, text=f"{label}:", bg=Theme.BG, fg=Theme.TEXT).grid(
                row=row, column=0, sticky="w", pady=4
            )
            tk.Spinbox(
                grid,
                from_=0.0,
                to=1.2,
                increment=step,
                width=8,
                textvariable=self.overspeed_vars[key],
                bg=Theme.GRAYPILL,
                fg=Theme.TEXT,
                bd=0,
                highlightthickness=1,
                highlightbackground=Theme.BORDER,
            ).grid(row=row, column=1, sticky="w", padx=(10, 6), pady=4)
            tk.Label(
                grid,
                text=suffix,
                bg=Theme.BG,
                fg=Theme.TEXT_DIM,
                font=("Segoe UI", 8),
            ).grid(row=row, column=2, sticky="w", pady=4)
            tk.Label(
                grid,
                text=f"默认 {default_value:.3f}",
                bg=Theme.BG,
                fg=Theme.TEXT_MUTED,
                font=("Segoe UI", 8),
            ).grid(row=row, column=3, sticky="w", padx=(12, 0), pady=4)

        action_frame = tk.Frame(frame, bg=Theme.BG)
        action_frame.pack(fill="x", pady=(14, 4))
        self._create_action_button(
            action_frame,
            "管理机型覆盖",
            self._open_overspeed_override_dialog,
            variant="neutral",
            width=12,
        ).pack(side="left")

        self.overspeed_override_summary_var = tk.StringVar()
        tk.Label(
            frame,
            textvariable=self.overspeed_override_summary_var,
            bg=Theme.BG,
            fg=Theme.TEXT,
            justify="left",
            anchor="w",
            wraplength=520,
        ).pack(fill="x", pady=(2, 0))

        tk.Label(
            frame,
            text="调参规则",
            bg=Theme.BG,
            fg=Theme.TEXT,
            font=("Segoe UI", 9, "bold"),
            justify="left",
            anchor="w",
        ).pack(fill="x", pady=(10, 2))

        tk.Label(
            frame,
            text="IAS：数值越小，越早提醒。0.940 表示到该机型 IAS 限速的 94% 开始提示。",
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            font=("Segoe UI", 8),
            justify="left",
            anchor="w",
            wraplength=620,
        ).pack(fill="x")
        tk.Label(
            frame,
            text="Mach：数值越大，越早提醒。0.040 表示距离该机型 Mach 限速只剩 0.04 开始提示。",
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            font=("Segoe UI", 8),
            justify="left",
            anchor="w",
            wraplength=620,
        ).pack(fill="x", pady=(2, 0))
        tk.Label(
            frame,
            text="拿不准时，先只改“提示线”；警告线和危险线尽量先保持默认。",
            bg=Theme.BG,
            fg=Theme.TEXT_DIM,
            font=("Segoe UI", 8),
            justify="left",
            anchor="w",
            wraplength=620,
        ).pack(fill="x", pady=(2, 0))

        self._refresh_overspeed_override_summary()

    def _open_overspeed_override_dialog(self):
        dialog = OverspeedAircraftOverrideDialog(self, self.overspeed_override_map)
        self.wait_window(dialog)
        if getattr(dialog, "result", None) is not None:
            self.overspeed_override_map = dialog.result
            self._refresh_overspeed_override_summary()

    @staticmethod
    def _format_aircraft_label(raw: str) -> str:
        return format_aircraft_override_label(raw)

    def _refresh_overspeed_override_summary(self):
        self.overspeed_override_summary_var.set(
            format_overspeed_override_summary(self.overspeed_override_map)
        )

    def _build_sound_tab(self):
        """构建音效设置页。"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["音效"] = frame

        self.sound_enabled_var = tk.BooleanVar(value=self.app.sound.is_enabled())
        self.zone_sound_enabled_var = tk.BooleanVar(
            value=bool(getattr(self.app, "_zone_sound_enabled", True))
        )
        self.sound_file_overrides = SoundConfig.export_user_config()
        self.sound_row_vars = {}

        tk.Checkbutton(
            frame,
            text="启用提示音",
            variable=self.sound_enabled_var,
            bg=Theme.BG,
            fg=Theme.TEXT,
            selectcolor=Theme.GRAYPILL,
            activebackground=Theme.BG,
            activeforeground=Theme.TEXT,
            highlightthickness=0,
        ).pack(anchor="w", pady=(0, 4))
        tk.Checkbutton(
            frame,
            text="启用战区摧毁提示音",
            variable=self.zone_sound_enabled_var,
            bg=Theme.BG,
            fg=Theme.TEXT,
            selectcolor=Theme.GRAYPILL,
            activebackground=Theme.BG,
            activeforeground=Theme.TEXT,
            highlightthickness=0,
        ).pack(anchor="w", pady=(0, 10))

        tk.Label(
            frame,
            text="支持导入 .wav / .mp3 / .wma / .mid / .midi，自定义文件会在保存时复制到软件自己的目录。",
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            font=("Segoe UI", 8),
            justify="left",
            anchor="w",
            wraplength=640,
        ).pack(fill="x", pady=(0, 10))

        for group_name, event_keys in SoundConfig.get_event_groups():
            section_shell = tk.Frame(frame, bg=Theme.SEPARATOR, bd=0, highlightthickness=0)
            section_shell.pack(fill="x", pady=(0, 10))
            section = tk.Frame(section_shell, bg=Theme.BG, bd=0, highlightthickness=0)
            section.pack(fill="x", padx=1, pady=1)

            tk.Label(
                section,
                text=group_name,
                bg=Theme.BG,
                fg=Theme.TEXT,
                font=("Segoe UI", 9, "bold"),
                anchor="w",
            ).pack(fill="x", padx=10, pady=(8, 4))

            for key in event_keys:
                meta = SoundConfig.get_event_meta(key)
                row = tk.Frame(section, bg=Theme.BG)
                row.pack(fill="x", padx=10, pady=(0, 8))

                left = tk.Frame(row, bg=Theme.BG)
                left.pack(side="left", fill="x", expand=True)

                tk.Label(
                    left,
                    text=meta["label"],
                    bg=Theme.BG,
                    fg=Theme.TEXT,
                    anchor="w",
                ).pack(fill="x")
                tk.Label(
                    left,
                    text=meta["description"],
                    bg=Theme.BG,
                    fg=Theme.TEXT_DIM,
                    font=("Segoe UI", 8),
                    anchor="w",
                    justify="left",
                    wraplength=380,
                ).pack(fill="x")

                self.sound_row_vars[key] = tk.StringVar()
                tk.Label(
                    left,
                    textvariable=self.sound_row_vars[key],
                    bg=Theme.GRAYPILL,
                    fg=Theme.BLUE,
                    anchor="w",
                    justify="left",
                    padx=8,
                    pady=5,
                ).pack(fill="x", pady=(5, 0))

                actions = tk.Frame(row, bg=Theme.BG)
                actions.pack(side="right", padx=(10, 0))
                self._create_action_button(
                    actions,
                    "选择文件",
                    lambda sound_key=key: self._choose_sound_file(sound_key),
                    variant="neutral",
                    width=9,
                ).pack(side="left")
                self._create_action_button(
                    actions,
                    "恢复默认",
                    lambda sound_key=key: self._clear_sound_file(sound_key),
                    variant="neutral",
                    width=9,
                ).pack(side="left", padx=(6, 0))
                self._create_action_button(
                    actions,
                    "试听",
                    lambda sound_key=key: self._preview_sound(sound_key),
                    variant="primary",
                    width=7,
                ).pack(side="left", padx=(6, 0))

                self._refresh_sound_override_label(key)

    def _sound_file_dialog_types(self):
        return [
            ("支持的音频文件", "*.wav *.mp3 *.wma *.mid *.midi"),
            ("WAV 文件", "*.wav"),
            ("MP3 文件", "*.mp3"),
            ("WMA 文件", "*.wma"),
            ("MIDI 文件", "*.mid *.midi"),
            ("所有文件", "*.*"),
        ]

    def _refresh_sound_override_label(self, sound_key: str) -> None:
        display_var = self.sound_row_vars.get(sound_key)
        if display_var is None:
            return
        path_str = str(self.sound_file_overrides.get(sound_key, "") or "").strip()
        if not path_str:
            display_var.set("当前：内置蜂鸣")
            return
        path = Path(path_str)
        if path.exists():
            display_var.set(f"当前：自定义文件 {path.name}")
        else:
            display_var.set(f"当前：自定义文件缺失 {path.name}")

    def _choose_sound_file(self, sound_key: str) -> None:
        file_path = filedialog.askopenfilename(
            parent=self,
            title=f"选择 {SoundConfig.get_event_meta(sound_key)['label']} 音频文件",
            filetypes=self._sound_file_dialog_types(),
        )
        if not file_path:
            return
        path = Path(file_path)
        if path.suffix.lower() not in SoundConfig.SUPPORTED_AUDIO_EXTS:
            messagebox.showwarning(
                "音效格式不支持",
                "当前只支持 .wav / .mp3 / .wma / .mid / .midi 文件。",
                parent=self,
            )
            return
        self.sound_file_overrides[sound_key] = str(path)
        self._refresh_sound_override_label(sound_key)

    def _clear_sound_file(self, sound_key: str) -> None:
        self.sound_file_overrides.pop(sound_key, None)
        self._refresh_sound_override_label(sound_key)

    def _preview_sound(self, sound_key: str) -> None:
        custom_file = str(self.sound_file_overrides.get(sound_key, "") or "").strip() or None
        self.app.sound.play(pattern=sound_key, force=True, custom_file=custom_file)

    @staticmethod
    def _is_managed_sound_file(path: Path) -> bool:
        try:
            return path.resolve().parent == FileConfig.CUSTOM_SOUND_DIR.resolve()
        except Exception:
            return False

    def _persist_sound_overrides(self) -> tuple[dict[str, str], list[Path], list[Path]]:
        current_saved = SoundConfig.export_user_config()
        final_overrides = {}
        created_paths: list[Path] = []
        old_paths_to_remove: list[Path] = []
        managed_dir = FileConfig.CUSTOM_SOUND_DIR
        managed_dir.mkdir(parents=True, exist_ok=True)

        for sound_key in SoundConfig.SOUND_EVENT_META:
            raw_path = str(self.sound_file_overrides.get(sound_key, "") or "").strip()
            if not raw_path:
                continue

            source = Path(raw_path)
            if not source.exists():
                continue
            if source.suffix.lower() not in SoundConfig.SUPPORTED_AUDIO_EXTS:
                continue

            if self._is_managed_sound_file(source):
                final_path = source
            else:
                safe_suffix = source.suffix.lower()
                target = managed_dir / f"{sound_key}_{int(time.time() * 1000)}{safe_suffix}"
                shutil.copy2(source, target)
                created_paths.append(target)
                final_path = target

            final_overrides[sound_key] = str(final_path)

        for old_path_str in current_saved.values():
            old_path_text = str(old_path_str or "").strip()
            if not old_path_text:
                continue
            old_path = Path(old_path_text)
            if (
                self._is_managed_sound_file(old_path)
                and str(old_path) not in final_overrides.values()
            ):
                old_paths_to_remove.append(old_path)

        return final_overrides, created_paths, old_paths_to_remove

    def _build_hotkey_tab(self):
        """构建快捷键设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["快捷键"] = frame

        tk.Label(frame, text="自定义快捷键绑定:", bg=Theme.BG, fg=Theme.TEXT).pack(
            anchor="w", pady=(0, 10)
        )

        # 快捷键配置
        self.hotkey_vars = {}
        hotkeys = [
            ("reset", "重置计时器", HotkeyConfig.KEY_RESET),
            ("lock", "锁定/解锁", HotkeyConfig.KEY_LOCK),
            ("corner", "切换角落", HotkeyConfig.KEY_CORNER),
            ("beep", "声音开关", HotkeyConfig.KEY_BEEP),
            ("zones", "战区提示音", HotkeyConfig.KEY_ZONES),
        ]
        if ENABLE_CCRP:
            hotkeys.insert(
                0,
                ("bomb_target", "CCRP 目标模式", HotkeyConfig.KEY_BOMB_TARGET),
            )

        for key, label, current in hotkeys:
            row_frame = tk.Frame(frame, bg=Theme.BG)
            row_frame.pack(fill="x", pady=3)

            tk.Label(
                row_frame, text=f"{label}:", bg=Theme.BG, fg=Theme.TEXT, width=12, anchor="w"
            ).pack(side="left")

            var = tk.StringVar(value=current)
            self.hotkey_vars[key] = var

            # 下拉选择框
            menu_btn = tk.Menubutton(
                row_frame,
                textvariable=var,
                bg=Theme.GRAYPILL,
                fg=Theme.TEXT,
                bd=0,
                padx=10,
                pady=2,
                highlightthickness=1,
                highlightbackground=Theme.BORDER,
                relief="flat",
            )
            menu_btn.pack(side="left", padx=(10, 0))

            menu = tk.Menu(menu_btn, tearoff=0, bg=Theme.GRAYPILL, fg=Theme.TEXT)
            for fkey in HotkeyConfig.AVAILABLE_KEYS:
                menu.add_command(label=fkey, command=lambda v=var, k=fkey: v.set(k))
            menu_btn["menu"] = menu

        # 提示
        tk.Label(
            frame,
            text=(
                "* 避免与游戏快捷键冲突\n"
                "* 不允许多个功能绑定同一个按键"
            ),
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            font=("Segoe UI", 8),
            justify="left",
        ).pack(anchor="w", pady=(15, 0))

    def _build_ccrp_tab(self):
        """构建投弹预测设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["CCRP"] = frame

        self.selected_bomb_id = BombConfig.selected_bomb
        self.ccrp_selected_bomb_var = tk.StringVar()
        self._refresh_ccrp_selected_bomb_text()

        tk.Label(frame, text="CCRP 默认炸弹:", bg=Theme.BG, fg=Theme.TEXT).pack(anchor="w")
        bomb_row = tk.Frame(frame, bg=Theme.BG)
        bomb_row.pack(fill="x", pady=(6, 4))
        tk.Label(
            bomb_row,
            textvariable=self.ccrp_selected_bomb_var,
            bg=Theme.GRAYPILL,
            fg=Theme.BLUE,
            padx=10,
            pady=6,
            anchor="w",
        ).pack(side="left", fill="x", expand=True)
        self._create_action_button(
            bomb_row,
            "更换 CCRP 炸弹",
            self._open_ccrp_bomb_selector,
            variant="neutral",
            width=12,
        ).pack(side="left", padx=(10, 0))

        tk.Label(
            frame,
            text="这里只设置高精度自由落体模型的默认炸弹；作战武器请点击主卡片选择。",
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(0, 10))

        if BombConfig.load_error:
            tk.Label(
                frame,
                text=f"炸弹数据库不可用：{BombConfig.load_error}",
                bg=Theme.BG,
                fg=Theme.RED,
                anchor="w",
                justify="left",
                wraplength=640,
            ).pack(fill="x", pady=(0, 10))

        tk.Label(
            frame,
            text=("预测使用高精度打击模型与内置地形数据；旧距离/时间经验倍率已移除。"),
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            font=("Segoe UI", 8),
            wraplength=640,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))

    def _refresh_ccrp_selected_bomb_text(self):
        bomb_id = getattr(self, "selected_bomb_id", BombConfig.selected_bomb)
        if BombConfig.get_bomb_data(bomb_id):
            text = BombConfig.format_bomb_name(bomb_id)
        elif BombConfig.load_error:
            text = f"{bomb_id}（数据库不可用）"
        else:
            text = bomb_id or "未选择炸弹"
        if hasattr(self, "ccrp_selected_bomb_var"):
            self.ccrp_selected_bomb_var.set(text)

    def _open_ccrp_bomb_selector(self):
        dialog = BombSelectorDialog(
            self,
            self.app,
            initial_bomb=getattr(self, "selected_bomb_id", BombConfig.selected_bomb),
            persist_selection=False,
        )
        self.wait_window(dialog)
        if getattr(dialog, "result", None):
            self.selected_bomb_id = dialog.result
            self._refresh_ccrp_selected_bomb_text()

    def _build_other_tab(self):
        """构建其他设置页"""
        frame = tk.Frame(self.content_frame, bg=Theme.BG)
        self.tab_frames["其他"] = frame

        row = 0

        # 全局热键开关
        tk.Label(frame, text="全局热键:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5
        )
        self.hotkeys_enabled_var = tk.BooleanVar(value=HotkeyConfig.GLOBAL_HOTKEYS)
        tk.Checkbutton(
            frame,
            text="启用全局热键",
            variable=self.hotkeys_enabled_var,
            bg=Theme.BG,
            fg=Theme.TEXT,
            selectcolor=Theme.GRAYPILL,
            activebackground=Theme.BG,
            activeforeground=Theme.TEXT,
            highlightthickness=0,
        ).grid(row=row, column=1, sticky="w", padx=10, pady=5)
        row += 1

        # 窗口吸附
        tk.Label(frame, text="窗口吸附:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5
        )
        self.snap_var = tk.BooleanVar(value=SnapConfig.enabled)
        tk.Checkbutton(
            frame,
            text="拖动时吸附到屏幕边缘",
            variable=self.snap_var,
            bg=Theme.BG,
            fg=Theme.TEXT,
            selectcolor=Theme.GRAYPILL,
            activebackground=Theme.BG,
            activeforeground=Theme.TEXT,
            highlightthickness=0,
        ).grid(row=row, column=1, sticky="w", padx=10, pady=5)
        row += 1

        # 吸附距离
        tk.Label(frame, text="吸附距离:", bg=Theme.BG, fg=Theme.TEXT).grid(
            row=row, column=0, sticky="w", pady=5
        )
        self.snap_dist_var = tk.IntVar(value=SnapConfig.SNAP_DISTANCE)
        tk.Scale(
            frame,
            from_=5,
            to=50,
            orient="horizontal",
            length=150,
            variable=self.snap_dist_var,
            bg=Theme.BG,
            fg=Theme.TEXT,
            highlightthickness=0,
            troughcolor=Theme.BORDER,
            activebackground=Theme.BLUE,
        ).grid(row=row, column=1, padx=10, pady=5, sticky="w")
        row += 1

        # 分隔线
        tk.Frame(frame, bg=Theme.SEPARATOR, height=1).grid(
            row=row, column=0, columnspan=2, sticky="ew", pady=10
        )
        row += 1

        # 重置按钮
        tk.Button(
            frame,
            text="重置所有设置为默认",
            command=self._reset_defaults,
            bg=Theme.YELLOW,
            fg=Theme.BG,
            bd=0,
            padx=15,
            pady=5,
        ).grid(row=row, column=0, columnspan=2, pady=10)

    def _reset_defaults(self):
        """重置为默认设置"""
        if messagebox.askyesno("确认", "确定要重置所有设置为默认值吗？", parent=self):
            # 重置显示设置
            self.alpha_var.set(210)
            self.nav_width_var.set(1.0)
            self.nav_scale_var.set(1.0)
            self.scale_var.set(UIConfig.DEFAULT_UI_SCALE_MULT)
            self.text_scale_var.set(1.0)
            self.theme_var.set("fluent_dark")

            # 重置面板设置
            for key in self.panel_vars:
                self.panel_vars[key].set(key != "speed_history_mode")

            # 重置快捷键
            defaults = {
                "bomb_target": "F6",
                "reset": "F7",
                "lock": "F8",
                "corner": "F9",
                "beep": "F10",
                "zones": "F11",
            }
            for key, val in defaults.items():
                if key in self.hotkey_vars:
                    self.hotkey_vars[key].set(val)

            # 重置其他设置
            self.hotkeys_enabled_var.set(True)
            self.snap_var.set(True)
            self.snap_dist_var.set(20)
            default_thresholds = OverspeedConfig.get_default_thresholds()
            for key, value in default_thresholds.items():
                if hasattr(self, "overspeed_vars") and key in self.overspeed_vars:
                    self.overspeed_vars[key].set(value)
            self.overspeed_override_map = {}
            if hasattr(self, "overspeed_override_summary_var"):
                self._refresh_overspeed_override_summary()

            if hasattr(self, "sound_enabled_var"):
                self.sound_enabled_var.set(False)
            if hasattr(self, "zone_sound_enabled_var"):
                self.zone_sound_enabled_var.set(True)
            if hasattr(self, "sound_file_overrides"):
                self.sound_file_overrides = {}
            for sound_key in getattr(self, "sound_row_vars", {}):
                self._refresh_sound_override_label(sound_key)

    def _center_on_parent(self, parent):
        """居中显示并限制到可见屏幕。"""
        self._center_dialog_on_parent(parent)

    def _restart_global_hotkeys_after_save(self) -> None:
        runtime_services = getattr(self.app, "runtime_services", None)
        if runtime_services is None:
            return

        stop_hotkeys = getattr(runtime_services, "stop_global_hotkeys", None)
        init_hotkeys = getattr(runtime_services, "init_global_hotkeys", None)
        if not (callable(stop_hotkeys) and callable(init_hotkeys)):
            return
        stop_hotkeys()
        if HotkeyConfig.GLOBAL_HOTKEYS:
            init_hotkeys()

    def _save(self):
        """保存所有设置"""
        # 收集设置值
        config = ConfigManager.load()
        previous = self._capture_runtime_settings_state()
        try:
            hotkey_bindings = collect_hotkey_bindings(self.hotkey_vars)
        except ValueError as exc:
            messagebox.showwarning("快捷键冲突", str(exc), parent=self)
            return

        try:
            payload = build_settings_save_payload(
                alpha_var=self.alpha_var,
                nav_width_var=self.nav_width_var,
                nav_scale_var=self.nav_scale_var,
                scale_var=self.scale_var,
                text_scale_var=self.text_scale_var,
                theme_var=self.theme_var,
                hotkeys_enabled_var=self.hotkeys_enabled_var,
                hotkey_bindings=hotkey_bindings,
                panel_vars=self.panel_vars,
                snap_var=self.snap_var,
                snap_dist_var=self.snap_dist_var,
                sound_enabled_var=self.sound_enabled_var,
                zone_sound_enabled_var=self.zone_sound_enabled_var,
                overspeed_vars=getattr(self, "overspeed_vars", {}),
                overspeed_override_map=getattr(self, "overspeed_override_map", None),
                existing_config=config,
                enable_ccrp=bool(ENABLE_CCRP),
                selected_bomb_id=getattr(self, "selected_bomb_id", None),
            )
        except ValueError as exc:
            messagebox.showwarning("数值无效", str(exc), parent=self)
            return

        # 音效设置
        try:
            (
                normalized_sound_overrides,
                created_sound_files,
                old_sound_files_to_remove,
            ) = self._persist_sound_overrides()
        except Exception as exc:
            messagebox.showerror("音效保存失败", f"无法保存自定义提示音：{exc}", parent=self)
            return
        apply_settings_payload_to_config(
            config,
            payload,
            sound_settings=normalized_sound_overrides,
        )

        # 保存配置
        if not ConfigManager.save(config):
            self._rollback_created_sound_files(created_sound_files)
            messagebox.showerror(
                "设置保存失败",
                "配置文件写入失败，本次更改未应用。",
                parent=self,
            )
            return

        for path in old_sound_files_to_remove:
            with contextlib.suppress(OSError):
                path.unlink(missing_ok=True)

        # 配置写入成功后，再应用运行时状态
        self._apply_runtime_settings(
            new_window_alpha=payload.window_alpha,
            new_nav_width=payload.nav_width,
            new_nav_scale=payload.nav_scale,
            new_ui_scale=payload.ui_scale,
            new_text_scale=payload.text_scale,
            panel_config=payload.panel_config,
            new_hotkeys_enabled=payload.hotkeys_enabled,
            hotkey_bindings=hotkey_bindings,
            new_snap_enabled=payload.snap_enabled,
            new_snap_distance=payload.snap_distance,
            new_sound_enabled=payload.sound_enabled,
            new_zone_sound_enabled=payload.zone_sound_enabled,
            normalized_sound_overrides=normalized_sound_overrides,
            normalized_overspeed_thresholds=payload.overspeed_thresholds,
            normalized_overspeed_overrides=payload.overspeed_overrides,
            pending_selected_bomb=payload.selected_bomb,
        )

        # 刷新托盘菜单勾选状态
        if hasattr(self.app, "_refresh_tray"):
            self.app._refresh_tray()

        # 应用透明度
        Win32.setup_window(self.app.hwnd, self.app._locked, UIConfig.WINDOW_ALPHA)

        sound_flags_changed = bool(previous["sound_enabled"]) != bool(
            self.app.sound.is_enabled()
        ) or bool(previous["zone_sound_enabled"]) != bool(self.app._zone_sound_enabled)
        if sound_flags_changed and hasattr(self.app, "_update_hint"):
            self.app._update_hint()
            if hasattr(self.app, "nav_window") and self.app.nav_window:
                self.app.nav_window.update_hint_text()

        # 重启热键服务（如果需要）
        need_restart_hotkeys = (
            previous["hotkeys_enabled"] != HotkeyConfig.GLOBAL_HOTKEYS
            or hotkey_bindings != previous["hotkey_bindings"]
        )
        if need_restart_hotkeys:
            self._restart_global_hotkeys_after_save()
            # 刷新提示文本（主窗口 + 导航窗口）
            self.app._update_hint()
            if hasattr(self.app, "nav_window") and self.app.nav_window:
                self.app.nav_window.update_hint_text()

        theme_changed = payload.theme != previous["theme"]
        ui_scale_changed = abs(UIConfig.UI_SCALE_MULT - float(previous["scale"])) > 1e-6
        text_scale_changed = abs(UIConfig.TEXT_SCALE_MULT - float(previous["text_scale"])) > 1e-6
        nav_width_changed = (
            abs(PanelConfig.navigation_bar_width - float(previous["nav_width"])) > 1e-6
        )
        nav_scale_changed = (
            abs(PanelConfig.navigation_bar_scale - float(previous["nav_scale"])) > 1e-6
        )
        Theme.apply(payload.theme)

        # 运行时应用显示设置，无需重启应用。
        if hasattr(self.app, "apply_display_settings_runtime"):
            self.app.apply_display_settings_runtime(
                theme_changed=theme_changed,
                ui_scale_changed=ui_scale_changed,
                text_scale_changed=text_scale_changed,
                nav_width_changed=nav_width_changed,
                nav_scale_changed=nav_scale_changed,
            )

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
        shell = tk.Frame(self, bg=Theme.BORDER, bd=0, highlightthickness=0)
        shell.pack(fill="both", expand=True, padx=15, pady=12)
        main = tk.Frame(shell, bg=Theme.BG, bd=0, highlightthickness=0)
        main.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(main, bg=Theme.BG)
        header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(
            header,
            text="检查清单编辑",
            font=("Segoe UI", 13, "bold"),
            bg=Theme.BG,
            fg=Theme.TEXT,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            header,
            text=f"每行一个检查项，最多 {ChecklistConfig.MAX_ITEMS} 项",
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        editor_shell = tk.Frame(main, bg=Theme.SEPARATOR, bd=0, highlightthickness=0)
        editor_shell.pack(fill="both", expand=True, padx=12, pady=(4, 10))
        editor = tk.Frame(editor_shell, bg=Theme.BG, bd=0, highlightthickness=0)
        editor.pack(fill="both", expand=True, padx=1, pady=1)

        self.text = tk.Text(
            editor,
            width=40,
            height=12,
            bg=Theme.GRAYPILL,
            fg=Theme.TEXT,
            insertbackground=Theme.TEXT,
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
            highlightcolor=Theme.BLUE,
            padx=8,
            pady=8,
        )
        self.text.pack(fill="both", expand=True, padx=8, pady=8)

        current_items = "\n".join(self.app.chk_items)
        self.text.insert("1.0", current_items)

        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.pack(fill="x", padx=12, pady=(0, 10))
        self._create_action_button(btn_frame, "保存", self._save, variant="primary", width=9).pack(
            side="right"
        )
        self._create_action_button(
            btn_frame, "恢复默认", self._restore_default, variant="accent", width=10
        ).pack(side="right", padx=(0, 8))
        self._create_action_button(
            btn_frame, "取消", self.destroy, variant="neutral", width=9
        ).pack(side="right", padx=(0, 8))

    def _center_on_parent(self, parent):
        self._center_dialog_on_parent(parent)

    def _save(self):
        """保存检查清单"""
        content = self.text.get("1.0", "end-1c")
        items = [line.strip() for line in content.split("\n") if line.strip()]

        if not items:
            messagebox.showwarning("警告", "检查清单不能为空", parent=self)
            return
        if len(items) > ChecklistConfig.MAX_ITEMS:
            messagebox.showwarning(
                "警告", f"检查项数量不能超过{ChecklistConfig.MAX_ITEMS}个", parent=self
            )
            return

        config = ConfigManager.load()
        config["checklist_items"] = items
        if not ConfigManager.save(config):
            messagebox.showerror("失败", "检查清单保存失败", parent=self)
            return
        self.app.chk_items = items
        self.app._rebuild_checklist()

        messagebox.showinfo("成功", "检查清单已保存", parent=self)
        self.destroy()

    def _restore_default(self):
        """恢复默认清单"""
        self.text.delete("1.0", "end")
        self.text.insert("1.0", "\n".join(ChecklistConfig.DEFAULT_ITEMS))


class OverspeedAircraftOverrideDialog(tk.Toplevel, _ScalableDialogMixin):
    """机型级超速阈值覆盖编辑器。"""

    def __init__(self, parent, initial_overrides: dict[str, dict[str, float]] | None = None):
        super().__init__(parent)
        self.db = SpeedLimitDatabase()
        self.result = None
        self.override_map = {
            key: OverspeedConfig.normalize_thresholds(value)
            for key, value in (initial_overrides or {}).items()
            if str(key or "").strip()
        }
        self.selected_aircraft_key = None
        self._listbox_keys = []

        self.title("机型空速覆盖")
        self.configure(bg=Theme.BG)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self._build_ui()
        self._fit_window_to_screen()
        self._init_dynamic_scaling()
        self._center_dialog_on_parent(parent)

    @staticmethod
    def _format_aircraft_title(entry: dict[str, object]) -> str:
        fm_name = str(entry.get("fm_name", "") or "")
        display_name = str(entry.get("display_name", "") or fm_name)
        if not display_name or display_name.lower() == fm_name.lower():
            return fm_name
        return f"{display_name} [{fm_name}]"

    def _build_ui(self):
        shell = tk.Frame(self, bg=Theme.BORDER, bd=0, highlightthickness=0)
        shell.pack(fill="both", expand=True, padx=15, pady=12)
        main = tk.Frame(shell, bg=Theme.BG, bd=0, highlightthickness=0)
        main.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(main, bg=Theme.BG)
        header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(
            header,
            text="机型空速阈值覆盖",
            font=("Segoe UI", 13, "bold"),
            bg=Theme.BG,
            fg=Theme.TEXT,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            header,
            text="从限速数据库中搜索机型并覆盖该机型的 IAS / Mach 预警阈值",
            font=("Segoe UI", 9),
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))
        tk.Label(
            header,
            text="只在某个机型明显过早或过晚提醒时再做覆盖；没问题的机型继续继承全局值即可。",
            font=("Segoe UI", 8),
            bg=Theme.BG,
            fg=Theme.TEXT_DIM,
            anchor="w",
            wraplength=620,
            justify="left",
        ).pack(anchor="w", pady=(2, 0))

        if not self.db.loaded:
            tk.Label(
                main,
                text=f"机型数据库不可用：{self.db.load_error or '未知错误'}",
                bg=Theme.BG,
                fg=Theme.RED,
                anchor="w",
            ).pack(fill="x", padx=12, pady=(0, 8))

        search_frame = tk.Frame(main, bg=Theme.BG)
        search_frame.pack(fill="x", padx=12, pady=(4, 8))

        self.search_var = tk.StringVar()
        self.search_var.trace("w", lambda *args: self._on_search())
        self.search_entry = tk.Entry(
            search_frame,
            textvariable=self.search_var,
            bg=Theme.GRAYPILL,
            fg=Theme.TEXT_MUTED,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
            highlightcolor=Theme.BLUE,
            insertbackground=Theme.TEXT,
            font=("Segoe UI", 10),
        )
        self.search_entry.pack(fill="x", ipady=6)
        self.search_entry.insert(0, "搜索机型 / FM / 别名...")
        self.search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)

        body = tk.Frame(main, bg=Theme.BG)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        list_shell = tk.Frame(body, bg=Theme.SEPARATOR, bd=0, highlightthickness=0)
        list_shell.pack(side="left", fill="both", expand=True)
        list_frame = tk.Frame(list_shell, bg=Theme.GRAYPILL, bd=0, highlightthickness=0)
        list_frame.pack(fill="both", expand=True, padx=1, pady=1)

        scrollbar = tk.Scrollbar(
            list_frame,
            troughcolor=Theme.BG,
            bg=Theme.GRAYPILL,
            activebackground=Theme.SEPARATOR,
            bd=0,
            highlightthickness=0,
        )
        scrollbar.pack(side="right", fill="y")

        self.listbox = tk.Listbox(
            list_frame,
            width=40,
            height=18,
            bg=Theme.GRAYPILL,
            fg=Theme.TEXT,
            selectbackground=Theme.BLUE,
            selectforeground=Theme.TEXT,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
            highlightcolor=Theme.BLUE,
            yscrollcommand=scrollbar.set,
            font=("Consolas", 9),
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<<ListboxSelect>>", self._on_list_selection)
        self.listbox.bind("<Double-Button-1>", lambda _e: self._apply_override())

        editor_shell = tk.Frame(body, bg=Theme.SEPARATOR, bd=0, highlightthickness=0)
        editor_shell.pack(side="left", fill="both", padx=(12, 0))
        editor = tk.Frame(editor_shell, bg=Theme.BG, bd=0, highlightthickness=0)
        editor.pack(fill="both", expand=True, padx=1, pady=1)

        self.aircraft_name_var = tk.StringVar(value="未选择机型")
        self.aircraft_alias_var = tk.StringVar(value="别名：-")
        self.aircraft_mode_var = tk.StringVar(value="状态：继承全局")

        tk.Label(
            editor,
            textvariable=self.aircraft_name_var,
            font=("Segoe UI", 11, "bold"),
            bg=Theme.BG,
            fg=Theme.TEXT,
            anchor="w",
            justify="left",
            wraplength=320,
        ).pack(fill="x", padx=10, pady=(10, 2))
        tk.Label(
            editor,
            textvariable=self.aircraft_alias_var,
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            anchor="w",
            justify="left",
            wraplength=320,
        ).pack(fill="x", padx=10)
        tk.Label(
            editor,
            textvariable=self.aircraft_mode_var,
            bg=Theme.BG,
            fg=Theme.GREEN,
            anchor="w",
        ).pack(fill="x", padx=10, pady=(2, 10))
        tk.Label(
            editor,
            text="IAS 线看“占限速百分比”，Mach 线看“距离 Mach 限速还剩多少”。",
            bg=Theme.BG,
            fg=Theme.TEXT_DIM,
            anchor="w",
            justify="left",
            wraplength=320,
        ).pack(fill="x", padx=10, pady=(0, 8))

        form = tk.Frame(editor, bg=Theme.BG)
        form.pack(fill="x", padx=10)

        base_thresholds = OverspeedConfig.get_global_thresholds()
        self.editor_vars = {
            "caution_ratio": tk.DoubleVar(value=base_thresholds["caution_ratio"]),
            "warning_ratio": tk.DoubleVar(value=base_thresholds["warning_ratio"]),
            "critical_ratio": tk.DoubleVar(value=base_thresholds["critical_ratio"]),
            "mach_caution_margin": tk.DoubleVar(value=base_thresholds["mach_caution_margin"]),
            "mach_warning_margin": tk.DoubleVar(value=base_thresholds["mach_warning_margin"]),
            "mach_critical_margin": tk.DoubleVar(value=base_thresholds["mach_critical_margin"]),
        }
        rows = [
            ("IAS 提示", "caution_ratio"),
            ("IAS 警告", "warning_ratio"),
            ("IAS 危险", "critical_ratio"),
            ("Mach 提示", "mach_caution_margin"),
            ("Mach 警告", "mach_warning_margin"),
            ("Mach 危险", "mach_critical_margin"),
        ]
        for row, (label, key) in enumerate(rows):
            tk.Label(form, text=f"{label}:", bg=Theme.BG, fg=Theme.TEXT).grid(
                row=row, column=0, sticky="w", pady=4
            )
            tk.Spinbox(
                form,
                from_=0.0,
                to=1.2,
                increment=0.001 if "ratio" in key else 0.005,
                width=8,
                textvariable=self.editor_vars[key],
                bg=Theme.GRAYPILL,
                fg=Theme.TEXT,
                bd=0,
                highlightthickness=1,
                highlightbackground=Theme.BORDER,
            ).grid(row=row, column=1, sticky="w", padx=(10, 0), pady=4)

        editor_actions = tk.Frame(editor, bg=Theme.BG)
        editor_actions.pack(fill="x", padx=10, pady=(12, 10))
        self._create_action_button(
            editor_actions,
            "继承全局值",
            self._reset_editor_to_global,
            variant="neutral",
            width=10,
        ).pack(side="left")
        self._create_action_button(
            editor_actions,
            "删除覆盖",
            self._remove_override,
            variant="accent",
            width=10,
        ).pack(side="left", padx=(8, 0))
        self._create_action_button(
            editor_actions,
            "应用覆盖",
            self._apply_override,
            variant="primary",
            width=10,
        ).pack(side="right")

        self.stats_var = tk.StringVar()
        tk.Label(
            main,
            textvariable=self.stats_var,
            bg=Theme.BG,
            fg=Theme.TEXT_DIM,
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(fill="x", padx=12, pady=(0, 0))
        tk.Label(
            main,
            text="提示：如果只是想让大多数机型更早提醒，请回到“空速”页修改全局值；这里只处理个别机型例外。",
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            font=("Segoe UI", 8),
            anchor="w",
            justify="left",
            wraplength=640,
        ).pack(fill="x", padx=12, pady=(4, 0))

        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.pack(fill="x", padx=12, pady=(10, 10))
        self._create_action_button(
            btn_frame, "确定", self._confirm, variant="primary", width=9
        ).pack(side="right")
        self._create_action_button(
            btn_frame, "取消", self.destroy, variant="neutral", width=9
        ).pack(side="right", padx=(0, 8))

        self._populate_list()

    def _on_search_focus_in(self, _event):
        if self.search_entry.get() == "搜索机型 / FM / 别名...":
            self.search_entry.delete(0, "end")
            self.search_entry.config(fg=Theme.TEXT)

    def _on_search_focus_out(self, _event):
        if not self.search_entry.get():
            self.search_entry.insert(0, "搜索机型 / FM / 别名...")
            self.search_entry.config(fg=Theme.TEXT_MUTED)

    def _on_search(self):
        if not hasattr(self, "listbox"):
            return
        query = self.search_var.get()
        if query == "搜索机型 / FM / 别名...":
            query = ""
        self._populate_list(query)

    def _populate_list(self, search_query: str = ""):
        self.listbox.delete(0, "end")
        self._listbox_keys = []
        if not self.db.loaded:
            self.stats_var.set("机型数据库未加载，无法编辑覆盖。")
            return

        if search_query:
            aircraft_keys = self.db.search_aircraft(search_query, limit=200)
        else:
            aircraft_keys = [entry["fm_name"] for entry in self.db.get_aircraft_entries()[:200]]

        selected_index = 0
        for index, aircraft_key in enumerate(aircraft_keys):
            entry = self.db.get_aircraft_entry(aircraft_key) or {
                "fm_name": aircraft_key,
                "display_name": aircraft_key,
                "aliases": [],
            }
            label = self._format_aircraft_title(entry)
            if aircraft_key in self.override_map:
                label += "  [已覆盖]"
            self.listbox.insert("end", label)
            if aircraft_key in self.override_map:
                self.listbox.itemconfig(index, fg=Theme.GREEN)
            self._listbox_keys.append(aircraft_key)
            if self.selected_aircraft_key == aircraft_key:
                selected_index = index

        if self._listbox_keys:
            if self.selected_aircraft_key not in self._listbox_keys:
                self.selected_aircraft_key = self._listbox_keys[0]
                selected_index = 0
            self.listbox.selection_set(selected_index)
            self.listbox.see(selected_index)
            self._load_selected_aircraft(self.selected_aircraft_key)
        else:
            self.selected_aircraft_key = None
            self._load_selected_aircraft(None)

        self.stats_var.set(
            f"显示 {len(self._listbox_keys)} / {len(self.db.get_aircraft_entries())} 个机型，已覆盖 {len(self.override_map)} 个"
        )

    def _on_list_selection(self, _event=None):
        selection = self.listbox.curselection()
        if not selection:
            return
        index = selection[0]
        if index < 0 or index >= len(self._listbox_keys):
            return
        self.selected_aircraft_key = self._listbox_keys[index]
        self._load_selected_aircraft(self.selected_aircraft_key)

    def _load_selected_aircraft(self, aircraft_key: str | None):
        global_thresholds = OverspeedConfig.get_global_thresholds()
        if not aircraft_key:
            self.aircraft_name_var.set("未选择机型")
            self.aircraft_alias_var.set("别名：-")
            self.aircraft_mode_var.set("状态：继承全局")
            for key, value in global_thresholds.items():
                self.editor_vars[key].set(value)
            return

        entry = self.db.get_aircraft_entry(aircraft_key) or {
            "fm_name": aircraft_key,
            "display_name": aircraft_key,
            "aliases": [],
        }
        self.aircraft_name_var.set(self._format_aircraft_title(entry))
        aliases = ", ".join(entry.get("aliases", [])[:6]) or "-"
        self.aircraft_alias_var.set(f"别名：{aliases}")
        has_override = aircraft_key in self.override_map
        self.aircraft_mode_var.set(f"状态：{'已覆盖' if has_override else '继承全局'}")
        thresholds = self.override_map.get(aircraft_key, global_thresholds)
        for key, value in thresholds.items():
            self.editor_vars[key].set(value)

    def _reset_editor_to_global(self):
        global_thresholds = OverspeedConfig.get_global_thresholds()
        for key, value in global_thresholds.items():
            self.editor_vars[key].set(value)

    def _collect_editor_thresholds(self) -> dict[str, float]:
        return collect_overspeed_thresholds(self.editor_vars)

    def _apply_override(self):
        if not self.selected_aircraft_key:
            messagebox.showwarning("提示", "请先从左侧选择一个机型。", parent=self)
            return
        try:
            thresholds = self._collect_editor_thresholds()
        except ValueError as exc:
            messagebox.showwarning("数值无效", str(exc), parent=self)
            return
        self.override_map[self.selected_aircraft_key] = thresholds
        self._populate_list(self._effective_search_query())
        self.aircraft_mode_var.set("状态：已覆盖")

    def _remove_override(self):
        if not self.selected_aircraft_key:
            return
        if self.selected_aircraft_key in self.override_map:
            self.override_map.pop(self.selected_aircraft_key, None)
            self._populate_list(self._effective_search_query())
        else:
            self._reset_editor_to_global()
        self.aircraft_mode_var.set("状态：继承全局")

    def _effective_search_query(self) -> str:
        query = self.search_var.get()
        return "" if query == "搜索机型 / FM / 别名..." else query

    def _confirm(self):
        self.result = {
            key: OverspeedConfig.normalize_thresholds(value)
            for key, value in self.override_map.items()
        }
        self.destroy()


class WeaponSelectorDialog(tk.Toplevel, _ScalableDialogMixin):
    """Manual selector for the Datamine-backed weapon catalog."""

    _ROLE_LABELS: ClassVar[dict[str, str]] = {
        "aam": "AAM",
        "agm": "AGM",
        "bomb": "炸弹",
    }
    _CONTROL_LABELS: ClassVar[dict[str, str]] = {
        "guided": "制导",
        "unguided": "非制导",
    }
    _PLANFORM_LABELS: ClassVar[dict[str, str]] = {
        "normal": "常规",
        "glide": "滑翔",
        "high_drag": "高阻",
    }
    _MODEL_LABELS: ClassVar[dict[str, str]] = {
        WeaponBallisticModelConfig.FOXTHREE_COMPATIBLE: "缺少官方数据时：使用推测替代",
        WeaponBallisticModelConfig.STRICT_OFFICIAL: "缺少官方数据时：不应用模型",
    }
    _MODEL_NOTES: ClassVar[dict[str, str]] = {
        WeaponBallisticModelConfig.FOXTHREE_COMPATIBLE: (
            "官方数据始终优先；只有无官方包线的武器会使用推测替代。"
        ),
        WeaponBallisticModelConfig.STRICT_OFFICIAL: (
            "官方数据始终优先；无官方包线时不显示替代射程。"
        ),
    }

    def __init__(
        self,
        parent,
        app,
        *,
        catalog: WeaponCatalog | None = None,
        initial_weapon: str | None = None,
        aircraft_type_name: str = "",
        airborne: bool = False,
    ):
        super().__init__(parent)
        self.app = app
        self.catalog = catalog if catalog is not None else get_weapon_catalog()
        self.result = None
        self.selected_weapon = initial_weapon or self.catalog.selected_weapon_id
        self._current_role = None
        self._visible_weapon_ids: list[str] = []
        self._scope_records, scope_note, self._compatible_only = build_weapon_selector_scope(
            self.catalog,
            aircraft_type_name=aircraft_type_name,
            airborne=airborne,
        )
        self._scope_ids = {
            str(record.get("id") or "") for record in self._scope_records if record.get("id")
        }

        self.title("选择武器")
        self.configure(bg=Theme.BG)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        shell = tk.Frame(self, bg=Theme.BORDER, bd=0, highlightthickness=0)
        shell.pack(fill="both", expand=True, padx=15, pady=12)
        main = tk.Frame(shell, bg=Theme.BG, bd=0, highlightthickness=0)
        main.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(main, bg=Theme.BG)
        header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(
            header,
            text="选择武器",
            font=("Segoe UI", 13, "bold"),
            bg=Theme.BG,
            fg=Theme.TEXT,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            header,
            text=scope_note,
            font=("Segoe UI", 9),
            bg=Theme.BG,
            fg=Theme.YELLOW if airborne and not self._compatible_only else Theme.TEXT_MUTED,
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(2, 0))

        model_frame = tk.Frame(main, bg=Theme.BG)
        model_frame.pack(fill="x", padx=12, pady=(2, 8))
        tk.Label(
            model_frame,
            text="缺少官方数据时",
            font=("Segoe UI", 9, "bold"),
            bg=Theme.BG,
            fg=Theme.TEXT,
            anchor="w",
        ).pack(anchor="w", pady=(0, 4))
        self.ballistic_model_var = tk.StringVar(value=WeaponBallisticModelConfig.selected_model)
        model_button_frame = tk.Frame(model_frame, bg=Theme.BG)
        model_button_frame.pack(fill="x")
        self.ballistic_model_buttons = {}
        for model, label in self._MODEL_LABELS.items():
            button = self._create_action_button(
                model_button_frame,
                label,
                lambda value=model: self._set_ballistic_model(value),
                variant="neutral",
                width=26,
            )
            button.pack(side="left", padx=(0, 6))
            self.ballistic_model_buttons[model] = button
        self.ballistic_model_note_lbl = tk.Label(
            model_frame,
            text="",
            font=("Segoe UI", 8),
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            anchor="w",
            justify="left",
        )
        self.ballistic_model_note_lbl.pack(fill="x", pady=(4, 0))
        self._refresh_ballistic_model_controls()

        search_frame = tk.Frame(main, bg=Theme.BG)
        search_frame.pack(fill="x", padx=12, pady=(4, 8))
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_args: self._populate_list())
        self.search_entry = tk.Entry(
            search_frame,
            textvariable=self.search_var,
            bg=Theme.GRAYPILL,
            fg=Theme.TEXT,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
            highlightcolor=Theme.BLUE,
            insertbackground=Theme.TEXT,
            font=("Segoe UI", 10),
        )
        self.search_entry.pack(fill="x", ipady=6)

        role_frame = tk.Frame(main, bg=Theme.BG)
        role_frame.pack(fill="x", padx=12, pady=(0, 8))
        self.role_buttons = {}
        for role, label in ((None, "全部"), ("aam", "AAM"), ("agm", "AGM"), ("bomb", "炸弹")):
            button = self._create_action_button(
                role_frame,
                label,
                lambda value=role: self._set_role(value),
                variant="primary" if role is None else "neutral",
                width=7,
            )
            button.pack(side="left", padx=(0, 6))
            self.role_buttons[role] = button

        list_shell = tk.Frame(main, bg=Theme.SEPARATOR, bd=0, highlightthickness=0)
        list_shell.pack(fill="both", expand=True, padx=12)
        list_frame = tk.Frame(list_shell, bg=Theme.GRAYPILL, bd=0, highlightthickness=0)
        list_frame.pack(fill="both", expand=True, padx=1, pady=1)
        scrollbar = tk.Scrollbar(
            list_frame,
            troughcolor=Theme.BG,
            bg=Theme.GRAYPILL,
            activebackground=Theme.SEPARATOR,
            bd=0,
            highlightthickness=0,
        )
        scrollbar.pack(side="right", fill="y")
        self.listbox = tk.Listbox(
            list_frame,
            width=62,
            height=20,
            bg=Theme.GRAYPILL,
            fg=Theme.TEXT,
            selectbackground=Theme.BLUE,
            selectforeground=Theme.TEXT,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
            highlightcolor=Theme.BLUE,
            yscrollcommand=scrollbar.set,
            font=("Segoe UI", 9),
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<Double-Button-1>", lambda _event: self._select())

        self.stats_lbl = tk.Label(
            main,
            text="",
            bg=Theme.BG,
            fg=Theme.TEXT_DIM,
            font=("Segoe UI", 9),
            anchor="w",
        )
        self.stats_lbl.pack(fill="x", padx=12, pady=(6, 0))

        button_frame = tk.Frame(main, bg=Theme.BG)
        button_frame.pack(fill="x", padx=12, pady=(10, 10))
        self._create_action_button(
            button_frame,
            "确定",
            self._select,
            variant="primary",
            width=9,
        ).pack(side="right")
        self._create_action_button(
            button_frame,
            "取消",
            self.destroy,
            variant="neutral",
            width=9,
        ).pack(side="right", padx=(0, 8))

        self._populate_list()
        self._fit_window_to_screen()
        self._init_dynamic_scaling()
        self._center_dialog_on_parent(parent)

    @staticmethod
    def _display_name(record: dict) -> str:
        return str(
            record.get("display_name_zh")
            or record.get("display_name")
            or record.get("id")
            or "未命名武器"
        )

    def _current_ballistic_model(self) -> str:
        model_var = getattr(self, "ballistic_model_var", None)
        value = model_var.get() if model_var is not None else None
        normalized = str(value or WeaponBallisticModelConfig.selected_model).strip().lower()
        if normalized not in WeaponBallisticModelConfig.VALID_MODELS:
            return WeaponBallisticModelConfig.DEFAULT_MODEL
        return normalized

    def _refresh_ballistic_model_controls(self) -> None:
        selected = self._current_ballistic_model()
        for model, button in getattr(self, "ballistic_model_buttons", {}).items():
            style_action_button(button, "primary" if model == selected else "neutral")
        note_label = getattr(self, "ballistic_model_note_lbl", None)
        if note_label is not None:
            note = self._MODEL_NOTES.get(selected, "")
            note_label.config(text=f"{note} 切换后立即保存并生效。")

    def _set_ballistic_model(self, value: str) -> None:
        normalized = str(value or "").strip().lower()
        if normalized not in WeaponBallisticModelConfig.VALID_MODELS:
            return
        if not persist_ballistic_model_selection(normalized):
            messagebox.showerror("失败", "飞行包线模型保存失败", parent=self)
            return
        self.ballistic_model_var.set(normalized)
        self._refresh_ballistic_model_controls()

    def _set_role(self, role: str | None) -> None:
        self._current_role = role
        for button_role, button in self.role_buttons.items():
            active = button_role == role
            style_action_button(button, "primary" if active else "neutral")
        self._populate_list()

    def _view_records(self) -> list[dict]:
        query = " ".join(self.search_var.get().split())
        if query:
            records = list(self.catalog.search(query))
            if self._compatible_only:
                records = [
                    record for record in records if str(record.get("id") or "") in self._scope_ids
                ]
        else:
            records = list(self._scope_records)
        if self._current_role:
            records = [
                record
                for record in records
                if str(record.get("role") or "").lower() == self._current_role
            ]
        return records

    def _record_text(self, record: dict) -> str:
        role = self._ROLE_LABELS.get(str(record.get("role") or "").lower(), "武器")
        control = self._CONTROL_LABELS.get(
            str(record.get("control") or "").lower(),
            "控制未知",
        )
        planform = self._PLANFORM_LABELS.get(
            str(record.get("planform") or "").lower(),
            "构型未知",
        )
        weapon_id = str(record.get("id") or "").strip()
        identity = f" [{weapon_id}]" if weapon_id else ""
        return f"{self._display_name(record)}{identity} · {role} · {control}/{planform}"

    def _populate_list(self) -> None:
        if not hasattr(self, "listbox"):
            return
        records = self._view_records()
        self.listbox.delete(0, "end")
        self._visible_weapon_ids = []
        selected_index = None
        for record in records:
            weapon_id = str(record.get("id") or "")
            if not weapon_id:
                continue
            index = len(self._visible_weapon_ids)
            self._visible_weapon_ids.append(weapon_id)
            self.listbox.insert("end", self._record_text(record))
            if weapon_id == self.selected_weapon:
                selected_index = index
                self.listbox.itemconfig(index, fg=Theme.GREEN)
        if selected_index is not None:
            self.listbox.selection_set(selected_index)
            self.listbox.see(selected_index)
        self.stats_lbl.config(
            text=f"显示 {len(self._visible_weapon_ids)} / {len(self._scope_records)} 种武器"
        )

    def _select(self) -> None:
        selection = self.listbox.curselection()
        if not selection:
            return
        index = int(selection[0])
        if index < 0 or index >= len(self._visible_weapon_ids):
            return
        weapon_id = self._visible_weapon_ids[index]
        weapon = self.catalog.get(weapon_id)
        if not weapon:
            return

        ballistic_model = self._current_ballistic_model()
        if not persist_weapon_selection(self.catalog, weapon_id, ballistic_model):
            messagebox.showerror("失败", "武器选择保存失败", parent=self)
            return
        self.result = weapon_id
        self.selected_weapon = weapon_id
        if hasattr(self.app, "bomb_select_lbl"):
            self.app.bomb_select_lbl.config(
                text=format_weapon_selection_label(
                    self._display_name(weapon),
                    str(weapon.get("role") or ""),
                    "manual",
                )
            )
        self.destroy()


class BombSelectorDialog(tk.Toplevel, _ScalableDialogMixin):
    """炸弹选择对话框"""

    def __init__(
        self, parent, app, initial_bomb: str | None = None, persist_selection: bool = True
    ):
        super().__init__(parent)
        self.app = app
        self.persist_selection = persist_selection
        self.result = None
        self.selected_bomb = initial_bomb or BombConfig.selected_bomb
        self._current_category = None

        self.title("选择炸弹")
        self.configure(bg=Theme.BG)
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        shell = tk.Frame(self, bg=Theme.BORDER, bd=0, highlightthickness=0)
        shell.pack(fill="both", expand=True, padx=15, pady=12)
        main = tk.Frame(shell, bg=Theme.BG, bd=0, highlightthickness=0)
        main.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(main, bg=Theme.BG)
        header.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(
            header,
            text="选择炸弹",
            font=("Segoe UI", 13, "bold"),
            bg=Theme.BG,
            fg=Theme.TEXT,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            header,
            text="支持关键词检索与分类筛选",
            font=("Segoe UI", 9),
            bg=Theme.BG,
            fg=Theme.TEXT_MUTED,
            anchor="w",
        ).pack(anchor="w", pady=(2, 0))

        if BombConfig.load_error:
            tk.Label(
                main,
                text=f"炸弹数据库不可用：{BombConfig.load_error}",
                bg=Theme.BG,
                fg=Theme.RED,
                anchor="w",
                justify="left",
                wraplength=620,
            ).pack(fill="x", padx=12, pady=(0, 8))

        # 搜索框
        search_frame = tk.Frame(main, bg=Theme.BG)
        search_frame.pack(fill="x", padx=12, pady=(4, 8))

        self.search_var = tk.StringVar()
        self.search_var.trace("w", lambda *args: self._on_search())
        self.search_entry = tk.Entry(
            search_frame,
            textvariable=self.search_var,
            bg=Theme.GRAYPILL,
            fg=Theme.TEXT_MUTED,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
            highlightcolor=Theme.BLUE,
            insertbackground=Theme.TEXT,
            font=("Segoe UI", 10),
        )
        self.search_entry.pack(fill="x", ipady=6)
        self.search_entry.insert(0, "搜索...")
        self.search_entry.bind("<FocusIn>", self._on_search_focus_in)
        self.search_entry.bind("<FocusOut>", self._on_search_focus_out)

        # 分类按钮
        cat_shell = tk.Frame(main, bg=Theme.SEPARATOR, bd=0, highlightthickness=0)
        cat_shell.pack(fill="x", padx=12, pady=(0, 10))
        cat_frame = tk.Frame(cat_shell, bg=Theme.BG, bd=0, highlightthickness=0)
        cat_frame.pack(fill="x", padx=1, pady=1)

        self.cat_buttons = {}
        categories = ["全部", *BombConfig.get_categories()]
        for cat in categories:
            btn = tk.Button(
                cat_frame,
                text=cat,
                bg=Theme.GRAYPILL if cat != "全部" else Theme.BLUE,
                fg=Theme.TEXT if cat == "全部" else Theme.TEXT_DIM,
                bd=0,
                relief="flat",
                padx=10,
                pady=4,
                font=("Segoe UI", 9),
                cursor="hand2",
                activebackground=Theme.SEPARATOR,
                activeforeground=Theme.TEXT,
                highlightthickness=1,
                highlightbackground=Theme.BORDER,
                highlightcolor=Theme.BORDER,
                command=lambda c=cat: self._filter_category(c),
            )
            btn.pack(side="left", padx=2)
            self.cat_buttons[cat] = btn
            btn.bind(
                "<Enter>", lambda _e, c=cat: self._style_category_button(c, hover=True), add="+"
            )
            btn.bind(
                "<Leave>", lambda _e, c=cat: self._style_category_button(c, hover=False), add="+"
            )

        # 列表区域
        list_shell = tk.Frame(main, bg=Theme.SEPARATOR, bd=0, highlightthickness=0)
        list_shell.pack(fill="both", expand=True, padx=12)
        list_frame = tk.Frame(list_shell, bg=Theme.GRAYPILL, bd=0, highlightthickness=0)
        list_frame.pack(fill="both", expand=True, padx=1, pady=1)

        scrollbar = tk.Scrollbar(
            list_frame,
            troughcolor=Theme.BG,
            bg=Theme.GRAYPILL,
            activebackground=Theme.SEPARATOR,
            bd=0,
            highlightthickness=0,
        )
        scrollbar.pack(side="right", fill="y")

        self.listbox = tk.Listbox(
            list_frame,
            width=55,
            height=20,
            bg=Theme.GRAYPILL,
            fg=Theme.TEXT,
            selectbackground=Theme.BLUE,
            selectforeground=Theme.TEXT,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
            highlightcolor=Theme.BLUE,
            yscrollcommand=scrollbar.set,
            font=("Consolas", 9),
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<Double-Button-1>", lambda e: self._select())

        # 统计
        self.stats_lbl = tk.Label(
            main, text="", bg=Theme.BG, fg=Theme.TEXT_DIM, font=("Segoe UI", 9), anchor="w"
        )
        self.stats_lbl.pack(fill="x", padx=12, pady=(6, 0))

        # 按钮
        btn_frame = tk.Frame(main, bg=Theme.BG)
        btn_frame.pack(fill="x", padx=12, pady=(10, 10))
        self._create_action_button(
            btn_frame, "确定", self._select, variant="primary", width=9
        ).pack(side="right")
        self._create_action_button(
            btn_frame, "取消", self.destroy, variant="neutral", width=9
        ).pack(side="right", padx=(0, 8))

        self._populate_list()
        self._fit_window_to_screen()
        self._init_dynamic_scaling()
        self._center_on_parent(parent)

    def _style_category_button(self, category: str, hover: bool = False) -> None:
        btn = self.cat_buttons.get(category)
        if not btn:
            return
        is_active = (self._current_category is None and category == "全部") or (
            self._current_category == category
        )
        if is_active:
            btn.configure(
                bg=Theme.BLUE,
                fg=Theme.TEXT,
                highlightbackground=Theme.BLUE,
                activebackground=Theme.BLUE,
                activeforeground=Theme.TEXT,
            )
            return
        if hover:
            btn.configure(
                bg=Theme.SEPARATOR,
                fg=Theme.TEXT,
                highlightbackground=Theme.BLUE,
            )
        else:
            btn.configure(
                bg=Theme.GRAYPILL,
                fg=Theme.TEXT_DIM,
                highlightbackground=Theme.BORDER,
            )

    def _refresh_category_button_styles(self) -> None:
        for cat in self.cat_buttons:
            self._style_category_button(cat, hover=False)

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
        self._current_category = None if category == "全部" else category
        self.search_var.set("")
        self._refresh_category_button_styles()
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

        def _profile_badge(bomb_data: dict) -> str:
            prediction_kind = str(bomb_data.get("prediction_kind", "freefall") or "freefall")
            if prediction_kind == "guided_glide":
                return " [制导/滑翔]"
            if prediction_kind == "high_drag":
                return " [高阻]"
            return ""

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
                        mass = bomb_data["mass"]
                        mass_str = f"{mass / 1000:.1f}t" if mass >= 1000 else f"{int(mass)}kg"
                        text = (
                            f"  {bomb_id} ({mass_str}, Cx={bomb_data.get('drag_cx', 0.04):.4f})"
                            f"{_profile_badge(bomb_data)}"
                        )
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
                    mass = bomb_data["mass"]
                    mass_str = f"{mass / 1000:.1f}t" if mass >= 1000 else f"{int(mass)}kg"
                    cat = bomb_data.get("category", "?")
                    text = (
                        f"{bomb_id} ({mass_str}, Cx={bomb_data.get('drag_cx', 0.04):.4f}) [{cat}]"
                        f"{_profile_badge(bomb_data)}"
                    )
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

        if BombConfig.load_error and not BombConfig.BOMB_DATABASE:
            self.stats_lbl.config(text=f"炸弹数据库未加载：{BombConfig.load_error}")
        else:
            self.stats_lbl.config(
                text=f"显示 {total_count} / {len(BombConfig.BOMB_DATABASE)} 种炸弹"
            )

    def _center_on_parent(self, parent):
        self._center_dialog_on_parent(parent)

    def _select(self):
        selection = self.listbox.curselection()
        if not selection:
            return

        text = self.listbox.get(selection[0]).strip()
        if text.startswith("━━"):
            return

        bomb_id = text.split(" (")[0].strip()

        if BombConfig.get_bomb_data(bomb_id):
            self.result = bomb_id
            if self.persist_selection:
                config = ConfigManager.load()
                config["selected_bomb"] = bomb_id
                if not ConfigManager.save(config):
                    messagebox.showerror("失败", "炸弹选择保存失败", parent=self)
                    return
                BombConfig.selected_bomb = bomb_id

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
        shell = tk.Frame(self, bg=Theme.BORDER, bd=0, highlightthickness=0)
        shell.pack(fill="both", expand=True, padx=16, pady=12)
        body = tk.Frame(shell, bg=Theme.BG, bd=0, highlightthickness=0)
        body.pack(fill="both", expand=True, padx=1, pady=1)

        canvas = tk.Canvas(body, bg=Theme.BG, highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(
            body,
            orient="vertical",
            command=canvas.yview,
            troughcolor=Theme.BG,
            bg=Theme.GRAYPILL,
            activebackground=Theme.SEPARATOR,
            bd=0,
            highlightthickness=0,
        )

        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        root = tk.Frame(canvas, bg=Theme.BG)
        canvas_window = canvas.create_window((0, 0), window=root, anchor="nw")

        def configure_scroll(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfig(canvas_window, width=event.width)

        def configure_canvas(_event):
            canvas.configure(scrollregion=canvas.bbox("all"))

        canvas.bind("<Configure>", configure_scroll)
        root.bind("<Configure>", configure_canvas)

        def on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        self._mousewheel_binding = _ScopedMousewheelBinding(self, canvas, on_mousewheel)

        content = tk.Frame(root, bg=Theme.BG)
        content.pack(fill="both", expand=True, padx=24, pady=20)

        header = self._make_card(content)
        title_row = tk.Frame(header, bg=Theme.GRAYPILL)
        title_row.pack(fill="x")
        if HAS_TRAY:
            try:
                from PIL import Image, ImageTk

                icon_path = resource_path(FileConfig.ICON_FILE)
                img = Image.open(icon_path).convert("RGBA")
                img = img.resize((56, 56), Image.Resampling.LANCZOS)
                self._app_icon = ImageTk.PhotoImage(img)
                tk.Label(title_row, image=self._app_icon, bg=Theme.GRAYPILL).pack(
                    side="left", padx=(0, 12)
                )
            except Exception:
                pass

        title_txt = tk.Frame(title_row, bg=Theme.GRAYPILL)
        title_txt.pack(side="left", fill="both", expand=True)
        tk.Label(
            title_txt,
            text=f"{AboutConfig.APP_NAME} v{AboutConfig.VERSION}",
            font=("Segoe UI", 18, "bold"),
            fg=Theme.TEXT,
            bg=Theme.GRAYPILL,
            anchor="w",
        ).pack(anchor="w")
        tk.Label(
            title_txt,
            text=AboutConfig.APP_NAME_CN,
            font=("Segoe UI", 11),
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))

        desc_card = self._make_card(content, title="项目说明")
        description = (
            "本软件用于战雷全真模式辅助计时，聚焦复活周期管理与基础导航信息。\n\n"
            "核心特性：\n"
            "• 使用 8111 遥测与版本化静态数据\n"
            "• 自动检测出生/死亡/着陆状态\n"
            "• 战区导航、燃油管理、检查清单等辅助能力\n"
            "• 开源维护，可审查与持续迭代"
        )
        tk.Label(
            desc_card,
            text=description,
            font=("Segoe UI", 10),
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            justify="left",
            anchor="w",
            wraplength=780,
        ).pack(fill="x")

        links_card = self._make_card(content, title="链接与隐私")
        if AboutConfig.GITHUB_URL:
            row = tk.Frame(links_card, bg=Theme.GRAYPILL)
            row.pack(fill="x", pady=(0, 6))
            tk.Label(
                row,
                text="项目主页：",
                font=("Segoe UI", 10),
                fg=Theme.TEXT_DIM,
                bg=Theme.GRAYPILL,
            ).pack(side="left")
            github_btn = tk.Label(
                row,
                text=AboutConfig.GITHUB_URL,
                font=("Segoe UI", 10, "underline"),
                fg=Theme.BLUE,
                bg=Theme.GRAYPILL,
                cursor="hand2",
            )
            github_btn.pack(side="left")
            style_clickable_surface(github_btn)
            github_btn.bind("<Button-1>", lambda _e: self._open_url(AboutConfig.GITHUB_URL))

        privacy_desc = (
            "本应用收集匿名 DAU 数据（设备ID、版本号等）用于统计分析，不涉及个人身份。\n"
            "详细字段与禁用方式请查看隐私政策。"
        )
        tk.Label(
            links_card,
            text=privacy_desc,
            font=("Segoe UI", 10),
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            justify="left",
            anchor="w",
            wraplength=780,
        ).pack(fill="x")
        privacy_link = tk.Label(
            links_card,
            text="查看完整隐私政策",
            font=("Segoe UI", 10, "underline"),
            fg=Theme.BLUE,
            bg=Theme.GRAYPILL,
            cursor="hand2",
            anchor="w",
        )
        privacy_link.pack(anchor="w", pady=(6, 0))
        style_clickable_surface(privacy_link)
        privacy_link.bind(
            "<Button-1>",
            lambda _e: self._open_url(f"{AboutConfig.GITHUB_URL}/blob/main/docs/PRIVACY.md"),
        )

        sponsor_card = self._make_card(content, title="支持作者")
        tk.Label(
            sponsor_card,
            text="如果这个工具对你有帮助，欢迎支持持续维护。",
            font=("Segoe UI", 10),
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="w",
        ).pack(anchor="w", pady=(0, 8))
        sponsor_frame = tk.Frame(sponsor_card, bg=Theme.GRAYPILL)
        sponsor_frame.pack(fill="x")
        for name, url, img_file in AboutConfig.SPONSOR_LINKS:
            self._add_sponsor_item(sponsor_frame, name, url, img_file)

        legal_card = self._make_card(content, title="许可证与声明")
        copyright_text = (
            f"作者：{AboutConfig.AUTHOR}\n\n"
            "MIT License\n"
            f"Copyright © 2024-2026 {AboutConfig.AUTHOR}\n\n"
            "War Thunder 及相关商标归 Gaijin Entertainment AG 及其子公司所有。\n"
            "本软件为独立项目，与 Gaijin Entertainment AG 无关联。\n"
            "请自行确保使用行为符合用户协议，风险由用户自行承担。"
        )
        tk.Label(
            legal_card,
            text=copyright_text,
            font=("Segoe UI", 10),
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            justify="left",
            anchor="w",
            wraplength=780,
        ).pack(fill="x")

        footer = tk.Frame(content, bg=Theme.BG)
        footer.pack(fill="x", pady=(6, 0))
        close_btn = tk.Button(
            footer,
            text="关闭",
            command=self._close,
            font=("Segoe UI", 10),
            bg=Theme.GRAYPILL,
            fg=Theme.TEXT,
            bd=0,
            relief="flat",
            padx=20,
            pady=6,
            cursor="hand2",
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
            highlightcolor=Theme.BORDER,
            activebackground=Theme.SEPARATOR,
            activeforeground=Theme.TEXT,
        )
        close_btn.pack(side="right")

    def _make_card(self, parent, title: str = ""):
        """创建统一的 Fluent 卡片区块。"""
        card_shell = tk.Frame(parent, bg=Theme.SEPARATOR, bd=0, highlightthickness=0)
        card_shell.pack(fill="x", pady=(0, 10))
        card = tk.Frame(card_shell, bg=Theme.GRAYPILL, bd=0, highlightthickness=0)
        card.pack(fill="both", expand=True, padx=1, pady=1)
        body = tk.Frame(card, bg=Theme.GRAYPILL)
        body.pack(fill="both", expand=True, padx=12, pady=10)
        if title:
            tk.Label(
                body,
                text=title,
                font=("Segoe UI", 12, "bold"),
                fg=Theme.TEXT,
                bg=Theme.GRAYPILL,
                anchor="w",
            ).pack(anchor="w", pady=(0, 8))
        return body

    def _add_sponsor_item(self, parent, name: str, url: str, img_file: str):
        bg = str(parent.cget("bg") or Theme.GRAYPILL)
        item_frame = tk.Frame(parent, bg=bg)
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

                img_lbl = tk.Label(item_frame, image=photo, bg=bg, cursor="hand2" if url else "")
                img_lbl.pack()
                if url:
                    style_clickable_surface(img_lbl)
                    img_lbl.bind("<Button-1>", lambda e, u=url: self._open_url(u))

                tk.Label(
                    item_frame, text=name, font=("Segoe UI", 10), fg=Theme.TEXT_DIM, bg=bg
                ).pack(pady=(5, 0))
                img_loaded = True
            except Exception:
                pass

        if not img_loaded:
            btn = tk.Button(
                item_frame,
                text=name,
                font=("Segoe UI", 11),
                bg=Theme.GRAYPILL,
                fg=Theme.TEXT,
                bd=0,
                padx=18,
                pady=8,
                relief="flat",
                highlightthickness=1,
                highlightbackground=Theme.BORDER,
                highlightcolor=Theme.BORDER,
                activebackground=Theme.SEPARATOR,
                activeforeground=Theme.TEXT,
                cursor="hand2" if url else "",
            )
            btn.pack()
            if url:
                btn.config(command=lambda u=url: self._open_url(u))

    def _open_url(self, url: str):
        if url:
            with contextlib.suppress(Exception):
                webbrowser.open(url)

    def _close(self):
        self.destroy()

    def destroy(self) -> None:
        binding = getattr(self, "_mousewheel_binding", None)
        if binding is not None:
            binding.cleanup()
        super().destroy()

    def _center_on_parent(self, parent):
        self._center_dialog_on_parent(parent)
