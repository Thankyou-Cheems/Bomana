import unittest
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from bomana.ui.icon_assets import IconManager
from bomana.ui.panel_renderer import AppPanelRenderer
from bomana.ui.theme import Theme


class FakeLabel:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}

    def config(self, **kwargs) -> None:
        self.options.update(kwargs)

    def cget(self, key: str):
        return self.options.get(key, "")


class FakePackLabel(FakeLabel):
    def __init__(self, manager: str = "") -> None:
        super().__init__()
        self.manager = manager

    def winfo_manager(self) -> str:
        return self.manager

    def pack(self, **_kwargs) -> None:
        self.manager = "pack"

    def pack_forget(self) -> None:
        self.manager = ""


class FakeIcons:
    @staticmethod
    def configure_label(label, *, icon, text, **_kwargs) -> None:
        label.config(icon=icon, text=text)


class PanelRendererNavListTests(unittest.TestCase):
    def test_weapon_detail_row_replaces_legacy_ccrp_detail_row(self) -> None:
        app = SimpleNamespace(
            scale=1.0,
            icons=FakeIcons(),
            bomb_select_lbl=FakeLabel(),
            bomb_trajectory_lbl=FakeLabel(),
            bomb_flight_lbl=FakePackLabel(),
            bomb_release_lbl=FakeLabel(),
            bomb_release_detail_lbl=FakePackLabel("pack"),
        )
        snap = SimpleNamespace(
            weapon_id="agm_65d",
            weapon_display_name="AGM-65D",
            weapon_role="agm",
            weapon_control="guided",
            weapon_selection_source="manual",
            weapon_selection_compatible=True,
            weapon_solution_valid=True,
            weapon_status="in_envelope",
            weapon_quality="two_dimensional",
            weapon_target_kind="poi",
            weapon_target_name="",
            weapon_target_distance_m=12_400.0,
            weapon_min_range_m=600.0,
            weapon_max_range_m=18_600.0,
            weapon_time_to_target_s=28.0,
            weapon_time_to_window_s=0.0,
        )

        AppPanelRenderer(app).update_bombing_display(snap)

        self.assertEqual(app.bomb_flight_lbl.winfo_manager(), "pack")
        self.assertEqual(app.bomb_flight_lbl.cget("text"), "飞行约 28s · 二维参考")
        self.assertEqual(app.bomb_release_detail_lbl.winfo_manager(), "")
        self.assertEqual(app.bomb_release_lbl.cget("text"), "估算窗内")

    def test_selected_nav_icon_replaces_base_icon(self) -> None:
        self.assertEqual(AppPanelRenderer._nav_list_icon("zone", selected=True), "target")
        self.assertEqual(AppPanelRenderer._nav_list_icon("airfield_enemy", selected=True), "target")
        self.assertEqual(
            AppPanelRenderer._nav_list_icon("airfield_enemy", selected=False),
            "airfield_enemy",
        )

    def test_nav_list_formatters_match_zone_and_airport_rows(self) -> None:
        self.assertEqual(AppPanelRenderer._format_nav_distance(8.25), "8.2km")
        self.assertEqual(AppPanelRenderer._format_nav_distance(12.9), "12km")
        self.assertEqual(AppPanelRenderer._format_nav_relative(4.9), "+4°")
        self.assertEqual(AppPanelRenderer._format_nav_relative(-4.9, precise=True), "-4.90°")

    def test_dense_nav_list_item_preserves_all_navigation_fields(self) -> None:
        item = AppPanelRenderer._build_nav_list_item(
            base_icon="zone",
            selected=True,
            direction="NE",
            distance_km=8.25,
            relative=-4.9,
            fg=Theme.GREEN,
            precise_relative=True,
        )

        self.assertEqual(item.icon, "target")
        self.assertEqual(item.direction, "NE")
        self.assertEqual(item.distance, "8.2km")
        self.assertEqual(item.relative, "-4.90°")
        self.assertEqual(item.fg, Theme.GREEN)

    def test_tape_status_row_keeps_zone_primary_when_poi_marker_exists(self) -> None:
        app = SimpleNamespace(
            tape_zone_label=FakeLabel(),
            tape_turn_lbl=FakeLabel(),
            tape_deviation_lbl=FakeLabel(),
            tape_tolerance_lbl=FakeLabel(),
            tape_zone_info=FakeLabel(),
            tape_tolerance_legend=FakeLabel(),
            tape_friendly_turn=None,
            tape_friendly_status=None,
            tape_friendly_info=None,
        )
        renderer = AppPanelRenderer(app)
        poi_info = {
            "type": "poi",
            "name": "补给点",
            "relative": 12.0,
            "distance_km": 4.25,
            "color": Theme.YELLOW,
        }
        zone_info = {
            "type": "zone",
            "name": "战区",
            "relative": -3.0,
            "distance_km": 7.0,
            "ete_str": "01:10",
            "color": Theme.RED,
        }

        renderer.update_tape_info_labels([poi_info, zone_info])

        self.assertEqual(app.tape_zone_label.cget("text"), "⊚战区:")
        self.assertEqual(app.tape_zone_label.cget("fg"), Theme.RED)
        self.assertNotIn("补给点", app.tape_zone_info.cget("text"))
        self.assertIn("7.0km", app.tape_zone_info.cget("text"))
        self.assertIn("01:10", app.tape_zone_info.cget("text"))
        self.assertEqual(app.tape_zone_info.cget("fg"), Theme.RED)
        self.assertTrue(app.tape_turn_lbl.cget("text"))
        self.assertTrue(app.tape_deviation_lbl.cget("text"))
        self.assertIn("°", app.tape_tolerance_legend.cget("text"))

    def test_icon_manager_uses_nearest_generated_size(self) -> None:
        self.assertEqual(IconManager._nearest_asset_size(17), 18)
        self.assertEqual(IconManager._nearest_asset_size(26), 28)
        self.assertEqual(IconManager._nearest_asset_size(31), 32)
        self.assertEqual(IconManager._nearest_asset_size(36), 40)
        self.assertEqual(IconManager._nearest_asset_size(49), 64)
        self.assertEqual(IconManager._nearest_asset_size(96), 64)

    def test_icon_manager_scaled_size_uses_extended_asset_range(self) -> None:
        self.assertEqual(IconManager.scaled_size(18, 1.0), 18)
        self.assertEqual(IconManager.scaled_size(18, 1.5), 27)
        self.assertEqual(IconManager._nearest_asset_size(IconManager.scaled_size(18, 1.5)), 28)
        self.assertEqual(IconManager.scaled_size(18, 2.5), 45)
        self.assertEqual(IconManager._nearest_asset_size(IconManager.scaled_size(18, 2.5)), 48)

    def test_remove_helpers_act_on_managed_but_unmapped_widgets(self) -> None:
        class FakeWidget:
            def __init__(self, manager: str) -> None:
                self.manager = manager
                self.grid_remove_calls = 0
                self.pack_forget_calls = 0

            def winfo_manager(self) -> str:
                return self.manager

            def winfo_ismapped(self) -> bool:
                return False

            def grid_remove(self) -> None:
                self.grid_remove_calls += 1
                self.manager = ""

            def pack_forget(self) -> None:
                self.pack_forget_calls += 1
                self.manager = ""

        grid_widget = FakeWidget("grid")
        pack_widget = FakeWidget("pack")

        self.assertTrue(AppPanelRenderer._grid_remove_if_needed(grid_widget))
        self.assertTrue(AppPanelRenderer._pack_forget_if_needed(pack_widget))
        self.assertEqual(grid_widget.grid_remove_calls, 1)
        self.assertEqual(pack_widget.pack_forget_calls, 1)

    def test_standalone_navigation_update_is_not_nested_under_zones_branch(self) -> None:
        source = Path("bomana/ui/panel_renderer.py").read_text(encoding="utf-8")
        update_index = source.index("app.nav_window.update_display(snap)")
        zones_branch_index = source.index("if zones_enabled:", update_index)

        self.assertLess(update_index, zones_branch_index)

    def test_extended_icon_assets_exist_for_large_text_scales(self) -> None:
        icon_dir = Path("bomana/assets/icons")
        for key in ("zone", "aircraft", "fuel", "clock", "target"):
            for size in (40, 48, 64):
                path = icon_dir / f"{key}_{size}.png"
                self.assertTrue(path.exists())
                with Image.open(path) as image:
                    self.assertEqual(image.size, (size, size))


if __name__ == "__main__":
    unittest.main()
