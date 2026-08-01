"""Bundled PNG icon helpers."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from typing import Any

from bomana.utils.file_utils import resource_path

ICON_ASSET_SIZES = (12, 14, 16, 18, 20, 24, 28, 32, 40, 48, 64)


class IconManager:
    """Load and attach bundled PNG icons while keeping Tk references alive."""

    _ASSET_SIZES = ICON_ASSET_SIZES

    def __init__(self, root: tk.Misc):
        self.root = root
        self._cache: dict[tuple[str, int], tk.PhotoImage] = {}

    @classmethod
    def _nearest_asset_size(cls, size: int) -> int:
        requested = max(1, int(size))
        for candidate in cls._ASSET_SIZES:
            if candidate >= requested:
                return candidate
        return cls._ASSET_SIZES[-1]

    @classmethod
    def scaled_size(
        cls,
        base_size: int,
        scale: float,
        *,
        min_size: int = 16,
        max_size: int | None = None,
    ) -> int:
        """Return an icon size request that can use the full bundled asset range."""
        upper = cls._ASSET_SIZES[-1] if max_size is None else int(max_size)
        requested = round(int(base_size) * max(0.6, float(scale or 1.0)))
        return max(int(min_size), min(int(upper), requested))

    def photo(self, key: str, size: int = 16) -> tk.PhotoImage | None:
        asset_size = self._nearest_asset_size(size)
        cache_key = (key, asset_size)
        if cache_key in self._cache:
            return self._cache[cache_key]

        path = Path(resource_path(f"bomana/assets/icons/{key}_{asset_size}.png"))
        if not path.exists():
            return None
        try:
            image = tk.PhotoImage(master=self.root, file=str(path))
        except tk.TclError:
            return None
        self._cache[cache_key] = image
        return image

    def configure_label(
        self,
        label: tk.Widget,
        *,
        icon: str | None,
        text: str = "",
        size: int = 16,
        compound: str = "left",
        padx: int = 4,
        **kwargs: Any,
    ) -> None:
        image = self.photo(icon, size) if icon else None
        config = {"text": text, **kwargs}
        if image is not None:
            config.update({"image": image, "compound": compound, "padx": padx})
            label._bomana_icon_image = image
        else:
            config.update({"image": "", "compound": "none", "padx": 0})
            label._bomana_icon_image = None
        label.config(**config)
