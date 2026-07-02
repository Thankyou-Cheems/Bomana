"""Headless HUD target presentation selection."""

from dataclasses import dataclass, field
from typing import Any

from bomana.core.state import Phase


@dataclass(frozen=True, slots=True)
class HUDTargetModel:
    has_target: bool
    relative: float = 0.0
    distance: float = 0.0
    pitch: float = 0.0
    roll: float = 0.0
    fallback: bool = True
    heading: float = 0.0
    altitude: float = 0.0
    secondary_targets: list[dict[str, float | str]] = field(default_factory=list)
    standby_text: str = "NO TARGET"


def build_hud_target_model(snap: Any, *, secondary_limit: int) -> HUDTargetModel:
    target_zone = None
    secondary_targets: list[dict[str, float | str]] = []

    if snap.phase in (Phase.ALIVE, Phase.LOSS_PENDING):
        target_zone = next((z for z in snap.zones if z.is_target), None)
        if target_zone is None and snap.zones:
            target_zone = min(snap.zones, key=lambda z: abs(z.relative))
        if snap.zones:
            for zone in sorted(snap.zones, key=lambda z: abs(z.relative)):
                if target_zone is not None and zone.id == target_zone.id:
                    continue
                secondary_targets.append(
                    {
                        "relative": float(zone.relative),
                        "distance": float(zone.distance_km),
                        "label": "",
                    }
                )
                if len(secondary_targets) >= secondary_limit:
                    break

    if target_zone is not None:
        return HUDTargetModel(
            has_target=True,
            relative=float(target_zone.relative),
            distance=float(target_zone.distance_km),
            pitch=float(getattr(snap, "attitude_pitch_deg", 0.0) or 0.0),
            roll=float(getattr(snap, "attitude_roll_deg", 0.0) or 0.0),
            fallback=bool(getattr(snap, "hud_attitude_fallback", True)),
            heading=float(getattr(snap, "player_heading", 0.0) or 0.0),
            altitude=float(getattr(snap, "altitude_m", 0.0) or 0.0),
            secondary_targets=secondary_targets,
        )

    if snap.api_down:
        standby_text = "8111 DELAY"
    elif snap.api_down_pending:
        standby_text = "8111 PENDING"
    elif snap.phase not in (Phase.ALIVE, Phase.LOSS_PENDING):
        standby_text = "HUD STANDBY"
    else:
        standby_text = "NO TARGET"
    return HUDTargetModel(has_target=False, standby_text=standby_text)
