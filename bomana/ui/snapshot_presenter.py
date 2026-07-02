"""Headless presentation helpers for UISnapshot compatibility fields."""

from dataclasses import dataclass

from bomana.config import Theme
from bomana.core.state import Phase


@dataclass(frozen=True, slots=True)
class StatusPresentation:
    """UI status strings and badge colors derived from domain snapshot facts."""

    main_badge: tuple[str, str, str]
    flight_badge: tuple[str, str, str]
    status_text: str


def build_status_presentation(
    *,
    phase: Phase,
    api_down: bool,
    api_down_pending: bool,
    has_life: bool,
    landed_flash: bool,
    on_ground: bool,
    overspeed_level: str,
) -> StatusPresentation:
    """Build the top-level status presentation without touching Tk widgets."""
    if api_down:
        main_badge = ("8111不可用", Theme.TEXT, Theme.RED)
        status_text = "未检测到 8111"
    elif api_down_pending and (phase in (Phase.IDLE, Phase.HANGAR, Phase.ARMING) or not has_life):
        main_badge = ("加入战斗中", Theme.TEXT, Theme.BLUE)
        status_text = "加入战斗中"
    elif phase == Phase.ALIVE:
        main_badge = ("战斗中", Theme.TEXT, Theme.GREEN)
        status_text = "计时中"
    elif phase == Phase.WAIT_NEXT:
        main_badge = ("等待复活", Theme.TEXT, Theme.YELLOW)
        status_text = "等待复活"
    elif phase == Phase.LOSS_PENDING:
        main_badge = ("坠毁/弹射", Theme.TEXT, Theme.YELLOW)
        status_text = "坠毁/弹射"
    elif phase == Phase.ARMING:
        main_badge = ("部署中", Theme.TEXT, Theme.BLUE)
        status_text = "部署中"
    elif phase == Phase.HANGAR:
        main_badge = ("机库", Theme.TEXT, Theme.GRAYPILL)
        status_text = "等待游戏开始"
    else:
        main_badge = ("IDLE", Theme.TEXT, Theme.GRAYPILL)
        status_text = "等待中"

    if phase == Phase.ALIVE and not api_down and not api_down_pending:
        if overspeed_level == "critical":
            status_text = "超速危险，立即减速"
        elif overspeed_level == "warning":
            status_text = "接近结构极限"

    if phase not in (Phase.ALIVE, Phase.LOSS_PENDING) or not has_life:
        flight_badge = ("—", Theme.TEXT_DIM, Theme.GRAYPILL)
    elif landed_flash:
        flight_badge = ("就绪✓", Theme.TEXT, Theme.GREEN)
    elif on_ground:
        flight_badge = ("着陆中", Theme.TEXT_DIM, Theme.GRAYPILL)
    else:
        flight_badge = ("飞行中", Theme.TEXT_DIM, Theme.GRAYPILL)

    return StatusPresentation(
        main_badge=main_badge,
        flight_badge=flight_badge,
        status_text=status_text,
    )
