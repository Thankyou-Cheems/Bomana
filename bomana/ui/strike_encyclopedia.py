"""User-openable strike encyclopedia with source-derived vector diagrams."""

from __future__ import annotations

import contextlib
import tkinter as tk
import webbrowser
from typing import Any

from bomana.core.strike_encyclopedia import (
    AirfieldLayout,
    StrikeEncyclopedia,
    load_strike_encyclopedia,
    project_airfield_scene,
)
from bomana.ui.theme import Theme
from bomana.ui.tk_style import style_action_button

_FONT = "Microsoft YaHei UI"


class StrikeEncyclopediaDialog(tk.Toplevel):
    """Non-modal reference window for EC durability and static airport geometry."""

    def __init__(self, parent: tk.Misc, app: Any):
        super().__init__(parent)
        self.app = app
        self.encyclopedia: StrikeEncyclopedia = load_strike_encyclopedia()
        self._selected_layout = self.encyclopedia.airfield_layouts[0]
        self._active_tab = "airport"
        self._redraw_after: str | None = None

        self.title("Bomana 打击百科")
        self.configure(bg=Theme.BG)
        self.resizable(True, True)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.geometry(self._initial_geometry(parent))
        self.minsize(760, 560)

        self._build_header()
        self.content = tk.Frame(self, bg=Theme.BG)
        self.content.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        self.pages = {
            "airport": self._build_airport_page(),
            "durability": self._build_durability_page(),
            "weapons": self._build_weapons_page(),
        }
        self._show_tab("airport")
        self.after_idle(self._draw_airfield)

    def _initial_geometry(self, parent: tk.Misc) -> str:
        with contextlib.suppress(tk.TclError):
            parent.update_idletasks()
            width = min(1080, max(820, parent.winfo_screenwidth() - 180))
            height = min(760, max(600, parent.winfo_screenheight() - 180))
            x = max(0, parent.winfo_rootx() + (parent.winfo_width() - width) // 2)
            y = max(0, parent.winfo_rooty() + (parent.winfo_height() - height) // 2)
            return f"{width}x{height}+{x}+{y}"
        return "980x700"

    def _label(
        self,
        parent: tk.Misc,
        text: str,
        *,
        size: int = 10,
        weight: str = "normal",
        fg: str | None = None,
        bg: str | None = None,
        **kwargs: Any,
    ) -> tk.Label:
        return tk.Label(
            parent,
            text=text,
            font=(_FONT, size, weight),
            fg=fg or Theme.TEXT,
            bg=bg or Theme.BG,
            **kwargs,
        )

    def _button(
        self,
        parent: tk.Misc,
        text: str,
        command: Any,
        *,
        variant: str = "secondary",
    ) -> tk.Button:
        button = tk.Button(
            parent,
            text=text,
            command=command,
            font=(_FONT, 9),
            padx=11,
            pady=5,
        )
        style_action_button(button, variant)
        return button

    def _build_header(self) -> None:
        header = tk.Frame(self, bg=Theme.BG)
        header.pack(fill="x", padx=18, pady=(16, 12))
        header.grid_columnconfigure(0, weight=1)
        title = tk.Frame(header, bg=Theme.BG)
        title.grid(row=0, column=0, sticky="w")
        self._label(title, "打击百科", size=18, weight="bold").pack(anchor="w")
        self._label(
            title,
            "EC 机场静态结构 · 战区任务耐久 · 炸弹字段参考",
            size=9,
            fg=Theme.TEXT_DIM,
        ).pack(anchor="w", pady=(3, 0))

        tabs = tk.Frame(header, bg=Theme.BG)
        tabs.grid(row=0, column=1, sticky="e")
        self.tab_buttons: dict[str, tk.Button] = {}
        for tab_id, label in (
            ("airport", "机场结构"),
            ("durability", "战区耐久"),
            ("weapons", "炸弹参考"),
        ):
            button = self._button(tabs, label, lambda value=tab_id: self._show_tab(value))
            button.pack(side="left", padx=(6, 0))
            self.tab_buttons[tab_id] = button

    def _new_page(self) -> tk.Frame:
        return tk.Frame(
            self.content,
            bg=Theme.GRAYPILL,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
        )

    def _build_airport_page(self) -> tk.Frame:
        page = self._new_page()
        page.grid_rowconfigure(1, weight=1)
        page.grid_columnconfigure(0, weight=1)
        selector = tk.Frame(page, bg=Theme.GRAYPILL)
        selector.grid(row=0, column=0, sticky="ew", padx=14, pady=(13, 8))
        self._label(
            selector,
            "选择静态几何",
            size=9,
            weight="bold",
            bg=Theme.GRAYPILL,
        ).pack(side="left", padx=(0, 8))
        self.layout_buttons: dict[str, tk.Button] = {}
        for layout in self.encyclopedia.airfield_layouts:
            button = self._button(
                selector,
                layout.label.replace("机场布局 ", "布局 "),
                lambda value=layout: self._select_layout(value),
            )
            button.pack(side="left", padx=(5, 0))
            self.layout_buttons[layout.layout_id] = button

        body = tk.Frame(page, bg=Theme.GRAYPILL)
        body.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 10))
        body.grid_rowconfigure(0, weight=1)
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        self.diagram_canvas = tk.Canvas(
            body,
            bg="#101722",
            bd=0,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
            width=620,
            height=420,
        )
        self.diagram_canvas.grid(row=0, column=0, sticky="nsew")
        self.diagram_canvas.bind("<Configure>", self._schedule_redraw)

        facts = tk.Frame(body, bg=Theme.GRAYPILL)
        facts.grid(row=0, column=1, sticky="nsew", padx=(14, 0))
        self.layout_title = self._label(
            facts,
            "",
            size=13,
            weight="bold",
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        self.layout_title.pack(fill="x")
        self.layout_summary = self._label(
            facts,
            "",
            size=9,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
            justify="left",
            anchor="nw",
            wraplength=300,
        )
        self.layout_summary.pack(fill="x", pady=(8, 12))
        self.module_facts = tk.Frame(facts, bg=Theme.GRAYPILL)
        self.module_facts.pack(fill="both", expand=True)

        warning = self._label(
            page,
            "图形由 start / end / width 数值实时生成；不绘制无静态命中语义的道路、建筑轮廓和编号。",
            size=8,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
            anchor="w",
        )
        warning.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 12))
        self._refresh_layout_facts()
        return page

    def _build_durability_page(self) -> tk.Frame:
        page = self._new_page()
        heading = tk.Frame(page, bg=Theme.GRAYPILL)
        heading.pack(fill="x", padx=16, pady=(14, 8))
        self._label(
            heading,
            "客户端任务耐久参数（mission_hp）",
            size=13,
            weight="bold",
            bg=Theme.GRAYPILL,
        ).pack(anchor="w")
        self._label(
            heading,
            "balance_level 由任务决定；以下数值不是 kg TNT，也不能直接推导必需弹量。",
            size=9,
            fg=Theme.YELLOW,
            bg=Theme.GRAYPILL,
        ).pack(anchor="w", pady=(4, 0))

        tables = tk.Frame(page, bg=Theme.GRAYPILL)
        tables.pack(fill="both", expand=True, padx=16, pady=(4, 10))
        tables.grid_columnconfigure(0, weight=1)
        tables.grid_columnconfigure(1, weight=1)
        airport = self._table_card(tables, "机场模块")
        airport.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        self._table_rows(
            airport,
            ("权重", "辅助模块", "跑道", "恢复基数"),
            [
                (
                    self._range_text(tier.balance_level_range),
                    self._integer(tier.auxiliary_module_mission_hp),
                    self._integer(tier.runway_mission_hp),
                    self._integer(tier.repair_base_hp),
                )
                for tier in self.encyclopedia.airport_tiers
            ],
        )
        zone = self._table_card(tables, "战区基地 / bombing_point")
        zone.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        self._table_rows(
            zone,
            ("权重", "空战", "直升机"),
            [
                (
                    self._range_text(tier.balance_level_range),
                    self._integer(tier.planes_mission_hp),
                    self._integer(tier.heli_mission_hp),
                )
                for tier in self.encyclopedia.bombing_point_tiers
            ],
        )
        source = self._label(
            page,
            "来源锁：ft_fields_template.blkx / bdt_bases_destroy_template.blkx · Datamine 2.57.1.89",
            size=8,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
        )
        source.pack(anchor="w", padx=16, pady=(0, 14))
        return page

    def _build_weapons_page(self) -> tk.Frame:
        page = self._new_page()
        self._label(
            page,
            "炸弹字段与实战参考",
            size=13,
            weight="bold",
            bg=Theme.GRAYPILL,
        ).pack(anchor="w", padx=16, pady=(14, 4))
        self._label(
            page,
            "原始装药质量、官方 Wiki TNTe 与任务伤害是不同数据层。Mk 77 为 napalm，不伪造 TNTe。",
            size=9,
            fg=Theme.YELLOW,
            bg=Theme.GRAYPILL,
        ).pack(anchor="w", padx=16, pady=(0, 10))

        table = self._table_card(page, "版本锁定样例")
        table.pack(fill="x", padx=16, pady=(0, 12))
        self._table_rows(
            table,
            ("武器", "弹体 kg", "爆炸物类型", "原始装药 kg", "Wiki TNTe kg"),
            [
                (
                    item.display_name,
                    f"{item.mass_kg:g}",
                    item.explosive_type,
                    f"{item.raw_explosive_mass_kg:g}",
                    "—" if item.tnte_reference_kg is None else f"{item.tnte_reference_kg:g}",
                )
                for item in self.encyclopedia.weapon_references
            ],
        )
        practical = self.encyclopedia.practical_references[0]
        reference_card = tk.Frame(
            page,
            bg=Theme.BG,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
        )
        reference_card.pack(fill="x", padx=16, pady=(0, 10))
        self._label(
            reference_card,
            "官方 Wiki 实战参考",
            size=10,
            weight="bold",
            bg=Theme.BG,
        ).pack(anchor="w", padx=12, pady=(10, 3))
        self._label(
            reference_card,
            f"{practical.scope}：约 {practical.weapon_count} 枚 Mk 83（合计 Wiki TNTe 参考 {practical.total_tnte_reference_kg:g} kg）",
            size=10,
            fg=Theme.TEXT,
            bg=Theme.BG,
        ).pack(anchor="w", padx=12)
        self._label(
            reference_card,
            "这是攻略级参考，不是 mission_hp 换算公式；版本、任务与实际命中会影响结果。",
            size=8,
            fg=Theme.TEXT_MUTED,
            bg=Theme.BG,
        ).pack(anchor="w", padx=12, pady=(4, 10))
        self._button(
            page,
            "打开官方 Wiki 来源",
            lambda: webbrowser.open(practical.source_url),
            variant="secondary",
        ).pack(anchor="w", padx=16, pady=(0, 14))
        return page

    def _table_card(self, parent: tk.Misc, title: str) -> tk.Frame:
        card = tk.Frame(
            parent,
            bg=Theme.BG,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
        )
        self._label(card, title, size=10, weight="bold", bg=Theme.BG).pack(
            anchor="w", padx=10, pady=(9, 5)
        )
        card.table_body = tk.Frame(card, bg=Theme.BG)  # type: ignore[attr-defined]
        card.table_body.pack(fill="both", expand=True, padx=8, pady=(0, 8))  # type: ignore[attr-defined]
        return card

    def _table_rows(
        self,
        card: tk.Frame,
        headers: tuple[str, ...],
        rows: list[tuple[str, ...]],
    ) -> None:
        body: tk.Frame = card.table_body  # type: ignore[attr-defined]
        for column, header in enumerate(headers):
            body.grid_columnconfigure(column, weight=1)
            self._label(
                body,
                header,
                size=8,
                weight="bold",
                fg=Theme.TEXT_DIM,
                bg=Theme.GRAYPILL,
                padx=5,
                pady=5,
            ).grid(row=0, column=column, sticky="nsew", padx=1, pady=1)
        for row_index, row in enumerate(rows, start=1):
            for column, value in enumerate(row):
                self._label(
                    body,
                    value,
                    size=9,
                    bg=Theme.BG,
                    padx=5,
                    pady=6,
                ).grid(row=row_index, column=column, sticky="nsew", padx=1, pady=1)

    @staticmethod
    def _integer(value: float) -> str:
        return f"{value:,.0f}"

    @staticmethod
    def _range_text(value: tuple[int, int]) -> str:
        return f"{value[0]}–{value[1]}"

    def _show_tab(self, tab_id: str) -> None:
        if tab_id not in self.pages:
            return
        self._active_tab = tab_id
        for page in self.pages.values():
            page.pack_forget()
        self.pages[tab_id].pack(fill="both", expand=True)
        for key, button in self.tab_buttons.items():
            style_action_button(button, "primary" if key == tab_id else "secondary")
        if tab_id == "airport":
            self.after_idle(self._draw_airfield)

    def _select_layout(self, layout: AirfieldLayout) -> None:
        self._selected_layout = layout
        self._refresh_layout_facts()
        self._draw_airfield()

    def _refresh_layout_facts(self) -> None:
        layout = self._selected_layout
        self.layout_title.configure(text=layout.label)
        self.layout_summary.configure(
            text=(
                f"跑道长度 {layout.runway_length_m:,.0f} m\n"
                f"静态模板 {layout.source_unit_class}\n"
                "四模块均按实际米制矩形显示"
            )
        )
        for child in self.module_facts.winfo_children():
            child.destroy()
        for module in layout.modules:
            length = (
                (module.end_xz[0] - module.start_xz[0]) ** 2
                + (module.end_xz[1] - module.start_xz[1]) ** 2
            ) ** 0.5
            row = tk.Frame(self.module_facts, bg=Theme.GRAYPILL)
            row.pack(fill="x", pady=3)
            tk.Frame(
                row,
                bg={
                    "airfield": "#2477A8",
                    "storage": "#C85145",
                    "parking": "#D7A62C",
                    "dwelling": "#37936B",
                }[module.module_id],
                width=8,
                height=34,
            ).pack(side="left", fill="y")
            self._label(
                row,
                f"{module.label}\n{length:,.0f} × {module.width_m:,.0f} m",
                size=9,
                bg=Theme.GRAYPILL,
                justify="left",
                anchor="w",
            ).pack(side="left", fill="x", expand=True, padx=(9, 0))
        for key, button in self.layout_buttons.items():
            style_action_button(
                button,
                "primary" if key == layout.layout_id else "secondary",
            )

    def _schedule_redraw(self, _event: tk.Event | None = None) -> None:
        if self._redraw_after is not None:
            with contextlib.suppress(tk.TclError):
                self.after_cancel(self._redraw_after)
        self._redraw_after = self.after(40, self._draw_airfield)

    def _draw_airfield(self) -> None:
        self._redraw_after = None
        canvas = self.diagram_canvas
        with contextlib.suppress(tk.TclError):
            width = max(240, canvas.winfo_width())
            height = max(180, canvas.winfo_height())
            scene = project_airfield_scene(self._selected_layout, width=width, height=height)
            canvas.delete("all")
            canvas.create_text(
                18,
                16,
                text="静态模块比例图",
                anchor="nw",
                fill="#F2F6FB",
                font=(_FONT, 12, "bold"),
            )
            for shape in scene.shapes:
                coordinates = [coordinate for point in shape.points for coordinate in point]
                canvas.create_polygon(
                    *coordinates,
                    fill=shape.color,
                    outline="#D8E7F7",
                    width=2,
                )
                canvas.create_text(
                    *shape.label_position,
                    text=shape.label.replace(" / ", "\n"),
                    fill="#FFFFFF",
                    font=(_FONT, 9, "bold"),
                    justify="center",
                )
            canvas.create_text(
                width - 16,
                height - 14,
                text=scene.disclaimer,
                anchor="se",
                fill="#96A5B8",
                font=(_FONT, 8),
            )

    def _close(self) -> None:
        if getattr(self.app, "_strike_encyclopedia_dialog", None) is self:
            self.app._strike_encyclopedia_dialog = None
        self.destroy()


__all__ = ["StrikeEncyclopediaDialog"]
