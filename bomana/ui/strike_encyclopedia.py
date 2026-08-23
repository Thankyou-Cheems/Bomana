"""User-openable strike encyclopedia with source-derived vector diagrams."""

from __future__ import annotations

import contextlib
import tkinter as tk
import webbrowser
from typing import Any

from bomana.core.strike_damage_calculator import (
    StrikeDamageCalculator,
    StrikeDamageCalculatorError,
    room_max_br_from_balance_level,
    valid_room_max_brs,
)
from bomana.core.strike_encyclopedia import (
    AirfieldLayout,
    StrikeEncyclopedia,
    WeaponReference,
    load_strike_encyclopedia,
    project_airfield_scene,
    search_weapon_references,
    wiki_weapon_samples,
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
        self.damage_calculator = StrikeDamageCalculator(self.encyclopedia)
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
            "calculator": self._build_calculator_page(),
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
            "EC 机场静态结构 · 战区任务耐久 · 空战对地武器数量",
            size=9,
            fg=Theme.TEXT_DIM,
        ).pack(anchor="w", pady=(3, 0))

        tabs = tk.Frame(header, bg=Theme.BG)
        tabs.grid(row=0, column=1, sticky="e")
        self.tab_buttons: dict[str, tk.Button] = {}
        for tab_id, label in (
            ("airport", "机场结构"),
            ("durability", "战区耐久"),
            ("weapons", "武器参考"),
            ("calculator", "数量计算器"),
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
            "档位取房间允许的最高 BR（maxRank），不是当前载具 BR；数值不是 kg TNT。",
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
            ("房间最高 BR", "辅助模块", "跑道", "恢复基数"),
            [
                (
                    self._tier_br_text(tier.balance_level_range),
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
            ("房间最高 BR", "空战", "直升机"),
            [
                (
                    self._tier_br_text(tier.balance_level_range),
                    self._integer(tier.planes_mission_hp),
                    self._integer(tier.heli_mission_hp),
                )
                for tier in self.encyclopedia.bombing_point_tiers
            ],
        )
        behavior = self._label(
            page,
            (
                "战区：90%直接伤害 / 约3秒燃尽为 hpFireMult=0.1、fireSpeed=0.03 的参数推断；"
                "无回血，摧毁后240秒满血重生。\n"
                "机场：未发现同类燃烧自毁；生活区存活时按脚本逐机场 repair visit 恢复，"
                "不是每座机场固定每秒回血。"
            ),
            size=8,
            fg=Theme.YELLOW,
            bg=Theme.GRAYPILL,
            justify="left",
        )
        behavior.pack(anchor="w", padx=16, pady=(0, 6))
        self._label(
            page,
            "来源锁：当前桌面 2.57.1.103 任务模板（与 Datamine 2.57.1.89 同哈希）",
            size=8,
            fg=Theme.TEXT_MUTED,
            bg=Theme.GRAYPILL,
        ).pack(anchor="w", padx=16, pady=(0, 12))
        return page

    def _build_weapons_page(self) -> tk.Frame:
        page = self._new_page()
        self._label(
            page,
            "对地武器字段与实战参考",
            size=13,
            weight="bold",
            bg=Theme.GRAYPILL,
        ).pack(anchor="w", padx=16, pady=(14, 4))
        self._label(
            page,
            "计算器收录全部飞机可挂载的炸弹、火箭弹和空对地导弹。"
            "下面只列出仍有官方 Wiki TNTe 的样例；Mk 77 等燃烧弹不伪造 TNTe。",
            size=9,
            fg=Theme.YELLOW,
            bg=Theme.GRAYPILL,
        ).pack(anchor="w", padx=16, pady=(0, 10))

        table = self._table_card(page, "官方 Wiki TNTe 样例")
        table.pack(fill="x", padx=16, pady=(0, 12))
        self._table_rows(
            table,
            ("武器", "弹体 kg", "爆炸物类型", "原始装药 kg", "Wiki TNTe kg"),
            [
                (
                    item.display_name_zh or item.display_name,
                    f"{item.mass_kg:g}",
                    item.explosive_type,
                    f"{item.raw_explosive_mass_kg:g}",
                    "—" if item.tnte_reference_kg is None else f"{item.tnte_reference_kg:g}",
                )
                for item in wiki_weapon_samples(self.encyclopedia.weapon_references)
            ],
        )
        self._label(
            page,
            (
                f"数量计算器当前收录 {len(self.encyclopedia.weapon_references)} 种空战对地武器"
                "（炸弹 / 火箭弹 / 导弹）。可用名称、ID 或种类搜索。"
            ),
            size=9,
            fg=Theme.TEXT,
            bg=Theme.GRAYPILL,
        ).pack(anchor="w", padx=16, pady=(0, 10))
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
            "这是旧攻略参考。当前溅射公式对高阶战区 Mk 83 满额摧毁也是 6 枚，但 Wiki 仍不是公式来源。",
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

    def _build_calculator_page(self) -> tk.Frame:
        page = self._new_page()
        self._label(
            page,
            "EC 目标与武器数量计算器",
            size=13,
            weight="bold",
            bg=Theme.GRAYPILL,
        ).pack(anchor="w", padx=16, pady=(14, 4))
        self._label(
            page,
            "选择战局房间允许的最高 BR；不要填写当前出击载具的 BR。"
            "可搜索全部空战对地武器。对战区伤害按大厅溅射公式自动计算，不是逐条手抄。",
            size=9,
            fg=Theme.YELLOW,
            bg=Theme.GRAYPILL,
        ).pack(anchor="w", padx=16, pady=(0, 10))

        controls = tk.Frame(page, bg=Theme.GRAYPILL)
        controls.pack(fill="x", padx=16)
        self.calculator_br_var = tk.StringVar(value="14.7")
        self.calculator_target_var = tk.StringVar(value="战区基地（空战）")
        self.calculator_kind_var = tk.StringVar(value="全部")
        self.calculator_search_var = tk.StringVar()
        self.calculator_weapon_id = "us_1000lb_mk_83_ldgp"
        self.calculator_dwelling_hp_var = tk.StringVar()
        self.calculator_result_title_var = tk.StringVar()
        self.calculator_result_detail_var = tk.StringVar()
        self._calculator_visible_weapons: tuple[WeaponReference, ...] = ()
        fields = (
            (
                "房间最高 BR",
                self.calculator_br_var,
                tuple(f"{value:.1f}" for value in valid_room_max_brs()),
            ),
            (
                "目标",
                self.calculator_target_var,
                (
                    "战区基地（空战）",
                    "战区基地（直升机）",
                    "机场跑道",
                    "机场油库 / 储存区",
                    "机场停机 / 维修区",
                    "机场生活区",
                ),
            ),
            (
                "武器种类",
                self.calculator_kind_var,
                ("全部", "炸弹", "火箭弹", "导弹"),
            ),
        )
        for column, (label, variable, values) in enumerate(fields):
            controls.grid_columnconfigure(column, weight=1)
            field = tk.Frame(controls, bg=Theme.GRAYPILL)
            field.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0))
            self._label(
                field,
                label,
                size=8,
                weight="bold",
                fg=Theme.TEXT_DIM,
                bg=Theme.GRAYPILL,
            ).pack(anchor="w")
            menu = tk.OptionMenu(field, variable, *values)
            menu.configure(
                font=(_FONT, 9),
                bg=Theme.BG,
                fg=Theme.TEXT,
                activebackground=Theme.BORDER,
                activeforeground=Theme.TEXT,
                highlightthickness=1,
                highlightbackground=Theme.BORDER,
                bd=0,
            )
            menu["menu"].configure(font=(_FONT, 9), bg=Theme.BG, fg=Theme.TEXT)
            menu.pack(fill="x", pady=(4, 0))
            if variable is self.calculator_kind_var:
                variable.trace_add("write", lambda *_args: self._refresh_weapon_list())

        weapon_picker = tk.Frame(page, bg=Theme.GRAYPILL)
        weapon_picker.pack(fill="both", expand=False, padx=16, pady=(10, 0))
        self._label(
            weapon_picker,
            "武器（名称 / ID 搜索）",
            size=8,
            weight="bold",
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
        ).pack(anchor="w")
        search_entry = tk.Entry(
            weapon_picker,
            textvariable=self.calculator_search_var,
            font=(_FONT, 9),
            bg=Theme.BG,
            fg=Theme.TEXT,
            insertbackground=Theme.TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
        )
        search_entry.pack(fill="x", pady=(4, 6), ipady=5)
        self.calculator_search_var.trace_add("write", lambda *_args: self._refresh_weapon_list())
        list_frame = tk.Frame(weapon_picker, bg=Theme.BG)
        list_frame.pack(fill="x")
        scrollbar = tk.Scrollbar(list_frame)
        scrollbar.pack(side="right", fill="y")
        self.calculator_weapon_list = tk.Listbox(
            list_frame,
            height=8,
            font=(_FONT, 9),
            bg=Theme.BG,
            fg=Theme.TEXT,
            selectbackground=Theme.BORDER,
            selectforeground=Theme.TEXT,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
            relief="flat",
            exportselection=False,
            yscrollcommand=scrollbar.set,
        )
        self.calculator_weapon_list.pack(side="left", fill="both", expand=True)
        scrollbar.configure(command=self.calculator_weapon_list.yview)
        self.calculator_weapon_list.bind("<<ListboxSelect>>", self._on_weapon_list_select)
        self._refresh_weapon_list()

        repair_input = tk.Frame(page, bg=Theme.GRAYPILL)
        repair_input.pack(fill="x", padx=16, pady=(10, 0))
        self._label(
            repair_input,
            "生活区当前剩余 HP（可选，仅用于计算机场单次 repair visit 回血）",
            size=8,
            fg=Theme.TEXT_DIM,
            bg=Theme.GRAYPILL,
        ).pack(side="left")
        tk.Entry(
            repair_input,
            textvariable=self.calculator_dwelling_hp_var,
            width=14,
            font=(_FONT, 9),
            bg=Theme.BG,
            fg=Theme.TEXT,
            insertbackground=Theme.TEXT,
            relief="flat",
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
        ).pack(side="left", padx=(10, 0), ipady=5)
        self._button(
            repair_input,
            "计算",
            self._refresh_calculator,
            variant="primary",
        ).pack(side="left", padx=(10, 0))

        result_card = tk.Frame(
            page,
            bg=Theme.BG,
            highlightthickness=1,
            highlightbackground=Theme.BORDER,
        )
        result_card.pack(fill="both", expand=True, padx=16, pady=(12, 14))
        self._label(
            result_card,
            "",
            size=15,
            weight="bold",
            fg=Theme.GREEN,
            bg=Theme.BG,
            textvariable=self.calculator_result_title_var,
            anchor="w",
        ).pack(fill="x", padx=14, pady=(12, 5))
        self._label(
            result_card,
            "",
            size=9,
            bg=Theme.BG,
            textvariable=self.calculator_result_detail_var,
            justify="left",
            anchor="nw",
            wraplength=860,
        ).pack(fill="both", expand=True, padx=14, pady=(0, 12))
        self._refresh_calculator()
        return page

    def _calculator_kind_filter(self) -> str | None:
        labels = {"炸弹": "bomb", "火箭弹": "rocket", "导弹": "missile"}
        return labels.get(self.calculator_kind_var.get())

    def _refresh_weapon_list(self) -> None:
        matches = search_weapon_references(
            self.encyclopedia.weapon_references,
            self.calculator_search_var.get(),
            kind=self._calculator_kind_filter(),
        )
        self._calculator_visible_weapons = matches
        self.calculator_weapon_list.delete(0, "end")
        selected_index = 0
        for index, weapon in enumerate(matches):
            self.calculator_weapon_list.insert("end", weapon.calculator_label)
            if weapon.weapon_id == self.calculator_weapon_id:
                selected_index = index
        if matches:
            if self.calculator_weapon_id not in {weapon.weapon_id for weapon in matches}:
                self.calculator_weapon_id = matches[0].weapon_id
                selected_index = 0
            self.calculator_weapon_list.selection_clear(0, "end")
            self.calculator_weapon_list.selection_set(selected_index)
            self.calculator_weapon_list.see(selected_index)
        self._refresh_calculator()

    def _select_calculator_weapon(self, weapon_id: str) -> None:
        self.calculator_weapon_id = weapon_id
        self._refresh_weapon_list()

    def _on_weapon_list_select(self, _event: object | None = None) -> None:
        selection = self.calculator_weapon_list.curselection()
        if not selection:
            return
        index = int(selection[0])
        if not 0 <= index < len(self._calculator_visible_weapons):
            return
        weapon_id = self._calculator_visible_weapons[index].weapon_id
        if weapon_id == self.calculator_weapon_id:
            return
        self.calculator_weapon_id = weapon_id
        self._refresh_calculator()

    def _refresh_calculator(self) -> None:
        target_map = {
            "战区基地（空战）": ("bombing_point", "planes", None),
            "战区基地（直升机）": ("bombing_point", "heli", None),
            "机场跑道": ("airport_module", "planes", "airfield"),
            "机场油库 / 储存区": ("airport_module", "planes", "storage"),
            "机场停机 / 维修区": ("airport_module", "planes", "parking"),
            "机场生活区": ("airport_module", "planes", "dwelling"),
        }
        target_kind, mission_mode, module = target_map[self.calculator_target_var.get()]
        raw_dwelling_hp = self.calculator_dwelling_hp_var.get().strip()
        try:
            dwelling_hp = None if not raw_dwelling_hp else float(raw_dwelling_hp)
            result = self.damage_calculator.calculate(
                room_max_br=float(self.calculator_br_var.get()),
                target_kind=target_kind,  # type: ignore[arg-type]
                mission_mode=mission_mode,  # type: ignore[arg-type]
                airport_module=module,  # type: ignore[arg-type]
                weapon_id=self.calculator_weapon_id,
                dwelling_remaining_hp=dwelling_hp,
            )
        except (KeyError, ValueError, StrikeDamageCalculatorError):
            self.calculator_result_title_var.set("输入值无效")
            self.calculator_result_detail_var.set(
                "生活区剩余 HP 必须在当前档辅助模块的 0 到满血之间。"
            )
            return

        if result.weapon_count is None:
            title = "所需枚数：原生未知"
        elif result.fire_trigger_weapon_count is not None:
            title = (
                f"摧毁：{result.weapon_count} 枚 · 触发燃烧：{result.fire_trigger_weapon_count} 枚"
            )
        else:
            title = f"摧毁：{result.weapon_count} 枚"
        details = [
            (
                f"房间最高 BR {result.room_max_br:.1f} → maxRank {result.balance_level} → "
                f"任务档位 {self._range_text(result.balance_level_range)}"
            ),
            f"目标满血：{self._integer(result.target_mission_hp)} mission_hp（静态精确）",
        ]
        if result.direct_damage_to_fire_reference is not None:
            details.extend(
                (
                    "战区燃烧参考：直接造成 "
                    f"{self._integer(result.direct_damage_to_fire_reference)} HP（90%）后，"
                    f"剩余 {self._integer(result.fire_remaining_hp_reference or 0)} HP；"
                    "约3秒燃尽仅为参数与历史语义推断。",
                    f"摧毁后 {result.respawn_seconds:.0f} 秒满血重生；战区没有脚本回血。",
                )
            )
        else:
            details.append("机场模块未发现 90% 后燃烧自毁逻辑；必须按满血直接伤害计算。")
            repair_min = (result.repair_base_hp or 0.0) / 10.0
            details.append(
                "生活区 0 < D < 满血时，每次该机场 repair visit 恢复约 "
                f"{self._integer(repair_min)}–{self._integer(result.repair_base_hp or 0)} HP；"
                "D=0 或 D=满血时该脚本分支为0。"
            )
            if result.repair_per_visit is not None:
                details.append(
                    f"按输入的生活区剩余 HP，本次 visit 恢复 {result.repair_per_visit:,.1f} HP。"
                )
        if result.damage_per_hit_mission_hp is not None:
            details.append(
                f"大厅对战区预估伤害：每枚 {result.damage_per_hit_mission_hp:,.2f}"
            )
            if result.weapon.mission_damage_model == "splash_tnte_curve":
                details.append(
                    f"输入 TNT 当量 {result.weapon.raw_explosive_mass_kg:g} kg × "
                    f"{result.weapon.strength_equivalent:g}"
                    + ("；穿深不足 25 mm，已乘 restrain=0.6。" if result.reduced_for_armor else "。")
                )
            if result.hangar_reward_ui_for_destroy is not None and result.weapon_count:
                details.append(
                    f"若只用这一种武器凑满摧毁枚数，攻击机大厅收益系数约 "
                    f"{result.hangar_reward_ui_for_destroy:.1f}（战斗机再 ×0.8）。"
                )
        details.extend(
            (
                result.quantity_message,
                "官方 Wiki「约6枚 Mk 83」与当前高阶战区满额摧毁枚数一致，仍不是公式来源。",
            )
        )
        self.calculator_result_title_var.set(title)
        self.calculator_result_detail_var.set("\n".join(details))

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

    @staticmethod
    def _tier_br_text(value: tuple[int, int]) -> str:
        start, end = value
        current_end = min(end, 41)
        return (
            f"{room_max_br_from_balance_level(start):.1f}–"
            f"{room_max_br_from_balance_level(current_end):.1f}"
        )

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
