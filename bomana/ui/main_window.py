"""Main window layout builder."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import TYPE_CHECKING

from bomana.config import (
    ENABLE_CCRP,
    BombConfig,
    OverspeedConfig,
    PanelConfig,
    Theme,
    UIConfig,
    ZoneConfig,
)
from bomana.ui.icon_assets import IconManager
from bomana.ui.text_utils import bind_dynamic_wrap, measure_min_width
from bomana.ui.widgets import HeadingTape, Pill

if TYPE_CHECKING:
    from bomana.ui.app import App


@dataclass(slots=True)
class NavListRow:
    """Stable multi-column row for zone/airport lists."""

    row_index: int
    icon_lbl: tk.Label
    direction_lbl: tk.Label
    distance_lbl: tk.Label
    relative_lbl: tk.Label | None = None


@dataclass(slots=True)
class MainWindowBuilder:
    """Build a stable grid-based main window skeleton for the App."""

    app: App

    _NAV_DISTANCE_SAMPLE = "999.9km"
    _NAV_RELATIVE_SAMPLE = "+179.99°"

    def build(self) -> None:
        app = self.app

        app.main_frame = tk.Frame(app.root, bg=Theme.BG, bd=0, highlightthickness=0)
        app.main_frame.pack(fill="both", expand=True)

        app.surface_frame = tk.Frame(app.main_frame, bg=Theme.BG, bd=0, highlightthickness=0)
        app.surface_frame.pack(fill="both", expand=True)
        app.surface_frame.grid_columnconfigure(0, weight=1)
        app.surface_frame.grid_rowconfigure(1, weight=1)

        self._build_top_card()
        self._build_mid_cards()
        self._build_bottom_card()

    def _create_card(
        self,
        parent: tk.Misc,
        *,
        row: int,
        pady: tuple[int, int] = (0, 0),
        padx: int = 0,
    ) -> tuple[tk.Frame, tk.Frame]:
        shell = tk.Frame(
            parent,
            bg=Theme.GRAYPILL,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.SEPARATOR,
            highlightcolor=Theme.SEPARATOR,
        )
        shell.grid(row=row, column=0, sticky="ew", padx=padx, pady=pady)
        shell.grid_columnconfigure(0, weight=1)

        body = tk.Frame(shell, bg=Theme.GRAYPILL, bd=0, highlightthickness=0)
        body.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=max(1, int(self.app.scale)),
            pady=max(1, int(self.app.scale)),
        )
        body.grid_columnconfigure(0, weight=1)
        return shell, body

    def _bind_label_wrap(self, label: tk.Label, parent: tk.Misc, *, margin: int = 0) -> None:
        """Keep label wrapping aligned with its live container width."""
        bind_dynamic_wrap(label, parent, minimum=80, margin=margin)

    def _configure_heading_status_row(
        self,
        row: tk.Frame,
        *,
        turn_label: tk.Label,
        status_label: tk.Label,
        info_label: tk.Label,
    ) -> None:
        """Give heading status rows elastic columns and live wrapping."""
        row.grid_columnconfigure(0, weight=0)
        row.grid_columnconfigure(1, weight=1, uniform="heading_status")
        row.grid_columnconfigure(2, weight=1, uniform="heading_status")
        row.grid_columnconfigure(3, weight=2)

        def update_wrap(event=None) -> None:
            width = int(getattr(event, "width", 0) or row.winfo_width() or 0)
            if width <= 1:
                return
            turn_label.configure(wraplength=max(44, int(width * 0.22)))
            status_label.configure(wraplength=max(44, int(width * 0.22)))
            info_label.configure(wraplength=max(74, int(width * 0.34)))

        row.bind("<Configure>", update_wrap, add="+")

    def _build_bottom_card(self) -> None:
        app = self.app
        s = app.scale
        font_hint = app._get_font("hint")
        font_debug = app._get_font("debug")
        btn_pad_x = int(6 * s)
        btn_pad_y = max(1, int(1 * s))

        app.bottom_card, bottom_frame = self._create_card(
            app.surface_frame,
            row=2,
            pady=(int(4 * s), 0),
            padx=int(1 * s),
        )
        bottom_frame.grid_rowconfigure(1, weight=1)
        bottom_frame.grid_columnconfigure(0, weight=1)

        app.nudge_row = tk.Frame(bottom_frame, bg=Theme.GRAYPILL)
        app.nudge_row.grid(row=0, column=0, sticky="ew", padx=int(6 * s), pady=(int(4 * s), 0))
        app.nudge_row.grid_columnconfigure(0, weight=1)

        app.nudge_lbl = tk.Label(
            app.nudge_row,
            text=app._nudge_text(),
            font=font_hint,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
            wraplength=int(420 * s),
        )
        app.nudge_lbl.grid(row=0, column=0, sticky="ew")

        app.star_lbl = tk.Label(
            app.nudge_row,
            text="GitHub Star",
            font=font_hint,
            fg=Theme.BLUE,
            bg=Theme.BG,
            cursor="hand2",
            padx=int(8 * s),
            pady=max(1, int(1 * s)),
        )
        app.star_lbl.bind("<Button-1>", lambda e: app._open_star_url())
        app.star_lbl.bind("<Enter>", lambda e: app.star_lbl.config(fg=Theme.TEXT, bg=Theme.BORDER))
        app.star_lbl.bind("<Leave>", lambda e: app.star_lbl.config(fg=Theme.BLUE, bg=Theme.BG))
        app.star_lbl.grid(row=0, column=1, sticky="e", padx=(int(8 * s), 0))

        app.hint_row = tk.Frame(bottom_frame, bg=Theme.GRAYPILL)
        app.hint_row.grid(row=1, column=0, sticky="ew", padx=int(6 * s), pady=(0, int(4 * s)))
        app.hint_row.grid_columnconfigure(0, weight=1)

        app.hint_lbl = tk.Label(
            app.hint_row,
            text=app._hint_text(),
            font=font_hint,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        app.hint_lbl.grid(row=0, column=0, sticky="ew")

        app.debug_ctrl_row = tk.Frame(bottom_frame, bg=Theme.GRAYPILL)
        app.debug_ctrl_row.grid_columnconfigure(3, weight=1)

        debug_btn_font = font_hint
        app.debug_source_btn = tk.Label(
            app.debug_ctrl_row,
            text="数据源: 模拟",
            font=debug_btn_font,
            fg=Theme.GREEN,
            bg=Theme.BG,
            cursor="hand2",
            padx=btn_pad_x,
            pady=btn_pad_y,
        )
        app.debug_source_btn.grid(row=0, column=0, sticky="w")
        app.debug_source_btn.bind("<Button-1>", lambda e: app._toggle_debug_mock_mode())
        app.debug_source_btn.bind(
            "<Enter>", lambda e: app.debug_source_btn.config(bg=Theme.BORDER, fg=Theme.TEXT)
        )
        app.debug_source_btn.bind("<Leave>", lambda e: app._update_debug_controls())

        app.debug_prev_btn = tk.Label(
            app.debug_ctrl_row,
            text="◀",
            font=debug_btn_font,
            fg=Theme.TEXT,
            bg=Theme.BG,
            cursor="hand2",
            padx=btn_pad_x,
            pady=btn_pad_y,
        )
        app.debug_prev_btn.grid(row=0, column=1, sticky="w", padx=(int(6 * s), 0))
        app.debug_prev_btn.bind("<Button-1>", lambda e: app._cycle_debug_scene(-1))
        app.debug_prev_btn.bind("<Enter>", lambda e: app.debug_prev_btn.config(bg=Theme.BORDER))
        app.debug_prev_btn.bind("<Leave>", lambda e: app.debug_prev_btn.config(bg=Theme.BG))

        app.debug_scene_lbl = tk.Label(
            app.debug_ctrl_row,
            text="",
            font=debug_btn_font,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        app.debug_scene_lbl.grid(row=0, column=2, sticky="w", padx=(int(6 * s), int(4 * s)))

        app.debug_next_btn = tk.Label(
            app.debug_ctrl_row,
            text="▶",
            font=debug_btn_font,
            fg=Theme.TEXT,
            bg=Theme.BG,
            cursor="hand2",
            padx=btn_pad_x,
            pady=btn_pad_y,
        )
        app.debug_next_btn.grid(row=0, column=3, sticky="w")
        app.debug_next_btn.bind("<Button-1>", lambda e: app._cycle_debug_scene(1))
        app.debug_next_btn.bind("<Enter>", lambda e: app.debug_next_btn.config(bg=Theme.BORDER))
        app.debug_next_btn.bind("<Leave>", lambda e: app.debug_next_btn.config(bg=Theme.BG))

        app.debug_hint_lbl = tk.Label(
            app.debug_ctrl_row,
            text="提示: 无 8111 数据时将自动使用模拟场景",
            font=debug_btn_font,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        app.debug_hint_lbl.grid(row=0, column=4, sticky="e")

        app.diag_lbl = tk.Label(
            bottom_frame,
            text="",
            font=font_debug,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
            wraplength=int(UIConfig.DEBUG_WRAP_LENGTH * s),
        )
        app._update_debug_controls()

    def _build_top_card(self) -> None:
        app = self.app
        s = app.scale
        app.top_frame, app.top_content = self._create_card(
            app.surface_frame,
            row=0,
            pady=(0, int(4 * s)),
            padx=int(1 * s),
        )
        app.top_content.grid_columnconfigure(0, weight=1)

        font_timer = app._get_font("timer")
        font_life = app._get_font("life")
        font_cycle = app._get_font("cycle")
        pill_font = app._get_font("pill")
        font_status = app._get_font("status")
        font_hint = app._get_font("hint")

        app.top_row1 = tk.Frame(app.top_content, bg=Theme.GRAYPILL)
        app.top_row1.grid(row=0, column=0, sticky="ew", padx=int(8 * s), pady=(int(6 * s), 0))
        app.top_row1.grid_columnconfigure(0, weight=1)

        app.timer_lbl = tk.Label(
            app.top_row1,
            text="--:--",
            font=font_timer,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        app.timer_lbl.grid(row=0, column=0, sticky="w")

        right = tk.Frame(app.top_row1, bg=Theme.GRAYPILL)
        right.grid(row=0, column=1, sticky="e", padx=(int(12 * s), 0))
        app.life_lbl = tk.Label(
            right,
            text="未复活",
            font=font_life,
            fg=Theme.BLUE,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        app.life_lbl.grid(row=0, column=0, sticky="e")
        app.cycle_lbl = tk.Label(
            right,
            text="未开始",
            font=font_cycle,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        app.cycle_lbl.grid(row=1, column=0, sticky="e", pady=(int(2 * s), 0))

        app.top_row2 = tk.Frame(app.top_content, bg=Theme.GRAYPILL)
        pad_top, pad_bot = UIConfig.PADDING_ROW2
        app.top_row2.grid(
            row=1, column=0, sticky="ew", padx=int(8 * s), pady=(int(pad_top * s), int(pad_bot * s))
        )
        app.top_row2.grid_columnconfigure(1, weight=1)

        badge_row = tk.Frame(app.top_row2, bg=Theme.GRAYPILL)
        badge_row.grid(row=0, column=0, sticky="w")
        app.badge_main = Pill(badge_row, text="IDLE", fg=Theme.TEXT, bg=Theme.BG, font=pill_font)
        app.badge_main.pack(side="left")
        app.badge_flight = Pill(badge_row, text="—", fg=Theme.TEXT_DIM, bg=Theme.BG, font=pill_font)
        app.badge_flight.pack(side="left", padx=(int(UIConfig.SPACING_BADGE * s), 0))
        app.badge_lock = Pill(badge_row, text="锁定", fg=Theme.TEXT, bg=Theme.BLUE, font=pill_font)
        app.badge_lock.pack(side="left", padx=(int(UIConfig.SPACING_BADGE * s), 0))
        app.badge_gear = Pill(badge_row, text="", fg=Theme.TEXT, bg=Theme.ORANGE, font=pill_font)
        app.gear_progress_bar = tk.Frame(app.badge_gear, bg=Theme.BLUE, height=int(3 * s))

        app.status_txt = tk.Label(
            app.top_row2,
            text="等待中",
            font=font_status,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        app.status_txt.grid(row=0, column=1, sticky="e")
        app._update_lock_badge()

        app.history_mode_frame = tk.Frame(app.top_content, bg=Theme.GRAYPILL)
        app._history_mode_pad_y = (int(pad_top * s), int(max(4, pad_bot * s)))
        history_header = tk.Frame(app.history_mode_frame, bg=Theme.GRAYPILL)
        history_header.grid(row=0, column=0, sticky="ew")
        history_header.grid_columnconfigure(0, weight=1)
        history_title_font = app._scaled_font(
            (UIConfig.FONT_STATUS[0], UIConfig.FONT_STATUS[1], "bold")
        )
        app.history_mode_title_lbl = tk.Label(
            history_header,
            text="空历速度监视",
            font=history_title_font,
            fg=Theme.TEXT,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        app.icons.configure_label(
            app.history_mode_title_lbl,
            icon="clock",
            text="空历速度监视",
            size=IconManager.scaled_size(18, s, min_size=18),
        )
        app.history_mode_title_lbl.grid(row=0, column=0, sticky="w")
        app.history_mode_phase_lbl = tk.Label(
            history_header,
            text="等待中",
            font=font_hint,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        app.history_mode_phase_lbl.grid(row=0, column=1, sticky="e")
        app.history_mode_hint_lbl = tk.Label(
            app.history_mode_frame,
            text="历史模式已隐藏计时和其他扩展，仅保留速度提醒。",
            font=font_hint,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
        )
        app.history_mode_hint_lbl.grid(row=1, column=0, sticky="ew", pady=(int(2 * s), 0))

        app.speed_row = tk.Frame(app.top_content, bg=Theme.GRAYPILL)
        pad_top, pad_bot = UIConfig.PADDING_SPEED_STRIP
        app.speed_row.grid(
            row=3, column=0, sticky="ew", padx=int(8 * s), pady=(int(pad_top * s), int(pad_bot * s))
        )
        app.speed_row.grid_columnconfigure(0, weight=1)
        speed_font = app._get_font("hint")
        speed_model_font = app._scaled_font(UIConfig.FONT_HINT, size_mult=0.92, min_size=7)
        app.speed_header_row = tk.Frame(app.speed_row, bg=Theme.GRAYPILL)
        app.speed_header_row.grid(row=0, column=0, sticky="ew")
        app.speed_header_row.grid_columnconfigure(0, weight=1)
        app.speed_meta_frame = tk.Frame(app.speed_header_row, bg=Theme.GRAYPILL)
        app.speed_meta_frame.grid(row=0, column=0, sticky="ew")
        app.speed_meta_frame.grid_columnconfigure(2, weight=1)
        app.speed_state_lbl = tk.Label(
            app.speed_meta_frame,
            text="速度监视",
            font=speed_font,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        app.speed_state_lbl.grid(row=0, column=0, sticky="w")
        app.speed_threshold_btn = tk.Label(
            app.speed_meta_frame,
            text="点我调速度阈值",
            font=app._scaled_font(UIConfig.FONT_HINT, size_mult=0.88, min_size=7),
            fg=Theme.BLUE,
            bg=Theme.GRAYPILL,
            anchor="w",
            cursor="hand2",
            padx=max(5, int(6 * s)),
            pady=max(1, int(1 * s)),
        )
        app.speed_threshold_btn.grid(row=0, column=1, sticky="w", padx=(max(6, int(8 * s)), 0))
        app.speed_threshold_btn.bind(
            "<Button-1>",
            lambda _e: app._show_settings(initial_tab="空速"),
        )
        app.speed_threshold_btn.bind(
            "<Enter>",
            lambda _e: app.speed_threshold_btn.config(fg=Theme.TEXT, bg=Theme.BG),
        )
        app.speed_threshold_btn.bind(
            "<Leave>",
            lambda _e: app.speed_threshold_btn.config(fg=Theme.BLUE, bg=Theme.GRAYPILL),
        )
        app.speed_model_lbl = tk.Label(
            app.speed_meta_frame,
            text="机型未识别",
            font=speed_model_font,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        app.speed_model_lbl.grid(row=1, column=0, columnspan=3, sticky="w")
        app.speed_value_lbl = tk.Label(
            app.speed_header_row,
            text="--",
            font=speed_font,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        app.speed_value_lbl.grid(row=0, column=1, sticky="e")

        speed_bar_height = max(8, int(UIConfig.SPEED_STRIP_HEIGHT * s))
        speed_bar_thickness = max(3, int(UIConfig.SPEED_STRIP_THICKNESS * s))
        app.speed_bar_host = tk.Frame(app.speed_row, bg=Theme.GRAYPILL, height=speed_bar_height)
        app.speed_bar_host.grid(row=1, column=0, sticky="ew", pady=(max(1, int(2 * s)), 0))
        app.speed_bar_host.grid_propagate(False)
        app.speed_bar_bg = tk.Frame(
            app.speed_bar_host, bg=Theme.SEPARATOR, height=speed_bar_thickness
        )
        app.speed_bar_bg.place(relx=0, rely=0.5, relwidth=1, anchor="w")
        app.speed_bar_fill = tk.Frame(app.speed_bar_bg, bg=Theme.GREEN, height=speed_bar_thickness)
        app.speed_bar_fill.place(relx=0, rely=0, relwidth=0, relheight=1)
        app.speed_bar_markers = {}
        for name, relx, color in (
            ("caution", OverspeedConfig.CAUTION_RATIO, Theme.BLUE),
            ("warning", OverspeedConfig.WARNING_RATIO, Theme.YELLOW),
            ("critical", OverspeedConfig.CRITICAL_RATIO, Theme.RED),
        ):
            marker = tk.Frame(
                app.speed_bar_bg,
                bg=color,
                width=max(1, int(2 * s)),
                height=max(speed_bar_thickness + 2, int(7 * s)),
            )
            marker.place(relx=max(0.0, min(1.0, relx)), rely=0.5, anchor="center")
            app.speed_bar_markers[name] = marker

        bar_height = int(UIConfig.PROGRESS_BAR_HEIGHT * s)
        app.progress_frame = tk.Frame(app.top_content, bg=Theme.GRAYPILL, height=bar_height)
        pad_top, pad_bot = UIConfig.PADDING_PROGRESS
        app.progress_frame.grid(
            row=4, column=0, sticky="ew", padx=int(8 * s), pady=(int(pad_top * s), int(pad_bot * s))
        )
        app.progress_frame.grid_propagate(False)
        bar_thickness = int(UIConfig.PROGRESS_BAR_THICKNESS * s)
        app.bar_bg = tk.Frame(app.progress_frame, bg=Theme.SEPARATOR, height=bar_thickness)
        app.bar_bg.place(relx=0, rely=0.5, relwidth=1, anchor="w")
        app.bar_fill = tk.Frame(app.bar_bg, bg=Theme.BLUE, height=bar_thickness)
        app.bar_fill.place(relx=0, rely=0, relwidth=0, relheight=1)

    def _build_mid_cards(self) -> None:
        app = self.app
        s = app.scale

        app.mid_frame = tk.Frame(app.surface_frame, bg=Theme.BG)
        app.mid_frame.grid(row=1, column=0, sticky="ew", pady=(0, int(4 * s)))
        app.mid_frame.grid_columnconfigure(0, weight=1)
        app.mid_frame.grid_columnconfigure(1, weight=1)

        app.zone_frame = tk.Frame(
            app.mid_frame,
            bg=Theme.GRAYPILL,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.SEPARATOR,
            highlightcolor=Theme.SEPARATOR,
        )
        self._build_zone_card()

        app.chk_frame = tk.Frame(
            app.mid_frame,
            bg=Theme.GRAYPILL,
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.SEPARATOR,
            highlightcolor=Theme.SEPARATOR,
        )
        app.chk_border_frame = tk.Frame(app.chk_frame, bg=Theme.BORDER, width=max(1, int(1 * s)))
        app.chk_content_frame = tk.Frame(app.chk_frame, bg=Theme.GRAYPILL)
        app._rebuild_checklist()

    def _build_nav_row_pool(
        self,
        parent: tk.Misc,
        count: int,
        font: tuple[str, int],
        *,
        bg: str,
        show_relative: bool,
    ) -> list[NavListRow]:
        pool: list[NavListRow] = []
        scale = float(getattr(self.app, "scale", 1.0) or 1.0)
        parent.grid_columnconfigure(0, minsize=max(20, int(24 * self.app.scale)))
        parent.grid_columnconfigure(1, weight=1)
        parent.grid_columnconfigure(
            2,
            minsize=measure_min_width(
                font,
                self._NAV_DISTANCE_SAMPLE,
                fallback_scale=scale,
            ),
        )
        if show_relative:
            parent.grid_columnconfigure(
                3,
                minsize=measure_min_width(
                    font,
                    self._NAV_RELATIVE_SAMPLE,
                    fallback_scale=scale,
                ),
            )
        for _ in range(count):
            row_index = len(pool)

            icon_lbl = tk.Label(
                parent,
                text="",
                font=font,
                fg=Theme.TEXT_MUTED,
                bg=bg,
                anchor="center",
            )
            icon_lbl.grid(row=row_index, column=0, sticky="ew")
            icon_lbl.grid_remove()

            direction_lbl = tk.Label(
                parent,
                text="",
                font=font,
                fg=Theme.TEXT_MUTED,
                bg=bg,
                anchor="w",
                justify="left",
            )
            direction_lbl.grid(row=row_index, column=1, sticky="ew")
            direction_lbl.grid_remove()

            distance_lbl = tk.Label(
                parent,
                text="",
                font=font,
                fg=Theme.TEXT_MUTED,
                bg=bg,
                anchor="e",
            )
            distance_lbl.grid(
                row=row_index,
                column=2,
                sticky="ew",
                padx=(int(6 * self.app.scale), 0),
                pady=(0, max(1, int(self.app.scale))),
            )
            distance_lbl.grid_remove()

            relative_lbl = None
            if show_relative:
                relative_lbl = tk.Label(
                    parent,
                    text="",
                    font=font,
                    fg=Theme.TEXT_MUTED,
                    bg=bg,
                    anchor="e",
                )
                relative_lbl.grid(
                    row=row_index,
                    column=3,
                    sticky="ew",
                    padx=(int(8 * self.app.scale), 0),
                    pady=(0, max(1, int(self.app.scale))),
                )
                relative_lbl.grid_remove()

            pool.append(
                NavListRow(
                    row_index=row_index,
                    icon_lbl=icon_lbl,
                    direction_lbl=direction_lbl,
                    distance_lbl=distance_lbl,
                    relative_lbl=relative_lbl,
                )
            )
        return pool

    def _build_panel_close_button(
        self,
        parent: tk.Misc,
        *,
        panel_key: str,
        font,
        scale: float,
    ) -> tk.Label:
        app = self.app
        close_btn = tk.Label(
            parent,
            text="关闭",
            font=font,
            fg=Theme.TEXT,
            bg=Theme.BG,
            cursor="hand2",
            padx=max(8, int(8 * scale)),
            pady=max(1, int(1 * scale)),
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
            highlightcolor=Theme.BORDER,
        )
        close_btn.bind("<Button-1>", lambda e, key=panel_key: app._toggle_panel(key))
        close_btn.bind(
            "<Enter>",
            lambda e, btn=close_btn: btn.config(
                fg=Theme.RED,
                bg=Theme.BORDER,
                highlightbackground=Theme.RED,
                highlightcolor=Theme.RED,
            ),
        )
        close_btn.bind(
            "<Leave>",
            lambda e, btn=close_btn: btn.config(
                fg=Theme.TEXT,
                bg=Theme.BG,
                highlightbackground=Theme.BORDER,
                highlightcolor=Theme.BORDER,
            ),
        )
        return close_btn

    def _build_zone_card(self) -> None:
        app = self.app
        s = app.scale
        pad_x = int(8 * s)
        app.zone_frame.grid_columnconfigure(0, weight=1)

        font_title = app._get_font("zone_title")
        font_item = app._get_font("zone_item")
        font_heading = font_item
        legend_font = app._scaled_font(UIConfig.FONT_ZONE_ITEM, size_mult=0.85, min_size=7)
        status_font = app._scaled_font(UIConfig.FONT_ZONE_ITEM, size_mult=0.95, min_size=7)

        app.zone_header_frame = tk.Frame(app.zone_frame, bg=Theme.GRAYPILL)
        app.zone_header_frame.grid(
            row=0, column=0, sticky="ew", padx=pad_x, pady=(int(4 * s), int(2 * s))
        )
        app.zone_header_frame.grid_columnconfigure(2, weight=1)
        app.zone_title = tk.Label(
            app.zone_header_frame,
            text="导航面板",
            font=font_title,
            fg=Theme.TEXT,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        app.zone_title.grid(row=0, column=0, sticky="w")

        app.heading_lbl = tk.Label(
            app.zone_header_frame,
            text="航向: ---°",
            font=font_heading,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        app.heading_lbl.grid(row=0, column=1, sticky="w", padx=(int(10 * s), 0))

        app.standalone_btn = tk.Label(
            app.zone_header_frame,
            text="切换独立导航窗",
            font=font_item,
            fg=Theme.TEXT_MUTED,
            bg=Theme.BG,
            cursor="hand2",
            padx=int(6 * s),
            pady=max(1, int(1 * s)),
        )
        app.standalone_btn.grid(row=0, column=3, sticky="e")
        app.standalone_btn.bind("<Button-1>", lambda e: app._toggle_navigation_mode())
        app.standalone_btn.bind(
            "<Enter>",
            lambda e: app.standalone_btn.config(
                fg=(Theme.BLUE if PanelConfig.navigation_mode != "standalone" else Theme.GREEN),
                bg=Theme.BORDER,
            ),
        )
        app.standalone_btn.bind("<Leave>", lambda e: app._update_nav_mode_button())
        app._update_nav_mode_button()

        if ZoneConfig.HEADING_TAPE_ENABLED:
            app.heading_tape_frame = tk.Frame(app.zone_frame, bg=Theme.GRAYPILL)
            app.heading_tape_frame.grid(
                row=1, column=0, sticky="ew", padx=pad_x, pady=(int(2 * s), int(4 * s))
            )
            app.heading_tape = HeadingTape(
                app.heading_tape_frame,
                width=int(ZoneConfig.HEADING_TAPE_WIDTH * s),
                height=int(ZoneConfig.HEADING_TAPE_HEIGHT * s),
                text_scale=UIConfig.TEXT_SCALE_MULT,
            )
            app.heading_tape.pack(fill="x", expand=True)

            app.tape_legend_row = tk.Frame(app.heading_tape_frame, bg=Theme.GRAYPILL)
            app.tape_legend_row.pack(fill="x", pady=(int(1 * s), 0))
            legend_left = tk.Label(
                app.tape_legend_row,
                text="⊚战区  ✈友方机场  ✈敌方机场  ✕摧毁目标",
                font=legend_font,
                fg=Theme.TEXT_MUTED,
                bg=Theme.GRAYPILL,
                anchor="w",
            )
            legend_left.pack(side="left", fill="x", expand=True)
            app.tape_tolerance_legend = tk.Label(
                app.tape_legend_row,
                text="",
                font=legend_font,
                fg=Theme.TEXT_MUTED,
                bg=Theme.GRAYPILL,
                anchor="e",
            )
            app.tape_tolerance_legend.pack(side="right", padx=(0, int(4 * s)))

            app.tape_zone_row = tk.Frame(app.heading_tape_frame, bg=Theme.GRAYPILL)
            app.tape_zone_row.pack(fill="x", pady=(int(2 * s), 0))
            app.tape_zone_label = tk.Label(
                app.tape_zone_row,
                text="⊚战区:",
                font=status_font,
                fg=Theme.RED,
                bg=Theme.GRAYPILL,
                anchor="w",
            )
            app.tape_zone_label.grid(row=0, column=0, sticky="w")
            app.tape_zone_turn = tk.Label(
                app.tape_zone_row,
                text="",
                font=status_font,
                fg=Theme.TEXT_MUTED,
                bg=Theme.GRAYPILL,
                anchor="w",
                justify="left",
            )
            app.tape_zone_turn.grid(row=0, column=1, sticky="ew", padx=(int(6 * s), 0))
            app.tape_zone_status = tk.Label(
                app.tape_zone_row,
                text="",
                font=status_font,
                fg=Theme.TEXT_MUTED,
                bg=Theme.GRAYPILL,
                anchor="w",
                justify="left",
            )
            app.tape_zone_status.grid(row=0, column=2, sticky="ew", padx=(int(8 * s), 0))
            app.tape_zone_info = tk.Label(
                app.tape_zone_row,
                text="",
                font=status_font,
                fg=Theme.TEXT_MUTED,
                bg=Theme.GRAYPILL,
                anchor="e",
                justify="right",
            )
            app.tape_zone_info.grid(row=0, column=3, sticky="ew", padx=(int(8 * s), 0))
            self._configure_heading_status_row(
                app.tape_zone_row,
                turn_label=app.tape_zone_turn,
                status_label=app.tape_zone_status,
                info_label=app.tape_zone_info,
            )
            app.tape_zone_tolerance = tk.Label(
                app.tape_zone_row,
                text="",
                font=status_font,
                fg=Theme.TEXT_MUTED,
                bg=Theme.GRAYPILL,
                anchor="e",
            )

            app.tape_friendly_row = tk.Frame(app.heading_tape_frame, bg=Theme.GRAYPILL)
            app.tape_friendly_row.pack(fill="x", pady=(int(1 * s), 0))
            app.tape_friendly_label = tk.Label(
                app.tape_friendly_row,
                text="✈友方:",
                font=status_font,
                fg=Theme.BLUE,
                bg=Theme.GRAYPILL,
                anchor="w",
            )
            app.tape_friendly_label.grid(row=0, column=0, sticky="w")
            app.tape_friendly_turn = tk.Label(
                app.tape_friendly_row,
                text="",
                font=status_font,
                fg=Theme.TEXT_MUTED,
                bg=Theme.GRAYPILL,
                anchor="w",
                justify="left",
            )
            app.tape_friendly_turn.grid(row=0, column=1, sticky="ew", padx=(int(6 * s), 0))
            app.tape_friendly_status = tk.Label(
                app.tape_friendly_row,
                text="",
                font=status_font,
                fg=Theme.TEXT_MUTED,
                bg=Theme.GRAYPILL,
                anchor="w",
                justify="left",
            )
            app.tape_friendly_status.grid(row=0, column=2, sticky="ew", padx=(int(8 * s), 0))
            app.tape_friendly_info = tk.Label(
                app.tape_friendly_row,
                text="",
                font=status_font,
                fg=Theme.TEXT_MUTED,
                bg=Theme.GRAYPILL,
                anchor="e",
                justify="right",
            )
            app.tape_friendly_info.grid(row=0, column=3, sticky="ew", padx=(int(8 * s), 0))
            self._configure_heading_status_row(
                app.tape_friendly_row,
                turn_label=app.tape_friendly_turn,
                status_label=app.tape_friendly_status,
                info_label=app.tape_friendly_info,
            )

            app.tape_turn_lbl = app.tape_zone_turn
            app.tape_deviation_lbl = app.tape_zone_status
            app.tape_tolerance_lbl = app.tape_zone_tolerance
            app.tape_info_container = None
            app._tape_info_labels = []
        else:
            app.heading_tape_frame = None
            app.heading_tape = None
            app.tape_info_container = None
            app._tape_info_labels = []
            app.tape_turn_lbl = None
            app.tape_deviation_lbl = None
            app.tape_tolerance_lbl = None
            app.tape_zone_row = None
            app.tape_friendly_row = None
            app.tape_friendly_turn = None
            app.tape_friendly_info = None
            app.tape_friendly_status = None
            app.tape_zone_info = None

        font_alert = app._get_font("zone_title")
        app.zone_alert_lbl = tk.Label(
            app.zone_frame,
            text="",
            font=font_alert,
            fg=Theme.RED,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
        )
        app.zone_alert_lbl.grid(row=2, column=0, sticky="ew", padx=pad_x, pady=(0, int(4 * s)))

        app.compact_nav_frame = tk.Frame(app.zone_frame, bg=Theme.GRAYPILL)
        app.compact_nav_frame.grid(row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(10 * s)))
        app.compact_nav_frame.grid_columnconfigure(0, weight=1)
        app.compact_nav_frame.grid_columnconfigure(1, weight=1)

        app.compact_zone_frame = tk.Frame(app.compact_nav_frame, bg=Theme.GRAYPILL)
        app.compact_zone_frame.grid(row=0, column=0, sticky="nsew", padx=(0, int(4 * s)))
        app.compact_zone_title = tk.Label(
            app.compact_zone_frame,
            text="战区",
            font=font_title,
            fg=Theme.RED,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        app.compact_zone_title.pack(fill="x")
        app.compact_zone_list = tk.Frame(app.compact_zone_frame, bg=Theme.GRAYPILL)
        app.compact_zone_list.pack(fill="x")

        app.compact_airport_frame = tk.Frame(app.compact_nav_frame, bg=Theme.GRAYPILL)
        app.compact_airport_frame.grid(row=0, column=1, sticky="nsew", padx=(int(4 * s), 0))
        app.compact_airport_title = tk.Label(
            app.compact_airport_frame,
            text="机场",
            font=font_title,
            fg=Theme.BLUE,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        app.compact_airport_title.pack(fill="x")
        app.compact_airport_list = tk.Frame(app.compact_airport_frame, bg=Theme.GRAYPILL)
        app.compact_airport_list.pack(fill="x")

        app.zone_list_header_frame = tk.Frame(app.zone_frame, bg=Theme.GRAYPILL)
        app.zone_list_header_frame.grid(
            row=3, column=0, sticky="ew", padx=pad_x, pady=(0, int(2 * s))
        )
        app.zone_list_header_frame.grid_columnconfigure(0, weight=1)
        app.zone_list_title_lbl = tk.Label(
            app.zone_list_header_frame,
            text="战区导航",
            font=font_title,
            fg=Theme.TEXT,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        app.zone_list_title_lbl.grid(row=0, column=0, sticky="w")
        app.zone_close_btn = self._build_panel_close_button(
            app.zone_list_header_frame,
            panel_key="show_zones",
            font=font_item,
            scale=s,
        )
        app.zone_close_btn.grid(row=0, column=1, sticky="e")
        app.zone_list_frame = tk.Frame(app.zone_frame, bg=Theme.GRAYPILL)
        app.zone_list_frame.grid(row=4, column=0, sticky="ew", padx=pad_x, pady=(0, int(4 * s)))
        app.airport_header_frame = tk.Frame(app.zone_frame, bg=Theme.GRAYPILL)
        app.airport_header_frame.grid(
            row=5, column=0, sticky="ew", padx=pad_x, pady=(0, int(2 * s))
        )
        app.airport_header_frame.grid_columnconfigure(0, weight=1)
        app.airport_title_lbl = tk.Label(
            app.airport_header_frame,
            text="机场导航",
            font=font_title,
            fg=Theme.TEXT,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        app.airport_title_lbl.grid(row=0, column=0, sticky="w")
        app.airport_close_btn = self._build_panel_close_button(
            app.airport_header_frame,
            panel_key="show_airfields",
            font=font_item,
            scale=s,
        )
        app.airport_close_btn.grid(row=0, column=1, sticky="e")
        app.airport_tape_frame = None
        app.friendly_heading_tape = None
        app.enemy_heading_tape = None
        app.airport_list_frame = tk.Frame(app.zone_frame, bg=Theme.GRAYPILL)
        app.airport_list_frame.grid(row=6, column=0, sticky="ew", padx=pad_x, pady=(0, int(4 * s)))

        app.fuel_header_frame = tk.Frame(app.zone_frame, bg=Theme.GRAYPILL)
        app.fuel_header_frame.grid(row=7, column=0, sticky="ew", padx=pad_x, pady=(0, int(2 * s)))
        app.fuel_header_frame.grid_columnconfigure(1, weight=1)
        app.fuel_title_lbl = tk.Label(
            app.fuel_header_frame,
            text="燃油管理",
            font=font_title,
            fg=Theme.TEXT,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        app.fuel_title_lbl.grid(row=0, column=0, sticky="w")
        fuel_header_right = tk.Frame(app.fuel_header_frame, bg=Theme.GRAYPILL)
        fuel_header_right.grid(row=0, column=1, sticky="e")
        app.fuel_time_lbl = tk.Label(
            fuel_header_right,
            text="--:--",
            font=font_item,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        app.icons.configure_label(
            app.fuel_time_lbl,
            icon="clock",
            text="--:--",
            size=IconManager.scaled_size(18, s, min_size=18),
        )
        app.fuel_time_lbl.pack(side="left")
        app.fuel_return_lbl = tk.Label(
            fuel_header_right,
            text="返航 --",
            font=font_item,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="e",
        )
        app.fuel_return_lbl.pack(side="left", padx=(int(10 * s), 0))
        app.fuel_close_btn = self._build_panel_close_button(
            app.fuel_header_frame,
            panel_key="show_fuel",
            font=font_item,
            scale=s,
        )
        app.fuel_close_btn.grid(row=0, column=2, sticky="e", padx=(int(10 * s), 0))
        app.fuel_info_frame = tk.Frame(app.zone_frame, bg=Theme.GRAYPILL)
        app.fuel_info_frame.grid(row=8, column=0, sticky="ew", padx=pad_x, pady=(0, int(4 * s)))
        app.zone_cdi_lbl = None
        app.friendly_cdi_lbl = None
        app.enemy_cdi_lbl = None

        app.fuel_main_lbl = tk.Label(
            app.fuel_info_frame,
            text="-- kg (--%)",
            font=font_item,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
        )
        app.fuel_main_lbl.pack(fill="x")
        app.fuel_detail_lbl = tk.Label(
            app.fuel_info_frame,
            text="油耗 --kg/min",
            font=font_item,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
        )
        app.fuel_detail_lbl.pack(fill="x")
        app.fuel_alt_lbl = tk.Label(
            app.fuel_info_frame,
            text="高度 --m",
            font=font_item,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
        )
        app.fuel_alt_lbl.pack(fill="x")
        app.fuel_return_detail_lbl = tk.Label(
            app.fuel_info_frame,
            text="返航 --",
            font=font_item,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
            justify="left",
        )
        app.fuel_return_detail_lbl.pack(fill="x")
        self._bind_label_wrap(app.fuel_main_lbl, app.fuel_info_frame)
        self._bind_label_wrap(app.fuel_detail_lbl, app.fuel_info_frame)
        self._bind_label_wrap(app.fuel_alt_lbl, app.fuel_info_frame)
        self._bind_label_wrap(app.fuel_return_detail_lbl, app.fuel_info_frame)

        if ENABLE_CCRP:
            app.bombing_header_frame = tk.Frame(app.zone_frame, bg=Theme.GRAYPILL)
            app.bombing_header_frame.grid(
                row=9, column=0, sticky="ew", padx=pad_x, pady=(0, int(2 * s))
            )
            app.bombing_header_frame.grid_columnconfigure(1, weight=1)
            app.bombing_title_lbl = tk.Label(
                app.bombing_header_frame,
                text="投弹预测",
                font=font_title,
                fg=Theme.TEXT,
                bg=Theme.GRAYPILL,
                anchor="w",
            )
            app.bombing_title_lbl.grid(row=0, column=0, sticky="w")
            font_release = app._get_font("zone_title")
            app.bomb_release_lbl = tk.Label(
                app.bombing_header_frame,
                text="等待目标",
                font=font_release,
                fg=Theme.TEXT_MUTED,
                bg=Theme.GRAYPILL,
                anchor="e",
            )
            app.bomb_release_lbl.grid(row=0, column=1, sticky="e")
            app.bombing_close_btn = self._build_panel_close_button(
                app.bombing_header_frame,
                panel_key="show_bombing",
                font=font_item,
                scale=s,
            )
            app.bombing_close_btn.grid(row=0, column=2, sticky="e", padx=(int(10 * s), 0))
            app.bombing_info_frame = tk.Frame(app.zone_frame, bg=Theme.GRAYPILL)
            app.bombing_info_frame.grid(
                row=10, column=0, sticky="ew", padx=pad_x, pady=(0, int(6 * s))
            )
            app.bomb_select_lbl = tk.Label(
                app.bombing_info_frame,
                text=f"炸弹: {BombConfig.format_bomb_name(BombConfig.selected_bomb)} (点击更换)",
                font=font_item,
                fg=Theme.BLUE,
                bg=Theme.GRAYPILL,
                anchor="w",
                justify="left",
                cursor="hand2",
            )
            app.bomb_select_lbl.pack(fill="x")
            self._bind_label_wrap(app.bomb_select_lbl, app.bombing_info_frame)
            app.bomb_select_lbl.bind("<Button-1>", lambda e: app._show_bomb_selector())
            app.bomb_select_lbl.bind(
                "<Enter>", lambda e: app.bomb_select_lbl.config(fg=Theme.TEXT, bg=Theme.BG)
            )
            app.bomb_select_lbl.bind(
                "<Leave>", lambda e: app.bomb_select_lbl.config(fg=Theme.BLUE, bg=Theme.GRAYPILL)
            )
            app.bomb_trajectory_lbl = tk.Label(
                app.bombing_info_frame,
                text="弹道: -- km",
                font=font_item,
                fg=Theme.TEXT_DIM,
                bg=Theme.GRAYPILL,
                anchor="w",
                justify="left",
            )
            app.bomb_trajectory_lbl.pack(fill="x")
            app.bomb_flight_lbl = tk.Label(
                app.bombing_info_frame,
                text="飞行: -- s",
                font=font_item,
                fg=Theme.TEXT_DIM,
                bg=Theme.GRAYPILL,
                anchor="w",
                justify="left",
            )
            app.bomb_flight_lbl.pack(fill="x")
            app.bomb_release_detail_lbl = tk.Label(
                app.bombing_info_frame,
                text="距离: --",
                font=font_item,
                fg=Theme.TEXT_MUTED,
                bg=Theme.GRAYPILL,
                anchor="w",
                justify="left",
            )
            app.bomb_release_detail_lbl.pack(fill="x")
            self._bind_label_wrap(app.bomb_trajectory_lbl, app.bombing_info_frame)
            self._bind_label_wrap(app.bomb_flight_lbl, app.bombing_info_frame)
            self._bind_label_wrap(app.bomb_release_detail_lbl, app.bombing_info_frame)

        app._zone_row_pool = self._build_nav_row_pool(
            app.zone_list_frame,
            ZoneConfig.MAX_DISPLAY_ZONES,
            font_item,
            bg=Theme.GRAYPILL,
            show_relative=True,
        )
        app._compact_zone_row_pool = self._build_nav_row_pool(
            app.compact_zone_list,
            ZoneConfig.MAX_DISPLAY_ZONES,
            font_item,
            bg=Theme.GRAYPILL,
            show_relative=False,
        )
        app._airport_row_pool = self._build_nav_row_pool(
            app.airport_list_frame,
            ZoneConfig.MAX_DISPLAY_AIRFIELDS,
            font_item,
            bg=Theme.GRAYPILL,
            show_relative=True,
        )
        app._compact_airport_row_pool = self._build_nav_row_pool(
            app.compact_airport_list,
            ZoneConfig.MAX_DISPLAY_AIRFIELDS,
            font_item,
            bg=Theme.GRAYPILL,
            show_relative=False,
        )
