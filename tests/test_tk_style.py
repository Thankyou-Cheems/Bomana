import ast
from pathlib import Path

from bomana.ui.dialogs import _ScalableDialogMixin
from bomana.ui.tk_style import TkPalette, action_button_style


def test_palette_from_source_fills_launcher_card_tokens() -> None:
    palette = TkPalette.from_source(
        {
            "BG": "#000000",
            "CARD": "#111111",
            "CARD_ALT": "#222222",
            "CARD_SOFT": "#333333",
            "BLUE": "#444444",
        }
    )

    assert palette.bg == "#000000"
    assert palette.card == "#111111"
    assert palette.card_alt == "#222222"
    assert palette.card_soft == "#333333"
    assert palette.blue == "#444444"


def test_action_button_variants_share_control_tokens() -> None:
    palette = TkPalette.from_source(
        {
            "CARD": "#101820",
            "CARD_ALT": "#182230",
            "CARD_SOFT": "#203044",
            "BORDER": "#405060",
            "SEPARATOR": "#303840",
            "TEXT": "#f0f6ff",
            "BLUE": "#60aaff",
            "GREEN": "#70d080",
            "YELLOW": "#f2c14e",
            "ORANGE": "#ff9a52",
        }
    )

    primary = action_button_style("primary", palette=palette)
    assert primary.bg == "#60aaff"
    assert primary.hover_bg == "#70d080"
    assert primary.fg == "#f0f6ff"

    secondary = action_button_style("secondary", palette=palette)
    assert secondary.bg == "#203044"
    assert secondary.hover_bg == "#405060"
    assert secondary.press_bg == "#303840"

    assert action_button_style("unknown", palette=palette) == action_button_style(
        "neutral", palette=palette
    )


def test_dialog_action_button_factory_stays_on_scalable_mixin() -> None:
    source = Path("bomana/ui/dialogs.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    definitions = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_create_action_button"
    ]

    assert len(definitions) == 1
    assert "_create_action_button" in _ScalableDialogMixin.__dict__
