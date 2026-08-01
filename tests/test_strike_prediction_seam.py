from __future__ import annotations

from bomana.ui.strike_prediction import (
    UnavailableStrikePredictionUi,
    create_bombing_bar,
    create_strike_prediction_ui,
)


def test_public_strike_prediction_adapter_is_inert() -> None:
    adapter = create_strike_prediction_ui(object())

    assert isinstance(adapter, UnavailableStrikePredictionUi)
    assert adapter.set_mode("standalone") is False
    assert adapter.update(object(), active=True) is None
    assert adapter.stop() is None


def test_public_bombing_view_is_not_loaded() -> None:
    assert create_bombing_bar(object(), object()) is None
