import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace

from bomana.config.settings import UIConfig
from bomana.core.state import Phase, UISnapshot
from bomana.ui.dialogs import _ScalableDialogMixin, _ScopedMousewheelBinding
from bomana.ui.main_window import MainWindowBuilder
from bomana.ui.nav_window import NavigationWindow
from bomana.ui.panel_renderer import AppPanelRenderer
from bomana.ui.text_utils import measure_min_width, set_elided_text
from bomana.ui.theme import Theme
from bomana.ui.widgets import HeadingTape


class FakeIcons:
    def configure_label(self, label: tk.Label, *, icon, text: str = "", **kwargs) -> None:
        kwargs.pop("size", None)
        kwargs.pop("compound", None)
        kwargs.pop("padx", None)
        label.config(text=text, **kwargs)


class DummyScalableDialog(tk.Toplevel, _ScalableDialogMixin):
    pass


class FakeTkRoot:
    def __init__(self) -> None:
        self.unbind_calls: list[tuple[tuple[str, str, str], str]] = []

    def _unbind(self, what: tuple[str, str, str], funcid: str | None = None) -> None:
        if funcid is not None:
            self.unbind_calls.append((what, funcid))


class FakeMousewheelWidget:
    def __init__(self, root: FakeTkRoot) -> None:
        self.root = root
        self.bind_handlers: dict[str, list[object]] = {}
        self.bind_all_calls: list[tuple[str, object, str | None]] = []

    def bind(self, sequence: str, func, add: str | None = None) -> None:
        self.bind_handlers.setdefault(sequence, []).append(func)

    def bind_all(self, sequence: str, func, add: str | None = None) -> str:
        self.bind_all_calls.append((sequence, func, add))
        return f"func-{len(self.bind_all_calls)}"

    def unbind_all(self, _sequence: str) -> None:
        raise AssertionError("unbind_all should not be used for scoped mousewheel cleanup")

    def _root(self) -> FakeTkRoot:
        return self.root

    def emit(self, sequence: str, *, widget=None) -> None:
        event = SimpleNamespace(widget=self if widget is None else widget)
        for handler in self.bind_handlers.get(sequence, []):
            handler(event)


def test_scoped_mousewheel_binding_unbinds_only_owned_callback() -> None:
    root = FakeTkRoot()
    owner = FakeMousewheelWidget(root)
    canvas = FakeMousewheelWidget(root)
    _ScopedMousewheelBinding(owner, canvas, lambda _event: None)

    canvas.emit("<Enter>")
    canvas.emit("<Leave>")

    assert canvas.bind_all_calls[0][0] == "<MouseWheel>"
    assert canvas.bind_all_calls[0][2] == "+"
    assert root.unbind_calls == [(("bind", "all", "<MouseWheel>"), "func-1")]

    canvas.emit("<Enter>")
    owner.emit("<Destroy>", widget=object())
    assert root.unbind_calls == [(("bind", "all", "<MouseWheel>"), "func-1")]

    owner.emit("<Destroy>", widget=owner)
    assert root.unbind_calls == [
        (("bind", "all", "<MouseWheel>"), "func-1"),
        (("bind", "all", "<MouseWheel>"), "func-2"),
    ]


def test_main_window_actions_have_persistent_button_affordances() -> None:
    source = (Path(__file__).resolve().parents[1] / "bomana" / "ui" / "main_window.py").read_text(
        encoding="utf-8"
    )

    assert "app.star_lbl = tk.Button(" in source
    assert "app.standalone_btn = tk.Button(" in source
    assert "app.weapon_select_btn = tk.Button(" in source
    assert "close_btn = tk.Button(" in source
    assert 'style_action_button(close_btn, "danger")' in source
    assert "app.weapon_select_btn.grid(row=0, column=2" in source
    assert "app.bombing_close_btn.grid(row=0, column=3" in source
    assert "POI四角标记" in source
    assert "上次坠毁点" in source
    assert "◇" not in source


class TkGeometryTests(unittest.TestCase):
    root: tk.Tk

    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.root = tk.Tk()
        except tk.TclError as exc:
            raise unittest.SkipTest(f"Tk display unavailable: {exc}") from exc
        cls.root.withdraw()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.root.destroy()

    def setUp(self) -> None:
        self.root.withdraw()
        for child in self.root.winfo_children():
            child.destroy()

    def test_heading_tape_height_scales_from_font_metrics(self) -> None:
        heights = []
        for scale in (1.0, 1.5, 2.0):
            tape = HeadingTape(self.root, width=280, height=36, text_scale=scale)
            tape.update_tape_multi(
                90.0,
                [
                    {"type": "zone", "relative": 0.0, "distance_km": 4.2, "is_primary": True},
                    {
                        "type": "friendly",
                        "relative": 18.0,
                        "distance_km": 12.7,
                        "is_primary": False,
                    },
                    {
                        "type": "enemy",
                        "relative": -25.0,
                        "distance_km": 33.0,
                        "is_primary": False,
                    },
                ],
                4.2,
            )
            self.root.update_idletasks()

            self.assertIsNotNone(tape.bbox("all"))
            self.assertGreaterEqual(tape.tape_height, tape._required_tape_height())
            for item_id in tape.find_all():
                if tape.type(item_id) != "text":
                    continue
                text_bbox = tape.bbox(item_id)
                self.assertIsNotNone(text_bbox)
                self.assertGreaterEqual(text_bbox[1], 0)
                self.assertLessEqual(text_bbox[3], tape.tape_height)
            heights.append(tape.tape_height)
            tape.destroy()

        self.assertLess(heights[0], heights[1])
        self.assertLess(heights[1], heights[2])

    def test_heading_tape_renders_interest_point_marker(self) -> None:
        tape = HeadingTape(self.root, width=280, height=36, text_scale=1.0)
        try:
            tape.update_tape_multi(
                90.0,
                [
                    {"type": "zone", "relative": 8.0, "distance_km": 7.0, "is_primary": True},
                    {
                        "type": "poi",
                        "relative": 0.0,
                        "distance_km": 4.2,
                        "is_primary": False,
                        "is_target": True,
                    },
                ],
                7.0,
            )
            self.root.update_idletasks()

            texts = [
                tape.itemcget(item_id, "text")
                for item_id in tape.find_all()
                if tape.type(item_id) == "text"
            ]
            marker_ids = tape.find_withtag("poi_marker")
            self.assertEqual(len(marker_ids), 4)
            self.assertTrue(all(tape.type(item_id) == "line" for item_id in marker_ids))
            self.assertTrue(all(len(tape.coords(item_id)) == 6 for item_id in marker_ids))
            self.assertTrue(
                all(tape.itemcget(item_id, "fill") == Theme.RED for item_id in marker_ids)
            )
            self.assertTrue(any(text.startswith("POI ") for text in texts))
            self.assertFalse(any("◇" in text for text in texts))
        finally:
            tape.destroy()

    def test_heading_tape_traceback_has_distinct_marker_and_overflow(self) -> None:
        tape = HeadingTape(self.root, width=280, height=36, text_scale=1.0)
        try:
            traceback = {
                "type": "traceback",
                "relative": 0.0,
                "distance_km": 2.8,
                "is_primary": False,
                "is_target": True,
            }
            tape.update_tape_multi(90.0, [traceback], 10.0)
            self.root.update_idletasks()

            marker_ids = tape.find_withtag("traceback_marker")
            self.assertEqual(len(marker_ids), 3)
            self.assertEqual({tape.type(item_id) for item_id in marker_ids}, {"line", "oval"})
            self.assertFalse(tape.find_withtag("poi_marker"))
            self.assertTrue(
                any(
                    tape.itemcget(item_id, "text").startswith("坠毁 ")
                    for item_id in tape.find_withtag("traceback_distance")
                )
            )

            traceback["relative"] = 180.0
            tape.update_tape_multi(90.0, [traceback], 10.0)
            self.root.update_idletasks()

            self.assertFalse(tape.find_withtag("traceback_marker"))
            overflow_ids = tape.find_withtag("traceback_overflow")
            self.assertGreaterEqual(len(overflow_ids), 2)
            self.assertTrue(
                any(
                    tape.type(item_id) == "text"
                    and tape.itemcget(item_id, "text").startswith("坠 ")
                    for item_id in overflow_ids
                )
            )
        finally:
            tape.destroy()

    def test_integrated_navigation_status_row_uses_elastic_columns(self) -> None:
        row = tk.Frame(self.root)
        row.pack(fill="x")
        labels = [
            tk.Label(row, text=""),
            tk.Label(row, text=""),
            tk.Label(row, text=""),
            tk.Label(row, text=""),
        ]
        labels[0].grid(row=0, column=0)
        labels[1].grid(row=0, column=1, sticky="ew")
        labels[2].grid(row=0, column=2, sticky="ew")
        labels[3].grid(row=0, column=3, sticky="ew")

        MainWindowBuilder(app=object())._configure_heading_status_row(
            row,
            turn_label=labels[1],
            status_label=labels[2],
            info_label=labels[3],
        )
        self.root.deiconify()
        self.root.geometry("320x80")
        self.root.update()

        self.assertEqual(labels[1].cget("width"), 0)
        self.assertEqual(labels[2].cget("width"), 0)
        self.assertEqual(labels[3].cget("width"), 0)
        self.assertEqual(row.grid_columnconfigure(1)["weight"], 1)
        self.assertEqual(row.grid_columnconfigure(2)["weight"], 1)
        self.assertEqual(row.grid_columnconfigure(3)["weight"], 2)
        self.assertGreaterEqual(labels[1].cget("wraplength"), 44)
        self.assertGreaterEqual(labels[3].cget("wraplength"), 74)

    def test_main_navigation_list_columns_use_font_metrics_not_fixed_widths(self) -> None:
        parent = tk.Frame(self.root)
        parent.pack(fill="x")
        builder = MainWindowBuilder(app=SimpleNamespace(scale=1.5))
        rows = builder._build_nav_row_pool(
            parent,
            1,
            ("Segoe UI", 12),
            bg="#000000",
            show_relative=True,
        )

        self.assertEqual(rows[0].distance_lbl.cget("width"), 0)
        self.assertEqual(rows[0].relative_lbl.cget("width"), 0)
        self.assertGreaterEqual(
            parent.grid_columnconfigure(2)["minsize"],
            measure_min_width(
                ("Segoe UI", 12),
                builder._NAV_DISTANCE_SAMPLE,
                fallback_scale=1.5,
            ),
        )
        self.assertGreaterEqual(
            parent.grid_columnconfigure(3)["minsize"],
            measure_min_width(
                ("Segoe UI", 12),
                builder._NAV_RELATIVE_SAMPLE,
                fallback_scale=1.5,
            ),
        )
        rows[0].distance_lbl.grid()
        rows[0].relative_lbl.grid()
        self.assertEqual(rows[0].distance_lbl.grid_info()["pady"], 0)
        self.assertEqual(rows[0].relative_lbl.grid_info()["pady"], 0)

    def test_main_navigation_compact_pools_keep_relative_bearing_columns(self) -> None:
        source = Path("bomana/ui/main_window.py").read_text(encoding="utf-8")

        self.assertNotIn("show_relative=False", source)

    def test_set_elided_text_uses_label_font_metrics(self) -> None:
        label = tk.Label(self.root, font=("Segoe UI", 10))
        full_text = "Very long aircraft display name"
        full_width = measure_min_width(label.cget("font"), full_text, master=label, padding=0)

        rendered = set_elided_text(label, full_text, max_width=max(1, full_width // 2))

        self.assertEqual(label.cget("text"), rendered)
        self.assertTrue(rendered.endswith("..."))
        self.assertLess(len(rendered), len(full_text))

    def test_dialog_wrap_and_scale_controls_follow_live_geometry(self) -> None:
        original_scale = UIConfig.UI_SCALE_MULT
        UIConfig.UI_SCALE_MULT = 1.75
        dialog = DummyScalableDialog(self.root)
        try:
            frame = tk.Frame(dialog)
            frame.pack(fill="x", expand=True)
            label = tk.Label(frame, text="long dialog guidance", wraplength=620)
            label.pack(fill="x")
            scale = tk.Scale(frame, orient="horizontal", length=180)
            scale.pack(fill="x")

            dialog._prepare_responsive_dialog_controls()
            dialog.geometry("260x120")
            self.root.update()

            self.assertEqual(label.cget("wraplength"), 236)
            self.assertEqual(scale.cget("length"), 315)
        finally:
            UIConfig.UI_SCALE_MULT = original_scale
            dialog.destroy()

    def test_dialog_fit_clamps_minimum_size_to_available_screen(self) -> None:
        dialog = DummyScalableDialog(self.root)
        dialog.withdraw()
        try:
            dialog.winfo_reqwidth = lambda: 1200
            dialog.winfo_reqheight = lambda: 900
            dialog.winfo_screenwidth = lambda: 480
            dialog.winfo_screenheight = lambda: 360

            dialog._fit_window_to_screen()

            min_w, min_h = dialog.minsize()
            max_w, max_h = dialog.maxsize()
            self.assertLessEqual(min_w, 360)
            self.assertLessEqual(min_h, 320)
            self.assertEqual(max_w, 360)
            self.assertEqual(max_h, 320)
        finally:
            dialog.destroy()

    def test_standalone_navigation_status_row_uses_elastic_columns(self) -> None:
        row = tk.Frame(self.root)
        row.pack(fill="x")
        labels = [
            tk.Label(row, text=""),
            tk.Label(row, text=""),
            tk.Label(row, text=""),
            tk.Label(row, text=""),
        ]
        labels[0].grid(row=0, column=0)
        labels[1].grid(row=0, column=1, sticky="ew")
        labels[2].grid(row=0, column=2, sticky="ew")
        labels[3].grid(row=0, column=3, sticky="ew")

        NavigationWindow._configure_status_row(
            row,
            turn_label=labels[1],
            status_label=labels[2],
            info_label=labels[3],
        )
        self.root.deiconify()
        self.root.geometry("320x80")
        self.root.update()

        self.assertEqual(labels[1].cget("width"), 0)
        self.assertEqual(labels[2].cget("width"), 0)
        self.assertEqual(labels[3].cget("width"), 0)
        self.assertEqual(row.grid_columnconfigure(1)["weight"], 1)
        self.assertEqual(row.grid_columnconfigure(2)["weight"], 1)
        self.assertEqual(row.grid_columnconfigure(3)["weight"], 2)
        self.assertGreaterEqual(labels[1].cget("wraplength"), 42)
        self.assertGreaterEqual(labels[3].cget("wraplength"), 72)

    def test_renderer_splits_fuel_and_bombing_details_across_labels(self) -> None:
        app = SimpleNamespace(
            scale=1.0,
            icons=FakeIcons(),
            fuel_main_lbl=tk.Label(self.root),
            fuel_time_lbl=tk.Label(self.root),
            fuel_return_lbl=tk.Label(self.root),
            fuel_detail_lbl=tk.Label(self.root),
            fuel_alt_lbl=tk.Label(self.root),
            fuel_return_detail_lbl=tk.Label(self.root),
            bomb_select_lbl=tk.Label(self.root),
            bomb_trajectory_lbl=tk.Label(self.root),
            bomb_flight_lbl=tk.Label(self.root),
            bomb_release_lbl=tk.Label(self.root),
            bomb_release_detail_lbl=tk.Label(self.root),
        )
        renderer = AppPanelRenderer(app)
        snap = UISnapshot(
            phase=Phase.ALIVE,
            life_index=1,
            cycle=1,
            remaining_sec=42.0,
            progress=0.5,
            sortie_id=1,
            api_down=False,
            api_down_pending=False,
            on_ground=False,
            landed_flash=False,
            fuel_kg=1800,
            fuel_initial_kg=2400,
            fuel_percent=75,
            fuel_rate_kg_min=96,
            fuel_rate_stable=True,
            fuel_remaining_time_min=18 + (45 / 60),
            altitude_m=4321,
            return_fuel_needed_kg=650,
            return_status="warning",
            friendly_distance_km=36,
            bombing_valid=True,
            bomb_name="FAB_500_M_62_extremely_long_test_name",
            weapon_id="FAB_500_M_62_extremely_long_test_name",
            weapon_display_name="FAB-500 M-62",
            weapon_role="bomb",
            weapon_control="unguided",
            weapon_selection_source="manual",
            weapon_selection_compatible=True,
            weapon_status="ccrp",
            bomb_range_m=2140,
            bomb_flight_time=12.3,
            release_distance_m=980,
            time_to_release=3.4,
            release_status="approaching",
            has_target=True,
            has_bombing_target=True,
            bombing_target_kind="zone",
            bombing_target_name="战区 #2",
            target_zone_distance_m=3120,
        )

        renderer.update_fuel_display(snap)
        renderer.update_bombing_display(snap)

        fuel_texts = [
            app.fuel_detail_lbl.cget("text"),
            app.fuel_return_detail_lbl.cget("text"),
        ]
        bomb_texts = [
            app.bomb_trajectory_lbl.cget("text"),
            app.bomb_flight_lbl.cget("text"),
            app.bomb_release_lbl.cget("text"),
            app.bomb_release_detail_lbl.cget("text"),
        ]
        self.assertEqual(fuel_texts, ["油耗 96kg/min · 高度 4321m", "返航 需 650kg (27%) · 36km"])
        self.assertEqual(bomb_texts[0], "目标 战区 #2 3.12km · 弹道 2.14km · 飞行 12.3s")
        self.assertEqual(bomb_texts[1], "")
        self.assertEqual(bomb_texts[2], "接近")
        self.assertEqual(bomb_texts[3], "战区窗口 3.4s / 980m")
        self.assertEqual(app.fuel_alt_lbl.winfo_manager(), "")
        self.assertEqual(app.bomb_flight_lbl.winfo_manager(), "")
        self.assertEqual(app.bomb_release_detail_lbl.winfo_manager(), "pack")
        self.assertNotIn("│", " ".join(fuel_texts + bomb_texts))

    def test_main_window_reuses_bombing_card_as_weapon_solution_card(self) -> None:
        source = Path("bomana/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn('text="武器解算"', source)
        self.assertNotIn("tactical_map", source)
        self.assertNotIn("weapon_map", source)


if __name__ == "__main__":
    unittest.main()
