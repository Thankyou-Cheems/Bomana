from __future__ import annotations

from types import SimpleNamespace

import pytest

from bomana.config.settings import GameConfig
from bomana.core.state import LifeState
from bomana.ui.app import App


@pytest.fixture(autouse=True)
def _restore_timer_period():
    previous = GameConfig.CYCLE_SECONDS
    yield
    GameConfig.CYCLE_SECONDS = previous


@pytest.mark.parametrize("minutes", [1, 15, 60, 180])
def test_game_config_accepts_bounded_integer_minutes(minutes: int) -> None:
    assert GameConfig.set_cycle_minutes(minutes) is True
    assert minutes * 60 == GameConfig.CYCLE_SECONDS
    assert GameConfig.cycle_minutes() == minutes


@pytest.mark.parametrize("value", [True, False, 0, 181, 1.5, "60", None])
def test_game_config_rejects_non_integer_or_out_of_range_minutes(value) -> None:
    GameConfig.CYCLE_SECONDS = 15 * 60
    assert GameConfig.set_cycle_minutes(value) is False
    assert GameConfig.CYCLE_SECONDS == 15 * 60


def test_active_life_recomputes_immediately_without_changing_spawn_time() -> None:
    life = LifeState(spawn_time=100.0, life_index=1)
    now = 100.0 + (20 * 60)

    GameConfig.set_cycle_minutes(15)
    assert life.current_cycle(now) == 2
    assert life.cycle_remaining(now) == pytest.approx(10 * 60)

    GameConfig.set_cycle_minutes(60)
    assert life.spawn_time == 100.0
    assert life.current_cycle(now) == 1
    assert life.cycle_remaining(now) == pytest.approx(40 * 60)
    assert life.cycle_progress(now) == pytest.approx(1 / 3)


def test_app_timer_target_rolls_back_when_config_save_fails() -> None:
    GameConfig.set_cycle_minutes(15)
    app = SimpleNamespace(
        _save_config=lambda **_kwargs: False,
        _publish_web_control_state=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("must not publish failed target")
        ),
        _refresh_tray=lambda: None,
    )

    assert App._set_timer_cycle_minutes(app, 60) is False
    assert GameConfig.cycle_minutes() == 15


def test_app_timer_target_persists_then_publishes() -> None:
    GameConfig.set_cycle_minutes(15)
    calls: list[str] = []
    app = SimpleNamespace(
        _save_config=lambda **_kwargs: calls.append("save") or True,
        _publish_web_control_state=lambda **_kwargs: calls.append("publish") or 2,
        _refresh_tray=lambda: calls.append("tray"),
    )

    assert App._set_timer_cycle_minutes(app, 60) is True
    assert GameConfig.cycle_minutes() == 60
    assert calls == ["save", "publish", "tray"]
