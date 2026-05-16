import tkinter as tk
import unittest
from types import SimpleNamespace

from bomana.config import UIConfig
from bomana.core.state import Phase, UISnapshot
from bomana.ui.dialogs import _ScalableDialogMixin
from bomana.ui.main_window import MainWindowBuilder
from bomana.ui.nav_window import NavigationWindow
from bomana.ui.panel_renderer import AppPanelRenderer
from bomana.ui.widgets import HeadingTape


class FakeIcons:
    def configure_label(self, label: tk.Label, *, icon, text: str = "", **kwargs) -> None:
        kwargs.pop("size", None)
        kwargs.pop("compound", None)
        kwargs.pop("padx", None)
        label.config(text=text, **kwargs)


class DummyScalableDialog(tk.Toplevel, _ScalableDialogMixin):
    pass


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
            builder._label_minsize_for_text(
                ("Segoe UI", 12),
                builder._NAV_DISTANCE_SAMPLE,
                scale=1.5,
            ),
        )
        self.assertGreaterEqual(
            parent.grid_columnconfigure(3)["minsize"],
            builder._label_minsize_for_text(
                ("Segoe UI", 12),
                builder._NAV_RELATIVE_SAMPLE,
                scale=1.5,
            ),
        )

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
            main_badge=("运行中", "#fff", "#000"),
            flight_badge=("飞行", "#fff", "#000"),
            status_text="",
            api_down=False,
            api_down_pending=False,
            on_ground=False,
            landed_flash=False,
            fuel_kg=1800,
            fuel_initial_kg=2400,
            fuel_percent=75,
            fuel_rate_kg_min=96,
            fuel_rate_stable=True,
            fuel_time_remaining_str="18:45",
            altitude_m=4321,
            return_fuel_needed_kg=650,
            return_status="warning",
            friendly_distance_km=36,
            bombing_valid=True,
            bomb_name="FAB_500_M_62_extremely_long_test_name",
            bomb_range_m=2140,
            bomb_flight_time=12.3,
            release_distance_m=980,
            time_to_release=3.4,
            release_status="approaching",
            has_target=True,
        )

        renderer.update_fuel_display(snap)
        renderer.update_bombing_display(snap)

        fuel_texts = [
            app.fuel_detail_lbl.cget("text"),
            app.fuel_alt_lbl.cget("text"),
            app.fuel_return_detail_lbl.cget("text"),
        ]
        bomb_texts = [
            app.bomb_trajectory_lbl.cget("text"),
            app.bomb_flight_lbl.cget("text"),
            app.bomb_release_lbl.cget("text"),
            app.bomb_release_detail_lbl.cget("text"),
        ]
        self.assertEqual(fuel_texts, ["油耗 96kg/min", "高度 4321m", "返航 需~650kg (27%)"])
        self.assertEqual(bomb_texts[0], "弹道: 2.14km")
        self.assertEqual(bomb_texts[1], "飞行: 12.3s")
        self.assertEqual(bomb_texts[2], "接近")
        self.assertIn("距离 980m", bomb_texts[3])
        self.assertNotIn("│", " ".join(fuel_texts + bomb_texts))


if __name__ == "__main__":
    unittest.main()
