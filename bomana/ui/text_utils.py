"""Shared Tk text measurement and wrapping helpers."""

from __future__ import annotations

import contextlib
import tkinter as tk
import tkinter.font as tkfont
from collections.abc import Callable
from typing import Any


def measure_text_width(
    font: Any,
    text: str,
    *,
    master: tk.Misc | None = None,
    fallback_scale: float = 1.0,
) -> int:
    """Measure text width using Tk font metrics with a conservative fallback."""
    try:
        return int(tkfont.Font(master=master, font=font).measure(text))
    except tk.TclError:
        return int(len(text) * 8 * max(0.6, float(fallback_scale or 1.0)))


def measure_min_width(
    font: Any,
    text: str,
    *,
    master: tk.Misc | None = None,
    fallback_scale: float = 1.0,
    padding: int | None = None,
) -> int:
    """Return a pixel minsize that can contain the text plus padding."""
    scale = max(0.6, float(fallback_scale or 1.0))
    resolved_padding = max(8, int(8 * scale)) if padding is None else int(padding)
    return measure_text_width(font, text, master=master, fallback_scale=scale) + resolved_padding


def set_elided_text(
    label: tk.Label,
    text: str,
    max_width: int,
    *,
    ellipsis: str = "...",
) -> str:
    """Set label text, truncating in the middle of a word only when needed."""
    if max_width <= 0:
        label.configure(text=text)
        return text

    font = label.cget("font") or "TkDefaultFont"
    if measure_text_width(font, text, master=label) <= max_width:
        label.configure(text=text)
        return text

    if measure_text_width(font, ellipsis, master=label) > max_width:
        label.configure(text="")
        return ""

    low = 0
    high = len(text)
    best = ellipsis
    while low <= high:
        mid = (low + high) // 2
        candidate = text[:mid].rstrip() + ellipsis
        if measure_text_width(font, candidate, master=label) <= max_width:
            best = candidate
            low = mid + 1
        else:
            high = mid - 1

    label.configure(text=best)
    return best


def bind_dynamic_wrap(
    label: tk.Label,
    parent: tk.Misc | None = None,
    *,
    minimum: int = 80,
    margin: int = 0,
    width_fn: Callable[[int], int] | None = None,
) -> None:
    """Keep a label's wraplength aligned with live container width."""
    if getattr(label, "_bomana_dynamic_wrap", False):
        return
    target = parent or label.master
    if target is None:
        return
    label._bomana_dynamic_wrap = True

    def update_wrap(event=None) -> None:
        width = int(getattr(event, "width", 0) or target.winfo_width() or 0)
        if width <= 1:
            return
        wrap = width_fn(width) if width_fn is not None else width - int(margin)
        label.configure(wraplength=max(int(minimum), int(wrap)))

    target.bind("<Configure>", update_wrap, add="+")
    label.after_idle(update_wrap)


def bind_existing_label_wraps(
    widget: tk.Misc,
    *,
    minimum_from_current: Callable[[int], int] | None = None,
    margin: int = 24,
) -> None:
    """Bind all labels under widget that already declare a wraplength."""
    for child in widget.winfo_children():
        bind_existing_label_wraps(
            child,
            minimum_from_current=minimum_from_current,
            margin=margin,
        )

    if not isinstance(widget, tk.Label):
        return
    with contextlib.suppress(tk.TclError, ValueError):
        wraplength = int(float(widget.cget("wraplength") or 0))
        if wraplength <= 0:
            return
        minimum = (
            minimum_from_current(wraplength)
            if minimum_from_current is not None
            else max(100, min(180, int(wraplength * 0.45)))
        )
        bind_dynamic_wrap(widget, minimum=minimum, margin=margin)


def scaled_control_length(base_length: int, ui_scale: float) -> int:
    """Scale a fixed Tk control length while preserving the original minimum."""
    return max(int(base_length), round(int(base_length) * max(0.6, float(ui_scale or 1.0))))
