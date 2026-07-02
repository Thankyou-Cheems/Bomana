from bomana.core.state import Phase
from bomana.ui.snapshot_presenter import build_status_presentation
from bomana.ui.theme import Theme


def test_status_presentation_prioritizes_api_down() -> None:
    model = build_status_presentation(
        phase=Phase.ALIVE,
        api_down=True,
        api_down_pending=False,
        has_life=True,
        landed_flash=False,
        on_ground=False,
        overspeed_level="critical",
    )

    assert model.main_badge == ("8111不可用", Theme.TEXT, Theme.RED)
    assert model.status_text == "未检测到 8111"
    assert model.flight_badge == ("飞行中", Theme.TEXT_DIM, Theme.GRAYPILL)


def test_status_presentation_overrides_alive_status_for_overspeed() -> None:
    model = build_status_presentation(
        phase=Phase.ALIVE,
        api_down=False,
        api_down_pending=False,
        has_life=True,
        landed_flash=False,
        on_ground=False,
        overspeed_level="warning",
    )

    assert model.main_badge == ("战斗中", Theme.TEXT, Theme.GREEN)
    assert model.status_text == "接近结构极限"
    assert model.flight_badge == ("飞行中", Theme.TEXT_DIM, Theme.GRAYPILL)


def test_status_presentation_formats_pending_and_landed_flash() -> None:
    pending = build_status_presentation(
        phase=Phase.HANGAR,
        api_down=False,
        api_down_pending=True,
        has_life=False,
        landed_flash=False,
        on_ground=False,
        overspeed_level="safe",
    )
    landed = build_status_presentation(
        phase=Phase.ALIVE,
        api_down=False,
        api_down_pending=False,
        has_life=True,
        landed_flash=True,
        on_ground=True,
        overspeed_level="safe",
    )

    assert pending.main_badge == ("加入战斗中", Theme.TEXT, Theme.BLUE)
    assert pending.flight_badge == ("—", Theme.TEXT_DIM, Theme.GRAYPILL)
    assert landed.flight_badge == ("就绪✓", Theme.TEXT, Theme.GREEN)
