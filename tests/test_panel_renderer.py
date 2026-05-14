import unittest

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
        self.assertEqual(IconManager._nearest_asset_size(17), 16)
        self.assertEqual(IconManager._nearest_asset_size(26), 24)
        self.assertEqual(IconManager._nearest_asset_size(31), 32)


if __name__ == "__main__":
    unittest.main()
