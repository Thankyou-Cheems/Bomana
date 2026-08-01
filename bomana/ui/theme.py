"""Runtime theme tokens for Tk UI surfaces."""

from typing import ClassVar


class Instrument:
    """Fixed dark-screen palette for canvas instruments (heading tape, CCRP cue).

    图标语言里仪表始终是深色屏幕；这些值与 fluent_dark 一致且不随主题切换，
    保证画布内按深色底调校的标记颜色在任何主题下都可读。
    """

    BG = "#10151d"
    GRID = "#2a3648"
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


class Theme:
    """颜色主题配置"""

    DEFAULT = "fluent_dark"
    LIGHT_THEMES: ClassVar[frozenset[str]] = frozenset({"glacier", "fluent_light", "light"})
    _current = DEFAULT

    # 图标签名元素：暗色芯片上的 LED 数字（主题无关）
    SCREEN = "#23262b"
    SCREEN_EDGE = "#0c0f13"
    LED = "#ff4136"
    LED_WARN = "#ffb400"
    LED_CRIT = "#ff8a80"
    LED_DIM = "#7d534f"

    THEMES: ClassVar[dict[str, dict[str, str]]] = {
        "glacier": {
            "name": "冰晶浅色 (Glacier)",
            "BG": "#dcecf8",
            "BORDER": "#a3c3da",
            "TEXT": "#10293d",
            "TEXT_DIM": "#3c5a73",
            "TEXT_MUTED": "#5f7d95",
            "GREEN": "#178a55",
            "YELLOW": "#a8730a",
            "RED": "#d83036",
            "BLUE": "#1b6fb5",
            "ORANGE": "#d55f14",
            "GRAYPILL": "#f4f9fd",
            "SEPARATOR": "#c6dcea",
        },
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
    def apply_or_default(cls, theme_name: object) -> str:
        """Apply a saved theme, falling back to the product default."""
        if not isinstance(theme_name, str) or not cls.apply(theme_name):
            cls.apply(cls.DEFAULT)
        return cls._current

    @classmethod
    def get_current(cls) -> str:
        return cls._current

    @classmethod
    def get_theme_names(cls) -> list[str]:
        return [cls.DEFAULT, *(name for name in cls.THEMES if name != cls.DEFAULT)]

    @classmethod
    def get_theme_display_name(cls, theme_name: str) -> str:
        if theme_name in cls.THEMES:
            return cls.THEMES[theme_name]["name"]
        return theme_name

    @classmethod
    def is_light(cls, theme_name: str | None = None) -> bool:
        """Return whether a named or active theme uses a light appearance."""
        return (theme_name or cls._current) in cls.LIGHT_THEMES
