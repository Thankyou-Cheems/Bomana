# enforces: docs/specs/weapon-fire-control.md WFC-07 WFC-08 WFC-10 WFC-11 WFC-12

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from bomana.config.settings import BombConfig
from bomana.core.state import GameState, Phase, TelemetryData, WeaponTarget
from bomana.core.weapon_scheduler import (
    apply_weapon_calculation,
    compute_weapon_calculation,
    prepare_weapon_calculation,
)
from bomana.ui import app as app_module
from bomana.ui.app import App
from bomana.ui.panel_presenter import build_bombing_display_model

ROOT = Path(__file__).resolve().parents[2]


class _AamCatalog:
    def __init__(self) -> None:
        self.selected_weapon_id = "test_aam"
        self.selection_source = "manual"
        self.weapon = {
            "id": "test_aam",
            "display_name": "Test AAM",
            "display_name_zh": "Test AAM",
            "role": "aam",
            "propulsion": "powered",
            "control": "guided",
            "planform": "normal",
        }

    def get(self, weapon_id: str):
        return deepcopy(self.weapon) if weapon_id == self.selected_weapon_id else None

    def compatible(self, weapon_id: str, aircraft: str) -> bool:
        return weapon_id == self.selected_weapon_id and aircraft == "test_plane"


def test_ui_reuses_core_catalog_failure_and_disables_selector(monkeypatch) -> None:
    app = App.__new__(App)
    app.root = object()
    app.game = SimpleNamespace(weapon_catalog=None)
    warnings: list[tuple[tuple[object, ...], dict[str, object]]] = []

    monkeypatch.setattr(
        app_module,
        "get_weapon_catalog",
        lambda: (_ for _ in ()).throw(AssertionError("UI must not reload the catalog")),
    )
    monkeypatch.setattr(
        app_module.messagebox,
        "showwarning",
        lambda *args, **kwargs: warnings.append((args, kwargs)),
    )

    assert app._get_weapon_catalog() is None
    app._show_bomb_selector()

    assert warnings and warnings[0][0][:2] == (
        "武器目录不可用",
        "武器目录缺失或校验失败，已停用武器选择与解算。",
    )
    main_window_source = (ROOT / "bomana/ui/main_window.py").read_text(encoding="utf-8")
    assert "weapon_catalog = app._get_weapon_catalog()" in main_window_source
    assert "weapon_catalog = get_weapon_catalog()" not in main_window_source
    app_source = (ROOT / "bomana/ui/app.py").read_text(encoding="utf-8")
    assert "catalog=weapon_catalog" in app_source

    model = build_bombing_display_model(
        SimpleNamespace(
            weapon_status="unknown_weapon",
            weapon_reason="catalog_unavailable",
            weapon_selection_source="unknown",
            weapon_selection_compatible=False,
            weapon_solution_valid=False,
        )
    )
    assert model.bomb_label_text.startswith("武器目录不可用")
    assert model.release.text == "目录不可用"


def test_hostile_disappearance_bypasses_calculation_throttle() -> None:
    catalog = _AamCatalog()
    state = GameState(phase=Phase.ALIVE)
    state.last_weapon_calc_time = 10.0
    state.weapon_target = WeaponTarget(
        id="hostile-1",
        kind="aircraft",
        name="Hostile",
        distance_m=2000.0,
    )
    state.weapon_solution_valid = True
    state.weapon_status = "in_envelope"
    telemetry = TelemetryData(
        ind_ok=True,
        state_resp_ok=True,
        valid=True,
        type_name="test_plane",
        ias_kmh=720.0,
        tas_kmh=900.0,
        altitude_m=2000.0,
    )

    work = prepare_weapon_calculation(
        state,
        telemetry,
        10.05,
        player_present=True,
        target=None,
        catalog=catalog,
    )

    assert work is not None
    result = compute_weapon_calculation(work)
    assert apply_weapon_calculation(state, result, catalog=catalog)
    assert state.weapon_target is None
    assert state.weapon_status == "no_target"
    assert not state.weapon_solution_valid


def test_ccrp_datamine_source_id_alias_resolves_without_generic_fallback() -> None:
    source_id = "uk_1000lbs_mc_mk1_mk2_bomb"

    params = BombConfig.get_bomb_data(source_id)

    assert params is not None
    assert params["mass"] == 463.1
    assert params["source_file"] == f"{source_id}.blkx"
    assert BombConfig.get_bomb_data("missing_catalog_weapon") is None
