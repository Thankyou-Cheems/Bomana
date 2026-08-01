"""Public UI seam for the optional private Strike Prediction implementation."""

from __future__ import annotations

from typing import Any, Protocol

from bomana.config.feature_profile import ENABLE_CCRP


class StrikePredictionUi(Protocol):
    """Interface consumed by the public App coordinator."""

    def init_window(self) -> None: ...

    def toggle_mode(self) -> None: ...

    def set_mode(self, mode: str) -> bool: ...

    def update(self, snapshot: Any, *, active: bool) -> None: ...

    def refresh_host(self) -> None: ...

    def apply_lock_state(self, *, locked: bool, alpha: int) -> None: ...

    def rebuild_after_display_change(self) -> None: ...

    def stop(self) -> None: ...


class UnavailableStrikePredictionUi:
    """Inert public adapter used by Lite and Standard."""

    def init_window(self) -> None:
        return None

    def toggle_mode(self) -> None:
        return None

    def set_mode(self, mode: str) -> bool:
        return False

    def update(self, snapshot: Any, *, active: bool) -> None:
        return None

    def refresh_host(self) -> None:
        return None

    def apply_lock_state(self, *, locked: bool, alpha: int) -> None:
        return None

    def rebuild_after_display_change(self) -> None:
        return None

    def stop(self) -> None:
        return None


def create_strike_prediction_ui(app: Any) -> StrikePredictionUi:
    """Load the private adapter only for an Enhanced source closure."""

    if not ENABLE_CCRP:
        return UnavailableStrikePredictionUi()
    try:
        from bomana.ui.bombing_runtime import AppBombingServices
    except ImportError as exc:
        raise RuntimeError("Strike Prediction implementation is not installed") from exc
    return AppBombingServices(app)


def create_bombing_bar(parent: Any, app: Any, **kwargs: Any) -> Any | None:
    """Create the private bombing view without importing it in public editions."""

    if not ENABLE_CCRP:
        return None
    try:
        from bomana.ui.bombing_bar import BombingBar
    except ImportError as exc:
        raise RuntimeError("Strike Prediction view is not installed") from exc
    return BombingBar(parent, app, **kwargs)


__all__ = [
    "StrikePredictionUi",
    "UnavailableStrikePredictionUi",
    "create_bombing_bar",
    "create_strike_prediction_ui",
]
