"""Shared Tk visual tokens and control styling helpers."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Mapping
from dataclasses import dataclass

from bomana.ui.theme import Theme


@dataclass(frozen=True, slots=True)
class TkPalette:
    bg: str
    card: str
    card_alt: str
    card_soft: str
    border: str
    separator: str
    text: str
    text_dim: str
    text_muted: str
    blue: str
    green: str
    yellow: str
    red: str
    orange: str

    @classmethod
    def from_source(cls, source: Mapping[str, str] | None = None) -> TkPalette:
        data = source or {}

        def pick(key: str, fallback: str) -> str:
            return str(data.get(key, fallback))

        bg = pick("BG", Theme.BG)
        card = pick("CARD", pick("GRAYPILL", Theme.GRAYPILL))
        card_alt = pick("CARD_ALT", card)
        return cls(
            bg=bg,
            card=card,
            card_alt=card_alt,
            card_soft=pick("CARD_SOFT", card_alt),
            border=pick("BORDER", Theme.BORDER),
            separator=pick("SEPARATOR", Theme.SEPARATOR),
            text=pick("TEXT", Theme.TEXT),
            text_dim=pick("TEXT_DIM", Theme.TEXT_DIM),
            text_muted=pick("TEXT_MUTED", Theme.TEXT_MUTED),
            blue=pick("BLUE", Theme.BLUE),
            green=pick("GREEN", Theme.GREEN),
            yellow=pick("YELLOW", Theme.YELLOW),
            red=pick("RED", Theme.RED),
            orange=pick("ORANGE", Theme.ORANGE),
        )


@dataclass(frozen=True, slots=True)
class TkButtonStyle:
    bg: str
    fg: str
    hover_bg: str
    press_bg: str
    border: str
    hover_border: str


def action_button_style(
    variant: str = "neutral",
    *,
    palette: Mapping[str, str] | TkPalette | None = None,
) -> TkButtonStyle:
    """Return the shared Bomana Tk action-button variant."""
    colors = palette if isinstance(palette, TkPalette) else TkPalette.from_source(palette)
    styles = {
        "primary": TkButtonStyle(
            bg=colors.blue,
            fg=colors.text,
            hover_bg=colors.green,
            press_bg=colors.blue,
            border=colors.blue,
            hover_border=colors.green,
        ),
        "success": TkButtonStyle(
            bg="#3d8458",
            fg=colors.text,
            hover_bg="#4c9a68",
            press_bg="#34724d",
            border="#78c896",
            hover_border="#78c896",
        ),
        "secondary": TkButtonStyle(
            bg=colors.card_soft,
            fg=colors.text,
            hover_bg=colors.border,
            press_bg=colors.separator,
            border=colors.border,
            hover_border=colors.blue,
        ),
        "neutral": TkButtonStyle(
            bg=colors.card,
            fg=colors.text,
            hover_bg=colors.separator,
            press_bg=colors.card_alt,
            border=colors.border,
            hover_border=colors.blue,
        ),
        "warning": TkButtonStyle(
            bg="#7f5a22",
            fg=colors.text,
            hover_bg="#9a6d2a",
            press_bg="#6b4b1b",
            border="#c79245",
            hover_border="#c79245",
        ),
        "danger": TkButtonStyle(
            bg="#672c32",
            fg=colors.text,
            hover_bg="#873940",
            press_bg="#55242a",
            border=colors.red,
            hover_border=colors.red,
        ),
        "accent": TkButtonStyle(
            bg=colors.yellow,
            fg=colors.text,
            hover_bg=colors.orange,
            press_bg=colors.yellow,
            border=colors.yellow,
            hover_border=colors.orange,
        ),
    }
    return styles.get(str(variant or "neutral"), styles["neutral"])


def clickable_surface_style(
    *,
    palette: Mapping[str, str] | TkPalette | None = None,
) -> TkButtonStyle:
    """Return the shared non-button click-target affordance."""
    colors = palette if isinstance(palette, TkPalette) else TkPalette.from_source(palette)
    return TkButtonStyle(
        bg=colors.card,
        fg=colors.blue,
        hover_bg=colors.separator,
        press_bg=colors.card_alt,
        border=colors.border,
        hover_border=colors.blue,
    )


def style_clickable_surface(
    widget: tk.Widget,
    *,
    palette: Mapping[str, str] | TkPalette | None = None,
) -> TkButtonStyle:
    """Give clickable labels/frames a visible border and hover response."""
    style = clickable_surface_style(palette=palette)
    options = {
        "bg": style.bg,
        "cursor": "hand2",
        "highlightthickness": 1,
        "highlightbackground": style.border,
        "highlightcolor": style.hover_border,
    }
    supported_options = set(widget.keys())
    if "fg" in supported_options:
        options["fg"] = style.fg
    widget.configure(**options)
    widget._bomana_clickable_style = style
    if getattr(widget, "_bomana_clickable_bound", False):
        return style
    widget._bomana_clickable_bound = True

    def on_enter(_event: tk.Event | None = None) -> None:
        widget.configure(bg=style.hover_bg, highlightbackground=style.hover_border)

    def on_leave(_event: tk.Event | None = None) -> None:
        widget.configure(bg=style.bg, highlightbackground=style.border)

    widget.bind("<Enter>", on_enter, add="+")
    widget.bind("<Leave>", on_leave, add="+")
    return style


def style_action_button(
    button: tk.Button,
    variant: str = "neutral",
    *,
    palette: Mapping[str, str] | TkPalette | None = None,
    bd: int = 0,
    highlightthickness: int = 1,
) -> TkButtonStyle:
    """Apply shared action-button colors and pointer feedback to a Tk button."""
    style = action_button_style(variant, palette=palette)
    button._bomana_button_style = style
    button.configure(
        bg=style.bg,
        fg=style.fg,
        activebackground=style.hover_bg,
        activeforeground=style.fg,
        bd=bd,
        relief="flat",
        highlightthickness=highlightthickness,
        highlightbackground=style.border,
        highlightcolor=style.border,
        cursor="hand2",
    )
    _bind_button_motion(button)
    return style


def _bind_button_motion(button: tk.Button) -> None:
    if getattr(button, "_bomana_motion_bound", False):
        return
    button._bomana_motion_bound = True

    def style_for_button() -> TkButtonStyle | None:
        style = getattr(button, "_bomana_button_style", None)
        return style if isinstance(style, TkButtonStyle) else None

    def on_enter(_event: tk.Event | None = None) -> None:
        if str(button.cget("state")) == "disabled":
            return
        if style := style_for_button():
            button.configure(bg=style.hover_bg, highlightbackground=style.hover_border)

    def on_leave(_event: tk.Event | None = None) -> None:
        if style := style_for_button():
            button.configure(bg=style.bg, highlightbackground=style.border)

    def on_press(_event: tk.Event | None = None) -> None:
        if str(button.cget("state")) == "disabled":
            return
        if style := style_for_button():
            button.configure(bg=style.press_bg, highlightbackground=style.hover_border)

    def on_release(event: tk.Event) -> None:
        style = style_for_button()
        if not style:
            return
        if str(button.cget("state")) == "disabled":
            button.configure(bg=style.bg, highlightbackground=style.border)
            return
        under = button.winfo_containing(event.x_root, event.y_root)
        if under == button:
            button.configure(bg=style.hover_bg, highlightbackground=style.hover_border)
        else:
            button.configure(bg=style.bg, highlightbackground=style.border)

    button.bind("<Enter>", on_enter, add="+")
    button.bind("<Leave>", on_leave, add="+")
    button.bind("<ButtonPress-1>", on_press, add="+")
    button.bind("<ButtonRelease-1>", on_release, add="+")
