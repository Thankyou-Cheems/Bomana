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
