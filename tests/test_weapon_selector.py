from types import SimpleNamespace

from bomana.config.settings import WeaponBallisticModelConfig
from bomana.ui import dialogs
from bomana.ui.dialogs import (
    WeaponSelectorDialog,
    build_weapon_selector_scope,
    persist_ballistic_model_selection,
    persist_weapon_selection,
)


class FakeCatalog:
    def __init__(self) -> None:
        self.records = [
            {
                "id": "agm_65d",
                "display_name": "AGM-65D",
                "display_name_zh": "AGM-65D",
                "role": "agm",
                "control": "guided",
                "planform": "normal",
            },
            {
                "id": "su_fab100",
                "display_name": "FAB-100",
                "display_name_zh": "FAB-100",
                "role": "bomb",
                "control": "unguided",
                "planform": "normal",
            },
        ]
        self.selected_weapon_id = "agm_65d"
        self.selection_source = "manual"
        self.set_calls: list[tuple[str, str]] = []

    def search(self, query: str = ""):
        query = query.casefold()
        if not query:
            return list(self.records)
        return [
            record
            for record in self.records
            if query in f"{record['id']} {record['display_name']}".casefold()
        ]

    def for_aircraft(self, aircraft: str):
        return [self.records[0]] if aircraft == "f_16c_block_50" else []

    def get(self, weapon_id: str):
        return next((record for record in self.records if record["id"] == weapon_id), None)

    def set_selected(self, weapon_id: str, source: str = "manual") -> bool:
        self.set_calls.append((weapon_id, source))
        if self.get(weapon_id) is None:
            return False
        self.selected_weapon_id = weapon_id
        self.selection_source = source
        return True


def test_weapon_selector_filters_to_compatible_records_in_flight() -> None:
    records, note, compatible_only = build_weapon_selector_scope(
        FakeCatalog(),
        aircraft_type_name="f_16c_block_50",
        airborne=True,
    )

    assert [record["id"] for record in records] == ["agm_65d"]
    assert note == "当前机型 f_16c_block_50：仅显示兼容武器"
    assert compatible_only is True


def test_weapon_selector_falls_back_to_annotated_full_catalog_without_match() -> None:
    catalog = FakeCatalog()

    records, note, compatible_only = build_weapon_selector_scope(
        catalog,
        aircraft_type_name="unknown_aircraft",
        airborne=True,
    )

    assert [record["id"] for record in records] == ["agm_65d", "su_fab100"]
    assert note == "未匹配 unknown_aircraft 的武器预设：显示全部（兼容性未验证）"
    assert compatible_only is False


def test_weapon_selector_shows_annotated_full_catalog_outside_flight() -> None:
    records, note, compatible_only = build_weapon_selector_scope(
        FakeCatalog(),
        aircraft_type_name="f_16c_block_50",
        airborne=False,
    )

    assert len(records) == 2
    assert note == "未在飞行中：显示全部武器"
    assert compatible_only is False


def test_weapon_selector_rows_include_datamine_id_to_disambiguate_variants() -> None:
    dialog = WeaponSelectorDialog.__new__(WeaponSelectorDialog)

    assert dialog._record_text(FakeCatalog().records[0]) == ("AGM-65D [agm_65d] · AGM · 制导/常规")


def test_weapon_selector_persists_manual_bomb_and_syncs_ccrp_selection(monkeypatch) -> None:
    catalog = FakeCatalog()
    saved = {}
    label_updates = []
    dialog = WeaponSelectorDialog.__new__(WeaponSelectorDialog)
    dialog.catalog = catalog
    dialog._visible_weapon_ids = ["su_fab100"]
    dialog.listbox = SimpleNamespace(curselection=lambda: (0,))
    dialog.app = SimpleNamespace(
        bomb_select_lbl=SimpleNamespace(config=lambda **kwargs: label_updates.append(kwargs))
    )
    dialog.destroy = lambda: None
    dialog.result = None
    dialog.selected_weapon = "agm_65d"

    monkeypatch.setattr(dialogs.ConfigManager, "load", lambda: {"keep": True})
    monkeypatch.setattr(dialogs.ConfigManager, "save", lambda config: saved.update(config) or True)
    monkeypatch.setattr(dialogs.BombConfig, "get_bomb_data", lambda weapon_id: {"mass": 100})
    monkeypatch.setattr(dialogs.BombConfig, "selected_bomb", "old_bomb")

    dialog._select()

    assert saved == {
        "keep": True,
        "selected_weapon": "su_fab100",
        "weapon_ballistic_model": "foxthree_compatible",
        "selected_bomb": "su_fab100",
    }
    assert catalog.set_calls == [("su_fab100", "manual")]
    assert dialogs.BombConfig.selected_bomb == "su_fab100"
    assert dialog.result == "su_fab100"
    assert label_updates == [{"text": "FAB-100 · 炸弹 · 手选"}]


def test_weapon_selector_keeps_ccrp_bomb_when_selecting_missile(monkeypatch) -> None:
    catalog = FakeCatalog()
    saved = {}
    dialog = WeaponSelectorDialog.__new__(WeaponSelectorDialog)
    dialog.catalog = catalog
    dialog._visible_weapon_ids = ["agm_65d"]
    dialog.listbox = SimpleNamespace(curselection=lambda: (0,))
    dialog.app = SimpleNamespace()
    dialog.destroy = lambda: None
    dialog.result = None
    dialog.selected_weapon = "su_fab100"

    monkeypatch.setattr(
        dialogs.ConfigManager,
        "load",
        lambda: {"selected_bomb": "su_fab100"},
    )
    monkeypatch.setattr(dialogs.ConfigManager, "save", lambda config: saved.update(config) or True)
    monkeypatch.setattr(dialogs.BombConfig, "selected_bomb", "su_fab100")

    dialog._select()

    assert saved == {
        "selected_bomb": "su_fab100",
        "selected_weapon": "agm_65d",
        "weapon_ballistic_model": "foxthree_compatible",
    }
    assert catalog.set_calls == [("agm_65d", "manual")]
    assert dialogs.BombConfig.selected_bomb == "su_fab100"


def test_weapon_ballistic_model_config_defaults_to_compatibility_and_rejects_unknown(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        WeaponBallisticModelConfig,
        "selected_model",
        WeaponBallisticModelConfig.DEFAULT_MODEL,
    )

    assert WeaponBallisticModelConfig.DEFAULT_MODEL == "foxthree_compatible"
    assert WeaponBallisticModelConfig.set_selected("strict_official")
    assert WeaponBallisticModelConfig.selected_model == "strict_official"
    assert not WeaponBallisticModelConfig.set_selected("unlicensed_guess")
    assert WeaponBallisticModelConfig.selected_model == "strict_official"


def test_weapon_selector_model_buttons_are_explicit_and_choice_applies_immediately(
    monkeypatch,
) -> None:
    saved = {}
    current = {"value": "foxthree_compatible"}
    dialog = WeaponSelectorDialog.__new__(WeaponSelectorDialog)
    dialog.ballistic_model_var = SimpleNamespace(
        get=lambda: current["value"],
        set=lambda value: current.update(value=value),
    )
    dialog._refresh_ballistic_model_controls = lambda: None

    monkeypatch.setattr(
        WeaponBallisticModelConfig,
        "selected_model",
        "foxthree_compatible",
    )
    monkeypatch.setattr(dialogs.ConfigManager, "load", lambda: {"keep": True})
    monkeypatch.setattr(dialogs.ConfigManager, "save", lambda config: saved.update(config) or True)

    dialog._set_ballistic_model("strict_official")

    assert set(dialog._MODEL_LABELS) == {"foxthree_compatible", "strict_official"}
    assert dialog._MODEL_LABELS["foxthree_compatible"] == "缺少官方数据时：使用推测替代"
    assert dialog._MODEL_LABELS["strict_official"] == "缺少官方数据时：不应用模型"
    assert all("官方数据始终优先" in note for note in dialog._MODEL_NOTES.values())
    assert saved == {"keep": True, "weapon_ballistic_model": "strict_official"}
    assert current["value"] == "strict_official"
    assert WeaponBallisticModelConfig.selected_model == "strict_official"


def test_ballistic_model_persistence_failure_restores_runtime_choice(monkeypatch) -> None:
    monkeypatch.setattr(
        WeaponBallisticModelConfig,
        "selected_model",
        "foxthree_compatible",
    )
    monkeypatch.setattr(dialogs.ConfigManager, "load", lambda: {})
    monkeypatch.setattr(dialogs.ConfigManager, "save", lambda _config: False)

    assert not persist_ballistic_model_selection("strict_official")
    assert WeaponBallisticModelConfig.selected_model == "foxthree_compatible"


def test_weapon_persistence_failure_restores_runtime_selection(monkeypatch) -> None:
    catalog = FakeCatalog()
    monkeypatch.setattr(
        WeaponBallisticModelConfig,
        "selected_model",
        "foxthree_compatible",
    )
    monkeypatch.setattr(dialogs.ConfigManager, "load", lambda: {})
    monkeypatch.setattr(dialogs.ConfigManager, "save", lambda _config: False)
    monkeypatch.setattr(dialogs.BombConfig, "selected_bomb", "su_fab100")

    assert not persist_weapon_selection(catalog, "su_fab100", "strict_official")
    assert catalog.selected_weapon_id == "agm_65d"
    assert catalog.set_calls == [
        ("su_fab100", "manual"),
        ("agm_65d", "manual"),
    ]
    assert WeaponBallisticModelConfig.selected_model == "foxthree_compatible"
    assert dialogs.BombConfig.selected_bomb == "su_fab100"
