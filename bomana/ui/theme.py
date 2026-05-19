"""Runtime theme tokens for Tk UI surfaces."""

from typing import ClassVar


class Theme:
    """颜色主题配置"""

    _current = "fluent_dark"

    THEMES: ClassVar[dict[str, dict[str, str]]] = {
        "fluent_dark": {
            "name": "Fluent 深色",
            "BG": "#10151d",
            "BORDER": "#354258",
            "TEXT": "#f2f6fb",
            "TEXT_DIM": "#bac7d8",
            "TEXT_MUTED": "#7f8da0",
            "GREEN": "#6ed081",
            "YELLOW": "#f2c14e",
            "RED": "#ff6b6b",
            "BLUE": "#5ab0ff",
            "ORANGE": "#ff9a52",
            "GRAYPILL": "#1a2330",
            "SEPARATOR": "#2a3648",
        },
        "fluent_light": {
            "name": "Fluent 亮色",
            "BG": "#f5f8fc",
            "BORDER": "#c8d5e6",
            "TEXT": "#132033",
            "TEXT_DIM": "#3b4e67",
            "TEXT_MUTED": "#677b96",
            "GREEN": "#1f8b4c",
            "YELLOW": "#9a6700",
            "RED": "#c63a3a",
            "BLUE": "#0a70e8",
            "ORANGE": "#c96a1f",
            "GRAYPILL": "#e9eff7",
            "SEPARATOR": "#d5e0ed",
        },
        "dark": {
            "name": "暗色 (Dark)",
            "BG": "#0a0e13",
            "BORDER": "#30363d",
            "TEXT": "#e6edf3",
            "TEXT_DIM": "#8b949e",
            "TEXT_MUTED": "#484f58",
            "GREEN": "#3fb950",
            "YELLOW": "#d29922",
            "RED": "#f85149",
            "BLUE": "#58a6ff",
            "ORANGE": "#f0883e",
            "GRAYPILL": "#161b22",
            "SEPARATOR": "#21262d",
        },
        "light": {
            "name": "亮色 (Light)",
            "BG": "#ffffff",
            "BORDER": "#d0d7de",
            "TEXT": "#1f2328",
            "TEXT_DIM": "#656d76",
            "TEXT_MUTED": "#8c959f",
            "GREEN": "#1a7f37",
            "YELLOW": "#9a6700",
            "RED": "#cf222e",
            "BLUE": "#0969da",
            "ORANGE": "#bc4c00",
            "GRAYPILL": "#f6f8fa",
            "SEPARATOR": "#d8dee4",
        },
        "high_contrast": {
            "name": "高对比度",
            "BG": "#000000",
            "BORDER": "#ffffff",
            "TEXT": "#ffffff",
            "TEXT_DIM": "#ffff00",
            "TEXT_MUTED": "#808080",
            "GREEN": "#00ff00",
            "YELLOW": "#ffff00",
            "RED": "#ff0000",
            "BLUE": "#00ffff",
            "ORANGE": "#ffa500",
            "GRAYPILL": "#1a1a1a",
            "SEPARATOR": "#404040",
        },
        "lunar_new_year": {
            "name": "农历新年 (Lunar New Year)",
            "BG": "#2a0d0d",
            "BORDER": "#9c4e1d",
            "TEXT": "#fbe7b2",
            "TEXT_DIM": "#e8c47a",
            "TEXT_MUTED": "#a8835c",
            "GREEN": "#8fbf6b",
            "YELLOW": "#e7b75b",
            "RED": "#e14c3a",
            "BLUE": "#5e8f8a",
            "ORANGE": "#c97a33",
            "GRAYPILL": "#4a1a14",
            "SEPARATOR": "#6a2b1a",
        },
    }

    BG = "#10151d"
    BORDER = "#354258"
    TEXT = "#f2f6fb"
    TEXT_DIM = "#bac7d8"
    TEXT_MUTED = "#7f8da0"
    GREEN = "#6ed081"
    YELLOW = "#f2c14e"
    RED = "#ff6b6b"
    BLUE = "#5ab0ff"
    ORANGE = "#ff9a52"
    GRAYPILL = "#1a2330"
    SEPARATOR = "#2a3648"

    @classmethod
    def apply(cls, theme_name: str) -> bool:
        if theme_name not in cls.THEMES:
            return False

        theme = cls.THEMES[theme_name]
        cls._current = theme_name
        cls.BG = theme["BG"]
        cls.BORDER = theme["BORDER"]
        cls.TEXT = theme["TEXT"]
        cls.TEXT_DIM = theme["TEXT_DIM"]
        cls.TEXT_MUTED = theme["TEXT_MUTED"]
        cls.GREEN = theme["GREEN"]
        cls.YELLOW = theme["YELLOW"]
        cls.RED = theme["RED"]
        cls.BLUE = theme["BLUE"]
        cls.ORANGE = theme["ORANGE"]
        cls.GRAYPILL = theme["GRAYPILL"]
        cls.SEPARATOR = theme["SEPARATOR"]
        return True

    @classmethod
    def get_current(cls) -> str:
        return cls._current

    @classmethod
    def get_theme_names(cls) -> list[str]:
        return list(cls.THEMES.keys())

    @classmethod
    def get_theme_display_name(cls, theme_name: str) -> str:
        if theme_name in cls.THEMES:
            return cls.THEMES[theme_name]["name"]
        return theme_name
