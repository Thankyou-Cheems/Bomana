from pathlib import Path

# enforces: docs/changes/202607-sdd-phase2/delta-spec.md UI-PRES-01..UI-PRES-02

ROOT = Path(__file__).resolve().parents[2]


def test_core_does_not_import_ui_presenters() -> None:
    offenders: list[str] = []
    for path in (ROOT / "bomana" / "core").glob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "bomana.ui" in source:
            offenders.append(path.name)

    assert offenders == []


def test_headless_presenters_do_not_import_tkinter() -> None:
    presenter_paths = [
        ROOT / "bomana" / "ui" / "dialog_presenter.py",
        ROOT / "bomana" / "ui" / "hud_presenter.py",
        ROOT / "bomana" / "ui" / "navigation_presenter.py",
        ROOT / "bomana" / "ui" / "panel_presenter.py",
        ROOT / "bomana" / "ui" / "snapshot_presenter.py",
    ]
    offenders = []
    for path in presenter_paths:
        source = path.read_text(encoding="utf-8")
        if "tkinter" in source or ".config(" in source or "grid(" in source or "pack(" in source:
            offenders.append(path.name)

    assert offenders == []
