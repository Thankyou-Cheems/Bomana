from bomana.ui.theme import Theme


def test_fluent_dark_remains_the_default_theme() -> None:
    previous = Theme.get_current()
    try:
        assert Theme.DEFAULT == "fluent_dark"
        assert Theme.get_theme_names()[0] == Theme.DEFAULT
        assert Theme.apply_or_default(None) == Theme.DEFAULT
        assert Theme.BG == "#10151d"
        assert Theme.GRAYPILL == "#1a2330"
        assert not Theme.is_light()
    finally:
        Theme.apply_or_default(previous)


def test_glacier_is_an_optional_light_theme() -> None:
    previous = Theme.get_current()
    try:
        assert Theme.apply_or_default("glacier") == "glacier"
        assert Theme.is_light()
        assert Theme.BG == "#dcecf8"
        assert Theme.get_theme_display_name("glacier") == "冰晶浅色 (Glacier)"
    finally:
        Theme.apply_or_default(previous)


def test_unknown_saved_theme_falls_back_to_default() -> None:
    previous = Theme.get_current()
    try:
        Theme.apply_or_default("glacier")
        assert Theme.apply_or_default("missing-theme") == Theme.DEFAULT
    finally:
        Theme.apply_or_default(previous)
