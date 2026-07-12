from types import SimpleNamespace

from bomana.core.state import Phase
from bomana.ui.nav_window import NavigationWindow


class FakeLabel:
    def __init__(self) -> None:
        self.options: dict[str, object] = {}

    def config(self, **kwargs) -> None:
        self.options.update(kwargs)

    def cget(self, key: str):
        return self.options.get(key, "")


class FakeHeadingTape:
    def __init__(self) -> None:
        self.targets: list[dict[str, object]] = []

    def clear(self) -> None:
        self.targets = []

    def update_tape_multi(self, _heading: float, targets, _primary_distance: float) -> None:
        self.targets = list(targets)


def test_standalone_aam_navigation_shows_notice_and_all_candidates() -> None:
    nav = object.__new__(NavigationWindow)
    nav._visible = True
    nav.heading_lbl = FakeLabel()
    nav.tolerance_lbl = FakeLabel()
    nav.heading_tape = FakeHeadingTape()
    nav.zone_label = FakeLabel()
    nav.zone_turn = FakeLabel()
    nav.zone_status = FakeLabel()
    nav.zone_info = FakeLabel()
    nav.friendly_turn = FakeLabel()
    nav.friendly_status = FakeLabel()
    nav.friendly_info = FakeLabel()
    snap = SimpleNamespace(
        phase=Phase.ALIVE,
        api_down=False,
        player_heading=0.0,
        weapon_role="aam",
        map_player_x=0.5,
        map_player_y=0.5,
        map_scale_x_m=100_000.0,
        map_scale_y_m=100_000.0,
        map_points=(
            SimpleNamespace(
                id="hostile-a",
                kind="hostile_aircraft",
                x=0.5,
                y=0.4,
                label="Fighter",
            ),
            SimpleNamespace(id="poi-a", kind="poi", x=0.6, y=0.5, label="Radar Point"),
        ),
        interest_point=None,
        traceback_point=None,
        zones=[SimpleNamespace(id="zone-a", relative=0.0, distance_km=5.0, is_target=True)],
        friendly_airfield=None,
        enemy_airfields=[],
        zone_destroyed_alert=False,
    )

    nav.update_display(snap)

    assert nav.zone_label.cget("text") == "空空导航"
    assert nav.zone_status.cget("text") == "战区解算已暂停，仅进行导航"
    assert nav.tolerance_lbl.cget("text") == "敌机 / POI"
    assert {target["type"] for target in nav.heading_tape.targets} == {
        "hostile_aircraft",
        "poi",
        "zone",
    }
    zone = next(target for target in nav.heading_tape.targets if target["type"] == "zone")
    assert zone["is_primary"] is False
    assert zone["is_target"] is False
