"""Game lifecycle state transitions extracted from GameLogic."""

from bomana.config import GameConfig
from bomana.core.state import (
    AttitudeConfidenceState,
    GameState,
    LifeState,
    TelemetryData,
    ZoneNavigationState,
)


def start_new_life(state: GameState, now: float) -> None:
    """Start a new life while the caller holds the GameLogic lock."""
    next_index = 1 if not state.current_life else (state.current_life.life_index + 1)
    state.current_life = LifeState(spawn_time=now, life_index=next_index)
    state.sortie_id += 1
    state.last_refit_ts = now
    state.last_player_present_ts = now
    state.attitude = AttitudeConfidenceState()


def prepare_new_battle_context(state: GameState) -> None:
    """Drop hangar-period cached context so the next battle refreshes map scale."""
    state.zone_nav = ZoneNavigationState()
    state.map_info = None


def reset_life_state(state: GameState) -> None:
    """Reset battle/life-scoped state while preserving app-level config."""
    state.current_life = None
    state.sortie_id = 0
    state.last_refit_ts = 0.0
    state.spawn_candidate_since = None
    state.missing_player_since = None
    state.last_player_present_ts = 0.0
    state.landing_start_time = None
    state.landed_flash_until = 0.0
    state.zone_nav = ZoneNavigationState()
    state.attitude = AttitudeConfidenceState()
    state.map_info = None
    state.fuel_state.reset()


def clear_transient_state(state: GameState) -> None:
    """Clear transient spawn/loss/landing candidates."""
    state.spawn_candidate_since = None
    state.missing_player_since = None
    state.landing_start_time = None
    state.landed_flash_until = 0.0


def update_landing(state: GameState, tel: TelemetryData, now: float) -> None:
    """Update landing confirmation state while the caller holds the lock."""
    if not state.current_life:
        return

    if not tel.state_resp_ok:
        return

    if tel.is_on_ground:
        if state.landing_start_time is None:
            state.landing_start_time = now
        elif (
            now - state.landing_start_time
        ) >= GameConfig.LAND_CONFIRM_SEC and state.landed_flash_until <= now:
            state.landed_flash_until = now + GameConfig.LANDED_FLASH_SEC
    else:
        state.landing_start_time = None
