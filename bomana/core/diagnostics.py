"""Core endpoint diagnostic helpers extracted from GameLogic."""

from collections.abc import Callable
from typing import Any

from bomana.core.state import GameState


def record_endpoint_diagnostic(
    state: GameState,
    ok: bool,
    streak_attr: str,
    count_attr: str,
) -> None:
    """Update per-endpoint failure counters while the caller holds the lock."""
    if ok:
        setattr(state, streak_attr, 0)
        return
    setattr(state, streak_attr, getattr(state, streak_attr) + 1)
    setattr(state, count_attr, getattr(state, count_attr) + 1)


def emit_endpoint_diagnostic(
    endpoint_diag_state: dict[str, int],
    log: Callable[..., Any],
    *,
    endpoint: str,
    ok: bool,
    error_kind: str,
    elapsed_ms: float,
    failure_streak: int,
    status_code: int | None = None,
) -> None:
    """Emit endpoint health changes without logging every polling tick."""
    previous_streak = endpoint_diag_state.get(endpoint, 0)
    if ok:
        if previous_streak > 0:
            log(
                "endpoint_recovered",
                endpoint=endpoint,
                previous_failure_streak=previous_streak,
                elapsed_ms=elapsed_ms,
            )
        endpoint_diag_state[endpoint] = 0
        return

    endpoint_diag_state[endpoint] = failure_streak
    if failure_streak not in {1, 5, 20} and (failure_streak % 100) != 0:
        return
    log(
        "endpoint_failed",
        endpoint=endpoint,
        error_kind=error_kind or "unknown",
        elapsed_ms=elapsed_ms,
        failure_streak=failure_streak,
        status_code=status_code,
    )
