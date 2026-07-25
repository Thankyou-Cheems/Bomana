import time
import tkinter as tk
import unittest
from pathlib import Path
from types import SimpleNamespace

from bomana.config.settings import PanelConfig, UIConfig
from bomana.core.state import Phase, UISnapshot
from bomana.ui.app import App
from bomana.ui.bombing_bar import BombingBar, CCRPCueProjection
from bomana.ui.dialogs import _ScalableDialogMixin, _ScopedMousewheelBinding
from bomana.ui.main_window import MainWindowBuilder
from bomana.ui.nav_window import NavigationWindow
from bomana.ui.panel_renderer import AppPanelRenderer
from bomana.ui.text_utils import measure_min_width, set_elided_text
from bomana.ui.theme import Theme
from bomana.ui.widgets import BananaProgress, HeadingTape


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
    root = Path(__file__).resolve().parents[1]
    source = (root / "bomana" / "ui" / "main_window.py").read_text(encoding="utf-8")
    renderer_source = (root / "bomana" / "ui" / "panel_renderer.py").read_text(
        encoding="utf-8"
    )
    bombing_source = (root / "bomana" / "ui" / "bombing_bar.py").read_text(
        encoding="utf-8"
    )

    assert "app.star_lbl = tk.Button(" in source
    assert "app.standalone_btn = tk.Button(" in source
    assert "close_btn = tk.Button(" in source
    assert 'style_action_button(close_btn, "danger")' in source
    assert "self.weapon_btn = tk.Label(" in bombing_source
    assert "style_clickable_surface(self.weapon_btn)" in bombing_source
    assert "self.weapon_prev_btn = None" in bombing_source
    assert "self.weapon_next_btn = None" in bombing_source
    assert '"切换独立显示"' in bombing_source
    assert "self.close_btn = tk.Label(" in bombing_source
    assert '"关闭"' in bombing_source
    assert 'variant="danger"' in bombing_source
    assert "self.close_btn.bind(\"<Button-1>\", self._return_to_integrated)" in bombing_source
    assert "self.target_mode_btn = self._button(" in bombing_source
    assert "self.trajectory_lbl.pack" not in bombing_source
    assert "self.release_detail_lbl.pack" not in bombing_source
    assert "app.bombing_bar.cue.stop()" in renderer_source
    assert "app.bombing_frame,\n                    row=9," in renderer_source
    assert "row=9,\n                    column=0,\n                    sticky=\"ew\",\n                    padx=0," in (
        renderer_source
    )
    assert "POI四角标记" in source
    assert "上次坠毁点" in source
    assert "◇" not in source
    assert "style_clickable_surface(app.web_access_lbl" in source
    assert "style_clickable_surface(app.speed_threshold_btn" in source
    assert "style_action_button(button, variant)" in bombing_source
    assert "app.web_control_btn" not in source


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

    def test_ccrp_integrated_alignment_and_standalone_close_contract(self) -> None:
        integrated_requests: list[str] = []
        app = SimpleNamespace(
            root=self.root,
            scale=1.0,
            icons=FakeIcons(),
            bombing_services=SimpleNamespace(
                set_mode=lambda mode: integrated_requests.append(mode)
            ),
            _scaled_font=lambda font, *, size_mult=1.0, min_size=1: (
                font[0],
                max(min_size, round(font[1] * size_mult)),
            ),
            _toggle_bombing_mode=lambda: None,
            _toggle_panel=lambda _panel: None,
            _show_bomb_selector=lambda: None,
            _toggle_bomb_target_mode=lambda: None,
        )
        host = tk.Frame(self.root, bg=Theme.GRAYPILL)
        host.pack(fill="x")
        baseline_header = tk.Frame(host, bg=Theme.GRAYPILL)
        baseline_header.grid(row=0, column=0, sticky="ew", padx=8)
        baseline_title = tk.Label(
            baseline_header,
            text="燃油管理",
            bg=Theme.GRAYPILL,
        )
        baseline_title.grid(row=0, column=0, sticky="w")
        integrated = BombingBar(host, app, scale=1.0, standalone=False)
        integrated.frame.grid(row=1, column=0, sticky="ew", padx=0)
        standalone = BombingBar(host, app, scale=1.0, standalone=True)
        standalone.frame.grid(row=2, column=0, sticky="ew", padx=0)
        self.root.update_idletasks()

        self.assertEqual(integrated.title_lbl.winfo_rootx(), baseline_title.winfo_rootx())
        self.assertEqual(integrated.title_lbl.cget("text"), "CCRP")
        self.assertEqual(integrated.close_btn.cget("text"), "关闭")
        self.assertIsNotNone(integrated.mode_btn)
        self.assertIsInstance(integrated.weapon_btn, tk.Label)
        self.assertIsNone(integrated.weapon_prev_btn)
        self.assertIsNone(integrated.weapon_next_btn)
        self.assertIs(integrated.target_summary_lbl.master, integrated.header_frame)
        self.assertEqual(integrated.info_frame.winfo_manager(), "")
        self.assertEqual(int(float(integrated.cue.cget("height"))), 42)
        managed_height = (
            integrated.header_frame.winfo_reqheight()
            + integrated.controls_frame.winfo_reqheight()
            + integrated.cue.winfo_reqheight()
        )
        self.assertLessEqual(integrated.frame.winfo_reqheight(), managed_height + 16)
        self.assertEqual(integrated.trajectory_lbl.winfo_manager(), "")
        self.assertEqual(integrated.flight_lbl.winfo_manager(), "")
        self.assertEqual(integrated.release_detail_lbl.winfo_manager(), "")
        self.assertEqual(
            BombingBar._target_context_text(
                "战区 #2 3.12km",
                "目标高程 186m",
            ),
            "高186m·战区#2 3.12km",
        )
        self.assertEqual(
            BombingBar._compact_weapon_label("MK82 500磅 · 炸弹 · 点击切换"),
            "MK82 500磅",
        )
        integrated.cue.set_projection(
            CCRPCueProjection(0.18, Theme.YELLOW, "T−2.4s")
        )
        integrated.cue._draw()
        cue_bbox = integrated.cue.bbox("all")
        self.assertIsNotNone(cue_bbox)
        assert cue_bbox is not None
        self.assertGreaterEqual(cue_bbox[1], 0)
        self.assertLessEqual(
            cue_bbox[3],
            max(integrated.cue.winfo_height(), integrated.cue.winfo_reqheight()),
        )

        self.assertIsNone(standalone.mode_btn)
        self.assertIsNone(standalone.drag_hint_lbl)
        self.assertEqual(standalone.close_btn.cget("text"), "✕")
        standalone._return_to_integrated()
        self.assertEqual(integrated_requests, ["integrated"])

        integrated.destroy()
        standalone.destroy()

    def test_standalone_navigation_scale_includes_heading_tape(self) -> None:
        old_scale = PanelConfig.navigation_bar_scale
        old_width = PanelConfig.navigation_bar_width
        app = SimpleNamespace(
            root=self.root,
            scale=1.0,
            _locked=False,
            navigation_services=SimpleNamespace(switch_to_integrated=lambda: None),
            _toggle_bombing_mode=lambda: None,
            _toggle_panel=lambda _panel: None,
            _cycle_bomb_weapon=lambda _direction: None,
            _show_bomb_selector=lambda: None,
            _toggle_bomb_target_mode=lambda: None,
            _scaled_font=lambda font, *, size_mult=1.0, min_size=1: (
                font[0],
                max(min_size, round(font[1] * size_mult)),
            ),
        )
        windows = []
        try:
            PanelConfig.navigation_bar_width = 1.0
            PanelConfig.navigation_bar_scale = 1.0
            base = NavigationWindow(app)
            windows.append(base)

            PanelConfig.navigation_bar_scale = 1.5
            scaled = NavigationWindow(app)
            windows.append(scaled)

            self.assertGreater(scaled.heading_tape.tape_height, base.heading_tape.tape_height)
            self.assertGreater(scaled.heading_tape.tape_width, base.heading_tape.tape_width)
            self.assertAlmostEqual(
                scaled.heading_tape.text_scale,
                UIConfig.clamp_text_scale(UIConfig.TEXT_SCALE_MULT * 1.5),
            )
        finally:
            for window in windows:
                window.destroy()
            PanelConfig.navigation_bar_scale = old_scale
            PanelConfig.navigation_bar_width = old_width

    def test_banana_progress_ring_separates_emoji_and_percent(self) -> None:
        banana = BananaProgress(self.root, size=64)
        banana.pack()
        try:
            banana.set_progress(0.5)
            self.root.update_idletasks()
            self.assertEqual(banana.progress, 0.5)
            self.assertEqual(banana.itemcget(banana.percent_text, "text"), "50%")
            self.assertEqual(banana.itemcget(banana.emoji_text, "text"), "🍌")
            self.assertEqual(float(banana.itemcget(banana.progress_arc, "extent")), -180.0)
            emoji_bbox = banana.bbox(banana.emoji_text)
            percent_bbox = banana.bbox(banana.percent_text)
            self.assertIsNotNone(emoji_bbox)
            self.assertIsNotNone(percent_bbox)
            assert emoji_bbox is not None and percent_bbox is not None
            self.assertLess(emoji_bbox[3], percent_bbox[1])

            banana.set_progress(2.0)
            self.assertEqual(banana.progress, 1.0)
            self.assertEqual(banana.itemcget(banana.percent_text, "text"), "100%")
            self.assertEqual(float(banana.itemcget(banana.progress_arc, "extent")), -359.9)
            bbox = banana.bbox("all")
            self.assertIsNotNone(bbox)
            assert bbox is not None
            self.assertGreaterEqual(bbox[0], 0)
            self.assertGreaterEqual(bbox[1], 0)
            self.assertLessEqual(bbox[2], banana.size)
            self.assertLessEqual(bbox[3], banana.size)
        finally:
            banana.destroy()

    def test_wrapped_content_schedules_geometry_expansion(self) -> None:
        calls: list[str] = []
        parent = tk.Frame(self.root, width=180)
        parent.pack(fill="x")
        label = tk.Label(
            parent,
            text="这是一段会在窄窗口换行并增加武器卡高度的测试文本",
            justify="left",
        )
        label.pack(fill="x")
        app = SimpleNamespace(
            scale=1.0,
            _schedule_content_geometry_sync=lambda: calls.append("sync"),
        )
        MainWindowBuilder(app)._bind_label_wrap(label, parent, margin=12)

        self.root.deiconify()
        self.root.geometry("180x80")
        self.root.update()

        self.assertTrue(calls)
        self.assertGreaterEqual(int(float(label.cget("wraplength"))), 80)

    def test_startup_geometry_convergence_shrinks_late_transient_wrap(self) -> None:
        frame = tk.Frame(self.root)
        frame.pack(fill="both", expand=True)
        label = tk.Label(frame, text="late startup row " * 80, wraplength=40)
        label.pack(fill="x")
        self.root.deiconify()
        self.root.geometry("300x100")
        self.root.update_idletasks()

        app = SimpleNamespace(
            root=self.root,
            _startup_geometry_after_id=None,
            _STARTUP_GEOMETRY_SETTLE_DELAYS_MS=(20, 20),
        )

        def recalc_size(**_kwargs) -> None:
            self.root.update_idletasks()
            self.root.geometry(f"300x{frame.winfo_reqheight() + 8}")

        app._recalc_size = recalc_size
        App._schedule_startup_geometry_convergence(app)
        self.root.update()
        inflated_height = self.root.winfo_height()

        label.config(text="settled", wraplength=280)
        self.root.update_idletasks()
        settled_requested_height = frame.winfo_reqheight() + 8
        deadline = time.monotonic() + 0.25
        while time.monotonic() < deadline and self.root.winfo_height() >= inflated_height:
            self.root.update()
            time.sleep(0.005)

        self.assertGreater(inflated_height, settled_requested_height)
        self.assertLess(self.root.winfo_height(), inflated_height)
        self.assertLessEqual(self.root.winfo_height(), settled_requested_height + 64)

    def test_checklist_uses_full_card_width_and_keeps_markers_separate(self) -> None:
        card = tk.Frame(self.root, width=640, height=360)
        card.pack()
        card.pack_propagate(False)
        border = tk.Frame(card)
        content = tk.Frame(card)
        recalc_calls: list[bool] = []
        app = SimpleNamespace(
            root=self.root,
            scale=1.5,
            chk_border_frame=border,
            chk_content_frame=content,
            chk_items=[
                "等待发动机转速稳定",
                "Y66或地图设定打击目标",
                "降落后Y65关闭座舱盖防噪音",
            ],
            _get_font=lambda _name: ("Segoe UI", 12),
            _recalc_size=lambda *, force_shrink=False: recalc_calls.append(force_shrink),
        )

        App._rebuild_checklist(app)
        self.root.update()
        app._checklist_wrap_updater(SimpleNamespace(width=640))
        self.root.update()

        rows = content.winfo_children()[1:]
        self.assertEqual(len(rows), 3)
        for row, expected_text in zip(rows, app.chk_items, strict=True):
            marker, item_label = row.winfo_children()
            self.assertEqual(marker.cget("text"), "○")
            self.assertEqual(item_label.cget("text"), expected_text)
            self.assertNotIn("○", item_label.cget("text"))
            self.assertGreater(int(float(item_label.cget("wraplength"))), 500)

        self.assertTrue(recalc_calls)
        self.assertTrue(all(recalc_calls))

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

    def test_heading_tape_renders_hostile_aircraft_candidate_in_red(self) -> None:
        tape = HeadingTape(self.root, width=280, height=36, text_scale=1.0)
        try:
            tape.update_tape_multi(
                90.0,
                [
                    {
                        "type": "hostile_aircraft",
                        "relative": 0.0,
                        "distance_km": 15.7,
                        "is_primary": False,
                        "is_target": True,
                    }
                ],
                10.0,
            )
            self.root.update_idletasks()

            distance_ids = tape.find_withtag("hostile_aircraft_distance")
            self.assertEqual(len(distance_ids), 1)
            self.assertEqual(tape.itemcget(distance_ids[0], "text"), "敌机 15.7")
            self.assertEqual(tape.itemcget(distance_ids[0], "fill"), Theme.RED)
        finally:
            tape.destroy()

    def test_heading_tape_integrates_centered_precision_guidance(self) -> None:
        tape = HeadingTape(self.root, width=320, height=36, text_scale=1.0)
        try:
            tape.update_tape_multi(
                90.0,
                [
                    {
                        "type": "zone",
                        "relative": 0.24,
                        "distance_km": 7.0,
                        "is_primary": True,
                    },
                    {
                        "type": "friendly",
                        "relative": -18.0,
                        "distance_km": 12.0,
                        "is_primary": False,
                    },
                ],
                7.0,
            )
            self.root.update_idletasks()

            guidance_text = tape.find_withtag("guidance_text")
            gate = tape.find_withtag("guidance_gate")
            pipper = tape.find_withtag("guidance_pipper")
            self.assertEqual(len(guidance_text), 1)
            self.assertTrue(gate)
            self.assertEqual(len(pipper), 1)
            self.assertTrue(tape.find_withtag("friendly_overflow"))
            self.assertIn("精确", tape.itemcget(guidance_text[0], "text"))
            self.assertIn("精确·右0.24°", tape.itemcget(guidance_text[0], "text"))
            self.assertIn("7.0km", tape.itemcget(guidance_text[0], "text"))

            text_bbox = tape.bbox(guidance_text[0])
            gate_bbox = tape.bbox("guidance_gate")
            pipper_bbox = tape.bbox(pipper[0])
            self.assertIsNotNone(text_bbox)
            self.assertIsNotNone(gate_bbox)
            self.assertIsNotNone(pipper_bbox)
            assert text_bbox is not None and gate_bbox is not None and pipper_bbox is not None
            center_x = tape.tape_width / 2
            self.assertLessEqual(gate_bbox[0], center_x)
            self.assertGreaterEqual(gate_bbox[2], center_x)
            self.assertGreater((pipper_bbox[0] + pipper_bbox[2]) / 2, center_x)
            self.assertGreater(text_bbox[1], tape._layout_metrics()["guidance_top"])
        finally:
            tape.destroy()

    def test_heading_guidance_expands_small_errors_without_losing_full_scale(self) -> None:
        tolerance = 3.0
        fine = HeadingTape._project_guidance_ratio(0.1, tolerance)
        edge = HeadingTape._project_guidance_ratio(tolerance, tolerance)
        overflow = HeadingTape._project_guidance_ratio(20.0, tolerance)

        self.assertGreater(fine, 0.1 / tolerance)
        self.assertAlmostEqual(edge, 1.0)
        self.assertAlmostEqual(overflow, 1.0)

    def test_heading_tape_places_aam_notice_inside_guidance_lane(self) -> None:
        tape = HeadingTape(self.root, width=280, height=36, text_scale=1.0)
        try:
            tape.update_tape_multi(
                90.0,
                [],
                10.0,
                mode_notice="战区解算已暂停，仅进行导航",
            )
            self.root.update_idletasks()

            guidance_text = tape.find_withtag("guidance_text")
            self.assertEqual(len(guidance_text), 1)
            self.assertEqual(
                tape.itemcget(guidance_text[0], "text"),
                "空空导航 · 战区解算暂停",
            )
            self.assertFalse(tape.find_withtag("guidance_pipper"))
        finally:
            tape.destroy()

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

    def test_main_card_stack_does_not_expand_middle_row_vertically(self) -> None:
        surface = tk.Frame(self.root)

        MainWindowBuilder._configure_surface_grid(surface)

        self.assertEqual(surface.grid_columnconfigure(0)["weight"], 1)
        self.assertEqual(surface.grid_rowconfigure(1)["weight"], 0)

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

    def test_navigation_surfaces_do_not_build_external_status_rows(self) -> None:
        main_source = Path("bomana/ui/main_window.py").read_text(encoding="utf-8")
        standalone_source = Path("bomana/ui/nav_window.py").read_text(encoding="utf-8")

        self.assertNotIn("tape_zone_row", main_source)
        self.assertNotIn("tape_friendly_row", main_source)
        self.assertNotIn("self.zone_row =", standalone_source)
        self.assertNotIn("self.friendly_row =", standalone_source)

    def test_renderer_compacts_fuel_to_one_line_and_keeps_bombing_details(self) -> None:
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
            app.fuel_main_lbl.cget("text"),
            app.fuel_detail_lbl.cget("text"),
            app.fuel_return_detail_lbl.cget("text"),
        ]
        bomb_texts = [
            app.bomb_trajectory_lbl.cget("text"),
            app.bomb_flight_lbl.cget("text"),
            app.bomb_release_lbl.cget("text"),
            app.bomb_release_detail_lbl.cget("text"),
        ]
        self.assertEqual(
            fuel_texts,
            [
                "油量 1800kg / 75% · 油耗 96kg/min · 高度 4321m · 返航需 650kg (27%) · 36km",
                "",
                "",
            ],
        )
        self.assertEqual(bomb_texts[0], "目标 战区 #2 3.12km · 弹道 2.14km · 飞行 12.3s")
        self.assertEqual(bomb_texts[1], "")
        self.assertEqual(bomb_texts[2], "接近")
        self.assertEqual(bomb_texts[3], "战区窗口 3.4s / 980m")
        self.assertEqual(app.fuel_alt_lbl.winfo_manager(), "")
        self.assertEqual(app.fuel_detail_lbl.winfo_manager(), "")
        self.assertEqual(app.fuel_return_detail_lbl.winfo_manager(), "")
        self.assertEqual(app.bomb_flight_lbl.winfo_manager(), "")
        self.assertEqual(app.bomb_release_detail_lbl.winfo_manager(), "pack")
        self.assertNotIn("│", " ".join(fuel_texts + bomb_texts))

    def test_main_window_reuses_shared_bombing_bar_without_tactical_map(self) -> None:
        source = Path("bomana/ui/main_window.py").read_text(encoding="utf-8")
        bombing_source = Path("bomana/ui/bombing_bar.py").read_text(encoding="utf-8")

        self.assertIn("app.bombing_bar = BombingBar(", source)
        self.assertIn('text="CCRP"', bombing_source)
        self.assertIn("padx=0,", source)
        self.assertNotIn("tactical_map", source + bombing_source)
        self.assertNotIn("weapon_map", source + bombing_source)


if __name__ == "__main__":
    unittest.main()
