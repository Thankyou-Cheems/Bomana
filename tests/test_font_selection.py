from bomana.utils import system


def _mock_families(monkeypatch, names):
    monkeypatch.setattr(system, "load_bundled_ui_fonts", lambda: False)
    monkeypatch.setattr(system.tkfont, "families", lambda root=None: tuple(names))


def test_select_ui_font_prefers_bundled_family(monkeypatch):
    _mock_families(monkeypatch, ["Segoe UI", "Bomana UI Sans", "Microsoft YaHei UI"])

    assert system.select_ui_font_family(object()) == "Bomana UI Sans"


def test_resolve_ui_font_uses_cjk_family_on_windows(monkeypatch):
    _mock_families(monkeypatch, ["Segoe UI", "Microsoft YaHei UI"])
    monkeypatch.setattr(system.os, "name", "nt")

    assert system.resolve_tk_font_tuple(object(), ("Segoe UI", 10)) == (
        "Microsoft YaHei UI",
        10,
    )


def test_resolve_monospace_font_preserves_size_and_weight(monkeypatch):
    _mock_families(monkeypatch, ["Segoe UI", "Cascadia Mono", "Consolas"])

    assert system.resolve_tk_font_tuple(object(), ("Consolas", 9, "bold")) == (
        "Cascadia Mono",
        9,
        "bold",
    )


def test_resolve_custom_available_font_is_preserved(monkeypatch):
    _mock_families(monkeypatch, ["Custom Display", "Segoe UI"])

    assert system.resolve_tk_font_tuple(object(), ("Custom Display", 12)) == (
        "Custom Display",
        12,
    )
