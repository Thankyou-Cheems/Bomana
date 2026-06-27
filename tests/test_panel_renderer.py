import unittest
from pathlib import Path

from PIL import Image

from bomana.ui.icon_assets import IconManager
from bomana.ui.panel_renderer import AppPanelRenderer


class PanelRendererNavListTests(unittest.TestCase):
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
