# PySide6 MVP Evaluation

Date: 2026-05-16

Status: Superseded on 2026-05-17. Production UI follow-up work is Tk-only. Do not add
Qt/PySide6 code, dependencies, entrypoints, or tests unless the project owner explicitly reopens
that direction. See `docs/TK_UI_FOLLOWUP_PLAN.md`.

This note records the migration assessment for the UI repair epic. It is not an approved
architecture change yet. The current recommendation is to keep shipping the repaired Tk UI while
building a narrow PySide6 MVP behind an explicit development flag or branch.

## Decision

Superseded decision: do not proceed with a Qt/PySide6 MVP in the next phase. Keep production UI
work on Tk and use this document only as historical evaluation context.

Proceed with a small PySide6 Widgets MVP, but do not add PySide6 to production dependencies until
the MVP proves package size, startup time, and Windows overlay compatibility.

The MVP scope is:

- Main information window: timer, navigation card, fuel card, bombing card, speed card.
- Standalone navigation window: title row, heading tape, zone/friendly status rows.
- Shared presenter/view-model boundary fed by existing `UISnapshot` data.

The MVP explicitly excludes:

- HUD overlay migration.
- Global hotkey implementation changes.
- Tray integration changes.
- Launcher UI migration.
- Cross-platform transparent/click-through overlay guarantees.

## Current Evidence

Official documentation checked:

- Qt for Python is the official Python binding for Qt, with PySide6 exposing Qt 6 APIs:
  https://doc.qt.io/qtforpython-6/index.html
- Qt high-level GUI/Widgets APIs use device-independent pixels and automatically account for
  high-DPI display resolution:
  https://doc.qt.io/qt-6.8/highdpi.html
- Qt for Python deployment supports `pyside6-deploy` and also documents PyInstaller, cx_Freeze,
  Briefcase, Nuitka, and related options:
  https://doc.qt.io/qtforpython-6.5/deployment/index.html
- `pyside6-deploy` is a wrapper around Nuitka and can be driven by an entry file or
  `pysidedeploy.spec`:
  https://doc.qt.io/qtforpython-6.5/deployment/deployment-pyside6-deploy.html
- PyPI currently lists PySide6 6.11.1, released 2026-05-13, with Python `>=3.10,<3.15` and
  Python 3.14 classifier support:
  https://pypi.org/project/PySide6/

Local probe on Windows / CPython 3.14.5:

| Dependency set | Install result | Approx. installed size | `PySide6.QtWidgets` import |
|---|---:|---:|---:|
| `PySide6==6.11.1` | OK | `PySide6` package ~633.8 MiB plus `shiboken6` ~2.9 MiB | 0.100-0.141s |
| `PySide6-Essentials==6.11.1` | OK | site-packages total ~206.3 MiB; `PySide6` package ~201.9 MiB plus `shiboken6` ~2.9 MiB | 0.099-0.107s |

Implication: use `PySide6-Essentials` for any MVP unless a missing module forces full PySide6.
Widgets/Core/Gui are enough for the planned MVP; pulling Addons by default would make the package
size risk unnecessarily worse.

## Current Bomana Boundaries

Useful seams already exist:

- `UISnapshot` is immutable UI input from `bomana/core/state.py`.
- `AppPanelRenderer` already concentrates zone/fuel/bombing/speed presentation updates.
- `navigation_presenter.py` already builds shared heading-tape target models for integrated and
  standalone navigation.
- `MainWindowBuilder` owns the static Tk card skeleton, so a Qt MVP can mirror panel structure
  without changing core logic.
- `NavigationWindow` is separate enough to migrate as the second MVP surface.

Hard coupling to keep out of the first MVP:

- `App`, `NavigationWindow`, and `HUDOverlay` use `overrideredirect`, `ctypes.windll.user32`, Win32
  layered-window styles, transparent color keys, and click-through behavior.
- `GlobalHotkeys` and single-instance handling live in `bomana/utils/system.py` and are Windows
  message/API based.
- `runtime_services.py` owns pystray and HUD lifecycle. Those should remain Tk/Win32-owned until
  the Qt main/nav surfaces are proven.

## Proposed MVP Architecture

Add new modules only after a branch/prototype confirms dependency and packaging impact:

```text
bomana/ui_qt/
  app.py                 # QApplication lifecycle and update timer
  main_window.py         # QWidget container for main cards
  nav_window.py          # QWidget standalone nav surface
  panels/
    bombing.py
    fuel.py
    navigation.py
    speed.py
  widgets/
    heading_tape.py      # QWidget/QPainter or QGraphicsView heading tape
  presenter/
    snapshot_viewmodel.py
```

Keep these rules:

- `bomana/core/` remains unchanged.
- Qt widgets receive plain view models, not `GameLogic`.
- Tk and Qt implementations must not share live widget classes.
- Shared logic belongs in presenter/model helpers, not in toolkit-specific modules.
- Feature flags still gate CCRP, zones, airfields, fuel, checklist, and advanced settings.
- MVP must be runnable without starting HUD, tray, or global hotkeys.

## Validation Plan

Minimum acceptance criteria before adding PySide6 to `pyproject.toml`:

1. **Dependency**
   - Use `PySide6-Essentials`, not full `PySide6`, unless a missing module is documented.
   - Confirm Python 3.14 install on Windows CI or a clean Windows runner.

2. **Startup**
   - Measure cold process startup for a minimal Qt main/nav MVP.
   - Target: no more than 300 ms additional local startup time over current Tk import path on the
     same machine.

3. **Package Size**
   - Build the existing app package path with Qt dependency included.
   - Record app zip size and installed/extracted size.
   - Decide whether the updater/launcher UX can tolerate the increase before proceeding.

4. **Layout**
   - Recreate the repaired Tk geometry matrix in Qt:
     - text scale 1.0 / 1.25 / 1.5 / 2.0
     - long bomb names
     - long aircraft names
     - navigation width multipliers
     - 100% / 125% / 150% / 200% Windows display scale where possible

5. **Runtime**
   - Feed recorded or debug `UISnapshot` values at the current UI update cadence.
   - Verify no widget creation churn during steady-state updates.
   - Verify no direct UI access from the polling thread.

6. **Packaging**
   - Compare PyInstaller and `pyside6-deploy` output.
   - Prefer the existing portable app package flow if it can ship Qt dependencies cleanly.
   - Do not replace the launcher build in the MVP.

## Rollout Plan

Phase 0: keep Tk repaired UI as default

- Current completed work already reduced fixed-width, long-line, and heading-tape clipping.
- Continue using Tk for production releases while the Qt MVP is isolated.

Phase 1: Qt main/nav prototype

- Add a local-only or branch-only Qt entry point.
- Implement main cards and standalone nav from `UISnapshot` and presenter helpers.
- No HUD, tray, hotkey, launcher, or config migration.

Phase 2: measurement gate

- Run validation plan above.
- Record app package size, extracted size, startup time, and CI feasibility.
- If size/startup is unacceptable, keep Tk and close the Qt path as rejected for now.

Phase 3: optional dual UI

- Add a guarded `UI_BACKEND=tk|qt` development setting only if Phase 2 passes.
- Keep Tk as default until the Qt path passes feature parity and packaging checks.

Phase 4: production decision

- Switch default only after:
  - all panel features are present,
  - geometry tests exist for Qt,
  - Windows packaging is reproducible,
  - launcher update/install flow handles the larger dependency payload,
  - rollback to Tk remains available for at least one release.

## Recommendation

Do not rewrite the whole UI now. The repaired Tk implementation should remain the release path.
The Qt path is worth a narrow MVP because it directly addresses the class of high-DPI and layout
problems that caused the UI repair epic, but its dependency footprint is large enough that package
size must be treated as a release blocker until measured through the actual Bomana app package.
