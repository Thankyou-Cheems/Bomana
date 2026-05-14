import unittest

from bomana.ui.panel_renderer import AppPanelRenderer


class PanelRendererNavListTests(unittest.TestCase):
    def test_selected_nav_icon_replaces_base_icon(self) -> None:
        self.assertEqual(AppPanelRenderer._nav_list_icon("○", selected=True), "➤")
        self.assertEqual(AppPanelRenderer._nav_list_icon("🔴", selected=True), "➤")
        self.assertEqual(AppPanelRenderer._nav_list_icon("🔴", selected=False), "🔴")

    def test_nav_list_formatters_match_zone_and_airport_rows(self) -> None:
        self.assertEqual(AppPanelRenderer._format_nav_distance(8.25), "8.2km")
        self.assertEqual(AppPanelRenderer._format_nav_distance(12.9), "12km")
        self.assertEqual(AppPanelRenderer._format_nav_relative(4.9), "+4°")
        self.assertEqual(AppPanelRenderer._format_nav_relative(-4.9, precise=True), "-4.90°")


if __name__ == "__main__":
    unittest.main()
